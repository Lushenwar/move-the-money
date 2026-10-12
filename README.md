# Move the Money

A small HTTP API where accounts hold a balance and money moves between them, built so that four rules can't be broken:

1. A balance never goes negative, even when requests arrive at the same moment.
2. A transfer is all or nothing.
3. The same transfer submitted twice is applied once.
4. Amounts are exact (integer cents, no floats anywhere).

Python 3.13, FastAPI (sync), psycopg 3 with plain SQL (no ORM), PostgreSQL 18. Correctness comes from the database: one transaction per transfer, row locks, `CHECK` and `UNIQUE` constraints. The tests run against real Postgres and include concurrency tests that were each shown to **fail** against deliberately broken code.

## Setup

Built with Python 3.13. The test suite passes on Windows with PostgreSQL 18 (my machine) and on Linux with PostgreSQL 16 (a separate check run outside my dev setup).

```sql
-- in psql, as a superuser
CREATE DATABASE movemoney;
```

```powershell
# Windows PowerShell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:DATABASE_URL = "postgres://postgres:<password>@localhost:5432/movemoney"
```

```bash
# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_URL="postgres://postgres:<password>@localhost:5432/movemoney"
```

Replace `postgres` with your Postgres user (with Homebrew on macOS it's usually your macOS username). Special characters in the password must be URL-encoded (e.g. `@` → `%40`). The tables are created automatically on startup (`schema.sql`, `CREATE TABLE IF NOT EXISTS`).

**Every command below needs `DATABASE_URL` set and the venv active.**

## Run

```
uvicorn app:app --reload
```

Open http://localhost:8000/docs to try every endpoint from the browser.

| Method | Path | Body | Success |
| --- | --- | --- | --- |
| POST | `/accounts` | `{"initial_balance_cents": 10000}` | 201 `{"id", "balance_cents"}` |
| GET | `/accounts/{id}` | | 200 `{"id", "balance_cents"}` |
| POST | `/transfers` | `{"idempotency_key", "from_account_id", "to_account_id", "amount_cents"}` | 201 transfer; **200** with the original transfer if the key is replayed with the same payload |
| GET | `/accounts/{id}/transfers` | | 200 list, sent and received, newest first |

| Status | Body | When |
| --- | --- | --- |
| 404 | `{"error": "account_not_found"}` | either account doesn't exist |
| 409 | `{"error": "idempotency_key_conflict"}` | same key reused with a different payload |
| 422 | `{"error": "insufficient_funds"}` | sender doesn't have enough |
| 422 | FastAPI's `{"detail": [...]}` | invalid input: non-integer, `<= 0`, wrong type, too large, self-transfer |

To clear the database before a demo (refuses without `--yes`, resets ids to 1):

```
python reset_db.py --yes
```

## Tests

```
pytest -v
```

54 tests, all against the real database (never mocked). The ones that matter most:

| Test | Proves |
| --- | --- |
| `test_concurrent_transfers_never_overdraw` | Rule 1. 50 threads send 1000 cents each from an account holding 10000, released together by a `threading.Barrier`, each on its own pooled connection. Exactly 10 succeed, the sender ends at 0, and the total is unchanged. |
| `test_opposite_direction_transfers_no_deadlock_and_conserve_money` | A→B and B→A at the same time: no deadlock, money conserved, balances match the success counts exactly. |
| `test_failed_credit_rolls_back_debit` | Rule 2. The credit fails after the debit has run; the sender keeps their money. |
| `test_concurrent_duplicates_apply_once` and `test_concurrent_same_key_different_accounts` | Rule 3. 20 simultaneous requests with one key: exactly one applies; the rest get the original (200) or a clean 409, never a 500. |
| `test_replay_after_balance_drained_returns_200_not_422` | A retry of a transfer that emptied the account is recognised as a replay, not reported as "insufficient funds". |
| `test_bad_transfer_rejected_and_changes_nothing` | Rule 4. 19 bad inputs (`10.5`, `100.0`, `"1000"`, `true`, `2^63`, ...), each also asserting no money moved. |

**How I know these tests can fail.** For each one I temporarily swapped in a broken version of the code, ran the test, and confirmed it failed (the broken versions were never committed; results are in the commit messages). For example, a read-the-balance-in-Python version let 18–19 of 10 transfers through. Some naive broken versions *didn't* fail, which is worth knowing: see "Design decisions".

The tests use the same database as the demo and leave their accounts behind; run `python reset_db.py --yes` afterwards for a clean demo.

## How a transfer works

All in **one transaction** in `service.do_transfer`:

1. **Lock both accounts** with `SELECT ... FOR UPDATE ORDER BY id`. Any other transfer touching either account waits here. Locking in id order (not "sender first") means A→B and B→A can't deadlock.
2. **Claim the idempotency key** with `INSERT ... ON CONFLICT (idempotency_key) DO NOTHING`. If the key already exists, return the original transfer (or 409 if the payload differs) without touching balances. A concurrent duplicate waits for the first one to commit or roll back.
3. **Debit** with `UPDATE ... SET balance_cents = balance_cents - x WHERE id = sender AND balance_cents >= x`, and check that exactly one row changed. The balance check happens inside the database, in the same statement as the write.
4. **Credit** the receiver.
5. **Commit.** Any exception at any step rolls back everything, including the key claim, so a failed transfer can be retried with the same key.

## Design decisions

- **Integer cents end to end.** `BIGINT` columns, Pydantic fields with `strict=True`. Without strict mode, Pydantic silently turns `100.0`, `"1000"` and `true` into integers and the money moves (I checked). Amounts above the `BIGINT` maximum are rejected with a 422 rather than a database 500.
- **Defence in depth, and testing the right layer.** Rule 1 is protected three times: the row lock, the conditional `UPDATE`, and `CHECK (balance_cents >= 0)`. Removing only `FOR UPDATE` still passed the concurrency test, so that smoke check proved nothing. The version that really fails reads the balance into Python and writes back a computed value (a lost update, which *creates* money). That's why the test asserts the exact success count and the total, not just "no negative balance", which the `CHECK` would guarantee even for broken code.
- **Order inside the transaction matters.** The key is claimed after the lock (the transfer row's foreign keys lock the accounts, and taking that before `FOR UPDATE` can deadlock) and before the debit (`DO NOTHING` doesn't raise, so a conflict after the debit would commit a second payment; a broken version that did this moved money twice).
- **Failed transfers aren't recorded.** A retry after insufficient funds is a new attempt with the same key.
- **History is ordered by `id`, not `created_at`.** The id is assigned inside the INSERT, after the lock, so for one account it follows the order money actually moved. `created_at` uses `clock_timestamp()` (write time) rather than `now()` (transaction start time, which can be before the transfer waited on a lock).
- **The balance is stored on the account** for fast reads; the `transfers` table is the history. A double-entry ledger would be the next step (below).
- **Synchronous FastAPI.** psycopg calls block anyway; `async def` with blocking calls would stall the event loop and add complexity for nothing.

### Why this stack

- **PostgreSQL:** locking, atomic transactions and uniqueness come from a battle-tested database instead of hand-written code, and they still hold with several server instances. SQLite serialises all writes, so a concurrency test can't tell safe code from broken code; in-memory state loses data and doesn't work across instances.
- **Python:** my strongest language, so my attention went to correctness rather than syntax. (KOHO's backend is Go; I'd ramp up on it.)

## What I cut, and why

- **Auth, users, currencies, fees, UI, deployment:** out of scope for the assignment; each is more code to defend without proving any of the four rules.
- **Pagination on history:** the list is unbounded. Fine at demo scale.
- **A separate test database:** tests and demo share `movemoney`. Simple to set up, but tests leave data behind.
- **A clean error for balance overflow:** crediting an account past the `BIGINT` maximum (about $92 quadrillion) returns a 500. The transaction rolls back, so no money is lost (there's a test for this).
- **Idempotency key expiry:** keys are kept forever.

## What's next

- Double-entry ledger plus a reconciliation job that checks stored balances against the ledger.
- Expiry (TTL) for old idempotency keys.
- Pagination for history, and indexes on `transfers(from_account_id)` / `transfers(to_account_id)` before real traffic.
- A separate test database (or a transaction-per-test fixture).
- A load test to measure throughput under lock contention on a hot account.

## Time spent

Started 13:28. Stopped: 16:15

See `BUILD_LOG.md` for how AI tools were used, where they were wrong, and what I rejected.

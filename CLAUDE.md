# CLAUDE.md — Move the Money

## CURRENT STATUS

```
╔══════════════════════════════════════════════════════════╗
║  BUILD PROGRESS                               3/5 DONE   ║
║  ██████████████░░░░░░░░░░  60%                           ║
║  Phase 1: Skeleton, Schema & Accounts       [x]          ║
║  Phase 2: Transfers & Concurrency Proof     [x]          ║
║  Phase 3: Idempotency                       [x]          ║
║  Phase 4: History, Validation & Hardening   [ ]          ║
║  Phase 5: README, Build Log & Demo Prep     [ ]          ║
╚══════════════════════════════════════════════════════════╝
```

Phase: Phase 4 in progress (4C bidirectional test next)
Time budget: 4 hours hard cap (start: 13:28 / stop by: 17:28, 2026-10-12)
Tests: 53 passing
**Claude updates this section (box, phase line, commit log) after every commit.**

### Done so far
| Commit | Step | What |
| --- | --- | --- |
| `d745abd` | setup | requirements, gitignore, CLAUDE.md, reviewer agent |
| `7d8a950` | setup | allow more reviewer runs, start clock, Claude commits |
| `87b748c` | 1A | schema.sql, db.py (pool), app.py (schema applied at import, no async lifespan) |
| `8bd1958` | 1A fix | close connection pool at exit |
| `aa1249f` | 1B | POST/GET accounts, strict validation, 0..BIGINT max, `{"error": ...}` bodies, httpx |
| `d2d7b70` | 2A | do_transfer: FOR UPDATE ORDER BY id, conditional debit, one transaction; rule-2 rollback test |
| `8c08029` | 2B/2C | 50-thread concurrency test; smoke check: no-FOR-UPDATE passed (proves nothing), read-check-write failed 18-19/10 |
| — | 2D | review checkpoint 1: cold-pool claim measured over 80 runs, half right, no change |
| `29d4756` | 3A | idempotency: lock → claim key (ON CONFLICT DO NOTHING) → debit → credit; 200 replay / 409 conflict |
| `4ece30b` | 3B | idempotency tests incl. drained replay, 20 concurrent duplicates, same key on different accounts |
| `8570434` | 3C | review checkpoint 2: no CRITICAL/MAJOR; added waiting-duplicate-after-rollback test |
| `a614082` | 4A | GET /accounts/{id}/transfers, 404 for unknown, ORDER BY id DESC (created_at is txn start; test proves it) |
| `bb32765` | 4B | 19-case validation table via HTTP, each asserts balances unchanged + no row; strict-mode smoke check |
| (this) | 4B+ | transfers.created_at DEFAULT clock_timestamp() (write time, not txn start) |

## WHAT THIS FILE IS

This document is the authoritative guide for building Move the Money, a take-home assignment for KOHO. Every rule, data contract, phase boundary, and constraint here is binding. Do not deviate without explicit approval from me (Ryan).

The assignment is graded on **correctness and judgment, not size**. When in doubt, build less and prove more.

---

## THE ASSIGNMENT (WHAT KOHO ASKED FOR)

### Build
A system where accounts hold a balance and money moves between them. It must let someone:
* open an account with a starting balance
* send an amount from one account to another
* look up an account's current balance
* look up an account's transaction history

No UI, no auth, no signup flow, no deployment. An HTTP API is the chosen interface.

### The four rules the system must never break
1. **An account's balance can never go negative**, under any sequence of requests, including ones that arrive at the same moment.
2. **A transfer is all or nothing.** There is no state where money left one account and did not arrive at the other.
3. **The same transfer submitted twice is only applied once.** Networks retry; users double-click.
4. **Amounts are exact.** If a cent goes missing anywhere, the system is wrong.

**At least one test must prove rule 1 survives two transfers competing for the same money at the same time.** This is the single thing KOHO will look at most closely.

### Deliverables
* **Git repo with real, incremental history.** They read the commits. Small commits, honest messages.
* **README:** how to run, how to run tests, what was cut, what's next.
* **Build log (~1 page):**
  * what I set out to do
  * where AI genuinely helped
  * where AI was confidently wrong and how I caught it
  * what I rejected and why
  * what I shipped that I'm not comfortable with
* **4-hour cap.** If time runs out, describe what the fifth hour would be.

### What KOHO is assessing
* Real leverage from AI tools, **and the ability to tell when they're wrong**.
* Correctness instincts: did I test the thing that could actually break?
* Scoping: cut the right things and explain why.
* Explaining everything to someone who hasn't seen the code.

### The interview (60 min)
| Time | What happens |
| --- | --- |
| 10 min | Demo |
| 10 min | Build log + walk through commits |
| 15 min | Questions about design decisions |
| 15 min | **Live change to this project, with AI tools open** |
| 10 min | My questions for them |

The live change means **every line must be something I understand and can modify under pressure.**

---

## PRODUCT DEFINITION

### What this IS:
* A small, synchronous HTTP API (FastAPI) backed by PostgreSQL.
* A system where **the database enforces correctness**: transactions, row locks, CHECK and UNIQUE constraints.
* A codebase with tests that **prove** the four rules, including tests demonstrated to fail against broken code.

### What this IS NOT:
* A banking product: no auth, no users, no currencies, no fees, no UI.
* A framework showcase: no ORM, no async, no message queues, no microservices.
* A place for clever code. Boring and obvious wins.

### How a transfer works:
1. Client sends `POST /transfers` with an idempotency key, sender, receiver, and amount in cents.
2. Pydantic validates the input strictly (positive integer cents, different accounts).
3. One DB transaction:
   * locks both accounts in id order
   * conditionally debits the sender
   * credits the receiver
   * inserts the transfer row (UNIQUE idempotency key)
4. Commit. Either all of it happened, or none of it did.

---

## STACK

* **Python 3.13 (x64)** in a venv at `.venv`
* **FastAPI**, synchronous endpoints only (`def`, never `async def`)
* **psycopg 3** + `psycopg_pool.ConnectionPool`. Plain SQL, **no ORM**
* **PostgreSQL 18**, native Windows service (no Docker). Connection via the `DATABASE_URL` env var
* **pytest** against the real database
* Dev machine: Windows on ARM (Snapdragon), **PowerShell**. Give PowerShell commands, not bash
* **Ask before adding any dependency** beyond `fastapi`, `uvicorn`, `psycopg[binary,pool]`, `pytest`, `httpx` (test-only, needed by FastAPI's TestClient; approved in Phase 1B)

### Why this stack (for the README / interview)
* **Postgres:** locking, atomic transactions, and uniqueness come from a battle-tested database, not hand-written code. SQLite serializes all writes, so a concurrency test can't distinguish safe code from broken code. In-memory state loses data and doesn't survive multiple server instances.
* **Python:** my strongest language, so my attention goes to correctness rather than syntax. (KOHO's backend is Go; I'd ramp up on it.)
* **Sync, not async:** simpler to reason about; psycopg calls are blocking anyway.

---

## SYSTEM ARCHITECTURE

```
┌──────────────────────┐        ┌──────────────────────────────┐
│ Client / pytest /    │  HTTP  │  app.py (FastAPI)            │
│ /docs Swagger page   │───────>│  thin endpoints: validate,   │
└──────────────────────┘        │  call service, map errors    │
                                └──────────────┬───────────────┘
           tests call directly                 │
        ┌──────────────────────────────────────▼──────────────┐
        │  service.py                                         │
        │  create_account / get_account / do_transfer /       │
        │  get_history — plain functions, raise specific      │
        │  exceptions, all DB writes in one transaction       │
        └──────────────────────────────┬──────────────────────┘
                                       │ psycopg ConnectionPool
                                       ▼
        ┌─────────────────────────────────────────────────────┐
        │  PostgreSQL 18                                      │
        │  accounts (CHECK balance >= 0)                      │
        │  transfers (UNIQUE idempotency_key, CHECK amount>0) │
        └─────────────────────────────────────────────────────┘
```

Keep business logic in `service.py` so the concurrency tests can call `do_transfer` directly from many threads.

---

## DATA CONTRACT

### Schema (`schema.sql`, applied on startup and in test setup)

```sql
CREATE TABLE IF NOT EXISTS accounts (
    id             BIGSERIAL PRIMARY KEY,
    balance_cents  BIGINT NOT NULL CHECK (balance_cents >= 0),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS transfers (
    id               BIGSERIAL PRIMARY KEY,
    idempotency_key  TEXT NOT NULL UNIQUE,
    from_account_id  BIGINT NOT NULL REFERENCES accounts(id),
    to_account_id    BIGINT NOT NULL REFERENCES accounts(id),
    amount_cents     BIGINT NOT NULL CHECK (amount_cents > 0),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),  -- write time, not txn start
    CHECK (from_account_id <> to_account_id)
);
```

### API

| Method | Path | Body | Success |
| --- | --- | --- | --- |
| POST | `/accounts` | `{"initial_balance_cents": 10000}` | 201 `{"id", "balance_cents"}` |
| GET | `/accounts/{id}` | — | 200 `{"id", "balance_cents"}` |
| POST | `/transfers` | `{"idempotency_key", "from_account_id", "to_account_id", "amount_cents"}` | 201 transfer object (200 with the original transfer if the key is replayed with the same payload) |
| GET | `/accounts/{id}/transfers` | — | 200 list of transfers (sent and received, newest first by id; 404 if unknown) |

### Error contract

| Status | `error` code | When |
| --- | --- | --- |
| 404 | `account_not_found` | Either account doesn't exist |
| 409 | `idempotency_key_conflict` | Same key reused with a different payload |
| 422 | `insufficient_funds` | Sender doesn't have enough money |
| 422 | (FastAPI default) | Validation failure: non-integer, ≤ 0, wrong type, self-transfer, > BIGINT max |

Error bodies are `{"error": "<code>"}`; validation failures keep FastAPI's default `{"detail": [...]}`.

### Design decisions (document in README)
* Amounts are **integer cents** end to end. Pydantic fields use `strict=True` so `10.5` and `"1000"` are rejected rather than coerced.
* **Failed transfers are not recorded**, so a retry with the same key after insufficient funds is treated as a new attempt.
* The balance is stored on the account (fast reads). The `transfers` table is the history. A double-entry ledger is future work.

---

## REPOSITORY STRUCTURE

```
move-the-money/
├── README.md
├── BUILD_LOG.md
├── CLAUDE.md
├── .claude/agents/
│   └── money-reviewer.md   # read-only reviewer subagent
├── requirements.txt
├── .gitignore              # .venv, __pycache__, .pytest_cache, .env, NOTES.md
├── schema.sql
├── db.py                   # ConnectionPool from DATABASE_URL, apply schema
├── service.py              # business logic + exceptions
├── app.py                  # FastAPI endpoints (thin)
├── reset_db.py             # empties tables for a clean demo
└── tests/
    ├── conftest.py         # pool, schema, fresh-account helpers
    ├── test_accounts.py
    ├── test_transfers.py
    ├── test_concurrency.py # rule 1 + bidirectional deadlock test
    └── test_idempotency.py # rule 3, including concurrent duplicates
```

---

## IMPLEMENTATION PHASES

Work **one phase step at a time**. Stop after each step so I can review, test, and commit.

### PHASE 1: SKELETON, SCHEMA & ACCOUNTS (~30 min)
**Exit criterion:** `uvicorn app:app --reload` starts, tables exist, and accounts can be created and read via `/docs`.
* **1A:** `schema.sql`, `db.py` (pool from `DATABASE_URL`, apply schema), empty `app.py`.
  * Commit: `project skeleton and schema`
* **1B:** `POST /accounts`, `GET /accounts/{id}`, with strict validation and tests.
  * Commit: `create account and get balance`

### PHASE 2: TRANSFERS & CONCURRENCY PROOF (~75 min) ⚠️ MOST IMPORTANT
**Exit criterion:** The concurrency test passes, AND I have watched it fail against a deliberately broken read-check-write version.
* **2A:** `do_transfer` in `service.py` plus `POST /transfers`:
  * one transaction
  * `SELECT ... FOR UPDATE` on both accounts `ORDER BY id`
  * conditional debit `WHERE balance_cents >= amount`, checking `rowcount`
  * credit
  * insert the transfer row
  * Commit: `transfer endpoint`
* **2B:** Concurrency test: account A = 10000, 50 threads × 1000 to B, released by `threading.Barrier`, each thread on its own pooled connection. Assert:
  * exactly 10 succeed
  * A ends at 0
  * A + B = 10000
  * Commit: `concurrency test for rule 1`
* **2C:** Smoke-detector check. Temporarily replace the safe logic with a plain SELECT → Python check → UPDATE (no `FOR UPDATE`). The test must fail. Revert. **Do not commit the broken version.** I'll record the result in the build log.
* **2D:** Review checkpoint 1: run the `money-reviewer` agent and verify each finding with a test.

### PHASE 3: IDEMPOTENCY (~40 min) ⚠️
**Exit criterion:** 20 threads sending the same key at once result in exactly one applied transfer.
* **3A:** The idempotency key is enforced by the UNIQUE constraint and inserted inside the same transaction.
  * Same key + same payload → return the original transfer (200).
  * Same key + different payload → 409.
  * Commit: `idempotency keys`
* **3B:** Concurrent-duplicate test, plus a sequential replay test and a different-payload test.
  * Commit: `idempotency tests`
* **3C:** Review checkpoint 2: run the `money-reviewer` agent and verify each finding with a test.

### PHASE 4: HISTORY, VALIDATION & HARDENING (~40 min)
**Exit criterion:** All endpoints done, every error path tested, full suite green.
* **4A:** `GET /accounts/{id}/transfers`.
  * Commit: `transaction history`
* **4B:** Validation tests: zero, negative, `10.5`, `"1000"`, self-transfer, unknown account.
  * Commit: `input validation tests`
* **4C (if time):** Bidirectional test: concurrent A→B and B→A, asserting no deadlock and conserved total.
  * Commit: `bidirectional concurrency test`
* **4D:** `reset_db.py` for demos.

### PHASE 5: README, BUILD LOG & DEMO PREP (~45 min)
**Exit criterion:** Repo is pushed, docs are complete, and the demo has been rehearsed.
* Review checkpoint 3: final `money-reviewer` run before writing docs.
* README covers:
  * setup
  * run
  * tests
  * design decisions
  * stack tradeoffs
  * what was cut
  * what's next
  * time spent
* Build log: **written by me** from my notes. Claude may tighten wording only, not invent content.
* Commit: `README and build log`

---

## TESTING RULES

* **Real Postgres only. Never mock the database.** Locking bugs only appear against the real thing.
* Concurrency tests use **`ThreadPoolExecutor` + `threading.Barrier`** so the threads truly overlap.
* **Every thread gets its own connection from the pool.** A shared connection runs everything in sequence, and the test proves nothing.
* Pool max size ≥ 20 so many transfers genuinely run at once.
* Assert **invariants**, not just "no exception":
  * exact success count
  * final balances
  * total money conserved
* **Every important test must be shown to fail against broken code** (the smoke-detector check).
* Tests use fresh accounts and unique idempotency keys (e.g. `uuid4`) so the suite can rerun any time.
* Run: `pytest -v`. Concurrency tests must pass reliably, so rerun them a few times before trusting a green result.

---

## DANGER ZONES — TRAPS TO AVOID

These are the classic "looks right, is wrong" mistakes. If Claude produces any of these, I will flag it, and it goes in the build log.

1. **Read-check-write in Python.** `SELECT balance` → `if balance >= amount` → `UPDATE`. Two requests both read 100 and both debit, so the balance goes negative. Safety must come from the DB.
2. **Floats for money.** Any `float`, `Decimal`, or Pydantic silently coercing `10.5` / `"1000"`. Use integer cents with strict validation.
3. **Split transactions.** Debit and credit committed separately, so a crash between them loses money.
4. **Check-then-insert idempotency.** `SELECT key` → if missing, `INSERT`. Two duplicates both see "missing." The UNIQUE constraint must do the work.
5. **Fake concurrency tests.** No Barrier, one shared connection, or threads that barely overlap. The test passes against broken code.
6. **Mocked database in tests.** It can't catch locking bugs.
7. **"It's safe because it's in a transaction."** Postgres's default isolation (Read Committed) does **not** prevent the read-check-write race on its own.
8. **Unordered locks.** Locking A then B in one transfer and B then A in another causes deadlock.
9. **Swallowed errors.** A broad `except Exception:` that hides a failed write or commits half the work.
10. **`async def` with blocking psycopg calls.** It blocks the event loop and adds complexity for nothing.
11. **Overbuilding.** ORMs, auth, fees, multi-currency, a UI. These are out of scope and are more code to defend live.
12. **Leaking secrets.** The password or connection string in code, tests, README, or commits. Use `DATABASE_URL` only; docs use `postgres://postgres:<password>@localhost:5432/movemoney`.

---

## HOW TO TELL IF CODE IS RIGHT OR WRONG

Judge by **evidence, not appearance**. Confident, clean-looking code is not proof.

1. **Rule checklist.** For any code touching money: can it go negative? Half-finish? Apply twice? Lose a cent? Each answer must be visible in the code or a test.
2. **The two questions.** For every balance or idempotency change, Claude must answer:
   * *What happens if two of these run at the same time?*
   * *What happens if the process crashes between these lines?*
   Then I check the answer actually matches the code.
3. **Tests over explanations.** "It's safe" → write a test. "This test proves X" → break the code and confirm it fails.
4. **Independent review.** The `money-reviewer` subagent (see REVIEW CHECKPOINTS) reviews the code in its own context, without defending what this session wrote.
5. **If Claude is unsure, it says so.** Never claim something is safe without a reason I can verify.

---

## REVIEW CHECKPOINTS (money-reviewer subagent)

`.claude/agents/money-reviewer.md` defines a read-only, skeptical reviewer. It never edits code; it reports findings as concrete failing scenarios with a test that would expose each one.

**Run it whenever I ask.** At minimum, run it at these three points:
1. After Phase 2 (transfer + concurrency test)
2. After Phase 3 (idempotency)
3. Once before submitting

How to call it: *"Use the money-reviewer agent to review the current code."*

**Its findings are claims, not facts.** For each one:
* Write the test it describes and run it.
* If the test fails, the bug is real: fix it, commit the fix with an honest message, and log it.
* If the test passes, the reviewer was wrong: keep the test if it's useful, and log the false alarm. Both outcomes are build-log material.
* Never apply a reviewer suggestion without a test proving it was needed.

Do not use multi-agent debate or "council" skills on this project. They cost far more and replace my judgment, which is the thing KOHO is assessing.

---

## COMMIT & HISTORY RULES

* **Claude commits and pushes** once a step works and its tests pass, then stops so I can review. No `Co-Authored-By` or other AI attribution lines in commit messages.
* **After every commit, Claude updates CURRENT STATUS** (progress box, phase line, test count, "Done so far" table) and commits that with the next change.
* One logical change per commit, with honest messages (including fix commits like `fix: transfer used read-check-write, switch to conditional update`).
* Never stage a fake mistake for the history. If something worked first time, it worked first time.
* Never commit `.venv`, secrets, or `NOTES.md` (my private prep notes).
* Push after each commit so history is backed up.

---

## ENGINEERING GUIDELINES

* **Simple over clever.** I must explain and modify every line live. Aim for a few files and a few hundred lines.
* **Thin endpoints, logic in `service.py`.** Endpoints validate, call one service function, and map exceptions to the error contract.
* **Specific exceptions:** `AccountNotFound`, `InsufficientFunds`, `IdempotencyConflict`. No bare `except`.
* **Contract first.** Any change to the schema or API must update the DATA CONTRACT section above.
* **PowerShell commands** for anything I need to run.

## COMMANDS (PowerShell)

```powershell
.\.venv\Scripts\Activate.ps1          # activate venv (every new terminal)
pip install -r requirements.txt       # install deps
uvicorn app:app --reload              # run server → http://localhost:8000/docs
pytest -v                             # run all tests
pytest -k concurrent -v               # run concurrency tests only
python reset_db.py                    # clean DB before a demo
```
Postgres runs as a Windows service (always on). The connection string is in `DATABASE_URL`.
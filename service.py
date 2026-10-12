from db import pool


class AccountNotFound(Exception):
    pass


class InsufficientFunds(Exception):
    pass


class IdempotencyConflict(Exception):
    pass


def create_account(initial_balance_cents: int) -> dict:
    with pool.connection() as conn:
        row = conn.execute(
            "INSERT INTO accounts (balance_cents) VALUES (%s) RETURNING id, balance_cents",
            (initial_balance_cents,),
        ).fetchone()
    return {"id": row[0], "balance_cents": row[1]}


def get_account(account_id: int) -> dict:
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT id, balance_cents FROM accounts WHERE id = %s", (account_id,)
        ).fetchone()
    if row is None:
        raise AccountNotFound(account_id)
    return {"id": row[0], "balance_cents": row[1]}


TRANSFER_COLUMNS = "id, idempotency_key, from_account_id, to_account_id, amount_cents, created_at"


def do_transfer(idempotency_key: str, from_id: int, to_id: int, amount_cents: int) -> tuple[dict, bool]:
    """Returns (transfer, created). created=False means this key was already applied (a replay)."""
    # Everything below is one transaction: any exception rolls back all of it.
    with pool.connection() as conn, conn.transaction():
        # 1. Lock both rows in id order, so A->B and B->A can't deadlock.
        # Any other transfer touching either account waits here until we commit.
        locked = conn.execute(
            "SELECT id FROM accounts WHERE id IN (%s, %s) ORDER BY id FOR UPDATE",
            (from_id, to_id),
        ).fetchall()
        if len(locked) < 2:
            raise AccountNotFound()

        # 2. Claim the idempotency key BEFORE touching balances, so a retry of a transfer
        # that drained the account is seen as a replay, not as insufficient funds.
        # Must come after the lock: the transfers FKs take a share lock on both accounts,
        # and taking that before FOR UPDATE lets two transfers deadlock.
        # Must also come BEFORE the debit: DO NOTHING doesn't raise, so a conflict after
        # the debit would commit a second payment.
        # If another transaction holds the same key uncommitted, Postgres makes this wait
        # for it: on commit we get no row (conflict), on rollback our insert goes ahead.
        row = conn.execute(
            "INSERT INTO transfers (idempotency_key, from_account_id, to_account_id, amount_cents)"
            " VALUES (%s, %s, %s, %s)"
            " ON CONFLICT (idempotency_key) DO NOTHING"
            f" RETURNING {TRANSFER_COLUMNS}",
            (idempotency_key, from_id, to_id, amount_cents),
        ).fetchone()
        if row is None:
            existing = conn.execute(
                f"SELECT {TRANSFER_COLUMNS} FROM transfers WHERE idempotency_key = %s",
                (idempotency_key,),
            ).fetchone()
            if existing[2:5] != (from_id, to_id, amount_cents):
                raise IdempotencyConflict()
            return _transfer_dict(existing), False

        # 3. The balance check happens in the DB, in the same statement as the debit.
        # Never read the balance into Python and compare: that races.
        debit = conn.execute(
            "UPDATE accounts SET balance_cents = balance_cents - %s"
            " WHERE id = %s AND balance_cents >= %s",
            (amount_cents, from_id, amount_cents),
        )
        if debit.rowcount != 1:
            raise InsufficientFunds()  # rolls back the transfer row too, so the key is unclaimed

        conn.execute(
            "UPDATE accounts SET balance_cents = balance_cents + %s WHERE id = %s",
            (amount_cents, to_id),
        )
    return _transfer_dict(row), True


def _transfer_dict(row) -> dict:
    return dict(zip(TRANSFER_COLUMNS.split(", "), row))


def get_history(account_id: int) -> list[dict]:
    with pool.connection() as conn:
        if conn.execute("SELECT 1 FROM accounts WHERE id = %s", (account_id,)).fetchone() is None:
            raise AccountNotFound(account_id)
        # Newest first by id, not created_at: created_at is now(), the time the transaction
        # *started*, so a transfer that waited on the account lock can carry an older timestamp
        # than one applied before it. ids are drawn inside the INSERT, after FOR UPDATE, so for
        # one account they follow the order its money actually moved.
        rows = conn.execute(
            f"SELECT {TRANSFER_COLUMNS} FROM transfers"
            " WHERE from_account_id = %s OR to_account_id = %s"
            " ORDER BY id DESC",
            (account_id, account_id),
        ).fetchall()
    return [_transfer_dict(r) for r in rows]

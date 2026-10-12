from db import pool


class AccountNotFound(Exception):
    pass


class InsufficientFunds(Exception):
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


def do_transfer(idempotency_key: str, from_id: int, to_id: int, amount_cents: int) -> dict:
    # Everything below is one transaction: any exception rolls back all of it.
    with pool.connection() as conn, conn.transaction():
        # Lock both rows in id order, so A->B and B->A can't deadlock.
        # Any other transfer touching either account waits here until we commit.
        locked = conn.execute(
            "SELECT id FROM accounts WHERE id IN (%s, %s) ORDER BY id FOR UPDATE",
            (from_id, to_id),
        ).fetchall()
        if len(locked) < 2:
            raise AccountNotFound()

        # The balance check happens in the DB, in the same statement as the debit.
        # Never read the balance into Python and compare: that races.
        debit = conn.execute(
            "UPDATE accounts SET balance_cents = balance_cents - %s"
            " WHERE id = %s AND balance_cents >= %s",
            (amount_cents, from_id, amount_cents),
        )
        if debit.rowcount != 1:
            raise InsufficientFunds()

        conn.execute(
            "UPDATE accounts SET balance_cents = balance_cents + %s WHERE id = %s",
            (amount_cents, to_id),
        )
        row = conn.execute(
            "INSERT INTO transfers (idempotency_key, from_account_id, to_account_id, amount_cents)"
            " VALUES (%s, %s, %s, %s)"
            " RETURNING id, idempotency_key, from_account_id, to_account_id, amount_cents, created_at",
            (idempotency_key, from_id, to_id, amount_cents),
        ).fetchone()
    return _transfer_dict(row)


def _transfer_dict(row) -> dict:
    keys = ("id", "idempotency_key", "from_account_id", "to_account_id", "amount_cents", "created_at")
    return dict(zip(keys, row))

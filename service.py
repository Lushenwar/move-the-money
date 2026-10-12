from db import pool


class AccountNotFound(Exception):
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

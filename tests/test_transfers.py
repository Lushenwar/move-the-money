import time
from uuid import uuid4

import psycopg
import pytest

import service
from conftest import balance, new_account
from db import pool

BIGINT_MAX = 2**63 - 1


def transfer_body(from_id, to_id, amount):
    return {
        "idempotency_key": str(uuid4()),
        "from_account_id": from_id,
        "to_account_id": to_id,
        "amount_cents": amount,
    }


def test_transfer_moves_money(client):
    a, b = new_account(10000), new_account(0)
    body = transfer_body(a, b, 3000)

    r = client.post("/transfers", json=body)

    assert r.status_code == 201
    t = r.json()
    assert (t["from_account_id"], t["to_account_id"], t["amount_cents"]) == (a, b, 3000)
    assert t["idempotency_key"] == body["idempotency_key"]
    assert balance(a) == 7000
    assert balance(b) == 3000


def test_transfer_entire_balance_allowed(client):
    a, b = new_account(500), new_account(0)
    assert client.post("/transfers", json=transfer_body(a, b, 500)).status_code == 201
    assert balance(a) == 0
    assert balance(b) == 500


def test_insufficient_funds_changes_nothing(client):
    a, b = new_account(500), new_account(100)

    r = client.post("/transfers", json=transfer_body(a, b, 501))

    assert r.status_code == 422
    assert r.json() == {"error": "insufficient_funds"}
    assert balance(a) == 500
    assert balance(b) == 100


@pytest.mark.parametrize("missing", ["from", "to"])
def test_unknown_account_404_changes_nothing(client, missing):
    real = new_account(1000)
    ids = (BIGINT_MAX, real) if missing == "from" else (real, BIGINT_MAX)

    r = client.post("/transfers", json=transfer_body(*ids, 100))

    assert r.status_code == 404
    assert r.json() == {"error": "account_not_found"}
    assert balance(real) == 1000


def test_failed_credit_rolls_back_debit():
    # Rule 2: crediting B overflows BIGINT, so the statement after the debit fails.
    # The debit on A must be rolled back with it.
    a, b = new_account(100), new_account(BIGINT_MAX)

    with pytest.raises(psycopg.errors.NumericValueOutOfRange):
        service.do_transfer(str(uuid4()), a, b, 100)

    assert balance(a) == 100
    assert balance(b) == BIGINT_MAX


def test_history_sent_and_received_newest_first(client):
    a, b, c, other = new_account(1000), new_account(1000), new_account(0), new_account(1000)
    sent = client.post("/transfers", json=transfer_body(a, b, 100)).json()
    received = client.post("/transfers", json=transfer_body(b, a, 30)).json()
    client.post("/transfers", json=transfer_body(b, c, 50))  # doesn't involve a
    client.post("/transfers", json=transfer_body(other, c, 50))  # doesn't involve a

    r = client.get(f"/accounts/{a}/transfers")

    assert r.status_code == 200
    assert [t["id"] for t in r.json()] == [received["id"], sent["id"]]


def test_history_excludes_failed_transfers_and_replays(client):
    a, b = new_account(100), new_account(0)
    body = transfer_body(a, b, 100)
    client.post("/transfers", json=body)
    client.post("/transfers", json=body)  # replay
    client.post("/transfers", json=transfer_body(a, b, 1))  # insufficient funds

    history = client.get(f"/accounts/{a}/transfers").json()

    assert [t["idempotency_key"] for t in history] == [body["idempotency_key"]]


def test_history_new_account_is_empty(client):
    r = client.get(f"/accounts/{new_account(0)}/transfers")
    assert r.status_code == 200
    assert r.json() == []


def test_history_unknown_account_404(client):
    r = client.get(f"/accounts/{BIGINT_MAX}/transfers")
    assert r.status_code == 404
    assert r.json() == {"error": "account_not_found"}


def test_history_orders_by_when_applied_not_when_transaction_started():
    # created_at is now(), the transaction START time. A transaction that starts first but
    # writes last (e.g. it waited on the account lock) gets the older created_at.
    # History must still list it first, because it happened last.
    a, b = new_account(1000), new_account(0)
    with pool.connection() as slow:
        slow.execute("SELECT 1")  # slow's transaction starts now, fixing its now()
        time.sleep(0.05)
        fast, _ = service.do_transfer(str(uuid4()), a, b, 100)  # starts later, commits first
        slow_id, slow_created = slow.execute(
            "INSERT INTO transfers (idempotency_key, from_account_id, to_account_id, amount_cents)"
            " VALUES (%s, %s, %s, 1) RETURNING id, created_at",  # row only: this test is about order
            (str(uuid4()), a, b),
        ).fetchone()

    assert slow_created < fast["created_at"]  # the timestamps disagree with what happened...
    assert [t["id"] for t in service.get_history(a)] == [slow_id, fast["id"]]  # ...history doesn't

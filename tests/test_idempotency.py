import threading
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import service
from conftest import balance, new_account


def transfer_body(from_id, to_id, amount, key=None):
    return {
        "idempotency_key": key or str(uuid4()),
        "from_account_id": from_id,
        "to_account_id": to_id,
        "amount_cents": amount,
    }


def test_replay_returns_original_and_moves_money_once(client):
    a, b = new_account(1000), new_account(0)
    body = transfer_body(a, b, 300)

    first = client.post("/transfers", json=body)
    replay = client.post("/transfers", json=body)

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert balance(a) == 700
    assert balance(b) == 300


def test_replay_after_balance_drained_returns_200_not_422(client):
    # The retry must be recognised as a replay before the balance check,
    # otherwise the client is told "insufficient funds" for a payment that went through.
    a, b = new_account(100), new_account(0)
    body = transfer_body(a, b, 100)

    first = client.post("/transfers", json=body)
    replay = client.post("/transfers", json=body)

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert balance(a) == 0
    assert balance(b) == 100


def test_same_key_different_payload_409(client):
    a, b, c = new_account(1000), new_account(0), new_account(1000)
    body = transfer_body(a, b, 100)
    assert client.post("/transfers", json=body).status_code == 201

    for change in [{"amount_cents": 200}, {"to_account_id": c}, {"from_account_id": c}]:
        r = client.post("/transfers", json={**body, **change})
        assert r.status_code == 409, change
        assert r.json() == {"error": "idempotency_key_conflict"}

    assert (balance(a), balance(b), balance(c)) == (900, 100, 1000)


def test_failed_transfer_does_not_claim_key(client):
    # Failed transfers aren't recorded, so a retry with the same key is a new attempt.
    a, b, funder = new_account(50), new_account(0), new_account(1000)
    body = transfer_body(a, b, 100)
    assert client.post("/transfers", json=body).status_code == 422

    assert client.post("/transfers", json=transfer_body(funder, a, 50)).status_code == 201
    retry = client.post("/transfers", json=body)

    assert retry.status_code == 201
    assert (balance(a), balance(b)) == (0, 100)


def test_concurrent_duplicates_apply_once():
    # Rule 3: 20 threads send the same key at the same instant. One applies, 19 replay.
    a, b = new_account(10000), new_account(0)
    key = str(uuid4())
    threads = 20
    barrier = threading.Barrier(threads, timeout=10)

    def attempt(_):
        barrier.wait()
        return service.do_transfer(key, a, b, 1000)  # any exception fails the test

    with ThreadPoolExecutor(max_workers=threads) as pool:
        results = list(pool.map(attempt, range(threads)))

    created = [was_created for _, was_created in results]
    assert created.count(True) == 1
    assert created.count(False) == 19
    assert len({t["id"] for t, _ in results}) == 1  # every caller got the same transfer
    assert balance(a) == 9000
    assert balance(b) == 1000


def test_concurrent_same_key_different_accounts():
    # Each thread uses its own account pair, so the FOR UPDATE account locks don't serialize
    # them: only the UNIQUE key does. One must apply, the other 19 get a clean 409, never a 500.
    key = str(uuid4())
    threads = 20
    pairs = [(new_account(1000), new_account(0)) for _ in range(threads)]
    barrier = threading.Barrier(threads, timeout=10)

    def attempt(pair):
        barrier.wait()
        try:
            service.do_transfer(key, pair[0], pair[1], 100)
            return "created"
        except service.IdempotencyConflict:
            return "conflict"  # any other exception (e.g. UniqueViolation) fails the test

    with ThreadPoolExecutor(max_workers=threads) as pool:
        results = list(pool.map(attempt, pairs))

    assert results.count("created") == 1
    assert results.count("conflict") == 19
    moved = [(balance(a), balance(b)) for a, b in pairs]
    assert moved.count((900, 100)) == 1
    assert moved.count((1000, 0)) == 19

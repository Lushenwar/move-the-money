import pytest

BIGINT_MAX = 2**63 - 1


def test_create_and_get_account(client):
    r = client.post("/accounts", json={"initial_balance_cents": 10000})
    assert r.status_code == 201
    account = r.json()
    assert account["balance_cents"] == 10000

    r = client.get(f"/accounts/{account['id']}")
    assert r.status_code == 200
    assert r.json() == account


def test_zero_starting_balance_allowed(client):
    r = client.post("/accounts", json={"initial_balance_cents": 0})
    assert r.status_code == 201
    assert r.json()["balance_cents"] == 0


def test_bigint_max_allowed(client):
    r = client.post("/accounts", json={"initial_balance_cents": BIGINT_MAX})
    assert r.status_code == 201
    assert r.json()["balance_cents"] == BIGINT_MAX


@pytest.mark.parametrize("bad", [10.5, 100.0, "1000", -1, True, None, BIGINT_MAX + 1, 99999999999999999999])
def test_invalid_initial_balance_rejected(client, bad):
    r = client.post("/accounts", json={"initial_balance_cents": bad})
    assert r.status_code == 422


def test_missing_balance_rejected(client):
    assert client.post("/accounts", json={}).status_code == 422


def test_unknown_account_404(client):
    r = client.get(f"/accounts/{BIGINT_MAX}")
    assert r.status_code == 404
    assert r.json() == {"error": "account_not_found"}


@pytest.mark.parametrize("bad_id", ["0", "-1", "abc", str(BIGINT_MAX + 1)])
def test_bad_account_id_rejected(client, bad_id):
    assert client.get(f"/accounts/{bad_id}").status_code == 422

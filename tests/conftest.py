import sys
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))  # so tests can import app, service

from app import app  # noqa: E402  (importing app also applies the schema)
import service  # noqa: E402


# No table wipes: every test creates its own fresh accounts, so the suite can rerun any time.
@pytest.fixture
def client():
    return TestClient(app)


def new_account(balance_cents):
    return service.create_account(balance_cents)["id"]


def balance(account_id):
    return service.get_account(account_id)["balance_cents"]


def transfer_body(from_id, to_id, amount, key=None):
    return {
        "idempotency_key": key or str(uuid4()),
        "from_account_id": from_id,
        "to_account_id": to_id,
        "amount_cents": amount,
    }

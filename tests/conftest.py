import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))  # so tests can import app, service

from app import app  # noqa: E402  (importing app also applies the schema)


# No table wipes: every test creates its own fresh accounts, so the suite can rerun any time.
@pytest.fixture
def client():
    return TestClient(app)

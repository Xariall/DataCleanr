import os
import tempfile

import pytest
from fastapi.testclient import TestClient

# Point DB to a temp file for each test session
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ.setdefault("DATABASE_PATH", _tmp_db.name)
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("STRIPE_SECRET_KEY", "sk_test_fake")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "whsec_fake")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")

from app.main import app  # noqa: E402 — import after env is set
from app.database import init_db, hash_key, generate_api_key  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path):
    """Give each test a clean database."""
    db_path = str(tmp_path / "test.db")
    os.environ["DATABASE_PATH"] = db_path
    import app.database as db_module
    db_module.DATABASE_PATH = db_path
    init_db()
    yield
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def registered_user(fresh_db):
    """Register a free-tier user and return (email, api_key)."""
    from app.database import create_user
    email = "test@example.com"
    api_key = create_user(email)
    return email, api_key


CSV_FIXTURE = b"name,email,age\nAlice,alice@x.com,30\nBob,,25\nBob,,25\n"

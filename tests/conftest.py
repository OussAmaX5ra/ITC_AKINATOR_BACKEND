"""
tests/conftest.py — Global pytest fixtures.

Configures an isolated testing application using in-memory SQLite
and test client fixtures.  Redis is replaced by fakeredis so tests
run without a real Redis server.
"""

import pytest
import fakeredis
from app import create_app
from app.extensions import db, redis_client


@pytest.fixture(scope="session")
def app():
    """Create and configure application for testing."""
    _app = create_app("testing")

    # ── Swap the real Redis client for an in-process fake ──────────────────
    fake = fakeredis.FakeRedis(decode_responses=True)
    redis_client._client = fake
    _app.extensions["redis"] = fake
    # ───────────────────────────────────────────────────────────────────────

    with _app.app_context():
        db.create_all()
        yield _app
        db.drop_all()


@pytest.fixture
def client(app):
    """Test client for issuing HTTP requests."""
    return app.test_client()


@pytest.fixture
def runner(app):
    """CLI test runner."""
    return app.test_cli_runner()


@pytest.fixture
def fake_redis(app):
    """Return the fakeredis client and flush it before each test."""
    r = app.extensions["redis"]
    r.flushdb()
    return r

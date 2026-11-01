"""
tests/conftest.py — Global pytest fixtures.

Configures an isolated testing application using in-memory SQLite
and test client fixtures.
"""

import pytest
from app import create_app
from app.extensions import db


@pytest.fixture(scope="session")
def app():
    """Create and configure application for testing."""
    _app = create_app("testing")

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

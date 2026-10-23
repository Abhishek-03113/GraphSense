"""Shared test configuration.

Importing the application needs no database settings (everything is read
lazily; ``tests/test_config.py`` proves it in a clean subprocess).  Requests
that resolve the session dependency do build a session factory, though, so
each test gets a placeholder DSN.  Nothing connects: engines are lazy and the
tests that run queries use recording or scripted sessions.
"""

import pytest

from src.config import reset_settings


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("DATABASE_DSN", "postgresql+asyncpg://user:pass@localhost:5432/unused")
    reset_settings()
    yield
    reset_settings()

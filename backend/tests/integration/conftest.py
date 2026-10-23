"""Fixtures for tests that need a real PostgreSQL server.

Set ``TEST_DATABASE_DSN`` to a superuser connection to any database of a
PostgreSQL 16 server, for example ``postgresql://postgres@127.0.0.1:5432/postgres``.
Each test gets a database of its own, cloned from a template that already has the
application migrations applied, and the database is dropped afterwards.  Without
the variable these tests are skipped.  pgvector is not needed.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from src.config import reset_settings
from src.datasets.registry import clear_package_cache
from src.db.migration_runner import apply_pending
from src.storage.engines import (
    async_dsn,
    dispose_sync_engines,
    make_owner_async_engine,
    sync_dsn,
)
from tests.conftest import FIXTURES, TOY_DATA_DIR

ADMIN_DSN = os.environ.get("TEST_DATABASE_DSN")
PACKAGES_DIR = FIXTURES / "packages"
# The real sample data is not in the repository: set O2C_DATA_ROOT to the directory that holds sap-o2c-data.
REAL_DATA_ROOT_CANDIDATES = [
    os.environ.get("O2C_DATA_ROOT"),
    str(Path(__file__).resolve().parents[3] / "data"),
]


def pytest_collection_modifyitems(config, items):
    if ADMIN_DSN:
        return
    skip = pytest.mark.skip(reason="TEST_DATABASE_DSN is not set")
    for item in items:
        if "tests/integration" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.integration)
            item.add_marker(skip)


def real_data_root() -> Path | None:
    for candidate in REAL_DATA_ROOT_CANDIDATES:
        if candidate and (Path(candidate) / "sap-o2c-data").is_dir():
            return Path(candidate)
    return None


@dataclass
class Database:
    name: str
    dsn: str  # asyncpg form, as the application settings carry it
    admin: object

    def sql(self, statement: str, **params):
        """Run a statement as the superuser on this database; returns all rows (or [])."""
        engine = create_engine(sync_dsn(self.dsn))
        try:
            with engine.begin() as conn:
                result = conn.execute(text(statement), params)
                return result.all() if result.returns_rows else []
        finally:
            engine.dispose()

    def scalar(self, statement: str, **params):
        rows = self.sql(statement, **params)
        return rows[0][0] if rows else None


def _admin_engine():
    return create_engine(sync_dsn(ADMIN_DSN), isolation_level="AUTOCOMMIT")


def _dsn_for(name: str) -> str:
    return async_dsn(make_url(ADMIN_DSN).set(database=name).render_as_string(hide_password=False))


@pytest.fixture(scope="session")
def template_database() -> Iterator[str]:
    """A database with the migrations applied, used as a template for each test."""
    name = f"gs_tpl_{uuid.uuid4().hex[:10]}"
    admin = _admin_engine()
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    os.environ["DATABASE_DSN"] = _dsn_for(name)
    reset_settings()

    async def migrate() -> None:
        engine = make_owner_async_engine()
        try:
            await apply_pending(engine)
        finally:
            await engine.dispose()

    asyncio.run(migrate())
    reset_settings()
    yield name
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()


@pytest.fixture
def db(template_database, monkeypatch) -> Iterator[Database]:
    """A fresh migrated database; the application settings point at it."""
    name = f"gs_t_{uuid.uuid4().hex[:10]}"
    admin = _admin_engine()
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}" TEMPLATE "{template_database}"'))
    dsn = _dsn_for(name)
    monkeypatch.setenv("DATABASE_DSN", dsn)
    monkeypatch.delenv("OWNER_DATABASE_DSN", raising=False)
    monkeypatch.setenv("PACKAGES_DIR", str(PACKAGES_DIR))
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("GRAPHSENSE_ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("POST_INGEST_HOOKS", raising=False)
    monkeypatch.delenv("DATA_ROOT", raising=False)
    reset_settings()
    clear_package_cache()
    dispose_sync_engines()
    yield Database(name, dsn, admin)
    dispose_sync_engines()
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    admin.dispose()
    reset_settings()
    clear_package_cache()


@pytest.fixture
async def client(db):
    """An HTTP client on the application (one event loop, so the async engine stays valid)."""
    import httpx

    from src.db.engine import dispose_engine
    from src.main import app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    await dispose_engine()


@pytest.fixture
def toy_root(tmp_path: Path) -> Path:
    """A private copy of the toy data root (tests edit it freely): ``<root>/toy-library/...``."""
    root = tmp_path / "toy-root"
    shutil.copytree(TOY_DATA_DIR, root / "toy-library")
    return root


@pytest.fixture
def demo_root(tmp_path: Path) -> Path:
    """Synthetic data in the raw export shape, written by ``scripts/make_demo_data.py``."""
    import importlib.util

    path = Path(__file__).resolve().parents[2] / "scripts" / "make_demo_data.py"
    spec = importlib.util.spec_from_file_location("make_demo_data", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / "demo-root"
    module.write(module.build(7), root)
    return root


@pytest.fixture
def real_root() -> Path:
    root = real_data_root()
    if root is None:
        pytest.skip("the real sample data (data/sap-o2c-data) is not available")
    return root


@pytest.fixture
def use_data_root(monkeypatch) -> Callable[[Path], None]:
    def apply(root: Path) -> None:
        monkeypatch.setenv("DATA_ROOT", str(root))
        reset_settings()

    return apply

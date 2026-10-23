"""Integration fixtures for the Ask layer: a throwaway database with real PostgreSQL behaviour.

Tests here need ``TEST_DATABASE_DSN`` (a superuser DSN of a PostgreSQL 16 server, for
example ``postgresql://postgres@127.0.0.1:55443/postgres``).  Each test session creates
its own database and roles and drops them afterwards, so it never touches data in the
database the DSN points at.  Without pgvector on the server the vector tests are
skipped (``has_vector`` is False) and everything else still runs.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass

import psycopg2
import pytest
from psycopg2.extras import Json, execute_values
from sqlalchemy.engine import make_url

from src.config import BACKEND_DIR
from src.datasets import row_coercer, schema_ddl
from src.datasets.models import DatasetPackage
from tests.conftest import FIXTURES, TOY_DATA_DIR

MIGRATION = BACKEND_DIR / "migrations" / "schema" / "V20261101000003__knowledge_and_log.sql"

def pytest_collection_modifyitems(items):
    for item in items:
        if "intelligence_pg" in str(item.fspath):
            item.add_marker(pytest.mark.integration)


@dataclass
class PgEnv:
    admin_dsn: str  # superuser, in the throwaway database (postgresql://)
    ro_dsn: str  # SELECT-only role (postgresql://)
    app_dsn_sqlalchemy: str  # admin DSN in SQLAlchemy asyncpg form
    db_name: str
    has_vector: bool
    ro_role: str

    def connect(self):
        conn = psycopg2.connect(self.admin_dsn)
        conn.autocommit = True
        return conn


def _statements(sql: str) -> list[str]:
    """Split a migration file the way the application's migration runner does."""
    lines = [line for line in sql.splitlines() if not line.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


def load_rows(cur, pkg: DatasetPackage, schema: str, records: dict[str, list[dict]]) -> None:
    for table in pkg.tables:
        rows_in = records.get(table.table, [])
        if not rows_in:
            continue
        coerce = row_coercer(table, empty_string_is_null=pkg.ingest.empty_string_is_null)
        pk = [i for i, c in enumerate(table.stored_columns()) if c.name in table.primary_key]
        seen: dict[tuple, tuple] = {}
        for record in rows_in:
            row, issues = coerce(record)
            if any(i.severity == "reject" for i in issues):
                continue
            seen[tuple(row[i] for i in pk)] = row
        columns = ", ".join(f'"{c.name}"' for c in table.stored_columns())
        values = [tuple(Json(v) if isinstance(v, dict | list) else v for v in r) for r in seen.values()]
        execute_values(cur, f'INSERT INTO "{schema}"."{table.table}" ({columns}) VALUES %s', values)


def toy_records() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for folder in sorted(TOY_DATA_DIR.iterdir()):
        records = []
        for part in sorted(folder.glob("*.jsonl")):
            records += [json.loads(line) for line in part.read_text(encoding="utf-8").splitlines() if line.strip()]
        out[folder.name] = records
    return out


def o2c_records() -> dict[str, list[dict]]:
    return json.loads((FIXTURES / "o2c_real_records.json").read_text(encoding="utf-8"))


def create_dataset(cur, pkg: DatasetPackage, records: dict[str, list[dict]]) -> None:
    schema = pkg.schema_name
    cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    for stmt in schema_ddl(pkg, schema):
        cur.execute(stmt)
    load_rows(cur, pkg, schema, records)


@pytest.fixture(scope="session")
def pg(toy_package, o2c_package):
    base = os.environ.get("TEST_DATABASE_DSN")
    if not base:
        pytest.skip("TEST_DATABASE_DSN is not set")
    base = re.sub(r"^postgresql\+\w+://", "postgresql://", base)
    suffix = uuid.uuid4().hex[:8]
    db_name = f"gs_ask_{suffix}"
    ro_role = f"gs_ask_ro_{suffix}"

    admin = psycopg2.connect(base)
    admin.autocommit = True
    try:
        admin.cursor().execute(f'CREATE DATABASE "{db_name}"')
    except psycopg2.Error as exc:
        admin.close()
        pytest.skip(f"cannot create a test database: {exc}")

    url = make_url(base).set(database=db_name)
    admin_dsn = url.render_as_string(hide_password=False)
    conn = psycopg2.connect(admin_dsn)
    conn.autocommit = True
    cur = conn.cursor()

    has_vector = True
    try:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
    except psycopg2.Error:
        has_vector = False
    statements = _statements(MIGRATION.read_text(encoding="utf-8"))
    for stmt in statements:
        if not has_vector:
            if stmt.startswith("CREATE EXTENSION"):
                continue
            stmt = re.sub(r"^\s*embedding\s+vector,\s*$", "", stmt, flags=re.MULTILINE)
        cur.execute(stmt)

    create_dataset(cur, toy_package, toy_records())
    create_dataset(cur, o2c_package, o2c_records())

    cur.execute(f"CREATE ROLE {ro_role} LOGIN PASSWORD 'ro'")
    cur.execute(f'GRANT CONNECT ON DATABASE "{db_name}" TO {ro_role}')
    for schema in (toy_package.schema_name, o2c_package.schema_name):
        cur.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO {ro_role}')
        cur.execute(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO {ro_role}')
    # No privileges at all on app.* or public for the read-only role.
    cur.execute(f"REVOKE ALL ON SCHEMA public FROM {ro_role}")
    conn.close()

    ro_dsn = url.set(username=ro_role, password="ro").render_as_string(hide_password=False)
    env = PgEnv(
        admin_dsn=admin_dsn,
        ro_dsn=ro_dsn,
        app_dsn_sqlalchemy=admin_dsn.replace("postgresql://", "postgresql+asyncpg://", 1),
        db_name=db_name,
        has_vector=has_vector,
        ro_role=ro_role,
    )
    yield env

    cleanup = psycopg2.connect(base)
    cleanup.autocommit = True
    c = cleanup.cursor()
    c.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
        (db_name,),
    )
    c.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
    c.execute(f"DROP ROLE IF EXISTS {ro_role}")
    cleanup.close()
    admin.close()


@pytest.fixture
def toy_ctx(toy_package):
    from src.datasets.context import DatasetContext

    return DatasetContext(id=toy_package.id, schema_name=toy_package.schema_name, package=toy_package)


@pytest.fixture
def o2c_ctx(o2c_package):
    from src.datasets.context import DatasetContext

    return DatasetContext(id=o2c_package.id, schema_name=o2c_package.schema_name, package=o2c_package)


@pytest.fixture
def app_engine(pg):
    """An async engine on the admin DSN of the throwaway database (a fresh one per test)."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    return create_async_engine(pg.app_dsn_sqlalchemy, poolclass=NullPool)


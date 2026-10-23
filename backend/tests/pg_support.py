"""Helpers for integration tests that need a real PostgreSQL (``TEST_DATABASE_DSN``).

Datasets are loaded with the package's own DDL and row coercion, independently
of the ingestion engine, so catalog tests do not depend on it.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from psycopg2.extras import Json, execute_values
from sqlalchemy import Engine, create_engine, text

from src.config import BACKEND_DIR
from src.datasets import row_coercer, schema_ddl
from src.datasets.ddl import qualified, quote_ident
from src.datasets.models import DatasetPackage

MIGRATIONS = BACKEND_DIR / "migrations" / "schema"
CATALOG_MIGRATION = MIGRATIONS / "V20261101000002__catalog.sql"


def database_dsn() -> str | None:
    value = os.environ.get("TEST_DATABASE_DSN", "").strip()
    return value or None


def _with_driver(dsn: str, driver: str) -> str:
    return re.sub(r"^postgres(?:ql)?(?:\+\w+)?://", f"postgresql+{driver}://", dsn)


def sync_url(dsn: str) -> str:
    return _with_driver(dsn, "psycopg2")


def async_url(dsn: str) -> str:
    return _with_driver(dsn, "asyncpg")


def sync_engine(dsn: str) -> Engine:
    return create_engine(sync_url(dsn))


def real_data_dir() -> Path | None:
    """The sample O2C source data (git-ignored, so searched for), or None when it is not on this machine."""
    candidates = [Path(p) for p in [os.environ.get("O2C_DATA_DIR")] if p]
    candidates += [parent / "data" / "sap-o2c-data" for parent in BACKEND_DIR.parents]
    return next((c for c in candidates if c.is_dir()), None)


def run_sql_file(engine: Engine, path: Path) -> None:
    """Run a migration file the way the migration runner does: comment lines dropped, split on semicolons."""
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if not line.strip().startswith("--")]
    with engine.begin() as conn:
        for statement in "\n".join(lines).split(";"):
            if statement.strip():
                conn.execute(text(statement))


def reset_catalog_tables(engine: Engine) -> None:
    with engine.begin() as conn:
        for table in ("catalog_relationships", "catalog_columns", "catalog_tables", "catalog_builds"):
            conn.execute(text(f"TRUNCATE app.{table}"))


def create_schema(engine: Engine, pkg: DatasetPackage, schema: str) -> None:
    with engine.begin() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        for statement in schema_ddl(pkg, schema):
            conn.execute(text(statement))


def load_source(engine: Engine, pkg: DatasetPackage, schema: str, source_dir: Path) -> dict[str, int]:
    """Create ``schema`` from the package and load every table from ``source_dir`` (JSON lines).

    Returns ``{table: rows loaded}``.  Rows the coercer rejects are skipped.
    """
    create_schema(engine, pkg, schema)
    counts: dict[str, int] = {}
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        for table in pkg.tables:
            coerce = row_coercer(table, empty_string_is_null=pkg.ingest.empty_string_is_null)
            rows = []
            directory = source_dir / table.source.path
            for file in sorted(directory.glob("*.jsonl")) if directory.is_dir() else []:
                with file.open(encoding="utf-8") as handle:
                    for line in handle:
                        if not line.strip():
                            continue
                        row, issues = coerce(json.loads(line))
                        if not any(i.severity == "reject" for i in issues):
                            rows.append(tuple(Json(v) if isinstance(v, dict | list) else v for v in row))
            if rows:
                cols = ", ".join(quote_ident(c.name) for c in table.stored_columns())
                pk = ", ".join(quote_ident(c) for c in table.primary_key)
                execute_values(
                    cur,
                    f"INSERT INTO {qualified(schema, table.table)} ({cols}) VALUES %s "
                    f"ON CONFLICT ({pk}) DO NOTHING",
                    rows,
                    page_size=1000,
                )
            counts[table.table] = len(rows)
        raw.commit()
    finally:
        raw.close()
    return counts

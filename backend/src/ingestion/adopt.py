"""Adopting a stage-1 database: dataset tables that live in ``public``.

Before dataset packages, the dataset tables were created in the ``public``
schema by a migration.  Adoption moves them into the dataset's own schema
(``ALTER TABLE ... SET SCHEMA`` is metadata only, so it is instant and keeps the
data), registers the dataset, adds the indexes the package declares, and, by
default, leaves a view with each table's old name in ``public`` so an older
application image keeps working.

It is idempotent, runs in one transaction, and is reversible
(:func:`revert_adoption`, or ``ALTER TABLE ... SET SCHEMA public`` by hand).
Item numbers keep their old padding until the next ``graphsense ingest``;
the graph queries tolerate both forms.  Take a backup before the first run.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy import Connection, Engine, insert, text

from src.datasets.ddl import index_ddl, qualified, quote_ident, table_ddl, table_indexes
from src.datasets.models import DatasetPackage, TableSpec
from src.ingestion.report import IngestBusy, IngestError
from src.storage import schema_manager as sm
from src.storage.app_tables import ingestion_issues, ingestion_runs
from src.storage.engines import get_owner_sync_engine
from src.storage.roles import existing_roles, grant_read
from src.storage.schema_names import live_schema

logger = structlog.get_logger(__name__)

# Package type -> database types that hold it.  ``varchar`` counts as ``text``.
_COMPATIBLE: dict[str, set[str]] = {
    "text": {"text", "character varying", "character"},
    "integer": {"integer", "smallint"},
    "bigint": {"bigint", "integer"},
    "decimal": {"numeric"},
    "boolean": {"boolean"},
    "date": {"date"},
    "time": {"time without time zone", "time with time zone"},
    "timestamp": {"timestamp with time zone"},
    "json": {"jsonb", "json"},
}


@dataclass
class AdoptReport:
    dataset_id: str
    adopted: bool = False
    reason: str | None = None
    run_id: str | None = None
    tables: dict[str, int] = field(default_factory=dict)  # table -> rows
    drift_errors: list[str] = field(default_factory=list)
    drift_warnings: list[str] = field(default_factory=list)
    added_columns: list[str] = field(default_factory=list)
    indexes_created: int = 0
    compat_views: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "adopted": self.adopted,
            "reason": self.reason,
            "tables": self.tables,
            "drift_errors": self.drift_errors,
            "drift_warnings": self.drift_warnings,
            "added_columns": self.added_columns,
            "indexes_created": self.indexes_created,
            "compat_views": self.compat_views,
        }


def _live_columns(conn: Connection, schema: str, table: str) -> dict[str, tuple[str, str]]:
    rows = conn.execute(
        text(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_schema = :s AND table_name = :t"
        ),
        {"s": schema, "t": table},
    )
    return {r[0]: (r[1], r[2]) for r in rows}


def compare_table(conn: Connection, table: TableSpec, schema: str = "public") -> tuple[list[str], list[str], list[Any]]:
    """Compare the live columns of ``schema.table`` with the package: ``(errors, warnings, addable columns)``."""
    live = _live_columns(conn, schema, table.table)
    errors: list[str] = []
    warnings: list[str] = []
    addable = []
    for col in table.stored_columns():
        found = live.get(col.name)
        if found is None:
            if col.nullable:
                addable.append(col)
            else:
                errors.append(f"{table.table}.{col.name}: required column is missing")
            continue
        if found[0] not in _COMPATIBLE[col.sql_type.kind]:
            warnings.append(f"{table.table}.{col.name}: stored as {found[0]}, the package says {col.sql_type}")
    declared = {c.name for c in table.stored_columns()}
    for name in sorted(set(live) - declared):
        warnings.append(f"{table.table}.{name}: column is not in the package")
    return errors, warnings, addable


def _if_not_exists(statement: str) -> str:
    return statement.replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ", 1)


def adopt_legacy(
    package: DatasetPackage,
    *,
    engine: Engine | None = None,
    compat_views: bool = True,
    if_needed: bool = False,
    allow_drift: bool = False,
    triggered_by: str | None = "cli",
) -> AdoptReport:
    """Move the package's tables from ``public`` into the dataset schema.  See the module docstring."""
    engine = engine or get_owner_sync_engine()
    dataset_id = package.id
    schema = live_schema(dataset_id)
    report = AdoptReport(dataset_id)

    lock = sm.DatasetLock(engine, dataset_id)
    if not lock.acquire():
        raise IngestBusy()
    try:
        with engine.begin() as conn:
            if not sm.has_app_schema(conn):
                raise IngestError("not_migrated", "The application schema is missing. Run `graphsense db migrate` first.")
            conn.exec_driver_sql("SET LOCAL lock_timeout = '15s'")
            conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"graphsense:swap:{dataset_id}"})

            if sm.schema_exists(conn, schema) and sm.tables_in(conn, schema):
                report.reason = "already_adopted"
                return report

            public = set(sm.tables_in(conn, "public"))
            present = [t for t in package.tables if t.table in public]
            if not present:
                report.reason = "no_legacy_tables"
                if if_needed:
                    return report
                raise IngestError("no_legacy_tables", "There are no stage-1 dataset tables in the public schema to adopt.")

            addable_by_table: dict[str, list[Any]] = {}
            for table in package.tables:
                if table.table not in public:
                    report.drift_errors.append(f"{table.table}: table is missing")
                    continue
                errors, warnings, addable = compare_table(conn, table)
                report.drift_errors += errors
                report.drift_warnings += warnings
                addable_by_table[table.table] = addable
            if report.drift_errors and not allow_drift:
                raise IngestError(
                    "drift",
                    "The existing tables do not match the package: " + "; ".join(report.drift_errors[:8])
                    + (" ..." if len(report.drift_errors) > 8 else "") + " (use --allow-drift to adopt anyway).",
                )

            conn.exec_driver_sql(f"CREATE SCHEMA IF NOT EXISTS {quote_ident(schema)}")
            for table in package.tables:
                name = table.table
                if name in public:
                    for col in addable_by_table.get(name, []):
                        conn.exec_driver_sql(
                            f"ALTER TABLE public.{quote_ident(name)} ADD COLUMN {quote_ident(col.name)} {col.sql_type.ddl}"
                        )
                        report.added_columns.append(f"{name}.{col.name}")
                    report.tables[name] = int(
                        conn.exec_driver_sql(f"SELECT count(*) FROM public.{quote_ident(name)}").scalar_one()
                    )
                    conn.exec_driver_sql(f"ALTER TABLE public.{quote_ident(name)} SET SCHEMA {quote_ident(schema)}")
                else:  # drift allowed: an empty table keeps the graph queries valid
                    conn.exec_driver_sql(table_ddl(table, schema))
                    report.tables[name] = 0
            for table in package.tables:
                for columns in table_indexes(package, table):
                    conn.exec_driver_sql(_if_not_exists(index_ddl(table, columns, schema)))
                    report.indexes_created += 1
            grant_read(conn, schema, existing_roles(conn))
            if compat_views:
                sm.create_compat_views(conn, schema, [t.table for t in package.tables])
            report.compat_views = compat_views

            run_id = str(uuid.uuid4())
            report.run_id = run_id
            conn.execute(
                insert(ingestion_runs).values(
                    id=run_id, dataset_id=dataset_id, kind="adopt", status="succeeded", phase="done",
                    package_hash=package.content_hash, finished_at=text("now()"), triggered_by=triggered_by,
                    table_counts=report.tables, reject_counts={},
                    report={"package": {"id": package.id, "version": package.version, "hash": package.content_hash},
                            "adopt": report.as_dict(), "tables": {t: {"loaded": n} for t, n in report.tables.items()}},
                )
            )
            findings = [("error", m) for m in report.drift_errors] + [("warning", m) for m in report.drift_warnings]
            if findings:
                conn.execute(
                    insert(ingestion_issues),
                    [
                        {"run_id": run_id, "table_name": m.split(".")[0].split(":")[0], "severity": sev,
                         "code": "schema_drift", "message": m, "count": 1}
                        for sev, m in findings
                    ],
                )
            sm.register_dataset(conn, dataset_id, package, status="legacy", run_id=run_id, compat_views=compat_views)
            report.adopted = True
    finally:
        lock.release()
    logger.info("adopt.done", dataset=dataset_id, tables=len(report.tables), compat_views=compat_views)
    return report


def revert_adoption(package: DatasetPackage, *, engine: Engine | None = None) -> list[str]:
    """Undo :func:`adopt_legacy`: tables go back to ``public``, the compat views and the record are removed.

    Refused when the live generation was produced by an ingestion (use ``rollback`` for that).
    Returns the tables moved.
    """
    engine = engine or get_owner_sync_engine()
    dataset_id = package.id
    schema = live_schema(dataset_id)
    lock = sm.DatasetLock(engine, dataset_id)
    if not lock.acquire():
        raise IngestBusy()
    try:
        with engine.begin() as conn:
            conn.exec_driver_sql("SET LOCAL lock_timeout = '15s'")
            conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"graphsense:swap:{dataset_id}"})
            status = conn.execute(text("SELECT status FROM app.datasets WHERE id = :i"), {"i": dataset_id}).scalar()
            if status != "legacy":
                raise IngestError(
                    "not_adopted",
                    "The live data was not adopted from a stage-1 database. Use `dataset rollback` to go back.",
                )
            tables = sm.tables_in(conn, schema)
            sm.drop_compat_views(conn, tables)
            for name in tables:
                conn.exec_driver_sql(f"ALTER TABLE {qualified(schema, name)} SET SCHEMA public")
            conn.exec_driver_sql(f"DROP SCHEMA {quote_ident(schema)}")
            conn.execute(text("DELETE FROM app.datasets WHERE id = :i"), {"i": dataset_id})
            return tables
    finally:
        lock.release()

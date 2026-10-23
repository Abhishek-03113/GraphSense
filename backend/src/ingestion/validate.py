"""Checks on a freshly loaded generation, before it can go live.

Errors stop the run (nothing is swapped).  Warnings and observations are
recorded and shown to the operator.

Errors
    * a table whose source directory is missing;
    * a required column that no record has;
    * a reject rate above the package's ``max_reject_rate``;
    * a table with fewer rows than its declared ``min_rows``;
    * repeated primary keys under ``on_duplicate_key: error``;
    * unknown source fields under ``unknown_fields: error``.
Observations (severity ``info``)
    * how many rows of a join have no partner row (dangling references);
    * columns that are almost entirely empty.
"""

from __future__ import annotations

from sqlalchemy import Connection

from src.datasets.ddl import qualified, quote_ident
from src.datasets.models import DatasetPackage
from src.datasets.relationships import package_relationships
from src.ingestion.report import IssueCollector, TableResult

HIGH_NULL_RATE = 0.99
MIN_ROWS_FOR_NULL_CHECK = 20


def check_tables(
    package: DatasetPackage,
    results: dict[str, TableResult],
    missing: list[str],
    issues: IssueCollector,
    *,
    max_reject_rate: float | None = None,
) -> None:
    """Checks that need only the load results."""
    limit = package.ingest.max_reject_rate if max_reject_rate is None else max_reject_rate
    for name in missing:
        issues.add(name, "error", "source_missing", "The table's source directory does not exist.")
    for table in package.tables:
        res = results.get(table.table)
        if res is None:
            continue
        if res.rejected and res.reject_rate() > limit:
            issues.add(
                table.table, "error", "reject_rate_exceeded",
                f"{res.rejected} of {res.records} records ({res.reject_rate():.2%}) were rejected, "
                f"more than the allowed {limit:.2%}.",
                count=res.rejected,
            )
        if table.min_rows is not None and res.loaded < table.min_rows:
            issues.add(
                table.table, "error", "below_min_rows",
                f"{res.loaded} rows were loaded but the package requires at least {table.min_rows}.",
            )
        if res.records:
            for col in table.columns:
                required = col.required or col.name in table.primary_key
                if required and col.source not in res.columns_seen:
                    issues.add(
                        table.table, "error", "required_column_absent",
                        f"Required column {col.name} (source field {col.source}) is in no record.",
                        column=col.name,
                    )


def observe_data(conn: Connection, package: DatasetPackage, schema: str, results: dict[str, TableResult],
                 issues: IssueCollector) -> None:
    """Observations about the loaded data (cost: one scan per table and one query per join)."""
    for table in package.tables:
        res = results.get(table.table)
        if res is None or res.loaded < MIN_ROWS_FOR_NULL_CHECK:
            continue
        pk = set(table.primary_key)
        cols = [c.name for c in table.columns if c.name not in pk]
        if not cols:
            continue
        counts = ", ".join(f"count({quote_ident(c)})" for c in cols)
        row = conn.exec_driver_sql(f"SELECT {counts} FROM {qualified(schema, table.table)}").one()
        for name, non_null in zip(cols, row, strict=True):
            null_rate = 1 - non_null / res.loaded
            if null_rate >= HIGH_NULL_RATE:
                issues.add(
                    table.table, "info", "high_null_rate",
                    f"Column {name} is empty in {null_rate:.1%} of rows.", column=name, count=res.loaded - non_null,
                )

    for join in package_relationships(package):
        if join.from_table not in results or join.to_table not in results:
            continue
        a, b = qualified(schema, join.from_table), qualified(schema, join.to_table)
        present = " AND ".join(f"a.{quote_ident(c)} IS NOT NULL" for c in join.from_columns)
        match = " AND ".join(
            f"b.{quote_ident(t)} = a.{quote_ident(f)}" for f, t in zip(join.from_columns, join.to_columns, strict=True)
        )
        checked, dangling = conn.exec_driver_sql(
            f"SELECT count(*), count(*) FILTER (WHERE NOT EXISTS (SELECT 1 FROM {b} b WHERE {match})) "
            f"FROM {a} a WHERE {present}"
        ).one()
        if checked and dangling:
            issues.add(
                join.from_table, "info", "dangling_reference",
                f"{dangling} of {checked} rows ({dangling / checked:.1%}) point to no row of {join.to_table} "
                f"({join.expression}).",
                count=dangling,
            )


def error_summary(issues: IssueCollector, limit: int = 5) -> str:
    """A short, safe sentence naming the first blocking findings."""
    parts = []
    for row in issues.rows():
        if row.severity == "error":
            parts.append(f"{row.table_name}: {row.message}")
    if not parts:
        return "Validation failed."
    shown = "; ".join(parts[:limit])
    more = f" (+{len(parts) - limit} more)" if len(parts) > limit else ""
    return f"Validation failed. {shown}{more}"

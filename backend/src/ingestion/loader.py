"""Loading one table's source files into a staging schema.

For each table the loader streams every file (sorted), turns each record into a
typed row with the package's type-driven coercer, and writes the accepted rows
with ``COPY`` into an unconstrained temporary table together with a sequence
number.  One ``INSERT ... SELECT DISTINCT ON (primary key) ... ORDER BY key,
sequence DESC`` then moves them into the real table, so for a repeated key the
record that came last wins, deterministically.  Rejected rows are counted and
sampled, never loaded.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import time
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection

from src.datasets.coerce import row_coercer
from src.datasets.ddl import qualified, quote_ident
from src.datasets.models import DatasetPackage, TableSpec
from src.ingestion.readers import SourceFile, read_records
from src.ingestion.report import IngestError, IssueCollector, TableResult

BATCH_ROWS = 20_000
RAW_TABLE = "_gs_raw"

_ESCAPES = str.maketrans({"\\": "\\\\", "\t": "\\t", "\n": "\\n", "\r": "\\r"})


def copy_field(value: Any) -> str:
    """One value in PostgreSQL's COPY text format (``\\N`` is NULL)."""
    if value is None:
        return "\\N"
    if isinstance(value, bool):
        return "t" if value else "f"
    if isinstance(value, str):
        return value.translate(_ESCAPES)
    if isinstance(value, Decimal | int):
        return str(value)
    if isinstance(value, dt.date | dt.time):  # also datetime
        return value.isoformat()
    if isinstance(value, dict | list):
        return json.dumps(value, separators=(",", ":")).translate(_ESCAPES)
    return str(value).translate(_ESCAPES)


def _has_nul(row: tuple) -> bool:
    return any(isinstance(v, str) and "\x00" in v for v in row)


def load_table(
    conn: Connection,
    package: DatasetPackage,
    table: TableSpec,
    schema: str,
    files: list[SourceFile],
    issues: IssueCollector,
    *,
    expected_hashes: dict[str, str] | None = None,
    tick: Callable[[], None] | None = None,
) -> TableResult:
    """Load ``files`` into ``schema.table`` using ``conn`` (a transaction owned by the caller)."""
    started = time.monotonic()
    result = TableResult(table.table, files=len(files), bytes=sum(f.size for f in files))
    policy = package.ingest
    coerce = row_coercer(table, empty_string_is_null=policy.empty_string_is_null)
    stored = table.stored_columns()
    known_fields = table.source_fields
    target = qualified(schema, table.table)
    columns = ", ".join(quote_ident(c.name) for c in stored)
    pk = ", ".join(quote_ident(c) for c in table.primary_key)

    conn.exec_driver_sql(f"DROP TABLE IF EXISTS pg_temp.{RAW_TABLE}")
    conn.exec_driver_sql(f"CREATE TEMP TABLE {RAW_TABLE} (LIKE {target}, _gs_seq bigint NOT NULL)")
    cursor = conn.connection.cursor()
    copy_sql = f"COPY {RAW_TABLE} ({columns}, _gs_seq) FROM STDIN"

    buffer = io.StringIO()
    buffered = 0
    sequence = 0
    accepted = 0
    unknown: dict[str, int] = {}
    unknown_first: dict[str, tuple[str, int]] = {}

    def flush() -> None:
        nonlocal buffer, buffered
        if buffered:
            buffer.seek(0)
            cursor.copy_expert(copy_sql, buffer)
            buffer = io.StringIO()
            buffered = 0
        if tick:
            tick()

    for source in files:
        digest = hashlib.sha256()
        for line, record, problem in read_records(source.path, digest):
            result.records += 1
            where = {"file": source.name, "line": line}
            if problem is not None or record is None:
                result.rejected += 1
                code = problem.code if problem else "invalid_json"
                message = problem.message if problem else "the line cannot be read"
                issues.add(table.table, "warning", "invalid_text" if code == "invalid_encoding" else code,
                           f"Row rejected: {message}.", sample=where)
                continue

            result.columns_seen.update(record.keys())
            extra = record.keys() - known_fields
            for name in extra:
                unknown[name] = unknown.get(name, 0) + 1
                unknown_first.setdefault(name, (source.name, line))

            row, row_issues = coerce(record)
            rejected = False
            for issue in row_issues:
                sample = dict(where)
                if issue.sample is not None:
                    sample["value"] = issue.sample
                if issue.severity == "reject":
                    rejected = True
                    issues.add(table.table, "warning", issue.code, f"Row rejected: {issue.message}.",
                               column=issue.column, sample=sample)
                else:
                    issues.add(table.table, "warning", issue.code, issue.message, column=issue.column, sample=sample)
            if not rejected and _has_nul(row):
                rejected = True
                issues.add(table.table, "warning", "invalid_text",
                           "Row rejected: text contains a NUL character.", sample=where)
            if rejected:
                result.rejected += 1
                continue

            sequence += 1
            accepted += 1
            buffer.write("\t".join(copy_field(v) for v in row))
            buffer.write(f"\t{sequence}\n")
            buffered += 1
            if buffered >= BATCH_ROWS:
                flush()
        flush()
        if expected_hashes is not None and expected_hashes.get(source.relative) not in (None, digest.hexdigest()):
            raise IngestError("source_changed", f"Table {table.table}: a source file changed while it was being loaded.")

    flush()

    # Last record of a repeated key wins.
    conn.exec_driver_sql(
        f"INSERT INTO {target} ({columns}) "
        f"SELECT DISTINCT ON ({pk}) {columns} FROM {RAW_TABLE} ORDER BY {pk}, _gs_seq DESC"
    )
    result.loaded = int(conn.exec_driver_sql(f"SELECT count(*) FROM {target}").scalar_one())
    result.duplicates = accepted - result.loaded
    conn.exec_driver_sql(f"DROP TABLE {RAW_TABLE}")

    for name, count in sorted(unknown.items()):
        first_file, first_line = unknown_first[name]
        issues.add(
            table.table,
            "error" if policy.unknown_fields == "error" else "warning",
            "unknown_field",
            f"Source field {name!r} is not in the package (not stored). Add it as a column or list it under ignore.",
            column=None,
            sample={"file": first_file, "line": first_line, "field": name},
            count=count,
        )
    if result.duplicates:
        issues.add(
            table.table,
            "error" if policy.on_duplicate_key == "error" else "warning",
            "duplicate_key",
            f"{result.duplicates} record(s) repeated the primary key of a later record "
            + ("and were dropped (the last one wins)." if policy.on_duplicate_key == "last_wins" else "(not allowed)."),
            count=result.duplicates,
        )
    result.duration_ms = int((time.monotonic() - started) * 1000)
    return result

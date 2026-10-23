"""Introspection of a live schema and comparison with the dataset package.

The package says what the tables should look like; ``information_schema`` says
what they do look like.  :func:`detect_drift` reports every difference.  Drift
is information for the operator, never a reason to stop a build: the catalog is
still built for the columns that exist.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

from sqlalchemy import Connection, text

from src.datasets.models import DatasetPackage

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class LiveColumn:
    name: str
    data_type: str  # information_schema.data_type, e.g. "text", "numeric", "timestamp with time zone"
    udt_name: str
    numeric_precision: int | None = None
    numeric_scale: int | None = None
    nullable: bool = True


@dataclass(frozen=True)
class DriftIssue:
    """One difference between the package and the live schema."""

    kind: str  # missing_table | extra_table | missing_column | extra_column | type_mismatch
    severity: Severity
    table: str
    column: str | None
    expected: str | None
    actual: str | None
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def introspect_schema(conn: Connection, schema: str) -> dict[str, dict[str, LiveColumn]]:
    """``{table: {column: LiveColumn}}`` for the base tables of ``schema``."""
    rows = conn.execute(
        text(
            """
            SELECT c.table_name, c.column_name, c.data_type, c.udt_name,
                   c.numeric_precision, c.numeric_scale, c.is_nullable
            FROM information_schema.columns c
            JOIN information_schema.tables t
              ON t.table_schema = c.table_schema AND t.table_name = c.table_name
            WHERE c.table_schema = :schema AND t.table_type = 'BASE TABLE'
            ORDER BY c.table_name, c.ordinal_position
            """
        ),
        {"schema": schema},
    )
    live: dict[str, dict[str, LiveColumn]] = {}
    for r in rows:
        live.setdefault(r.table_name, {})[r.column_name] = LiveColumn(
            name=r.column_name,
            data_type=r.data_type,
            udt_name=r.udt_name,
            numeric_precision=r.numeric_precision,
            numeric_scale=r.numeric_scale,
            nullable=r.is_nullable == "YES",
        )
    return live


def schema_exists(conn: Connection, schema: str) -> bool:
    return bool(
        conn.execute(
            text("SELECT 1 FROM information_schema.schemata WHERE schema_name = :s"), {"s": schema}
        ).first()
    )


def _compatible(expected_kind: str, precision: int | None, scale: int | None, live: LiveColumn) -> bool:
    """Whether a live column can hold the package type.

    ``varchar`` counts as ``text`` (databases adopted from an older layout use it),
    and ``numeric`` without a declared precision accepts any decimal.
    """
    if expected_kind == "text":
        return live.udt_name in ("text", "varchar", "bpchar")
    if expected_kind == "decimal":
        if live.udt_name != "numeric":
            return False
        if live.numeric_precision is None:
            return True
        return live.numeric_precision == precision and live.numeric_scale == scale
    return live.udt_name == {
        "integer": "int4",
        "bigint": "int8",
        "boolean": "bool",
        "date": "date",
        "time": "time",
        "timestamp": "timestamptz",
        "json": "jsonb",
    }[expected_kind]


def _describe(live: LiveColumn) -> str:
    if live.udt_name == "numeric" and live.numeric_precision is not None:
        return f"numeric({live.numeric_precision},{live.numeric_scale})"
    return live.data_type


def detect_drift(
    pkg: DatasetPackage,
    live: dict[str, dict[str, LiveColumn]],
    *,
    shared_schema: bool = False,
) -> list[DriftIssue]:
    """Differences between ``pkg`` and the introspected schema.

    ``shared_schema`` is set when the tables live in a schema that holds other
    things as well (the legacy ``public`` schema); tables the package does not
    know are then not reported.
    """
    issues: list[DriftIssue] = []
    for table in pkg.tables:
        live_cols = live.get(table.table)
        if live_cols is None:
            issues.append(
                DriftIssue(
                    "missing_table", "error", table.table, None, table.table, None,
                    f"table {table.table} is in the package but not in the database",
                )
            )
            continue
        expected = {c.name: c for c in table.stored_columns()}
        for name, col in expected.items():
            found = live_cols.get(name)
            if found is None:
                issues.append(
                    DriftIssue(
                        "missing_column", "error", table.table, name, str(col.sql_type), None,
                        f"column {table.table}.{name} is in the package but not in the database",
                    )
                )
            elif not _compatible(col.sql_type.kind, col.sql_type.precision, col.sql_type.scale, found):
                issues.append(
                    DriftIssue(
                        "type_mismatch", "error", table.table, name, str(col.sql_type), _describe(found),
                        f"column {table.table}.{name} is {_describe(found)} in the database, "
                        f"the package declares {col.sql_type}",
                    )
                )
        for name in live_cols:
            if name not in expected:
                issues.append(
                    DriftIssue(
                        "extra_column", "warning", table.table, name, None, _describe(live_cols[name]),
                        f"column {table.table}.{name} is in the database but not in the package",
                    )
                )
    if not shared_schema:
        known = {t.table for t in pkg.tables}
        for name in sorted(set(live) - known):
            issues.append(
                DriftIssue(
                    "extra_table", "warning", name, None, None, name,
                    f"table {name} is in the database but not in the package",
                )
            )
    return issues

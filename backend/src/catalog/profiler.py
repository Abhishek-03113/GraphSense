"""Profiling of a live table: row counts, null rates, distinct counts, ranges, frequent values.

Cost model: one aggregate query per table (per chunk of 100 columns) for the
statistics, plus one query for the frequent and sample values.  Both read at
most ``sample_rows`` rows of the table, taken in primary-key order so the result
is deterministic; ``row_count`` is always exact.

Sensitive columns (``sensitive: true`` in the package) are counted - null rate
and distinct count are aggregates - but their values are never selected: no
minimum, maximum, frequent value or sample leaves the database.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import Connection, text

from src.datasets.ddl import qualified, quote_ident
from src.datasets.models import StoredColumn, TableSpec

# Columns that hold a coded domain even when each value happens to occur once.
CODED_ROLES = frozenset({"code", "status", "flag", "currency"})
# Types that cannot be ordered, so they have no minimum or maximum.
UNORDERED_KINDS = frozenset({"boolean", "json"})


@dataclass(frozen=True)
class ProfileConfig:
    sample_rows: int = 50_000
    enum_max_distinct: int = 50
    top_n: int = 10
    sample_n: int = 5
    chunk_columns: int = 100
    value_chars: int = 80
    statement_timeout_ms: int = 60_000


@dataclass(frozen=True)
class ColumnProfile:
    name: str
    null_rate: float | None
    distinct_count: int | None
    min_value: str | None = None
    max_value: str | None = None
    # (value, count) pairs, most frequent first.
    top_values: tuple[tuple[str, int], ...] = ()
    sample_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class TableProfile:
    table: str
    row_count: int
    profiled_rows: int
    columns: dict[str, ColumnProfile] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# SQL (pure functions, unit tested)
# ---------------------------------------------------------------------------


def source_query(schema: str, table: TableSpec, columns: Sequence[str], cap: int) -> str:
    """The rows a profile reads: the first ``cap`` rows in primary-key order."""
    cols = ", ".join(quote_ident(c) for c in columns) or "1"
    order = ", ".join(quote_ident(c) for c in table.primary_key)
    return f"SELECT {cols} FROM {qualified(schema, table.table)} ORDER BY {order} LIMIT {int(cap)}"


def stats_query(schema: str, table: TableSpec, columns: Sequence[StoredColumn], cap: int) -> str:
    """One statement with null count, distinct count and (non-sensitive, ordered) min/max per column."""
    parts = ["count(*) AS n"]
    for i, col in enumerate(columns):
        ident = quote_ident(col.name)
        parts.append(f"count(*) FILTER (WHERE {ident} IS NULL) AS nul_{i}")
        parts.append(f"count(DISTINCT {ident}) AS dis_{i}")
        if not col.spec.sensitive and col.sql_type.kind not in UNORDERED_KINDS:
            parts.append(f"min({ident})::text AS min_{i}")
            parts.append(f"max({ident})::text AS max_{i}")
    source = source_query(schema, table, [c.name for c in columns], cap)
    return "SELECT " + ", ".join(parts) + f" FROM ({source}) AS s"


def values_query(
    schema: str,
    table: TableSpec,
    wanted: Sequence[tuple[str, int]],
    cap: int,
    value_chars: int,
) -> str:
    """Frequent values: ``wanted`` is ``(column, how_many)``; rows are ``(i, value, count)``.

    ``i`` is the position in ``wanted``.  Never called for sensitive columns.
    """
    source = source_query(schema, table, [c for c, _ in wanted], cap)
    branches = []
    for i, (name, limit) in enumerate(wanted):
        ident = quote_ident(name)
        branches.append(
            f"(SELECT {i} AS i, left({ident}::text, {int(value_chars) + 1}) AS v, count(*) AS c "
            f"FROM s WHERE {ident} IS NOT NULL GROUP BY {ident} ORDER BY c DESC, v LIMIT {int(limit)})"
        )
    return f"WITH s AS ({source}) " + " UNION ALL ".join(branches)


def wants_top_values(col: StoredColumn, pk: Sequence[str], distinct: int, non_null: int, cfg: ProfileConfig) -> bool:
    """A column is an enumerated domain when it has few distinct values that repeat (or is declared coded)."""
    if distinct < 1 or distinct > cfg.enum_max_distinct:
        return False
    role = col.spec.role
    if role == "id" or (len(pk) == 1 and col.name == pk[0]):
        return False
    return non_null > distinct or role in CODED_ROLES


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _clip(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[: limit - 1] + "…"


def profile_table(conn: Connection, schema: str, table: TableSpec, cfg: ProfileConfig) -> TableProfile:
    """Profile ``table`` in ``schema``.  Raises ``sqlalchemy.exc.SQLAlchemyError`` when a query fails."""
    conn.execute(text(f"SET LOCAL statement_timeout = {int(cfg.statement_timeout_ms)}"))
    stored = list(table.stored_columns())
    profiled = 0
    raw: dict[str, tuple[int, int, str | None, str | None]] = {}
    for start in range(0, len(stored), cfg.chunk_columns):
        chunk = stored[start : start + cfg.chunk_columns]
        row = conn.execute(text(stats_query(schema, table, chunk, cfg.sample_rows))).one()._mapping
        profiled = int(row["n"])
        for i, col in enumerate(chunk):
            raw[col.name] = (
                int(row[f"nul_{i}"]),
                int(row[f"dis_{i}"]),
                row.get(f"min_{i}"),
                row.get(f"max_{i}"),
            )
    if profiled >= cfg.sample_rows:
        row_count = int(conn.execute(text(f"SELECT count(*) FROM {qualified(schema, table.table)}")).scalar_one())
    else:
        row_count = profiled

    pk = table.primary_key
    wanted: list[tuple[str, int]] = []
    kinds: dict[str, str] = {}
    for col in stored:
        nulls, distinct, _, _ = raw[col.name]
        if col.spec.sensitive or distinct == 0:
            continue
        if wants_top_values(col, pk, distinct, profiled - nulls, cfg):
            wanted.append((col.name, cfg.top_n))
            kinds[col.name] = "top"
        else:
            wanted.append((col.name, cfg.sample_n))
            kinds[col.name] = "sample"

    tops: dict[str, list[tuple[str, int]]] = {}
    for start in range(0, len(wanted), 40):
        chunk = wanted[start : start + 40]
        result = conn.execute(text(values_query(schema, table, chunk, cfg.sample_rows, cfg.value_chars)))
        for r in result:
            name = chunk[int(r.i)][0]
            tops.setdefault(name, []).append((_clip(r.v, cfg.value_chars), int(r.c)))

    columns: dict[str, ColumnProfile] = {}
    for col in stored:
        nulls, distinct, low, high = raw[col.name]
        found = tops.get(col.name, [])
        top = tuple(found) if kinds.get(col.name) == "top" else ()
        samples = tuple(v for v, _ in found) if kinds.get(col.name) == "sample" else ()
        columns[col.name] = ColumnProfile(
            name=col.name,
            null_rate=(nulls / profiled) if profiled else None,
            distinct_count=distinct,
            min_value=None if col.spec.sensitive or low is None else _clip(low, cfg.value_chars),
            max_value=None if col.spec.sensitive or high is None else _clip(high, cfg.value_chars),
            top_values=top,
            sample_values=samples,
        )
    return TableProfile(table.table, row_count, profiled, columns)

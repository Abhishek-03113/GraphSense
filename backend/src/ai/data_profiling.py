"""Data profiling module — generates per-table statistical summaries.

Replaces DATA_SUMMARY_QUERIES in training.py with structured, per-table
profiles that embed more precisely than monolithic prose summaries.

Category written to rag_embeddings: "data_profile"
"""

from dataclasses import dataclass
from typing import Optional

import structlog
from sqlalchemy import text

from .embeddings import content_hash, generate_embeddings, upsert_embeddings, clear_category
from .schema_ingestion import ColumnMeta, TableSchema

logger = structlog.get_logger(__name__)

# Max distinct values to check before treating a column as high-cardinality
_CATEGORICAL_CARDINALITY_THRESHOLD = 50

# Numeric types we compute min/max/avg for
_NUMERIC_TYPES = frozenset({
    "integer", "bigint", "smallint", "double precision", "real",
    "numeric", "decimal", "money",
})

# Date/timestamp types we compute min/max for
_DATE_TYPES = frozenset({
    "date", "timestamp without time zone", "timestamp with time zone",
    "time without time zone", "time with time zone",
})

# String/categorical types we compute top values for
_STRING_TYPES = frozenset({"character varying", "character", "text", "uuid"})

# Tables to skip profiling
_EXCLUDED_TABLES = frozenset({"rag_embeddings"})


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ColumnStats:
    column_name: str
    null_rate: float
    top_values: tuple[str, ...]   # For categorical columns (up to 5 values)
    min_val: Optional[str]        # For numeric/date columns
    max_val: Optional[str]
    avg_val: Optional[str]
    true_count: Optional[int]     # For boolean columns
    false_count: Optional[int]


@dataclass(frozen=True)
class TableProfile:
    table_name: str
    row_count: int
    column_stats: tuple[ColumnStats, ...]


# ---------------------------------------------------------------------------
# Profiling helpers
# ---------------------------------------------------------------------------


def _safe_query(conn, sql: str, params: dict | None = None):
    """Execute a query, returning rows or empty list on error."""
    try:
        result = conn.execute(text(sql), params or {})
        return result.fetchall()
    except Exception as e:
        logger.warning("data_profiling.query_failed", sql=sql[:120], error=str(e))
        return []


def profile_table(engine, table: TableSchema) -> Optional[TableProfile]:
    """Run statistical queries for a single table and return a TableProfile."""
    if table.table_name in _EXCLUDED_TABLES:
        return None

    with engine.connect() as conn:
        # Row count
        count_row = _safe_query(conn, f"SELECT COUNT(*) FROM {table.table_name}")
        row_count = int(count_row[0][0]) if count_row else 0

        col_stats: list[ColumnStats] = []
        for col in table.columns:
            col_name = col.column_name
            dtype = col.data_type
            qualified = f'"{col_name}"'

            # Null rate
            null_rows = _safe_query(
                conn,
                f"SELECT COUNT(*) FILTER (WHERE {qualified} IS NULL) FROM {table.table_name}",
            )
            null_count = int(null_rows[0][0]) if null_rows else 0
            null_rate = (null_count / row_count) if row_count > 0 else 0.0

            top_values: tuple[str, ...] = ()
            min_val = max_val = avg_val = None
            true_count = false_count = None

            if dtype == "boolean":
                bool_rows = _safe_query(
                    conn,
                    f"""
                    SELECT
                        COUNT(*) FILTER (WHERE {qualified} = TRUE),
                        COUNT(*) FILTER (WHERE {qualified} = FALSE)
                    FROM {table.table_name}
                    """,
                )
                if bool_rows:
                    true_count = int(bool_rows[0][0])
                    false_count = int(bool_rows[0][1])

            elif dtype in _NUMERIC_TYPES:
                stats_rows = _safe_query(
                    conn,
                    f"""
                    SELECT
                        MIN({qualified})::text,
                        MAX({qualified})::text,
                        ROUND(AVG({qualified})::numeric, 2)::text
                    FROM {table.table_name}
                    """,
                )
                if stats_rows and stats_rows[0][0] is not None:
                    min_val, max_val, avg_val = (
                        str(stats_rows[0][0]),
                        str(stats_rows[0][1]),
                        str(stats_rows[0][2]),
                    )

            elif dtype in _DATE_TYPES:
                date_rows = _safe_query(
                    conn,
                    f"""
                    SELECT MIN({qualified})::text, MAX({qualified})::text
                    FROM {table.table_name}
                    """,
                )
                if date_rows and date_rows[0][0] is not None:
                    min_val, max_val = str(date_rows[0][0]), str(date_rows[0][1])

            elif dtype in _STRING_TYPES:
                # Check cardinality before fetching top values
                card_rows = _safe_query(
                    conn,
                    f"SELECT COUNT(DISTINCT {qualified}) FROM {table.table_name}",
                )
                cardinality = int(card_rows[0][0]) if card_rows else 0
                if 0 < cardinality <= _CATEGORICAL_CARDINALITY_THRESHOLD:
                    top_rows = _safe_query(
                        conn,
                        f"""
                        SELECT {qualified}::text, COUNT(*) AS cnt
                        FROM {table.table_name}
                        WHERE {qualified} IS NOT NULL
                        GROUP BY {qualified}
                        ORDER BY cnt DESC
                        LIMIT 5
                        """,
                    )
                    top_values = tuple(str(r[0]) for r in top_rows)

            col_stats.append(
                ColumnStats(
                    column_name=col_name,
                    null_rate=null_rate,
                    top_values=top_values,
                    min_val=min_val,
                    max_val=max_val,
                    avg_val=avg_val,
                    true_count=true_count,
                    false_count=false_count,
                )
            )

    return TableProfile(
        table_name=table.table_name,
        row_count=row_count,
        column_stats=tuple(col_stats),
    )


def build_profile_text(profile: TableProfile) -> str:
    """Render a TableProfile to a dense natural-language string for embedding."""
    lines: list[str] = [
        f"Table {profile.table_name}: {profile.row_count:,} rows."
    ]

    for cs in profile.column_stats:
        parts: list[str] = []

        if cs.null_rate > 0.0:
            parts.append(f"{cs.null_rate:.0%} null")

        if cs.top_values:
            values_str = ", ".join(cs.top_values)
            parts.append(f"top values: {values_str}")

        if cs.min_val is not None and cs.max_val is not None:
            if cs.avg_val is not None:
                parts.append(f"range [{cs.min_val}, {cs.max_val}], avg={cs.avg_val}")
            else:
                parts.append(f"range [{cs.min_val}, {cs.max_val}]")

        if cs.true_count is not None:
            parts.append(f"true={cs.true_count}, false={cs.false_count}")

        if parts:
            lines.append(f"  {cs.column_name}: {'; '.join(parts)}.")

    return "\n".join(lines)


def profile_all_tables(engine, tables: list[TableSchema]) -> list[TableProfile]:
    """Profile every table, skipping excluded ones and catching per-table errors."""
    profiles: list[TableProfile] = []
    for table in tables:
        try:
            profile = profile_table(engine, table)
            if profile is not None:
                profiles.append(profile)
                logger.info(
                    "data_profiling.table_done",
                    table=table.table_name,
                    rows=profile.row_count,
                )
        except Exception:
            logger.exception("data_profiling.table_failed", table=table.table_name)
    return profiles


# ---------------------------------------------------------------------------
# Ingestion orchestrator
# ---------------------------------------------------------------------------


def ingest_data_profiles(engine) -> int:
    """Profile all tables, embed the summaries, and upsert into pgvector.

    Clears existing 'data_profile' rows before writing.
    Returns count of rows upserted.
    """
    from .schema_ingestion import extract_tables

    clear_count = clear_category(engine, "data_profile")
    logger.info("data_profiling.cleared", count=clear_count)

    tables = extract_tables(engine)
    profiles = profile_all_tables(engine, tables)

    if not profiles:
        logger.warning("data_profiling.no_profiles")
        return 0

    texts = [build_profile_text(p) for p in profiles]
    metas = [{"table": p.table_name, "row_count": p.row_count} for p in profiles]

    embeddings = generate_embeddings(texts)
    items = [
        {
            "category": "data_profile",
            "content": txt,
            "metadata": meta,
            "embedding": emb,
            "content_hash": content_hash(f"data_profile:{txt}"),
        }
        for txt, emb, meta in zip(texts, embeddings, metas)
    ]

    count = upsert_embeddings(engine, items)
    logger.info("data_profiling.upserted", count=count)
    return count

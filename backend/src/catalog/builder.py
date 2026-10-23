"""Building a catalog snapshot: the package, plus the live schema, plus the data.

``build_catalog`` is pure with respect to the application tables: it reads the
dataset's schema and returns a :class:`BuiltCatalog`; storing it is the
repository's job.  ``apply_profile`` merges measured statistics into a
package-derived snapshot and is shared by the builder (fresh measurements) and
the service (stored measurements), so both produce identical snapshots.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime

from sqlalchemy import Connection, text
from sqlalchemy.exc import SQLAlchemyError

from src.catalog.introspect import DriftIssue, detect_drift, introspect_schema
from src.catalog.model import CatalogSnapshot, ColumnInfo, RelationshipInfo, TableInfo, ValueCount
from src.catalog.profiler import ColumnProfile, ProfileConfig, TableProfile, profile_table
from src.catalog.relationships import RelationshipStat, measure_relationship
from src.datasets.models import DatasetPackage
from src.utils.logger import get_logger

logger = get_logger(__name__)

RelKey = tuple[str, tuple[str, ...], str, tuple[str, ...]]


def relationship_key(rel: RelationshipInfo) -> RelKey:
    return (rel.from_table, rel.from_columns, rel.to_table, rel.to_columns)


@dataclass(frozen=True)
class BuildInfo:
    """Facts about one catalog build, stored with it."""

    dataset_id: str
    run_id: str
    package_version: str
    package_hash: str
    schema_name: str
    built_at: datetime | None = None
    duration_ms: int = 0
    sample_rows: int = 0
    enum_max_distinct: int = 0
    table_count: int = 0
    column_count: int = 0
    relationship_count: int = 0
    drift: tuple[DriftIssue, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class BuiltCatalog:
    snapshot: CatalogSnapshot
    info: BuildInfo
    # Per-table row counts actually profiled (below row_count when the table was sampled).
    profiled_rows: dict[str, int] = field(default_factory=dict)
    profiles: dict[str, TableProfile] = field(default_factory=dict)
    relationship_stats: dict[RelKey, RelationshipStat] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def _apply_column(col: ColumnInfo, prof: ColumnProfile | None) -> ColumnInfo:
    if prof is None:
        return col
    if col.sensitive:
        # Aggregates only: never a value, whatever the profile holds.
        return replace(col, null_rate=prof.null_rate, distinct_count=prof.distinct_count)
    return replace(
        col,
        null_rate=prof.null_rate,
        distinct_count=prof.distinct_count,
        min_value=prof.min_value,
        max_value=prof.max_value,
        top_values=tuple(ValueCount(v, n, col.value_labels.get(v)) for v, n in prof.top_values),
        sample_values=prof.sample_values,
    )


def apply_profile(
    base: CatalogSnapshot,
    profiles: Mapping[str, TableProfile],
    rel_stats: Mapping[RelKey, RelationshipStat],
    *,
    run_id: str | None,
) -> CatalogSnapshot:
    """``base`` (from the package) with measured statistics filled in.

    Labels come from ``base``, so edited value labels apply to old measurements.
    Profiles of tables or columns ``base`` does not know are ignored.
    """
    tables: list[TableInfo] = []
    for table in base.tables:
        prof = profiles.get(table.name)
        if prof is None:
            tables.append(table)
            continue
        columns = tuple(_apply_column(c, prof.columns.get(c.name)) for c in table.columns)
        tables.append(replace(table, row_count=prof.row_count, columns=columns))
    relationships = tuple(
        replace(r, match_rate=stat.match_rate, coverage=stat.coverage) if (stat := rel_stats.get(relationship_key(r))) else r
        for r in base.relationships
    )
    return replace(base, tables=tuple(tables), relationships=relationships, run_id=run_id, source="live")


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def build_catalog(
    conn: Connection,
    pkg: DatasetPackage,
    *,
    schema: str,
    run_id: str,
    cfg: ProfileConfig | None = None,
    shared_schema: bool = False,
) -> BuiltCatalog:
    """Profile the dataset living in ``schema`` and return the catalog.

    Never raises for problems with the data: a table or relationship that
    cannot be measured is left without statistics and a note says why.  A
    database that cannot be reached at all still raises.
    """
    cfg = cfg or ProfileConfig()
    started = time.perf_counter()
    notes: list[str] = []
    base = CatalogSnapshot.from_package(pkg)

    conn.execute(text("SET LOCAL TIME ZONE 'UTC'"))
    live = introspect_schema(conn, schema)
    drift = detect_drift(pkg, live, shared_schema=shared_schema)
    broken = {i.table for i in drift if i.kind in ("missing_table", "missing_column", "type_mismatch")}

    profiles: dict[str, TableProfile] = {}
    for table in pkg.tables:
        if table.table not in live or table.table in broken:
            continue
        try:
            with conn.begin_nested():
                profiles[table.table] = profile_table(conn, schema, table, cfg)
        except SQLAlchemyError as exc:
            logger.warning("catalog: table %s could not be profiled (%s)", table.table, type(exc).__name__)
            notes.append(f"table {table.table} could not be profiled ({type(exc).__name__})")

    stats: dict[RelKey, RelationshipStat] = {}
    for rel in base.relationships:
        if rel.from_table not in profiles or rel.to_table not in profiles:
            continue
        try:
            with conn.begin_nested():
                stats[relationship_key(rel)] = measure_relationship(
                    conn, schema, pkg, rel, cfg.sample_rows, cfg.statement_timeout_ms
                )
        except SQLAlchemyError as exc:
            logger.warning("catalog: relationship %s could not be measured (%s)", rel.expression, type(exc).__name__)
            notes.append(f"relationship {rel.expression} could not be measured ({type(exc).__name__})")

    snapshot = apply_profile(base, profiles, stats, run_id=run_id)
    info = BuildInfo(
        dataset_id=pkg.id,
        run_id=run_id,
        package_version=pkg.version,
        package_hash=pkg.content_hash,
        schema_name=schema,
        duration_ms=int((time.perf_counter() - started) * 1000),
        sample_rows=cfg.sample_rows,
        enum_max_distinct=cfg.enum_max_distinct,
        table_count=len(snapshot.tables),
        column_count=sum(len(t.columns) for t in snapshot.tables),
        relationship_count=len(snapshot.relationships),
        drift=tuple(drift),
        notes=tuple(notes),
    )
    return BuiltCatalog(
        snapshot=snapshot,
        info=info,
        profiled_rows={name: p.profiled_rows for name, p in profiles.items()},
        profiles=profiles,
        relationship_stats=stats,
    )

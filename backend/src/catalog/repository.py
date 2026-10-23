"""Storing and loading catalog builds (``app.catalog_*``).

All functions take a synchronous SQLAlchemy ``Connection``.  Async callers run
them with ``AsyncConnection.run_sync``, so there is one implementation for the
CLI, the ingestion hook and the API.

Stored rows never contain values of sensitive columns: the builder does not
collect them and :func:`save_build` drops them again before writing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Connection, text
from sqlalchemy.exc import SQLAlchemyError

from src.catalog.builder import BuildInfo, BuiltCatalog, RelKey
from src.catalog.introspect import DriftIssue
from src.catalog.profiler import ColumnProfile, TableProfile
from src.catalog.relationships import RelationshipStat

# Builds kept per dataset besides the active one: the previous generation stays
# available for a rollback, and one more for a build that never went live.
KEEP_BUILDS = 3


@dataclass(frozen=True)
class StoredCatalog:
    info: BuildInfo
    profiles: dict[str, TableProfile]
    relationship_stats: dict[RelKey, RelationshipStat]


# ---------------------------------------------------------------------------
# Where is the live data?  (app.datasets is created by the ingestion workstream)
# ---------------------------------------------------------------------------


def _datasets_row(conn: Connection, dataset_id: str) -> Any | None:
    """The ``app.datasets`` row of the dataset, or None when the table or row does not exist."""
    try:
        with conn.begin_nested():
            if conn.execute(text("SELECT to_regclass('app.datasets')")).scalar() is None:
                return None
            return conn.execute(
                text("SELECT active_run_id::text AS active_run_id, schema_name FROM app.datasets WHERE id = :id"),
                {"id": dataset_id},
            ).first()
    except SQLAlchemyError:
        return None


def active_run_id(conn: Connection, dataset_id: str) -> str | None:
    row = _datasets_row(conn, dataset_id)
    return row.active_run_id if row is not None and row.active_run_id else None


def registered_schema(conn: Connection, dataset_id: str) -> str | None:
    row = _datasets_row(conn, dataset_id)
    return row.schema_name if row is not None and row.schema_name else None


def catalog_tables_exist(conn: Connection) -> bool:
    return conn.execute(text("SELECT to_regclass('app.catalog_builds')")).scalar() is not None


def latest_run_id(conn: Connection, dataset_id: str) -> str | None:
    if not catalog_tables_exist(conn):
        return None
    return conn.execute(
        text("SELECT run_id FROM app.catalog_builds WHERE dataset_id = :d ORDER BY built_at DESC, run_id LIMIT 1"),
        {"d": dataset_id},
    ).scalar()


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _loads(value: Any) -> Any:
    """A jsonb column: the asyncpg driver returns text, psycopg2 returns the parsed value."""
    return json.loads(value) if isinstance(value, str) else value


def save_build(conn: Connection, built: BuiltCatalog, *, active: str | None = None) -> None:
    """Replace the stored catalog of ``(dataset, run)`` with ``built``, in the caller's transaction.

    Old builds are pruned: the active run, this run and the most recent others
    are kept (:data:`KEEP_BUILDS` in all).
    """
    info, snap = built.info, built.snapshot
    key = {"d": info.dataset_id, "r": info.run_id}
    for table in ("catalog_relationships", "catalog_columns", "catalog_tables", "catalog_builds"):
        conn.execute(text(f"DELETE FROM app.{table} WHERE dataset_id = :d AND run_id = :r"), key)

    conn.execute(
        text(
            """
            INSERT INTO app.catalog_builds
              (dataset_id, run_id, package_version, package_hash, schema_name, duration_ms,
               profile_sample_rows, enum_max_distinct, table_count, column_count, relationship_count,
               drift, notes)
            VALUES (:d, :r, :v, :h, :s, :ms, :sr, :em, :tc, :cc, :rc, CAST(:drift AS jsonb), CAST(:notes AS jsonb))
            """
        ),
        {
            **key,
            "v": info.package_version,
            "h": info.package_hash,
            "s": info.schema_name,
            "ms": info.duration_ms,
            "sr": info.sample_rows,
            "em": info.enum_max_distinct,
            "tc": info.table_count,
            "cc": info.column_count,
            "rc": info.relationship_count,
            "drift": _json([i.to_dict() for i in info.drift]),
            "notes": _json(list(info.notes)),
        },
    )

    tables = [
        {
            **key,
            "t": t.name,
            "desc": t.description,
            "grain": t.grain,
            "rows": t.row_count,
            "prof": built.profiled_rows.get(t.name),
            "node": t.node_type,
        }
        for t in snap.tables
    ]
    if tables:
        conn.execute(
            text(
                """
                INSERT INTO app.catalog_tables
                  (dataset_id, run_id, table_name, description, grain, row_count, profiled_rows, node_type)
                VALUES (:d, :r, :t, :desc, :grain, :rows, :prof, :node)
                """
            ),
            tables,
        )

    columns = []
    for t in snap.tables:
        for c in t.columns:
            # Defence in depth: a sensitive column is stored without any value.
            quiet = c.sensitive
            columns.append(
                {
                    **key,
                    "t": t.name,
                    "c": c.name,
                    "ord": c.ordinal,
                    "type": c.data_type,
                    "nullable": c.nullable,
                    "role": c.role,
                    "desc": c.description,
                    "pk": c.is_pk,
                    "sens": c.sensitive,
                    "hidden": c.hidden,
                    "nr": c.null_rate,
                    "dc": c.distinct_count,
                    "mn": None if quiet else c.min_value,
                    "mx": None if quiet else c.max_value,
                    "top": _json([] if quiet else [{"value": v.value, "count": v.count} for v in c.top_values]),
                    "samples": _json([] if quiet else list(c.sample_values)),
                    "vs": c.value_set,
                    "vl": _json({} if quiet else c.value_labels),
                    "cur": c.currency_column,
                }
            )
    if columns:
        conn.execute(
            text(
                """
                INSERT INTO app.catalog_columns
                  (dataset_id, run_id, table_name, column_name, ordinal, data_type, nullable, role, description,
                   is_pk, sensitive, hidden, null_rate, distinct_count, min_value, max_value,
                   top_values, sample_values, value_set, value_labels, currency_column)
                VALUES (:d, :r, :t, :c, :ord, :type, :nullable, :role, :desc, :pk, :sens, :hidden, :nr, :dc,
                        :mn, :mx, CAST(:top AS jsonb), CAST(:samples AS jsonb), :vs, CAST(:vl AS jsonb), :cur)
                """
            ),
            columns,
        )

    rels = []
    for rel in snap.relationships:
        stat = built.relationship_stats.get((rel.from_table, rel.from_columns, rel.to_table, rel.to_columns))
        rels.append(
            {
                **key,
                "ft": rel.from_table,
                "fc": list(rel.from_columns),
                "tt": rel.to_table,
                "tc": list(rel.to_columns),
                "kind": rel.kind,
                "card": rel.cardinality,
                "expr": rel.expression,
                "desc": rel.description,
                "mr": rel.match_rate,
                "fr": stat.from_rows if stat else None,
                "kr": stat.keyed_rows if stat else None,
                "mt": stat.matched_rows if stat else None,
                "tr": stat.to_rows if stat else None,
                "rr": stat.referenced_rows if stat else None,
            }
        )
    if rels:
        conn.execute(
            text(
                """
                INSERT INTO app.catalog_relationships
                  (dataset_id, run_id, from_table, from_columns, to_table, to_columns, kind, cardinality,
                   expression, description, match_rate, from_rows, keyed_rows, matched_rows, to_rows, referenced_rows)
                VALUES (:d, :r, :ft, CAST(:fc AS text[]), :tt, CAST(:tc AS text[]), :kind, :card,
                        :expr, :desc, :mr, :fr, :kr, :mt, :tr, :rr)
                """
            ),
            rels,
        )
    prune(conn, info.dataset_id, keep_run_ids={info.run_id} | ({active} if active else set()))


def prune(conn: Connection, dataset_id: str, *, keep_run_ids: set[str]) -> None:
    """Delete all but the newest builds of a dataset (and those in ``keep_run_ids``)."""
    old = conn.execute(
        text("SELECT run_id FROM app.catalog_builds WHERE dataset_id = :d ORDER BY built_at DESC, run_id"),
        {"d": dataset_id},
    ).scalars().all()
    keep = set(keep_run_ids) | set(old[:KEEP_BUILDS])
    for run_id in old:
        if run_id in keep:
            continue
        for table in ("catalog_relationships", "catalog_columns", "catalog_tables", "catalog_builds"):
            conn.execute(
                text(f"DELETE FROM app.{table} WHERE dataset_id = :d AND run_id = :r"),
                {"d": dataset_id, "r": run_id},
            )


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------


def _drift_from_json(items: list[dict[str, Any]]) -> tuple[DriftIssue, ...]:
    return tuple(
        DriftIssue(
            kind=i["kind"], severity=i["severity"], table=i["table"], column=i.get("column"),
            expected=i.get("expected"), actual=i.get("actual"), message=i["message"],
        )
        for i in items
    )


def load_build(conn: Connection, dataset_id: str, run_id: str) -> StoredCatalog | None:
    """The stored build of ``(dataset, run)``, or None when there is none."""
    if not catalog_tables_exist(conn):
        return None
    key = {"d": dataset_id, "r": run_id}
    head = conn.execute(
        text(
            """
            SELECT package_version, package_hash, schema_name, built_at, duration_ms, profile_sample_rows,
                   enum_max_distinct, table_count, column_count, relationship_count, drift, notes
            FROM app.catalog_builds WHERE dataset_id = :d AND run_id = :r
            """
        ),
        key,
    ).first()
    if head is None:
        return None
    info = BuildInfo(
        dataset_id=dataset_id,
        run_id=run_id,
        package_version=head.package_version,
        package_hash=head.package_hash,
        schema_name=head.schema_name,
        built_at=head.built_at,
        duration_ms=head.duration_ms,
        sample_rows=head.profile_sample_rows,
        enum_max_distinct=head.enum_max_distinct,
        table_count=head.table_count,
        column_count=head.column_count,
        relationship_count=head.relationship_count,
        drift=_drift_from_json(_loads(head.drift)),
        notes=tuple(_loads(head.notes)),
    )

    counts = {
        r.table_name: (r.row_count, r.profiled_rows)
        for r in conn.execute(
            text("SELECT table_name, row_count, profiled_rows FROM app.catalog_tables WHERE dataset_id = :d AND run_id = :r"),
            key,
        )
    }
    by_table: dict[str, dict[str, ColumnProfile]] = {}
    for r in conn.execute(
        text(
            """
            SELECT table_name, column_name, sensitive, null_rate, distinct_count, min_value, max_value,
                   top_values, sample_values
            FROM app.catalog_columns WHERE dataset_id = :d AND run_id = :r
            ORDER BY table_name, ordinal
            """
        ),
        key,
    ):
        quiet = r.sensitive
        by_table.setdefault(r.table_name, {})[r.column_name] = ColumnProfile(
            name=r.column_name,
            null_rate=r.null_rate,
            distinct_count=r.distinct_count,
            min_value=None if quiet else r.min_value,
            max_value=None if quiet else r.max_value,
            top_values=() if quiet else tuple((v["value"], v["count"]) for v in _loads(r.top_values)),
            sample_values=() if quiet else tuple(_loads(r.sample_values)),
        )
    profiles = {
        name: TableProfile(name, rows if rows is not None else 0, prof if prof is not None else 0, by_table.get(name, {}))
        for name, (rows, prof) in counts.items()
        if rows is not None
    }
    stats: dict[RelKey, RelationshipStat] = {}
    for r in conn.execute(
        text(
            """
            SELECT from_table, from_columns, to_table, to_columns, from_rows, keyed_rows, matched_rows,
                   to_rows, referenced_rows
            FROM app.catalog_relationships WHERE dataset_id = :d AND run_id = :r
            """
        ),
        key,
    ):
        if r.from_rows is None:
            continue
        stats[(r.from_table, tuple(r.from_columns), r.to_table, tuple(r.to_columns))] = RelationshipStat(
            r.from_rows, r.keyed_rows, r.matched_rows, r.to_rows, r.referenced_rows
        )
    return StoredCatalog(info, profiles, stats)


def stored_built_at(conn: Connection, dataset_id: str, run_id: str) -> datetime | None:
    return conn.execute(
        text("SELECT built_at FROM app.catalog_builds WHERE dataset_id = :d AND run_id = :r"),
        {"d": dataset_id, "r": run_id},
    ).scalar()

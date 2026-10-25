"""Run records: the repository of ``app.ingestion_runs`` and ``app.ingestion_issues``.

The ingestion pipeline writes through :class:`RunStore` (synchronous, on the
owner engine, each call in its own short transaction so progress is visible
while a run is going).  The API reads through the ``fetch_*`` coroutines.
Everything that leaves this module as a dict is safe to return to a client:
messages are written by the pipeline itself (never driver text) and no
filesystem path is ever stored.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import Engine, delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.app_tables import (
    RUN_ACTIVE,
    RUN_SUCCESS,
    datasets,
    ingestion_issues,
    ingestion_runs,
)

# A run whose heartbeat is older than this is considered dead.
STALE_RUN_SECONDS = 300


@dataclass
class IssueRow:
    table_name: str
    severity: str  # error | warning | info
    code: str
    message: str
    count: int = 1
    sample: dict[str, Any] | None = None


class RunStore(Protocol):
    """What the pipeline needs to record a run."""

    def create(self, dataset_id: str, kind: str, *, package_hash: str | None, triggered_by: str | None,
               status: str = "running") -> str: ...

    def set_phase(self, run_id: str, phase: str) -> None: ...

    def heartbeat(self, run_id: str) -> None: ...

    def finish(self, run_id: str, status: str, *, table_counts: dict | None = None,
               reject_counts: dict | None = None, report: dict | None = None,
               error_code: str | None = None, error_message: str | None = None,
               source_fingerprint: str | None = None) -> None: ...

    def add_issues(self, run_id: str, issues: list[IssueRow]) -> None: ...


def _json(value: Any) -> Any:
    """JSON-safe copy (the report may hold Decimals, datetimes, sets)."""
    return json.loads(json.dumps(value, default=_default))


def _default(value: Any) -> Any:
    if isinstance(value, set | frozenset | tuple):
        return list(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


class SqlRunStore:
    """:class:`RunStore` on the ``app`` tables."""

    def __init__(self, engine: Engine):
        self.engine = engine

    def create(self, dataset_id: str, kind: str, *, package_hash: str | None, triggered_by: str | None,
               status: str = "running") -> str:
        run_id = str(uuid.uuid4())
        with self.engine.begin() as conn:
            conn.execute(
                insert(ingestion_runs).values(
                    id=run_id, dataset_id=dataset_id, kind=kind, status=status, phase="plan",
                    package_hash=package_hash, triggered_by=triggered_by,
                    table_counts={}, reject_counts={}, report={},
                )
            )
        return run_id

    def set_phase(self, run_id: str, phase: str, *, status: str | None = None) -> None:
        values: dict[str, Any] = {"phase": phase, "heartbeat_at": func.now()}
        if status:
            values["status"] = status
        with self.engine.begin() as conn:
            conn.execute(update(ingestion_runs).where(ingestion_runs.c.id == run_id).values(**values))

    def heartbeat(self, run_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(ingestion_runs).where(ingestion_runs.c.id == run_id).values(heartbeat_at=func.now())
            )

    def finish(self, run_id: str, status: str, *, table_counts: dict | None = None,
               reject_counts: dict | None = None, report: dict | None = None,
               error_code: str | None = None, error_message: str | None = None,
               source_fingerprint: str | None = None) -> None:
        values: dict[str, Any] = {
            "status": status,
            "phase": "done",
            "finished_at": func.now(),
            "heartbeat_at": func.now(),
            "error_code": error_code,
            "error_message": error_message,
        }
        if table_counts is not None:
            values["table_counts"] = _json(table_counts)
        if reject_counts is not None:
            values["reject_counts"] = _json(reject_counts)
        if report is not None:
            values["report"] = _json(report)
        if source_fingerprint is not None:
            values["source_fingerprint"] = source_fingerprint
        with self.engine.begin() as conn:
            conn.execute(update(ingestion_runs).where(ingestion_runs.c.id == run_id).values(**values))

    def set_fingerprint(self, run_id: str, fingerprint: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                update(ingestion_runs).where(ingestion_runs.c.id == run_id).values(source_fingerprint=fingerprint)
            )

    def add_issues(self, run_id: str, issues: list[IssueRow]) -> None:
        if not issues:
            return
        rows = [
            {
                "run_id": run_id,
                "table_name": i.table_name,
                "severity": i.severity,
                "code": i.code,
                "message": i.message,
                "count": i.count,
                "sample": _json(i.sample) if i.sample is not None else None,
            }
            for i in issues
        ]
        with self.engine.begin() as conn:
            conn.execute(insert(ingestion_issues), rows)

    # --- lookups used by the pipeline ------------------------------------

    def reap_stale(self, dataset_id: str) -> int:
        """Mark runs of ``dataset_id`` that can no longer be alive as failed.

        Called while holding the dataset's ingest lock, so any run still
        recorded as queued or running belongs to a process that has died.
        """
        with self.engine.begin() as conn:
            result = conn.execute(
                update(ingestion_runs)
                .where(ingestion_runs.c.dataset_id == dataset_id, ingestion_runs.c.status.in_(RUN_ACTIVE))
                .values(
                    status="failed",
                    phase="done",
                    finished_at=func.now(),
                    error_code="stale_run",
                    error_message="The run stopped responding and was marked failed.",
                )
            )
            return result.rowcount or 0

    def active_fingerprint(self, dataset_id: str) -> str | None:
        """Source fingerprint of the run whose data is live, if known."""
        with self.engine.connect() as conn:
            return conn.execute(
                select(ingestion_runs.c.source_fingerprint)
                .select_from(
                    datasets.join(ingestion_runs, ingestion_runs.c.id == datasets.c.active_run_id)
                )
                .where(datasets.c.id == dataset_id, ingestion_runs.c.status.in_(RUN_SUCCESS))
            ).scalar()

    def purge(self, dataset_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(delete(ingestion_runs).where(ingestion_runs.c.dataset_id == dataset_id))


class NullRunStore:
    """Records nothing (dry runs)."""

    def __init__(self) -> None:
        self._n = 0

    def create(self, dataset_id: str, kind: str, *, package_hash: str | None, triggered_by: str | None,
               status: str = "running") -> str:
        self._n += 1
        return str(uuid.uuid4())

    def set_phase(self, run_id: str, phase: str, *, status: str | None = None) -> None: ...

    def heartbeat(self, run_id: str) -> None: ...

    def finish(self, run_id: str, status: str, **_: Any) -> None: ...

    def add_issues(self, run_id: str, issues: list[IssueRow]) -> None: ...

    def set_fingerprint(self, run_id: str, fingerprint: str) -> None: ...

    def reap_stale(self, dataset_id: str) -> int:
        return 0

    def active_fingerprint(self, dataset_id: str) -> str | None:
        return None


# ---------------------------------------------------------------------------
# Reads for the API (async, application engine)
# ---------------------------------------------------------------------------


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def run_summary(row: Any) -> dict[str, Any]:
    """The short, client-safe description of a run."""
    counts = row.table_counts or {}
    rejects = row.reject_counts or {}
    report = row.report or {}
    return {
        "id": str(row.id),
        "dataset_id": row.dataset_id,
        "kind": row.kind,
        "status": row.status,
        "phase": row.phase,
        "started_at": _iso(row.started_at),
        "finished_at": _iso(row.finished_at),
        "summary": {
            "tables": len(counts),
            "rows": sum(int(v) for v in counts.values()),
            "rejected": sum(int(n) for per_table in rejects.values() for n in per_table.values()),
            "duplicates": int(report.get("duplicates", 0)),
            "warnings": int(report.get("warnings", 0)),
        },
        "error_code": row.error_code,
        "error_message": row.error_message,
    }


def run_detail(row: Any, issues: list[Any]) -> dict[str, Any]:
    report = dict(row.report or {})
    return {
        **run_summary(row),
        "package_hash": row.package_hash,
        "source_fingerprint": row.source_fingerprint,
        "heartbeat_at": _iso(row.heartbeat_at),
        "triggered_by": row.triggered_by,
        "table_counts": row.table_counts or {},
        "reject_counts": row.reject_counts or {},
        "tables": report.get("tables", {}),
        "timings_ms": report.get("timings_ms", {}),
        "hooks": report.get("hooks", []),
        "issues": [
            {
                "table": i.table_name,
                "severity": i.severity,
                "code": i.code,
                "message": i.message,
                "count": i.count,
                "sample": i.sample,
            }
            for i in issues
        ],
    }


async def fetch_runs(session: AsyncSession, dataset_id: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    query = select(ingestion_runs).order_by(ingestion_runs.c.started_at.desc()).limit(limit)
    if dataset_id:
        query = query.where(ingestion_runs.c.dataset_id == dataset_id)
    rows = (await session.execute(query)).all()
    return [run_summary(r) for r in rows]


async def fetch_run(session: AsyncSession, run_id: str) -> dict[str, Any] | None:
    row = (await session.execute(select(ingestion_runs).where(ingestion_runs.c.id == run_id))).first()
    if row is None:
        return None
    issues = (
        await session.execute(
            select(ingestion_issues)
            .where(ingestion_issues.c.run_id == run_id)
            .order_by(ingestion_issues.c.severity, ingestion_issues.c.table_name, ingestion_issues.c.code, ingestion_issues.c.id)
        )
    ).all()
    return run_detail(row, list(issues))


@dataclass
class DatasetRow:
    id: str
    package_version: str
    status: str
    active_run_id: str | None
    previous_run_id: str | None
    updated_at: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)


async def fetch_dataset_rows(session: AsyncSession) -> dict[str, DatasetRow]:
    rows = (await session.execute(select(datasets))).all()
    return {
        r.id: DatasetRow(
            id=r.id, package_version=r.package_version, status=r.status,
            active_run_id=str(r.active_run_id) if r.active_run_id else None,
            previous_run_id=str(r.previous_run_id) if r.previous_run_id else None,
            updated_at=r.updated_at,
        )
        for r in rows
    }

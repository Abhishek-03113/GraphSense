"""Dataset status for clients: what exists, whether its data is loaded, what the last load did.

Read-only and safe for every client: responses carry names, counts, versions and
timestamps, never filesystem paths, SQL or error internals.

``status`` is one of

``empty``    no data has been loaded yet
``loading``  a load is running
``ready``    data is loaded
``failed``   the first load failed (a failed reload of a loaded dataset leaves it ``ready``)
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.datasets.context import DatasetContext
from src.datasets.errors import PackageError, UnknownDatasetError
from src.datasets.registry import get_package, list_packages
from src.db.session import get_db_session
from src.intelligence.status import ai_status
from src.repositories.graph_cache import graph_cache
from src.storage.app_tables import RUN_ACTIVE, ingestion_runs
from src.storage.readiness import is_missing_relation
from src.storage.runs import DatasetRow, fetch_dataset_rows, run_summary
from src.storage.session import use_dataset
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


def _status(row: DatasetRow | None, latest: Any) -> str:
    if latest is not None and latest.status in RUN_ACTIVE:
        return "loading"
    if row is not None:
        return row.status
    return "empty"


async def _status_rows(db: AsyncSession, dataset_id: str) -> tuple[DatasetRow | None, Any, Any]:
    """The dataset's record, its latest run and its active run, under one savepoint.

    The three reads only fail together (when the application schema has not been
    created yet), so one savepoint is enough; that case answers ``(None, None, None)``.
    """
    try:
        async with db.begin_nested():
            row = (await fetch_dataset_rows(db)).get(dataset_id)
            query = (
                select(ingestion_runs)
                .where(ingestion_runs.c.dataset_id == dataset_id)
                .order_by(ingestion_runs.c.started_at.desc())
                .limit(1)
            )
            latest = (await db.execute(query)).first()
            active = None
            if row is not None and row.active_run_id is not None:
                active = (
                    await db.execute(select(ingestion_runs).where(ingestion_runs.c.id == row.active_run_id))
                ).first()
            return row, latest, active
    except Exception:
        logger.info("datasets.app_schema_unavailable")
        return None, None, None


@router.get("")
async def list_datasets(db: AsyncSession = Depends(get_db_session)) -> list[dict[str, Any]]:
    """Every available dataset with its load status."""
    rows, latest, finished = await _listing_rows(db)
    out = []
    for info in list_packages():
        if not info.valid:
            continue
        row = rows.get(info.id)
        done = finished.get(row.active_run_id) if row is not None and row.active_run_id else None
        out.append(
            {
                "id": info.id,
                "name": info.name,
                "description": info.description,
                "status": _status(row, latest.get(info.id)),
                "package_version": info.version,
                "last_ingested_at": done.isoformat() if done else None,
            }
        )
    return out


async def _listing_rows(db: AsyncSession) -> tuple[dict[str, DatasetRow], dict[str, Any], dict[str, Any]]:
    """Dataset records, the latest run of each, and when each active run finished, under one savepoint.

    All empty when the application schema has not been created yet.
    """
    try:
        async with db.begin_nested():
            rows = await fetch_dataset_rows(db)
            query = (
                select(ingestion_runs)
                .distinct(ingestion_runs.c.dataset_id)
                .order_by(ingestion_runs.c.dataset_id, ingestion_runs.c.started_at.desc())
            )
            latest = {row.dataset_id: row for row in (await db.execute(query)).all()}
            active_ids = [r.active_run_id for r in rows.values() if r.active_run_id]
            finished: dict[str, Any] = {}
            if active_ids:
                found = await db.execute(
                    select(ingestion_runs.c.id, ingestion_runs.c.finished_at).where(ingestion_runs.c.id.in_(active_ids))
                )
                finished = {str(run_id): at for run_id, at in found.all()}
            return rows, latest, finished
    except Exception:
        logger.info("datasets.app_schema_unavailable")
        return {}, {}, {}


@router.get("/{dataset_id}/status")
async def dataset_status(dataset_id: str, db: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    """Load status of one dataset, its last run and what the AI layer can do."""
    try:
        pkg = get_package(dataset_id)
    except UnknownDatasetError:
        raise HTTPException(status_code=404, detail=f"Unknown dataset: {dataset_id}") from None
    except PackageError:
        raise HTTPException(status_code=409, detail="The dataset package is not valid.") from None

    row, latest, active = await _status_rows(db, dataset_id)
    status = _status(row, latest)

    last_run = None
    if latest is not None:
        summary = run_summary(latest)
        last_run = {
            "id": summary["id"],
            "kind": summary["kind"],
            "status": summary["status"],
            "phase": summary["phase"],
            "started_at": summary["started_at"],
            "finished_at": summary["finished_at"],
            "summary": summary["summary"],
            "error_code": summary["error_code"],
            "error_message": summary["error_message"],
        }
    body: dict[str, Any] = {
        "id": pkg.id,
        "name": pkg.name,
        "status": status,
        "package_version": pkg.version,
        "last_run": last_run,
        "ai": await ai_status(dataset_id),
    }
    if active is not None and active.table_counts:
        body["record_counts"] = dict(active.table_counts)
    return body


async def _has_rows(db: AsyncSession, table: str) -> bool:
    """Whether ``table`` holds at least one row.

    A table that does not exist has none.  When the question cannot be answered (the database
    is unreachable, say) the answer is "yes", so a hiccup never empties the list of suggestions.
    """
    try:
        async with db.begin_nested():
            return bool((await db.execute(text(f"SELECT EXISTS (SELECT 1 FROM {table})"))).scalar())
    except Exception as exc:  # noqa: BLE001
        if is_missing_relation(exc):
            return False
        logger.warning("datasets.suggested_questions.row_check_failed table=%s error=%s", table, type(exc).__name__)
        return True


async def _types_with_rows(db: AsyncSession, tables: dict[str, str]) -> dict[str, bool]:
    """``record type -> has rows``, in one statement; one statement per table when that fails (a table is missing)."""
    if not tables:
        return {}
    keys = list(tables)
    checks = ", ".join(f"EXISTS (SELECT 1 FROM {tables[key]}) AS has_{i}" for i, key in enumerate(keys))
    try:
        async with db.begin_nested():
            row = (await db.execute(text(f"SELECT {checks}"))).one()
        return {key: bool(row[i]) for i, key in enumerate(keys)}
    except Exception:  # noqa: BLE001 - answered table by table below
        return {key: await _has_rows(db, table) for key, table in tables.items()}


@router.get("/{dataset_id}/suggested-questions")
async def suggested_questions(dataset_id: str, db: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    """Starter questions written by the dataset's package.

    A question whose ``requires`` lists a record type with no rows is left out, so the
    suggestions never point at data that is not there.  Clients without an answer here
    (older servers, an empty list) fall back to questions they generate themselves.
    """
    try:
        pkg = get_package(dataset_id)
    except UnknownDatasetError:
        raise HTTPException(status_code=404, detail=f"Unknown dataset: {dataset_id}") from None
    except PackageError:
        raise HTTPException(status_code=409, detail="The dataset package is not valid.") from None

    questions = list(pkg.semantics.suggested_questions)
    needed = {key for q in questions for key in q.requires}
    if needed:
        graph = pkg.graph_dataset()
        tables = {key: node.table for key in sorted(needed) if (node := graph.get_node_type(key)) is not None}
        await use_dataset(db, DatasetContext(id=pkg.id, schema_name=pkg.schema_name, package=pkg))
        # Which record types have rows only changes when a load swaps in new data.
        available = await graph_cache.get(
            db, pkg.schema_name, ("record_types_with_rows", tuple(tables.items())), lambda: _types_with_rows(db, tables)
        )
        questions = [q for q in questions if all(available.get(key, True) for key in q.requires)]

    return {
        "dataset_id": pkg.id,
        "questions": [{"text": q.text, "category": q.category} for q in questions],
    }

"""Dataset status for clients: what exists, whether its data is loaded, what the last load did.

Read-only and safe for every client: responses carry names, counts, versions and
timestamps, never filesystem paths, SQL or error internals.

``status`` is one of

``empty``    no data has been loaded yet
``loading``  a load is running
``ready``    data is loaded
``failed``   the first load failed (a failed reload of a loaded dataset leaves it ``ready``)
``legacy``   data adopted from a stage-1 database, not yet reloaded
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.datasets.context import DatasetContext
from src.datasets.errors import PackageError, UnknownDatasetError
from src.datasets.models import DatasetPackage
from src.datasets.registry import get_package, list_packages
from src.db.session import get_db_session
from src.intelligence.status import ai_status
from src.storage.app_tables import RUN_ACTIVE, ingestion_runs
from src.storage.readiness import is_missing_relation
from src.storage.runs import DatasetRow, fetch_dataset_rows, run_summary
from src.storage.session import use_dataset
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


async def _dataset_rows(db: AsyncSession) -> dict[str, DatasetRow]:
    """``app.datasets`` rows, or none when the application schema has not been created yet."""
    try:
        async with db.begin_nested():
            return await fetch_dataset_rows(db)
    except Exception:
        logger.info("datasets.app_schema_unavailable")
        return {}


async def _public_tables(db: AsyncSession) -> set[str]:
    rows = await db.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"))
    return {r[0] for r in rows}


async def _latest_runs(db: AsyncSession, dataset_id: str | None = None) -> dict[str, Any]:
    """Latest run per dataset."""
    try:
        async with db.begin_nested():
            query = select(ingestion_runs).order_by(ingestion_runs.c.started_at.desc())
            if dataset_id:
                query = query.where(ingestion_runs.c.dataset_id == dataset_id)
            latest: dict[str, Any] = {}
            for row in (await db.execute(query)).all():
                latest.setdefault(row.dataset_id, row)
            return latest
    except Exception:
        return {}


def _status(pkg: DatasetPackage, row: DatasetRow | None, latest: Any, public: set[str]) -> str:
    if latest is not None and latest.status in RUN_ACTIVE:
        return "loading"
    if row is not None:
        return row.status
    if pkg.tables and all(t.table in public for t in pkg.tables):
        return "legacy"
    return "empty"


async def _active_run(db: AsyncSession, row: DatasetRow | None) -> Any:
    if row is None or row.active_run_id is None:
        return None
    try:
        async with db.begin_nested():
            return (await db.execute(select(ingestion_runs).where(ingestion_runs.c.id == row.active_run_id))).first()
    except Exception:
        return None


@router.get("")
async def list_datasets(db: AsyncSession = Depends(get_db_session)) -> list[dict[str, Any]]:
    """Every available dataset with its load status."""
    rows = await _dataset_rows(db)
    latest = await _latest_runs(db)
    public = await _public_tables(db)
    out = []
    for info in list_packages():
        if not info.valid:
            continue
        pkg = get_package(info.id)
        row = rows.get(info.id)
        active = await _active_run(db, row)
        out.append(
            {
                "id": info.id,
                "name": info.name,
                "description": info.description,
                "status": _status(pkg, row, latest.get(info.id), public),
                "package_version": info.version,
                "last_ingested_at": active.finished_at.isoformat() if active is not None and active.finished_at else None,
            }
        )
    return out


@router.get("/{dataset_id}/status")
async def dataset_status(dataset_id: str, db: AsyncSession = Depends(get_db_session)) -> dict[str, Any]:
    """Load status of one dataset, its last run and what the AI layer can do."""
    try:
        pkg = get_package(dataset_id)
    except UnknownDatasetError:
        raise HTTPException(status_code=404, detail=f"Unknown dataset: {dataset_id}") from None
    except PackageError:
        raise HTTPException(status_code=409, detail="The dataset package is not valid.") from None

    rows = await _dataset_rows(db)
    row = rows.get(dataset_id)
    latest = (await _latest_runs(db, dataset_id)).get(dataset_id)
    public = await _public_tables(db)
    status = _status(pkg, row, latest, public)
    active = await _active_run(db, row)

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
        await use_dataset(db, DatasetContext(id=pkg.id, schema_name=pkg.schema_name, package=pkg))
        available: dict[str, bool] = {}
        for key in sorted(needed):
            node = graph.get_node_type(key)
            available[key] = True if node is None else await _has_rows(db, node.table)
        questions = [q for q in questions if all(available.get(key, True) for key in q.requires)]

    return {
        "dataset_id": pkg.id,
        "questions": [{"text": q.text, "category": q.category} for q in questions],
    }

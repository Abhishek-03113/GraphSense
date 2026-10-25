"""Operator API: start ingestion, inspect runs, roll back.

These routes exist only when ``ADMIN_TOKEN`` is configured (``mount_admin``
mounts nothing otherwise, so they answer 404 like any unknown path) and every
call needs ``Authorization: Bearer <token>``.

No request carries a filesystem path: the source directory is always
``DATA_ROOT`` (operator configuration) plus the package's own relative
location.  Responses contain run records only, which hold counts, table names
and short messages; never paths, SQL or stack traces (those go to the log).
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import require_admin
from src.config import get_settings
from src.db.engine import dispose_engine
from src.db.session import get_db_session
from src.ingestion.report import IngestBusy, IngestError
from src.ingestion.runner import IngestOptions, IngestRun, execute_in_worker_process, prepare_refresh, prepare_run
from src.storage import schema_manager as sm
from src.storage.engines import get_owner_sync_engine
from src.storage.runs import fetch_run, fetch_runs
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])

_STATUS_FOR_CODE = {
    "unknown_dataset": 404,
    "busy": 409,
}


class _Body(BaseModel):
    # Anything not listed is refused (422): in particular there is no way to name a path.
    model_config = ConfigDict(extra="forbid")


class IngestRequest(_Body):
    force: bool = False
    mode: Literal["full"] = "full"


class RefreshRequest(_Body):
    force: bool = False


def _http_error(exc: IngestError) -> HTTPException:
    return HTTPException(status_code=_STATUS_FOR_CODE.get(exc.code, 409), detail=exc.message)


async def _execute(run: IngestRun) -> None:
    """Run in the background, in a worker process so the load never stalls this server's requests.

    Afterwards drop pooled connections so none keeps statements of the old generation.
    A dry run (no run record, nothing to load) stays in this process.
    """
    try:
        if run.options.dry_run:
            await run_in_threadpool(run.execute)
        else:
            await execute_in_worker_process(run)
    except Exception:  # failures are recorded on the run; this is a last resort
        logger.error("admin.run.crashed run=%s", run.run_id, exc_info=True)
        run.release()
    finally:
        await dispose_engine()


async def _start(prepare, dataset_id: str, options: IngestOptions, background: BackgroundTasks) -> dict:
    try:
        run = await run_in_threadpool(prepare, dataset_id, options)
    except IngestError as exc:
        raise _http_error(exc) from None
    background.add_task(_execute, run)
    return {"run_id": run.run_id, "status": "queued", "dataset_id": dataset_id}


@router.post("/datasets/{dataset_id}/ingestions", status_code=202)
async def start_ingest(dataset_id: str, background: BackgroundTasks, body: IngestRequest | None = None) -> dict:
    """Start a full ingestion of the dataset from the operator's data root.  Returns the run id."""
    body = body or IngestRequest()
    options = IngestOptions(force=body.force, triggered_by="admin_api")
    return await _start(prepare_run, dataset_id, options, background)


@router.post("/datasets/{dataset_id}/knowledge-refreshes", status_code=202)
async def refresh_knowledge(dataset_id: str, background: BackgroundTasks, body: RefreshRequest | None = None) -> dict:
    """Re-run the post-ingest hooks (such as the knowledge refresh) on the live data."""
    body = body or RefreshRequest()
    options = IngestOptions(force=body.force, triggered_by="admin_api")
    return await _start(prepare_refresh, dataset_id, options, background)


@router.get("/runs")
async def list_runs(
    dataset_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db_session),
) -> dict:
    return {"runs": await fetch_runs(db, dataset_id, limit)}


@router.get("/runs/{run_id}")
async def get_run(run_id: str, db: AsyncSession = Depends(get_db_session)) -> dict:
    try:
        found = await fetch_run(db, run_id)
    except Exception:
        # Not a UUID, or the table is unavailable: either way there is no such run to show.
        await db.rollback()
        found = None
    if found is None:
        raise HTTPException(status_code=404, detail="No such run.")
    return found


def _rollback(dataset_id: str) -> dict:
    engine = get_owner_sync_engine()
    lock = sm.DatasetLock(engine, dataset_id)
    if not lock.acquire():
        raise IngestBusy()
    try:
        sm.rollback(dataset_id, engine=engine)
    finally:
        lock.release()
    return {"dataset_id": dataset_id, "status": "rolled_back"}


@router.post("/datasets/{dataset_id}/rollbacks")
async def rollback_dataset(dataset_id: str) -> dict:
    """Make the previous generation live again (calling it twice rolls forward)."""
    from src.datasets.errors import PackageError, UnknownDatasetError
    from src.datasets.registry import get_package

    try:
        get_package(dataset_id)
    except UnknownDatasetError:
        raise HTTPException(status_code=404, detail="No such dataset.") from None
    except PackageError:
        raise HTTPException(status_code=409, detail="The dataset package is not valid.") from None
    try:
        result = await run_in_threadpool(_rollback, dataset_id)
    except IngestError as exc:
        raise _http_error(exc) from None
    except sm.SchemaError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    await dispose_engine()
    return result


def mount_admin(app: FastAPI) -> bool:
    """Add the admin routes to ``app`` if (and only if) an admin token is configured."""
    if not get_settings().admin_enabled:
        return False
    app.include_router(router)
    return True

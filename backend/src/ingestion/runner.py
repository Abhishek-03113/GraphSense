"""The ingestion pipeline: plan, stage, load, validate, hooks, swap, hooks.

One run builds a complete new generation of a dataset in a staging schema and
swaps it in atomically (see ``src/storage/schema_manager.py``).  Any failure
before the swap leaves the live generation untouched and removes the staging
schema.  A failure after the swap (post-swap hooks) never undoes live data.

Use :func:`prepare_run` then ``run.execute()``.  Preparing takes the dataset's
lock and creates the run record, so a caller (the admin API) can answer "busy"
immediately and run the rest in the background.
"""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy import Engine, text

from src.config import get_settings
from src.datasets.errors import PackageError, UnknownDatasetError
from src.datasets.models import DatasetPackage
from src.datasets.registry import get_package
from src.ingestion.fingerprint import SourcePlan, plan_sources
from src.ingestion.hooks import (
    HookContext,
    HookResult,
    LoadedHooks,
    load_hooks,
    run_hooks,
)
from src.ingestion.loader import load_table
from src.ingestion.readers import resolve_data_root
from src.ingestion.report import IngestBusy, IngestError, IssueCollector, TableResult
from src.ingestion.validate import check_tables, error_summary, observe_data
from src.storage import schema_manager as sm
from src.storage.engines import get_owner_sync_engine, make_owner_async_engine
from src.storage.runs import IssueRow, NullRunStore, RunStore, SqlRunStore
from src.storage.schema_names import live_schema

logger = structlog.get_logger(__name__)

HEARTBEAT_SECONDS = 10.0


@dataclass
class IngestOptions:
    data_root: Path | str | None = None  # None: the DATA_ROOT setting
    force: bool = False
    dry_run: bool = False
    skip_hooks: bool = False
    max_reject_rate: float | None = None
    triggered_by: str | None = "cli"
    # Hook specs ("module:attr"); None means the POST_INGEST_HOOKS setting.
    hook_specs: list[str] | None = None


@dataclass
class IngestOutcome:
    dataset_id: str
    kind: str
    run_id: str
    status: str  # succeeded | succeeded_with_warnings | failed | skipped
    dry_run: bool = False
    table_counts: dict[str, int] = field(default_factory=dict)
    reject_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    report: dict[str, Any] = field(default_factory=dict)
    issues: list[IssueRow] = field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None

    @property
    def ok(self) -> bool:
        return self.status != "failed"


def _run_coroutine(factory):
    """Run ``factory()`` (returning a coroutine) to completion, also when called inside a running loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(factory())).result()


def run_hook_phase(
    hooks: list,
    phase: str,
    *,
    package: DatasetPackage,
    run_id: str,
    schema: str,
    engine: Engine,
    options: dict[str, Any] | None = None,
) -> list[HookResult]:
    """Run the hooks of one phase with a fresh async owner engine."""
    if not any(h.phase == phase for h in hooks):
        return []

    async def go() -> list[HookResult]:
        async_engine = make_owner_async_engine()
        try:
            ctx = HookContext(
                dataset_id=package.id, run_id=run_id, package=package, schema=schema,
                engine=async_engine, settings=get_settings(), sync_engine=engine,
                phase=phase,  # type: ignore[arg-type]
                options=dict(options or {}),
            )
            return await run_hooks(hooks, phase, ctx)  # type: ignore[arg-type]
        finally:
            await async_engine.dispose()

    return _run_coroutine(go)


class IngestRun:
    """A prepared run: the dataset lock is held and the run record exists."""

    def __init__(
        self,
        package: DatasetPackage,
        options: IngestOptions,
        engine: Engine,
        store: RunStore,
        lock: sm.DatasetLock | None,
        run_id: str,
        data_root: Path | None,
        kind: str = "ingest",
    ):
        self.package = package
        self.options = options
        self.engine = engine
        self.store = store
        self.lock = lock
        self.run_id = run_id
        self.data_root = data_root
        self.kind = kind
        self.issues = IssueCollector()
        self.report: dict[str, Any] = {"timings_ms": {}, "hooks": []}
        self._staging: str | None = None
        self._swapped = False
        self._last_beat = time.monotonic()
        self._executed = False

    # ------------------------------------------------------------------

    def release(self) -> None:
        if self.lock is not None:
            self.lock.release()
            self.lock = None

    def _phase(self, name: str, *, running: bool = False) -> float:
        self.store.set_phase(self.run_id, name, **({"status": "running"} if running else {}))  # type: ignore[call-arg]
        self._last_beat = time.monotonic()
        return time.monotonic()

    def _beat(self) -> None:
        if time.monotonic() - self._last_beat >= HEARTBEAT_SECONDS:
            self.store.heartbeat(self.run_id)
            self._last_beat = time.monotonic()

    def _time(self, phase: str, started: float) -> None:
        self.report["timings_ms"][phase] = int((time.monotonic() - started) * 1000)

    # ------------------------------------------------------------------

    def execute(self) -> IngestOutcome:
        """Run the pipeline.  Never raises for an ordinary failure: the outcome says what happened."""
        if self._executed:
            raise RuntimeError("a run executes once")
        self._executed = True
        try:
            if self.kind == "refresh":
                return self._refresh()
            return self._ingest()
        except IngestError as exc:
            return self._fail(exc.code, exc.message)
        except Exception:
            logger.error("ingest.unexpected_failure", dataset=self.package.id, run=self.run_id, exc_info=True)
            return self._fail("internal_error", "The ingestion failed unexpectedly. See the server log for details.")
        finally:
            self._cleanup()
            self.release()

    # --- ingest ----------------------------------------------------------

    def _ingest(self) -> IngestOutcome:
        pkg, opts = self.package, self.options
        started_all = time.monotonic()
        self.report["package"] = {"id": pkg.id, "version": pkg.version, "hash": pkg.content_hash}

        t = self._phase("plan", running=True)
        assert self.data_root is not None
        plan = plan_sources(pkg, self.data_root)
        self.store.set_fingerprint(self.run_id, plan.fingerprint)
        self._time("plan", t)
        if not opts.force and not opts.dry_run and self._unchanged(plan):
            self.report.update(skipped_reason="unchanged")
            return self._finish("skipped", plan=plan)

        t = self._phase("stage")
        self._staging = sm.create_staging(pkg, self.run_id, engine=self.engine)
        self._time("stage", t)

        t = self._phase("load")
        results = self._load(plan)
        self._time("load", t)

        t = self._phase("validate")
        check_tables(pkg, results, plan.missing, self.issues, max_reject_rate=opts.max_reject_rate)
        if self.issues.count("error"):
            raise IngestError("validation_failed", error_summary(self.issues))
        sm.create_indexes(pkg, self._staging, engine=self.engine)
        sm.analyze(pkg, self._staging, engine=self.engine)
        with self.engine.connect() as conn:
            observe_data(conn, pkg, self._staging, results, self.issues)
        self._time("validate", t)

        hooks = self._hooks()
        if opts.dry_run:
            self.report["dry_run"] = True
            return self._finish("succeeded", results=results, plan=plan)

        t = self._phase("pre_swap")
        pre = run_hook_phase(hooks.hooks, "pre_swap", package=pkg, run_id=self.run_id,
                             schema=self._staging, engine=self.engine)
        self.report["hooks"] += [r.as_dict() for r in hooks.skipped] + [r.as_dict() for r in pre]
        pre_problems = sum(1 for r in pre if r.status in ("failed", "warning"))
        self._time("pre_swap", t)

        t = self._phase("swap")
        sm.swap(pkg.id, self._staging, package=pkg, run_id=self.run_id, engine=self.engine)
        self._swapped = True
        self._staging = None
        self._time("swap", t)

        t = self._phase("post_swap")
        post = run_hook_phase(hooks.hooks, "post_swap", package=pkg, run_id=self.run_id,
                              schema=live_schema(pkg.id), engine=self.engine)
        self.report["hooks"] += [r.as_dict() for r in post]
        hook_problems = sum(1 for r in post if r.status in ("failed", "warning")) + sum(
            1 for r in hooks.skipped if r.status == "warning"
        )
        self._time("post_swap", t)
        self.report["timings_ms"]["total"] = int((time.monotonic() - started_all) * 1000)
        return self._finish("succeeded", results=results, plan=plan, extra_warnings=hook_problems + pre_problems)

    def _unchanged(self, plan: SourcePlan) -> bool:
        if not sm.generations(self.package.id, engine=self.engine)["live"]:
            return False
        return self.store.active_fingerprint(self.package.id) == plan.fingerprint

    def _hooks(self) -> LoadedHooks:
        if self.options.skip_hooks:
            return LoadedHooks()
        return load_hooks(self.options.hook_specs)

    def _load(self, plan: SourcePlan) -> dict[str, TableResult]:
        assert self._staging is not None
        results: dict[str, TableResult] = {}
        with self.engine.connect() as conn:
            for table in self.package.tables:
                files = plan.files.get(table.table)
                if files is None:
                    continue
                results[table.table] = load_table(
                    conn, self.package, table, self._staging, files, self.issues,
                    expected_hashes=plan.hashes, tick=self._beat,
                )
            conn.commit()
        return results

    # --- refresh (post-swap hooks only) ------------------------------------

    def _refresh(self) -> IngestOutcome:
        pkg = self.package
        self.report["package"] = {"id": pkg.id, "version": pkg.version, "hash": pkg.content_hash}
        if not sm.generations(pkg.id, engine=self.engine)["live"]:
            raise IngestError("dataset_not_ready", "The dataset has no data yet.")
        self._phase("post_swap", running=True)
        hooks = self._hooks()
        post = run_hook_phase(
            hooks.hooks, "post_swap", package=pkg, run_id=self.run_id, schema=live_schema(pkg.id),
            engine=self.engine, options={"force": self.options.force, "refresh": True},
        )
        self.report["hooks"] = [r.as_dict() for r in hooks.skipped] + [r.as_dict() for r in post]
        failed = [r for r in post if r.status == "failed"]
        if failed and len(failed) == len([r for r in post]):
            raise IngestError("hook_failed", f"Hook {failed[0].name} failed: {failed[0].message}".strip())
        problems = sum(1 for r in post if r.status in ("warning", "failed"))
        return self._finish("succeeded", extra_warnings=problems)

    # --- ending a run --------------------------------------------------------

    def _finish(
        self,
        status: str,
        *,
        results: dict[str, TableResult] | None = None,
        plan: SourcePlan | None = None,
        extra_warnings: int = 0,
    ) -> IngestOutcome:
        results = results or {}
        warnings = self.issues.kinds("warning") + extra_warnings
        if status == "succeeded" and warnings:
            status = "succeeded_with_warnings"
        table_counts = {name: r.loaded for name, r in results.items()}
        self.report.update(
            tables={name: r.as_dict() for name, r in results.items()},
            duplicates=sum(r.duplicates for r in results.values()),
            warnings=warnings,
        )
        if plan is not None:
            self.report["source"] = {"files": plan.file_count, "bytes": plan.byte_count}
        reject_counts = self.issues.reject_counts()
        rows = self.issues.rows()
        self.store.add_issues(self.run_id, rows)
        self.store.finish(
            self.run_id, status, table_counts=table_counts, reject_counts=reject_counts, report=self.report,
            source_fingerprint=plan.fingerprint if plan else None,
        )
        logger.info("ingest.finished", dataset=self.package.id, run=self.run_id, status=status,
                    rows=sum(table_counts.values()))
        return IngestOutcome(
            self.package.id, self.kind, self.run_id, status, dry_run=self.options.dry_run,
            table_counts=table_counts, reject_counts=reject_counts, report=self.report, issues=rows,
        )

    def _fail(self, code: str, message: str) -> IngestOutcome:
        logger.warning("ingest.failed", dataset=self.package.id, run=self.run_id, code=code)
        rows = self.issues.rows()
        try:
            self.store.add_issues(self.run_id, rows)
            self.store.finish(
                self.run_id, "failed", reject_counts=self.issues.reject_counts(), report=self.report,
                error_code=code, error_message=message[:1000],
            )
            if self.kind == "ingest" and not self.options.dry_run:
                self._mark_dataset_failed()
        except Exception:
            logger.error("ingest.record_failure_failed", run=self.run_id, exc_info=True)
        return IngestOutcome(
            self.package.id, self.kind, self.run_id, "failed", dry_run=self.options.dry_run,
            reject_counts=self.issues.reject_counts(), report=self.report, issues=rows,
            error_code=code, error_message=message,
        )

    def _mark_dataset_failed(self) -> None:
        """A dataset that has never had data shows as failed; one with data keeps its status."""
        if sm.generations(self.package.id, engine=self.engine)["live"]:
            return
        with self.engine.begin() as conn:
            if not sm.has_app_schema(conn):
                return
            pkg = self.package
            conn.execute(
                text(
                    "INSERT INTO app.datasets (id, package_id, package_version, package_hash, schema_name, status) "
                    "VALUES (:id, :pid, :v, :h, :s, 'failed') "
                    "ON CONFLICT (id) DO UPDATE SET status = 'failed', updated_at = now() "
                    "WHERE app.datasets.active_run_id IS NULL"
                ),
                {"id": pkg.id, "pid": pkg.id, "v": pkg.version, "h": pkg.content_hash, "s": live_schema(pkg.id)},
            )

    def _cleanup(self) -> None:
        """Remove a staging schema that was not swapped in."""
        if self._staging and not self._swapped:
            try:
                sm.drop_schema(self._staging, engine=self.engine)
            except Exception:
                logger.error("ingest.cleanup_failed", dataset=self.package.id, exc_info=True)
            self._staging = None


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def _package_for(dataset_id: str) -> DatasetPackage:
    try:
        return get_package(dataset_id)
    except UnknownDatasetError:
        raise IngestError("unknown_dataset", "No such dataset.") from None
    except PackageError:
        raise IngestError("invalid_package", "The dataset package is not valid. Run `graphsense package lint`.") from None


def _prepare(
    dataset_id: str,
    options: IngestOptions,
    kind: str,
    engine: Engine | None,
    needs_data: bool,
) -> IngestRun:
    package = _package_for(dataset_id)
    engine = engine or get_owner_sync_engine()
    data_root: Path | None = None
    if needs_data:
        data_root = resolve_data_root(options.data_root if options.data_root is not None else get_settings().DATA_ROOT)

    if options.dry_run:
        null = NullRunStore()
        run_id = null.create(dataset_id, kind, package_hash=None, triggered_by=None)
        return IngestRun(package, options, engine, null, None, run_id, data_root, kind)

    with engine.connect() as conn:
        if not sm.has_app_schema(conn):
            raise IngestError("not_migrated", "The application schema is missing. Run `graphsense db migrate` first.")
    lock = sm.DatasetLock(engine, dataset_id)
    if not lock.acquire():
        raise IngestBusy()
    try:
        store = SqlRunStore(engine)
        reaped = store.reap_stale(dataset_id)
        if reaped:
            logger.warning("ingest.stale_runs_reaped", dataset=dataset_id, count=reaped)
        sm.drop_orphan_staging(dataset_id, engine=engine)
        run_id = store.create(dataset_id, kind, package_hash=package.content_hash,
                              triggered_by=options.triggered_by, status="queued")
    except Exception:
        lock.release()
        raise
    return IngestRun(package, options, engine, store, lock, run_id, data_root, kind)


def prepare_run(dataset_id: str, options: IngestOptions | None = None, *, engine: Engine | None = None) -> IngestRun:
    """Validate the request, take the dataset lock and create the run record.

    Raises :class:`IngestError` (``IngestBusy`` when another run is active).  The
    caller must call ``execute()`` (which releases the lock) or ``release()``.
    """
    return _prepare(dataset_id, options or IngestOptions(), "ingest", engine, needs_data=True)


def prepare_refresh(dataset_id: str, options: IngestOptions | None = None, *, engine: Engine | None = None) -> IngestRun:
    """Like :func:`prepare_run` for a run that only re-runs the post-swap hooks on the live data."""
    return _prepare(dataset_id, options or IngestOptions(), "refresh", engine, needs_data=False)


def ingest(dataset_id: str, options: IngestOptions | None = None, *, engine: Engine | None = None) -> IngestOutcome:
    """Prepare and execute a run in one call."""
    run = prepare_run(dataset_id, options, engine=engine)
    return run.execute()


__all__ = [
    "IngestOptions",
    "IngestOutcome",
    "IngestRun",
    "ingest",
    "prepare_refresh",
    "prepare_run",
]

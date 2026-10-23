"""``CatalogService``: the catalog snapshot the rest of the application reads.

``get_snapshot(dataset_id)`` answers, in order:

1. the stored build of the dataset's active run (``app.datasets.active_run_id``),
   merged into the current package;
2. when the database does not track runs yet: the most recent stored build;
3. when nothing is stored: a live profile built on the spot (kept in memory only);
4. when even that is impossible (no database, no tables): the package-only
   snapshot.

It never raises for a missing or unreachable database.  Snapshots are cached
per dataset; the cache entry is revalidated against the active run id (and the
package hash) at most every ``ttl_seconds``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Literal

from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

from src.catalog import repository
from src.catalog.builder import BuildInfo, apply_profile, build_catalog
from src.catalog.introspect import DriftIssue
from src.catalog.model import CatalogSnapshot
from src.catalog.refresh import profile_config, resolve_schema
from src.config import get_settings
from src.datasets.models import DatasetPackage
from src.datasets.registry import get_package
from src.utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_TTL_SECONDS = 5.0
LIVE_TTL_SECONDS = 300.0

Origin = Literal["stored", "live", "package"]


@dataclass(frozen=True)
class CatalogStatus:
    """Where a snapshot came from and how fresh it is."""

    dataset_id: str
    origin: Origin
    run_id: str | None = None
    built_at: datetime | None = None
    duration_ms: int | None = None
    # The package changed after the catalog was built: statistics may not cover new columns.
    stale: bool = False
    drift: tuple[DriftIssue, ...] = ()
    notes: tuple[str, ...] = ()
    profile_sample_rows: int | None = None


@dataclass
class _Entry:
    snapshot: CatalogSnapshot
    status: CatalogStatus
    run_key: str | None
    package_hash: str
    checked_at: float
    ttl: float
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class CatalogService:
    def __init__(
        self,
        engine: Callable[[], AsyncEngine] | AsyncEngine | None = None,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        live_ttl_seconds: float = LIVE_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        package_resolver: Callable[[str], DatasetPackage] = get_package,
    ) -> None:
        self._engine = engine
        self._ttl = ttl_seconds
        self._live_ttl = live_ttl_seconds
        self._clock = clock
        self._packages = package_resolver
        self._entries: dict[str, _Entry] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    # --- public -----------------------------------------------------------

    async def get_snapshot(self, dataset_id: str) -> CatalogSnapshot:
        """The catalog of ``dataset_id``.  Raises ``UnknownDatasetError`` for an unknown dataset only."""
        return (await self._entry(dataset_id)).snapshot

    async def get_status(self, dataset_id: str) -> CatalogStatus:
        return (await self._entry(dataset_id)).status

    def invalidate(self, dataset_id: str | None = None) -> None:
        """Forget cached snapshots (all, or one dataset's)."""
        if dataset_id is None:
            self._entries.clear()
        else:
            self._entries.pop(dataset_id, None)

    # --- internals --------------------------------------------------------

    def _engine_or_none(self) -> AsyncEngine | None:
        engine = self._engine
        if engine is None:
            from src.db.engine import get_engine

            return get_engine()
        return engine() if callable(engine) else engine

    async def _entry(self, dataset_id: str) -> _Entry:
        pkg = self._packages(dataset_id)
        lock = self._locks.setdefault(dataset_id, asyncio.Lock())
        async with lock:
            entry = self._entries.get(dataset_id)
            now = self._clock()
            if entry is not None and entry.package_hash == pkg.content_hash and now - entry.checked_at < entry.ttl:
                return entry
            run_key = await self._current_run(pkg)
            if (
                entry is not None
                and entry.package_hash == pkg.content_hash
                and entry.run_key == run_key
                and entry.status.origin == "stored"
            ):
                entry.checked_at = now
                return entry
            entry = await self._load(pkg, run_key)
            entry.checked_at = self._clock()
            self._entries[dataset_id] = entry
            return entry

    async def _current_run(self, pkg: DatasetPackage) -> str | None:
        """The run the stored catalog should belong to; None when the database does not say."""

        def work(conn: Connection) -> str | None:
            return repository.active_run_id(conn, pkg.id) or repository.latest_run_id(conn, pkg.id)

        try:
            engine = self._engine_or_none()
            if engine is None:
                return None
            async with engine.connect() as aconn:
                return await aconn.run_sync(work)
        except Exception as exc:  # noqa: BLE001  (an unreachable database must not break callers)
            logger.warning("catalog: database not available (%s)", type(exc).__name__)
            return None

    async def _load(self, pkg: DatasetPackage, run_key: str | None) -> _Entry:
        base = CatalogSnapshot.from_package(pkg)
        if run_key is not None:
            stored = await self._read_stored(pkg, run_key)
            if stored is not None:
                info = stored.info
                snapshot = apply_profile(base, stored.profiles, stored.relationship_stats, run_id=run_key)
                status = CatalogStatus(
                    dataset_id=pkg.id,
                    origin="stored",
                    run_id=run_key,
                    built_at=info.built_at,
                    duration_ms=info.duration_ms,
                    stale=info.package_hash != pkg.content_hash,
                    drift=info.drift,
                    notes=info.notes,
                    profile_sample_rows=info.sample_rows,
                )
                return _Entry(snapshot, status, run_key, pkg.content_hash, 0.0, self._ttl)
        live = await self._build_live(pkg)
        if live is not None:
            snapshot, info = live
            status = CatalogStatus(
                pkg.id, "live", None, None, info.duration_ms, False, info.drift, info.notes, info.sample_rows
            )
            return _Entry(snapshot, status, run_key, pkg.content_hash, 0.0, self._live_ttl)
        return _Entry(base, CatalogStatus(pkg.id, "package"), run_key, pkg.content_hash, 0.0, self._ttl)

    async def _read_stored(self, pkg: DatasetPackage, run_key: str) -> repository.StoredCatalog | None:
        try:
            engine = self._engine_or_none()
            if engine is None:
                return None
            async with engine.connect() as aconn:
                return await aconn.run_sync(lambda conn: repository.load_build(conn, pkg.id, run_key))
        except Exception as exc:  # noqa: BLE001
            logger.warning("catalog: stored catalog not readable (%s)", type(exc).__name__)
            return None

    async def _build_live(self, pkg: DatasetPackage) -> tuple[CatalogSnapshot, BuildInfo] | None:
        """Profile the live data without storing anything.  None when the dataset has no loaded tables."""
        cfg = profile_config(get_settings())

        def work(conn: Connection):
            schema, shared = resolve_schema(conn, pkg)
            built = build_catalog(conn, pkg, schema=schema, run_id="live", cfg=cfg, shared_schema=shared)
            conn.rollback()
            return built

        try:
            engine = self._engine_or_none()
            if engine is None:
                return None
            async with engine.connect() as aconn:
                built = await aconn.run_sync(work)
        except Exception as exc:  # noqa: BLE001
            logger.warning("catalog: live build not possible (%s)", type(exc).__name__)
            return None
        if not built.profiles:
            return None
        # A live-built snapshot is not tied to a stored run.
        return replace(built.snapshot, run_id=None), built.info


_default: CatalogService | None = None


def get_catalog_service() -> CatalogService:
    """The process-wide service (FastAPI dependency and default for callers)."""
    global _default
    if _default is None:
        _default = CatalogService()
    return _default


def reset_catalog_service() -> None:
    """Drop the process-wide service and its cache (tests)."""
    global _default
    _default = None

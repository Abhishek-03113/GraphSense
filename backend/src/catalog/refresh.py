"""Building the catalog and storing it: the one entry point the CLI and the ingestion hook share."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from sqlalchemy import Connection, Engine
from sqlalchemy.ext.asyncio import AsyncEngine

from src.catalog import repository
from src.catalog.builder import BuiltCatalog, build_catalog
from src.catalog.introspect import schema_exists
from src.catalog.profiler import ProfileConfig
from src.datasets.models import DatasetPackage

UNVERSIONED_RUN = "unversioned"


def profile_config(settings: Any) -> ProfileConfig:
    """Profiling limits from the application settings."""
    return ProfileConfig(
        sample_rows=int(settings.PROFILE_SAMPLE_ROWS), enum_max_distinct=int(settings.ENUM_MAX_DISTINCT)
    )


def resolve_schema(conn: Connection, pkg: DatasetPackage, explicit: str | None = None) -> str:
    """The schema holding the live data of ``pkg``.

    Order: the schema asked for; the one registered for the dataset; the
    dataset's own schema.
    """
    if explicit:
        return explicit
    registered = repository.registered_schema(conn, pkg.id)
    if registered and schema_exists(conn, registered):
        return registered
    return pkg.schema_name


def refresh_on_connection(
    conn: Connection,
    pkg: DatasetPackage,
    *,
    schema: str | None = None,
    run_id: str | None = None,
    cfg: ProfileConfig,
    commit: bool = True,
) -> BuiltCatalog:
    """Build the catalog from the dataset's live data and store it as the build of ``run_id``.

    ``run_id`` defaults to the dataset's active run (so ``catalog refresh``
    re-profiles the live data in place) and then to ``unversioned``.
    """
    target = resolve_schema(conn, pkg, schema)
    active = repository.active_run_id(conn, pkg.id)
    built = build_catalog(conn, pkg, schema=target, run_id=run_id or active or UNVERSIONED_RUN, cfg=cfg)
    repository.save_build(conn, built, active=active)
    if commit:
        conn.commit()
    return built


async def run_on[T](engine: AsyncEngine | Engine, fn: Callable[[Connection], T]) -> T:
    """Run ``fn(connection)`` on a sync or async engine, committing afterwards."""
    if isinstance(engine, AsyncEngine):
        async with engine.connect() as aconn:
            result = await aconn.run_sync(fn)
            await aconn.commit()
            return result

    def work() -> T:
        with engine.connect() as conn:
            value = fn(conn)
            conn.commit()
            return value

    return await asyncio.to_thread(work)

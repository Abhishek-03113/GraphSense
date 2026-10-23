"""What the Ask layer can do for a dataset right now (for the dataset status endpoint).

``await ai_status(dataset_id)`` replaces the configuration-only placeholder in
``src/api/datasets.py``::

    {
      "mode": "full" | "degraded" | "disabled",
      "llm_configured": bool,
      "embeddings_configured": bool,
      "knowledge": {"state": "ready" | "stale" | "missing", "items": int, "embed_model": str | None,
                    "embedded": int, "text_only": int, "last_refresh": ISO time | None}
    }

It never raises and never exposes paths, SQL or provider errors: when the database cannot be
asked, the knowledge state is reported as ``missing``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from src.datasets.context import DatasetContext
from src.datasets.errors import UnknownDatasetError
from src.datasets.registry import get_package
from src.intelligence.catalog_access import build_catalog_source
from src.intelligence.knowledge.items import build_items
from src.intelligence.knowledge.refresh import summarise
from src.intelligence.knowledge.store import KnowledgeStore
from src.intelligence.providers.base import is_configured
from src.intelligence.providers.factory import build_providers
from src.utils.logger import get_logger

logger = get_logger(__name__)


def configured_ai() -> dict[str, Any]:
    """Mode and provider state from configuration alone (no database)."""
    providers = build_providers()
    return {
        "mode": providers.mode,
        "llm_configured": is_configured(providers.llm),
        "embeddings_configured": is_configured(providers.embedder),
    }


# The most recent run that finished and in which the knowledge hook ran.  Ingest runs count (the
# hook runs after the swap) as do refresh runs; a run that was skipped or whose hook failed does not.
_LAST_REFRESH_RUN = text(
    """
    SELECT max(r.finished_at)
    FROM app.ingestion_runs r
    WHERE r.dataset_id = :d
      AND r.status IN ('succeeded', 'succeeded_with_warnings')
      AND EXISTS (
          SELECT 1
          FROM jsonb_array_elements(
              CASE WHEN jsonb_typeof(r.report -> 'hooks') = 'array' THEN r.report -> 'hooks' ELSE '[]'::jsonb END
          ) AS h
          WHERE h ->> 'name' = 'knowledge' AND h ->> 'status' IN ('ok', 'warning')
      )
    """
)
_LAST_ITEM_CREATED = text("SELECT max(created_at) FROM app.knowledge_items WHERE dataset_id = :d")


async def last_refresh_time(engine: AsyncEngine, dataset_id: str) -> datetime | None:
    """When the knowledge of ``dataset_id`` was last refreshed.

    This is the finish time of the latest run (ingest or refresh) whose knowledge hook ran, which
    moves forward even when a refresh finds nothing to change.  ``max(created_at)`` of the items
    would not: unchanged items keep their old timestamp.  Knowledge built outside a recorded run
    (``graphsense knowledge refresh``) has no run, so the newest item is the best answer left.
    """
    try:
        async with engine.connect() as conn:
            when = await conn.scalar(_LAST_REFRESH_RUN, {"d": dataset_id})
        if when is not None:
            return when
    except Exception as exc:  # noqa: BLE001 - the run table may not exist yet; fall back below
        logger.info("No refresh run history for %s (%s)", dataset_id, type(exc).__name__)
    async with engine.connect() as conn:
        return await conn.scalar(_LAST_ITEM_CREATED, {"d": dataset_id})


async def ai_status(dataset_id: str, engine: AsyncEngine | None = None) -> dict[str, Any]:
    providers = build_providers()
    out: dict[str, Any] = {
        "mode": providers.mode,
        "llm_configured": is_configured(providers.llm),
        "embeddings_configured": is_configured(providers.embedder),
        "knowledge": {
            "state": "missing",
            "items": 0,
            "embed_model": providers.embedder.model or None,
            "embedded": 0,
            "text_only": 0,
            "last_refresh": None,
        },
    }
    try:
        if engine is None:
            from src.db.engine import get_engine

            engine = get_engine()
        store = KnowledgeStore(engine)
        rows = await store.existing(dataset_id)
        desired = None
        try:
            package = get_package(dataset_id)
            snapshot = await build_catalog_source().get_snapshot(
                DatasetContext(id=package.id, schema_name=package.schema_name, package=package)
            )
            desired = {(i.kind, i.content_hash) for i in build_items(snapshot)}
        except UnknownDatasetError:
            pass
        model = providers.embedder.model if is_configured(providers.embedder) else ""
        summary = summarise(rows, model, desired)
        out["knowledge"].update(
            state=summary.state, items=summary.items, embedded=summary.embedded, text_only=summary.text_only
        )
        if rows:
            latest = await last_refresh_time(engine, dataset_id)
            out["knowledge"]["last_refresh"] = latest.isoformat() if latest else None
    except Exception as exc:  # noqa: BLE001 - a status page must not fail because the knowledge store is down
        logger.warning("Could not read the knowledge state for %s (%s)", dataset_id, type(exc).__name__)
    return out

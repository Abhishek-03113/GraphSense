"""Post-swap hook: refresh the knowledge store after a dataset has been (re)loaded.

Register it with ``POST_INGEST_HOOKS=src.intelligence.knowledge.hooks:refresh_knowledge``.
It follows the ingestion hook protocol of ``src.ingestion.hooks`` (``name``, ``phase``,
``async run(ctx)`` returning a ``HookResult``).  A failure never raises: the data is already
live, so the run only gets a warning.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from src.config import get_settings
from src.datasets.context import DatasetContext
from src.ingestion.hooks import HookContext, HookResult
from src.intelligence.catalog_access import catalog_source_for
from src.intelligence.knowledge.refresh import refresh_knowledge as run_refresh
from src.intelligence.knowledge.store import KnowledgeStore
from src.intelligence.providers.factory import build_providers
from src.utils.logger import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def knowledge_engine(candidate: Any = None) -> AsyncIterator[AsyncEngine]:
    """The caller's async engine, or a short-lived one.

    A hook may run on its own event loop (a worker thread), where pooled connections
    created elsewhere cannot be used, so the fallback is an unpooled engine that is
    disposed afterwards.
    """
    if isinstance(candidate, AsyncEngine):
        yield candidate
        return
    engine = create_async_engine(get_settings().require_database_dsn(), poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


class RefreshKnowledgeHook:
    name = "knowledge"
    phase = "post_swap"

    def __call__(self) -> RefreshKnowledgeHook:  # tolerate registries that call a factory
        return self

    async def run(self, ctx: HookContext) -> HookResult:
        try:
            dataset = DatasetContext(id=ctx.dataset_id, schema_name=ctx.schema, package=ctx.package)
            providers = build_providers()
            options = getattr(ctx, "options", None) or {}
            async with knowledge_engine(getattr(ctx, "engine", None)) as engine:
                # Read the catalog through this hook's engine: a hook runs on its own event loop,
                # where the process-wide application engine must not be created.
                snapshot = await catalog_source_for(engine, ctx.package).get_snapshot(dataset)
                report = await run_refresh(
                    KnowledgeStore(engine), snapshot, providers.embedder, force=bool(options.get("force"))
                )
        except Exception as exc:
            logger.exception("Knowledge refresh failed for %s", ctx.dataset_id)
            return HookResult(
                name=self.name, status="warning", message=f"knowledge refresh failed ({type(exc).__name__})"
            )
        details = report.as_dict()
        if report.warnings or (report.not_embedded_reason and report.embed_model):
            return HookResult(name=self.name, status="warning", message="; ".join(report.warnings), details=details)
        message = "knowledge refreshed"
        if not report.embed_model:
            message += " (text only: no embedding model configured)"
        return HookResult(name=self.name, status="ok", message=message, details=details)


refresh_knowledge = RefreshKnowledgeHook()

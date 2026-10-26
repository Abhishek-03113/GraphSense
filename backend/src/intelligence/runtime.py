"""The process-wide ``AskService`` and its collaborators, built on first use."""

from __future__ import annotations

from src.db.engine import get_engine
from src.intelligence.catalog_access import build_catalog_source
from src.intelligence.knowledge.store import KnowledgeStore
from src.intelligence.providers.factory import build_providers
from src.intelligence.querylog import QueryLog
from src.intelligence.retrieval.hybrid import HybridRetriever
from src.intelligence.service import AskService
from src.intelligence.sql.executor import ReadOnlyExecutor, assert_ready_for_production

_service: AskService | None = None


def get_ask_service() -> AskService:
    """The application's service (also usable as a FastAPI dependency, so tests can override it)."""
    global _service
    if _service is None:
        providers = build_providers()
        _service = AskService(
            llm=providers.llm,
            embedder=providers.embedder,
            catalog=build_catalog_source(),
            executor=ReadOnlyExecutor(),
            retriever=HybridRetriever(KnowledgeStore(get_engine), providers.embedder),
            query_log=QueryLog(get_engine, background=True),
        )
    return _service


def check_startup() -> None:
    """Called when the application starts: production must have the read-only database role."""
    assert_ready_for_production()


async def shutdown() -> None:
    """Finish the query log writes still in flight, then release the read-only connection pool."""
    global _service
    service, _service = _service, None
    query_log = getattr(service, "query_log", None)
    if query_log is not None and hasattr(query_log, "drain"):
        await query_log.drain()
    executor = getattr(service, "executor", None)
    if executor is not None and hasattr(executor, "close"):
        await executor.close()

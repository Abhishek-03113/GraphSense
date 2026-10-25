"""Async SQLAlchemy engine — created on first use, reused for every request.

Connection pooling is handled by SQLAlchemy's AsyncAdaptedQueuePool.  The
engine is not built at import time (so the application imports without a
database configured); call ``get_engine()``.  It is disposed during
application shutdown via ``dispose_engine()``.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from src.config import dsn_host, get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

_engine: AsyncEngine | None = None


def _build_engine() -> AsyncEngine:
    """Create the async engine with pool settings from config."""
    settings = get_settings()
    dsn = settings.require_database_dsn()
    logger.info(
        "db.engine.creating dsn=%s pool_size=%s max_overflow=%s",
        dsn_host(dsn),  # credentials hidden
        settings.DB_POOL_SIZE,
        settings.DB_MAX_OVERFLOW,
    )

    return create_async_engine(
        dsn,
        echo=settings.DB_ECHO,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        pool_timeout=settings.DB_POOL_TIMEOUT,
        pool_recycle=settings.DB_POOL_RECYCLE,
        pool_pre_ping=True,  # validates connections before handing them out
    )


def get_engine() -> AsyncEngine:
    """The shared engine, created on first use."""
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


async def dispose_engine() -> None:
    """Gracefully close all pooled connections (no-op if the engine was never used).

    Call this in the FastAPI lifespan shutdown handler.
    """
    global _engine
    if _engine is None:
        return
    engine, _engine = _engine, None
    await engine.dispose()
    logger.info("db.engine.disposed")

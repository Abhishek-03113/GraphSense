"""Async SQLAlchemy engine — created once, reused for every request.

Connection pooling is handled by SQLAlchemy's AsyncAdaptedQueuePool.
The module-level `engine` object must be disposed during application
shutdown via `dispose_engine()`.
"""

import structlog
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from .config import db_settings

logger = structlog.get_logger(__name__)


def _build_engine() -> AsyncEngine:
    """Create the async engine with pool settings from config."""
    dsn = str(db_settings.DATABASE_DSN)
    log = logger.bind(pool_size=db_settings.DB_POOL_SIZE, max_overflow=db_settings.DB_MAX_OVERFLOW)
    log.info("db.engine.creating", dsn=dsn.split("@")[-1])  # hide credentials

    return create_async_engine(
        dsn,
        echo=db_settings.DB_ECHO,
        pool_size=db_settings.DB_POOL_SIZE,
        max_overflow=db_settings.DB_MAX_OVERFLOW,
        pool_timeout=db_settings.DB_POOL_TIMEOUT,
        pool_recycle=db_settings.DB_POOL_RECYCLE,
        pool_pre_ping=True,  # validates connections before handing them out
    )


# Single engine instance shared across the entire application lifetime.
engine: AsyncEngine = _build_engine()


async def dispose_engine() -> None:
    """Gracefully close all pooled connections.

    Call this in the FastAPI lifespan shutdown handler.
    """
    await engine.dispose()
    logger.info("db.engine.disposed")

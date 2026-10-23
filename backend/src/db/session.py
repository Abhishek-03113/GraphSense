"""Async session factory and FastAPI dependency for database sessions.

Usage in a FastAPI route:
    from src.db import get_db_session
    from sqlalchemy.ext.asyncio import AsyncSession

    @router.get("/items")
    async def list_items(db: AsyncSession = Depends(get_db_session)):
        ...
"""

from collections.abc import AsyncGenerator

import structlog
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from .engine import get_engine

logger = structlog.get_logger(__name__)

_sessionmaker: async_sessionmaker[AsyncSession] | None = None
_bound_engine: AsyncEngine | None = None


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Session factory bound to the shared engine (rebuilt if the engine was disposed).

    expire_on_commit=False keeps ORM instances usable after commit without re-querying.
    """
    global _sessionmaker, _bound_engine
    engine = get_engine()
    if _sessionmaker is None or _bound_engine is not engine:
        _sessionmaker = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
        _bound_engine = engine
    return _sessionmaker


def AsyncSessionLocal() -> AsyncSession:
    """Open a new session; the factory is created on first use."""
    return get_sessionmaker()()


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields an AsyncSession per request.

    Commits on success, rolls back on any exception, and always closes the
    session so the connection is returned to the pool immediately.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("db.session.rollback")
            raise

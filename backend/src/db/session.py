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
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .engine import engine

logger = structlog.get_logger(__name__)

# Session factory bound to the shared engine.
# expire_on_commit=False keeps ORM instances usable after commit without re-querying.
AsyncSessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


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

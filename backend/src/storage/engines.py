"""Database engines by role.

* the **application** engine (``src.db.engine.get_engine``) serves the API with
  ``DATABASE_DSN``;
* the **owner** engines create schemas, load data and run migrations with
  ``OWNER_DATABASE_DSN`` (falling back to ``DATABASE_DSN``).  Ingestion is a
  batch job, so its main engine is synchronous (psycopg2 ``COPY``); an async
  owner engine exists for the migration runner and for hooks;
* the **read-only** engine runs generated SQL with ``READONLY_DATABASE_DSN``.

Engines are built on first use and cached; ``dispose_all`` closes them.
"""

from __future__ import annotations

import threading

import structlog
from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool

from src.config import dsn_host, get_settings

logger = structlog.get_logger(__name__)

_lock = threading.Lock()
_owner_sync: Engine | None = None
_readonly_async: AsyncEngine | None = None


def sync_dsn(dsn: str) -> str:
    """The psycopg2 form of a DSN (settings carry the asyncpg form)."""
    for prefix in ("postgresql+asyncpg://", "postgresql://", "postgres://"):
        if dsn.startswith(prefix):
            return "postgresql+psycopg2://" + dsn[len(prefix):]
    return dsn


def async_dsn(dsn: str) -> str:
    for prefix in ("postgresql+psycopg2://", "postgresql://", "postgres://"):
        if dsn.startswith(prefix):
            return "postgresql+asyncpg://" + dsn[len(prefix):]
    return dsn


def get_owner_sync_engine() -> Engine:
    """Synchronous engine for the owner role (ingestion, schema management)."""
    global _owner_sync
    with _lock:
        if _owner_sync is None:
            dsn = get_settings().require_owner_dsn()
            logger.info("storage.owner_engine.creating", dsn=dsn_host(dsn))
            _owner_sync = create_engine(sync_dsn(dsn), pool_size=4, max_overflow=4, pool_pre_ping=True)
        return _owner_sync


def make_owner_async_engine() -> AsyncEngine:
    """A new async owner engine without pooling.

    Not cached: an async engine is bound to the event loop it first connects on,
    and ingestion creates short-lived loops (one per CLI call or hook run).  The
    caller disposes it.
    """
    return create_async_engine(async_dsn(get_settings().require_owner_dsn()), poolclass=NullPool)


def get_readonly_engine() -> AsyncEngine:
    """Async engine for generated SQL.  Needs ``READONLY_DATABASE_DSN``."""
    global _readonly_async
    with _lock:
        if _readonly_async is None:
            dsn = get_settings().READONLY_DATABASE_DSN
            if dsn is None:
                raise RuntimeError("READONLY_DATABASE_DSN is not set.")
            logger.info("storage.readonly_engine.creating", dsn=dsn_host(dsn))
            _readonly_async = create_async_engine(
                async_dsn(str(dsn)), pool_size=3, max_overflow=3, pool_pre_ping=True
            )
        return _readonly_async


def dispose_sync_engines() -> None:
    """Close the cached synchronous engines (safe outside an event loop)."""
    global _owner_sync
    with _lock:
        engine, _owner_sync = _owner_sync, None
    if engine is not None:
        engine.dispose()


async def dispose_all() -> None:
    """Close every cached engine, including the application engine."""
    global _readonly_async
    from src.db.engine import dispose_engine

    dispose_sync_engines()
    with _lock:
        ro, _readonly_async = _readonly_async, None
    if ro is not None:
        await ro.dispose()
    await dispose_engine()

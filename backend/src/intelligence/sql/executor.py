"""Run validated, model-written SQL on a read-only connection.

Defence in depth.  The guard has already restricted *what* the query says; the
executor limits what it can *do* even if the guard had a bug:

* it connects with ``READONLY_DATABASE_DSN`` (a role that can only ``SELECT``
  from the dataset schemas).  Without that setting it falls back to the
  application DSN, logs ``degraded_security`` once, and still enforces the
  transaction-level limits below.  Production refuses to start in that state;
* each query runs in ``BEGIN READ ONLY``, so a write fails inside PostgreSQL;
* ``statement_timeout``, ``lock_timeout`` and ``idle_in_transaction_session_timeout``
  are set for the transaction (and as connection defaults);
* ``search_path`` is set to the dataset's schema, so generated SQL uses plain
  table names;
* rows are fetched through a cursor, at most ``row_cap + 1`` of them.

Failures are reduced to a category; the database's own message only goes to the log.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

import asyncpg

from src.config import Settings, dsn_host, get_settings
from src.intelligence.models import (
    ExecutionCategory,
    ExecutionError,
    ExecutionResult,
    ValidatedSql,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

_SCHEMA = re.compile(r"^[a-z][a-z0-9_]*$")

# SQLSTATE -> what went wrong.
_CATEGORY_BY_STATE: dict[str, ExecutionCategory] = {
    "57014": "timeout",  # query_canceled (statement_timeout)
    "55P03": "timeout",  # lock_not_available (lock_timeout)
    "25P03": "timeout",  # idle_in_transaction_session_timeout
    "42601": "syntax",
    "42000": "syntax",
    "42P01": "unknown_table",
    "3F000": "unknown_table",  # invalid_schema_name
    "42703": "unknown_column",
    "42702": "unknown_column",  # ambiguous column
    "42P10": "unknown_column",  # invalid column reference
    "42803": "syntax",  # grouping error
    "42883": "type",  # undefined function / operator does not exist
    "42804": "type",
    "42846": "type",
    "42809": "type",
    "22P02": "type",
    "22007": "type",
    "22008": "type",
    "22003": "type",
    "22012": "type",
    "22023": "type",
    "22001": "type",
}


def asyncpg_dsn(dsn: str) -> str:
    """The plain ``postgresql://`` form asyncpg wants (SQLAlchemy's ``+asyncpg`` marker removed)."""
    return re.sub(r"^postgres(?:ql)?(?:\+\w+)?://", "postgresql://", dsn, count=1)


def classify(exc: BaseException) -> ExecutionError:
    """Turn a driver failure into an :class:`ExecutionError` (category only; detail is for the log)."""
    detail = f"{type(exc).__name__}: {exc}"
    if isinstance(exc, asyncio.TimeoutError | TimeoutError):
        return ExecutionError("timeout", detail)
    state = getattr(exc, "sqlstate", None)
    if state in _CATEGORY_BY_STATE:
        category = _CATEGORY_BY_STATE[state]
        return ExecutionError(category, detail, not_ready=state in ("42P01", "3F000"))
    return ExecutionError("other", detail)


class ReadOnlyExecutor:
    """Pooled, read-only executor.  One instance per process; call :meth:`close` on shutdown."""

    def __init__(self, settings: Settings | None = None, *, dsn: str | None = None, pool_size: int = 5) -> None:
        self._settings = settings
        self._explicit_dsn = dsn
        self._pool_size = pool_size
        self._pool: asyncpg.Pool | None = None
        self._pool_loop: asyncio.AbstractEventLoop | None = None
        self._lock: asyncio.Lock | None = None
        self.degraded = False

    # --- configuration ----------------------------------------------------

    @property
    def settings(self) -> Settings:
        return self._settings or get_settings()

    def resolve_dsn(self) -> str:
        if self._explicit_dsn:
            return self._explicit_dsn
        s = self.settings
        if s.READONLY_DATABASE_DSN is not None:
            return str(s.READONLY_DATABASE_DSN)
        self.degraded = True
        return s.require_database_dsn()

    # --- pool -------------------------------------------------------------

    async def _get_pool(self) -> asyncpg.Pool:
        loop = asyncio.get_running_loop()
        if self._pool is not None and self._pool_loop is loop:
            return self._pool
        if self._lock is None or self._pool_loop is not loop:
            self._lock = asyncio.Lock()
        async with self._lock:
            if self._pool is not None and self._pool_loop is loop:
                return self._pool
            self._pool = None  # a pool of another loop cannot be used or closed from here
            dsn = self.resolve_dsn()
            timeout_ms = self.settings.SQL_STATEMENT_TIMEOUT_MS
            if self.degraded:
                logger.warning(
                    "degraded_security: READONLY_DATABASE_DSN is not set; generated SQL runs with the "
                    "application role (read-only transactions and timeouts still apply) on %s",
                    dsn_host(dsn),
                )
            else:
                logger.info("SQL executor connecting to %s", dsn_host(dsn))
            self._pool = await asyncpg.create_pool(
                asyncpg_dsn(dsn),
                min_size=0,
                max_size=self._pool_size,
                # No prepared-statement cache: a schema swap must never serve a stale plan.
                statement_cache_size=0,
                max_inactive_connection_lifetime=300,
                server_settings={
                    "application_name": "graphsense_ask",
                    "default_transaction_read_only": "on",
                    "statement_timeout": str(timeout_ms),
                    "lock_timeout": "2000",
                    "idle_in_transaction_session_timeout": str(timeout_ms * 2),
                },
            )
            self._pool_loop = loop
            return self._pool

    async def close(self) -> None:
        pool, self._pool = self._pool, None
        if pool is not None and self._pool_loop is asyncio.get_running_loop():
            await pool.close()

    # --- execution --------------------------------------------------------

    async def execute(self, schema_name: str | None, validated: ValidatedSql) -> ExecutionResult:
        """Run the query.  Raises :class:`ExecutionError`."""
        if schema_name is not None and not _SCHEMA.match(schema_name):
            raise ExecutionError("other", "invalid schema name")
        search_path = schema_name or "public"
        timeout_ms = self.settings.SQL_STATEMENT_TIMEOUT_MS
        started = time.perf_counter()
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                result = await asyncio.wait_for(
                    self._run(conn, search_path, timeout_ms, validated), timeout=timeout_ms / 1000 + 2
                )
        except ExecutionError:
            raise
        except Exception as exc:  # noqa: BLE001 - reduced to a category below
            error = classify(exc)
            logger.warning("SQL execution failed (%s): %s", error.category, error.detail[:300])
            raise error from None
        elapsed = int((time.perf_counter() - started) * 1000)
        return ExecutionResult(
            columns=result.columns,
            column_types=result.column_types,
            rows=result.rows,
            truncated=result.truncated,
            elapsed_ms=elapsed,
        )

    @staticmethod
    async def _run(conn: asyncpg.Connection, search_path: str, timeout_ms: int, v: ValidatedSql) -> ExecutionResult:
        async with conn.transaction(readonly=True):
            await conn.execute(
                "SELECT set_config('search_path', $1, true), set_config('statement_timeout', $2, true), "
                "set_config('lock_timeout', '2000', true)",
                search_path,
                str(timeout_ms),
            )
            stmt = await conn.prepare(v.sql)
            attributes = stmt.get_attributes()
            cursor = await stmt.cursor()
            fetched: list[Any] = await cursor.fetch(v.row_cap + 1)
        truncated = len(fetched) > v.row_cap
        rows = [tuple(r.values()) for r in fetched[: v.row_cap]]
        return ExecutionResult(
            columns=_unique_names([a.name for a in attributes]),
            column_types=tuple(a.type.name for a in attributes),
            rows=rows,
            truncated=truncated,
        )


def _unique_names(names: list[str]) -> tuple[str, ...]:
    """Two output columns may share a name in SQL; a row dict cannot, so repeats get a suffix."""
    seen: dict[str, int] = {}
    out = []
    for name in names:
        count = seen.get(name, 0) + 1
        seen[name] = count
        out.append(name if count == 1 else f"{name}_{count}")
    return tuple(out)


def assert_ready_for_production(settings: Settings | None = None) -> None:
    """Refuse to run in production without the read-only role."""
    s = settings or get_settings()
    if s.is_production and s.READONLY_DATABASE_DSN is None:
        raise RuntimeError(
            "READONLY_DATABASE_DSN must be set when GRAPHSENSE_ENV=production: model-written SQL "
            "may only run with a SELECT-only database role."
        )

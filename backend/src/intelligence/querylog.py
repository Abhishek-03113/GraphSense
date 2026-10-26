"""``app.query_log``: the questions asked and the SQL written for them.

Questions can contain personal or business information, so rows are kept for
``QUERY_LOG_RETENTION_DAYS`` (default 90) and then deleted: opportunistically while
the application runs (at most once an hour) and on demand with
``graphsense knowledge purge-log``.  Writing the log never fails a request.

The application writes in the background (``background=True``): the entry's id is
generated here, returned at once, and the row is inserted after the answer has gone
out, so a question never waits for its log line.  ``drain()`` waits for pending writes.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from src.config import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)

PURGE_INTERVAL_S = 3600
MAX_QUESTION_CHARS = 2000


@dataclass(frozen=True)
class LogEntry:
    dataset_id: str
    question: str
    sql: str | None = None
    validated: bool = False
    error_code: str | None = None
    row_count: int | None = None
    latency_ms: int | None = None
    prompt_version: str | None = None
    model: str | None = None
    tokens: int | None = None


class QueryLog:
    def __init__(self, engine: AsyncEngine | Callable[[], AsyncEngine], *, background: bool = False) -> None:
        self._engine = engine
        self._last_purge = 0.0
        self._background = background
        self._pending: set[asyncio.Task] = set()

    @property
    def engine(self) -> AsyncEngine:
        return self._engine() if callable(self._engine) else self._engine

    async def record(self, entry: LogEntry) -> str | None:
        """Store one entry.  Returns its id, or ``None`` when logging is off or (when written in place) failed."""
        settings = get_settings()
        if not settings.QUERY_LOG_ENABLED:
            return None
        if not self._background:
            return await self._write(entry, None, settings.QUERY_LOG_RETENTION_DAYS)
        query_id = str(uuid.uuid4())
        task = asyncio.create_task(self._write(entry, query_id, settings.QUERY_LOG_RETENTION_DAYS))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)
        return query_id

    async def drain(self) -> None:
        """Wait for the entries still being written in the background."""
        if self._pending:
            await asyncio.gather(*list(self._pending), return_exceptions=True)

    async def _write(self, entry: LogEntry, query_id: str | None, retention_days: int) -> str | None:
        try:
            async with self.engine.begin() as conn:
                query_id = await conn.scalar(
                    text(
                        "INSERT INTO app.query_log (id, dataset_id, question, sql, validated, error_code, row_count, "
                        "latency_ms, prompt_version, model, tokens) "
                        "VALUES (COALESCE(CAST(:id AS uuid), gen_random_uuid()), :d, :q, :s, :v, :e, :r, :l, :p, :m, :t) "
                        "RETURNING id"
                    ),
                    {
                        "id": query_id,
                        "d": entry.dataset_id,
                        "q": entry.question[:MAX_QUESTION_CHARS],
                        "s": entry.sql,
                        "v": entry.validated,
                        "e": entry.error_code,
                        "r": entry.row_count,
                        "l": entry.latency_ms,
                        "p": entry.prompt_version,
                        "m": entry.model,
                        "t": entry.tokens,
                    },
                )
        except Exception as exc:  # noqa: BLE001 - the answer matters more than its log line
            logger.warning("Could not write the query log (%s)", type(exc).__name__)
            return None
        await self._maybe_purge(retention_days)
        return str(query_id) if query_id else None

    async def purge(self, older_than_days: int | None = None) -> int:
        """Delete entries older than the retention period (or ``older_than_days``).  Returns the count."""
        days = older_than_days if older_than_days is not None else get_settings().QUERY_LOG_RETENTION_DAYS
        async with self.engine.begin() as conn:
            result = await conn.execute(
                text("DELETE FROM app.query_log WHERE ts < now() - make_interval(days => :days)"), {"days": days}
            )
            return result.rowcount or 0

    async def _maybe_purge(self, days: int) -> None:
        now = time.monotonic()
        if now - self._last_purge < PURGE_INTERVAL_S:
            return
        self._last_purge = now
        try:
            removed = await self.purge(days)
            if removed:
                logger.info("Purged %d query log entries older than %d days", removed, days)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Query log purge failed (%s)", type(exc).__name__)

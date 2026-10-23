"""``app.query_log``: the questions asked and the SQL written for them.

Questions can contain personal or business information, so rows are kept for
``QUERY_LOG_RETENTION_DAYS`` (default 90) and then deleted: opportunistically while
the application runs (at most once an hour) and on demand with
``graphsense knowledge purge-log``.  Writing the log never fails a request.
"""

from __future__ import annotations

import time
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
    def __init__(self, engine: AsyncEngine | Callable[[], AsyncEngine]) -> None:
        self._engine = engine
        self._last_purge = 0.0

    @property
    def engine(self) -> AsyncEngine:
        return self._engine() if callable(self._engine) else self._engine

    async def record(self, entry: LogEntry) -> str | None:
        """Store one entry.  Returns its id, or ``None`` when logging is off or failed."""
        settings = get_settings()
        if not settings.QUERY_LOG_ENABLED:
            return None
        try:
            async with self.engine.begin() as conn:
                query_id = await conn.scalar(
                    text(
                        "INSERT INTO app.query_log (dataset_id, question, sql, validated, error_code, row_count, "
                        "latency_ms, prompt_version, model, tokens) "
                        "VALUES (:d, :q, :s, :v, :e, :r, :l, :p, :m, :t) RETURNING id"
                    ),
                    {
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
        await self._maybe_purge(settings.QUERY_LOG_RETENTION_DAYS)
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

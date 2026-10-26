"""Dataset-scoped database sessions.

Graph SQL names tables without a schema.  A request reads the right dataset
because its transaction runs with ``search_path = ds_<id>``
(``set_config(..., true)`` is transaction-local, so a pooled connection never
carries it to the next request).  Nothing else is on the path: a dataset that
is not loaded yet answers "relation does not exist", never another dataset's rows.

The path names a schema, not an object: when a load swaps a new generation in,
the same name resolves to the new tables on the next statement.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

import asyncpg
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.datasets.context import DatasetContext
from src.storage.readiness import DATASET_NOT_READY_MESSAGE, MISSING_RELATION_STATES, DatasetNotReady
from src.storage.schema_names import search_path_for

_SET_PATH = text("SELECT set_config('search_path', :path, true)")


async def use_dataset(session: AsyncSession, ctx: DatasetContext) -> AsyncSession:
    """Point ``session``'s transactions at the dataset's schema.  Returns the session.

    The path is applied whenever a transaction begins, so a request that never
    queries (for example one answered 404) never opens a connection for it.
    """
    params = {"path": search_path_for(ctx.schema_name)}
    sync_session = getattr(session, "sync_session", None)
    if sync_session is None:  # a stand-in session (tests): apply it right away
        await session.execute(_SET_PATH, params)
        return session

    @event.listens_for(sync_session, "after_begin")
    def _apply(_session, _transaction, connection) -> None:
        connection.execute(_SET_PATH, params)

    if session.in_transaction():
        await session.execute(_SET_PATH, params)
    return session



# ---------------------------------------------------------------------------
# Generated statements, straight to the driver
# ---------------------------------------------------------------------------
#
# ``session.execute(text(...))`` costs about 0.4 ms of Python per statement (compile
# cache, result wrapping, greenlet hops), more than a round trip to a nearby database.
# Graph requests run a dozen generated statements, so they go to the asyncpg
# connection underneath the session instead: the same connection and transaction, so
# the dataset's search_path and any savepoint apply as usual.

_NAMED_PARAM = re.compile(r"(?<![:\w]):([A-Za-z_]\w*)")
_positional_cache: dict[str, tuple[str, tuple[str, ...]]] = {}


def positional(sql: str) -> tuple[str, tuple[str, ...]]:
    """``:name`` parameters rewritten as ``$1, $2, ...``; returns the SQL and the names in order.

    Casts (``::text``) are left alone.  Only for generated SQL, whose string literals
    hold no colon-prefixed words.
    """
    found = _positional_cache.get(sql)
    if found is not None:
        return found
    names: list[str] = []

    def number(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in names:
            names.append(name)
        return f"${names.index(name) + 1}"

    found = (_NAMED_PARAM.sub(number, sql), tuple(names))
    if len(_positional_cache) > 2048:
        _positional_cache.clear()
    _positional_cache[sql] = found
    return found


async def fetch(db: AsyncSession, sql: str, params: Mapping[str, Any] | None = None) -> Sequence[Any]:
    """The rows of one generated statement, run on the session's own connection.

    A missing table or schema raises :class:`DatasetNotReady`.  A stand-in session
    (tests) is asked through ``execute`` as before.
    """
    params = params or {}
    if not isinstance(db, AsyncSession):
        return (await db.execute(text(sql), dict(params))).fetchall()
    query, names = positional(sql)
    connection = await db.connection()
    driver = (await connection.get_raw_connection()).driver_connection
    try:
        return await driver.fetch(query, *(params[name] for name in names))
    except asyncpg.PostgresError as exc:
        if exc.sqlstate in MISSING_RELATION_STATES:
            raise DatasetNotReady(DATASET_NOT_READY_MESSAGE) from exc
        raise

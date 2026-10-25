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


from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.datasets.context import DatasetContext
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


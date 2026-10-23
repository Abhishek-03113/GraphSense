"""The record ids the graph serves, so extracted entities can be checked against them."""

from __future__ import annotations

from collections.abc import Collection
from typing import Any, Protocol

from sqlalchemy import text

from src.datasets.context import DatasetContext
from src.repositories.graph_sql import GraphSqlBuilder
from src.storage.schema_names import search_path_for

# Far above the size of any dataset the evaluation is meant for; a hard stop for a huge one.
MAX_IDS_PER_TYPE = 2_000_000


class GraphIdSource(Protocol):
    async def ids(self, node_types: Collection[str]) -> dict[str, set[str]]:
        """``{node type: ids}`` for each requested node type."""
        ...


class DbGraphIds:
    """Ids read from the dataset's tables with the graph's own id SQL (cached per node type)."""

    def __init__(self, engine: Any, ctx: DatasetContext, *, limit: int = MAX_IDS_PER_TYPE) -> None:
        self._engine = engine
        self._ctx = ctx
        self._limit = limit
        self._cache: dict[str, set[str]] = {}

    async def ids(self, node_types: Collection[str]) -> dict[str, set[str]]:
        wanted = [t for t in node_types if t not in self._cache]
        if wanted:
            builder = GraphSqlBuilder(self._ctx.package.graph_dataset())
            engine = self._engine() if callable(self._engine) else self._engine
            nodes = {n.key: n for n in self._ctx.package.graph.node_types}
            async with engine.connect() as conn:
                if self._ctx.schema_name:
                    await conn.execute(
                        text("SELECT set_config('search_path', :p, true)"),
                        {"p": search_path_for(self._ctx.schema_name)},
                    )
                for key in wanted:
                    node = nodes.get(key)
                    if node is None:
                        self._cache[key] = set()
                        continue
                    rows = await conn.execute(text(builder.entities_query(node)), {"limit": self._limit})
                    self._cache[key] = {str(r[0]) for r in rows}
        return {t: self._cache.get(t, set()) for t in node_types}

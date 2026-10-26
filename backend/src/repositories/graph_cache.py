"""Graph responses cached per loaded generation of a dataset.

A dataset's data only changes when a load or a rollback renames another schema
into place as ``ds_<id>``, so the OID of the live schema identifies the data
exactly: a cached response is reused while the OID is the same and is never
served for another generation.  Nothing has to be invalidated, and every
worker process keeps its own cache.

Counts and samples scan whole tables; with the cache they are computed once
per generation instead of on every page load.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable
from typing import TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from src.storage.session import fetch

T = TypeVar("T")

_GENERATION = "SELECT to_regnamespace(:schema)::oid"


async def generation(db: AsyncSession, schema_name: str) -> int | None:
    """The OID of the dataset's live schema; ``None`` when it is not loaded."""
    rows = await fetch(db, _GENERATION, {"schema": schema_name})
    value = rows[0][0] if rows else None
    return int(value) if value is not None else None


class GenerationCache:
    """A small LRU of responses keyed by (schema, generation, request)."""

    def __init__(self, max_entries: int = 256) -> None:
        self.max_entries = max_entries
        self._entries: OrderedDict[tuple, object] = OrderedDict()

    async def get(self, db: AsyncSession, schema_name: str, key: Hashable, compute: Callable[[], Awaitable[T]]) -> T:
        """The cached value for ``key`` in the current generation, computing it on a miss.

        The generation is read again after computing; when a load swapped the data in
        between, the value is returned but not kept.
        """
        before = await generation(db, schema_name)
        if before is None:
            return await compute()
        full_key = (schema_name, before, key)
        if full_key in self._entries:
            self._entries.move_to_end(full_key)
            return self._entries[full_key]  # type: ignore[return-value]
        value = await compute()
        if await generation(db, schema_name) == before:
            self._entries[full_key] = value
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
        return value

    def clear(self) -> None:
        self._entries.clear()


graph_cache = GenerationCache()

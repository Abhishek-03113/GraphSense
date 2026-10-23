"""``app.knowledge_items``: persistence and search of the knowledge items.

All SQL uses bound parameters.  The vector is sent as text and cast on the server
(``CAST(:v AS vector)``).  When the pgvector extension is not installed the table
has no ``embedding`` column; the store notices and only offers full-text search.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from src.utils.logger import get_logger

logger = get_logger(__name__)

_TABLE = re.compile(r"^[a-z_][a-z0-9_]*(\.[a-z_][a-z0-9_]*)?$")


@dataclass(frozen=True)
class StoredRow:
    id: int
    kind: str
    ref: str
    content_hash: str
    embed_model: str
    dims: int | None
    has_embedding: bool


@dataclass(frozen=True)
class NewRow:
    kind: str
    ref: str
    text: str
    content_hash: str
    embed_model: str = ""
    dims: int | None = None
    embedding: list[float] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Hit:
    kind: str
    ref: str
    text: str
    metadata: dict[str, Any]
    score: float


def vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{float(v):.8g}" for v in values) + "]"


def tsquery_or(terms: list[str]) -> str:
    """An OR query over plain words (anything that could be tsquery syntax is dropped)."""
    clean = [re.sub(r"[^a-z0-9]", "", t.lower()) for t in terms]
    return " | ".join(dict.fromkeys(t for t in clean if t))


class KnowledgeStore:
    def __init__(self, engine: AsyncEngine | Callable[[], AsyncEngine], table: str = "app.knowledge_items") -> None:
        if not _TABLE.match(table):
            raise ValueError("invalid table name")
        self._engine = engine
        self.table = table
        self._has_vector: bool | None = None

    @property
    def engine(self) -> AsyncEngine:
        """The engine; a callable is resolved on every use so a disposed engine is never kept."""
        return self._engine() if callable(self._engine) else self._engine

    # --- capabilities -------------------------------------------------------

    async def has_vector(self) -> bool:
        """True when the table has an ``embedding`` column (pgvector is installed)."""
        if self._has_vector is None:
            schema, _, name = self.table.rpartition(".")
            async with self.engine.connect() as conn:
                found = await conn.scalar(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_schema = COALESCE(NULLIF(:s, ''), current_schema()) "
                        "AND table_name = :t AND column_name = 'embedding'"
                    ),
                    {"s": schema, "t": name},
                )
            self._has_vector = bool(found)
        return self._has_vector

    # --- reading ------------------------------------------------------------

    async def existing(self, dataset_id: str) -> list[StoredRow]:
        has_vec = await self.has_vector()
        embedded = "(embedding IS NOT NULL)" if has_vec else "FALSE"
        async with self.engine.connect() as conn:
            result = await conn.execute(
                text(
                    f"SELECT id, kind, ref, content_hash, embed_model, dims, {embedded} AS has_embedding "
                    f"FROM {self.table} WHERE dataset_id = :d ORDER BY id"
                ),
                {"d": dataset_id},
            )
            return [
                StoredRow(r.id, r.kind, r.ref, r.content_hash, r.embed_model, r.dims, bool(r.has_embedding))
                for r in result
            ]

    async def count(self, dataset_id: str) -> int:
        async with self.engine.connect() as conn:
            return int(
                await conn.scalar(
                    text(f"SELECT COUNT(*) FROM {self.table} WHERE dataset_id = :d AND active"), {"d": dataset_id}
                )
                or 0
            )

    async def search_lexical(self, dataset_id: str, terms: list[str], limit: int) -> list[Hit]:
        query = tsquery_or(terms)
        if not query:
            return []
        async with self.engine.connect() as conn:
            result = await conn.execute(
                text(
                    f"SELECT kind, ref, text, metadata, ts_rank_cd(tsv, q) AS score "
                    f"FROM {self.table}, to_tsquery('english', :q) AS q "
                    f"WHERE dataset_id = :d AND active AND tsv @@ q "
                    f"ORDER BY score DESC, id LIMIT :k"
                ),
                {"q": query, "d": dataset_id, "k": limit},
            )
            return _dedupe([Hit(r.kind, r.ref, r.text, _meta(r.metadata), float(r.score)) for r in result])

    async def search_vector(
        self, dataset_id: str, vector: list[float], embed_model: str, limit: int
    ) -> list[Hit]:
        """Nearest items embedded with ``embed_model``; ``score`` is cosine similarity (1 = identical)."""
        if not await self.has_vector():
            return []
        async with self.engine.connect() as conn:
            result = await conn.execute(
                text(
                    f"SELECT kind, ref, text, metadata, 1 - (embedding <=> CAST(:v AS vector)) AS score "
                    f"FROM {self.table} "
                    f"WHERE dataset_id = :d AND active AND embedding IS NOT NULL "
                    f"AND embed_model = :m AND dims = :n "
                    f"ORDER BY embedding <=> CAST(:v AS vector) LIMIT :k"
                ),
                {"v": vector_literal(vector), "d": dataset_id, "m": embed_model, "n": len(vector), "k": limit},
            )
            return _dedupe([Hit(r.kind, r.ref, r.text, _meta(r.metadata), float(r.score)) for r in result])

    # --- writing ------------------------------------------------------------

    async def replace(self, dataset_id: str, insert: list[NewRow], delete_ids: list[int]) -> None:
        """Insert ``insert`` and delete ``delete_ids`` in ONE transaction.

        Readers see the old rows or the new ones, never an empty or half-filled table.
        """
        has_vec = await self.has_vector()
        async with self.engine.begin() as conn:
            if delete_ids:
                await conn.execute(
                    text(f"DELETE FROM {self.table} WHERE dataset_id = :d AND id = ANY(:ids)"),
                    {"d": dataset_id, "ids": delete_ids},
                )
            if insert:
                columns = "dataset_id, kind, ref, text, content_hash, embed_model, dims, metadata"
                values = ":d, :kind, :ref, :text, :hash, :model, :dims, CAST(:meta AS jsonb)"
                if has_vec:
                    columns += ", embedding"
                    values += ", CAST(:emb AS vector)"
                params = []
                for row in insert:
                    p: dict[str, Any] = {
                        "d": dataset_id,
                        "kind": row.kind,
                        "ref": row.ref,
                        "text": row.text,
                        "hash": row.content_hash,
                        "model": row.embed_model,
                        "dims": row.dims,
                        "meta": json.dumps(row.metadata, default=str),
                    }
                    if has_vec:
                        p["emb"] = vector_literal(row.embedding) if row.embedding is not None else None
                    params.append(p)
                await conn.execute(
                    text(
                        f"INSERT INTO {self.table} ({columns}) VALUES ({values}) "
                        f"ON CONFLICT (dataset_id, kind, content_hash, embed_model) DO NOTHING"
                    ),
                    params,
                )

    async def delete_dataset(self, dataset_id: str) -> int:
        async with self.engine.begin() as conn:
            result = await conn.execute(text(f"DELETE FROM {self.table} WHERE dataset_id = :d"), {"d": dataset_id})
            return result.rowcount or 0


def _meta(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
            return loaded if isinstance(loaded, dict) else {}
        except ValueError:
            return {}
    return {}


def _dedupe(hits: list[Hit]) -> list[Hit]:
    seen: set[tuple[str, str]] = set()
    out = []
    for h in hits:
        key = (h.kind, h.ref)
        if key not in seen:
            seen.add(key)
            out.append(h)
    return out

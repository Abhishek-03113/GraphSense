"""Hybrid retrieval: vector similarity and full-text rank fused by reciprocal rank.

Sources, best first:

* the knowledge store (pgvector cosine similarity for items embedded with the current
  model, plus PostgreSQL full-text search on every item);
* an in-memory index of the same items, when the store is empty or unavailable.

With no embedding model the vector part is simply absent (``mode == "lexical"``).
The question is embedded once; the same vector also serves the scope check
(``best_similarity``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from src.catalog import CatalogSnapshot
from src.intelligence.knowledge.items import KnowledgeItem, build_items
from src.intelligence.knowledge.store import Hit, KnowledgeStore
from src.intelligence.providers.base import EmbeddingProvider, ProviderError, is_configured
from src.intelligence.retrieval.lexical import InMemoryIndex
from src.intelligence.text import tokens
from src.utils.logger import get_logger

logger = get_logger(__name__)

RRF_K = 60
Mode = Literal["hybrid", "lexical", "memory"]


def reciprocal_rank_fusion(rankings: list[list[Hit]], k: int = RRF_K) -> list[tuple[Hit, float]]:
    """Fuse ranked lists: an item's score is the sum of ``1 / (k + rank)`` over the lists it is in."""
    scores: dict[tuple[str, str], float] = {}
    first: dict[tuple[str, str], Hit] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, start=1):
            key = (hit.kind, hit.ref)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            first.setdefault(key, hit)
    ordered = sorted(scores, key=lambda key: (-scores[key], key))
    return [(first[key], scores[key]) for key in ordered]


class QueryEmbedding:
    """The question's embedding, computed at most once per request."""

    def __init__(self, embedder: EmbeddingProvider, question: str) -> None:
        self._embedder = embedder
        self._question = question
        self._done = False
        self._vector: list[float] | None = None
        self.failed: Exception | None = None
        self.calls = 0

    @property
    def available(self) -> bool:
        return is_configured(self._embedder)

    async def get(self) -> list[float] | None:
        if self._done or not self.available:
            return self._vector
        self._done = True
        try:
            self.calls += 1
            vectors = await self._embedder.embed([self._question], task="query")
            self._vector = vectors[0] if vectors else None
        except ProviderError as exc:
            self.failed = exc
            logger.warning("Question embedding failed (%s); using text search only", type(exc).__name__)
        return self._vector


@dataclass
class Retrieval:
    hits: list[tuple[Hit, float]] = field(default_factory=list)
    # Highest cosine similarity between the question and any stored item; None without vectors.
    best_similarity: float | None = None
    mode: Mode = "memory"
    warnings: list[str] = field(default_factory=list)


class HybridRetriever:
    def __init__(
        self,
        store: KnowledgeStore | None,
        embedder: EmbeddingProvider,
        *,
        items_for: Callable[[CatalogSnapshot], list[KnowledgeItem]] = build_items,
    ) -> None:
        self.store = store
        self.embedder = embedder
        self._items_for = items_for
        self._memory: dict[tuple[str, str, str | None], InMemoryIndex] = {}

    def _index(self, snapshot: CatalogSnapshot) -> InMemoryIndex:
        key = (snapshot.dataset_id, snapshot.package_hash, snapshot.run_id)
        index = self._memory.get(key)
        if index is None:
            self._memory = {k: v for k, v in self._memory.items() if k[0] != snapshot.dataset_id}
            index = self._memory[key] = InMemoryIndex(self._items_for(snapshot))
        return index

    async def retrieve(
        self,
        snapshot: CatalogSnapshot,
        question: str,
        query: QueryEmbedding | None = None,
        *,
        limit: int = 30,
    ) -> Retrieval:
        result = Retrieval()
        terms = tokens(question)
        dataset_id = snapshot.dataset_id

        if self.store is not None:
            try:
                if await self.store.count(dataset_id) > 0:
                    lexical = await self.store.search_lexical(dataset_id, terms, limit)
                    vector_hits: list[Hit] = []
                    vector = await query.get() if query is not None else None
                    if vector is not None:
                        vector_hits = await self.store.search_vector(
                            dataset_id, vector, self.embedder.model, limit
                        )
                    if vector_hits:
                        result.best_similarity = max(h.score for h in vector_hits)
                    result.mode = "hybrid" if vector_hits else "lexical"
                    result.hits = reciprocal_rank_fusion([vector_hits, lexical])
                    return result
            except Exception as exc:  # noqa: BLE001 - the in-memory index below still answers
                logger.warning("Knowledge store unavailable (%s); using the in-memory index", type(exc).__name__)
                result.warnings.append("knowledge store unavailable")

        result.mode = "memory"
        result.hits = reciprocal_rank_fusion([self._index(snapshot).search(question, limit)])
        return result

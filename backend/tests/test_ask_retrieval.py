"""Retrieval pieces that need no database: fusion, the in-memory index, context assembly."""

from src.catalog import CatalogSnapshot
from src.intelligence.catalog_access import llm_safe
from src.intelligence.knowledge.items import build_items
from src.intelligence.knowledge.store import Hit
from src.intelligence.providers import FakeEmbedder
from src.intelligence.retrieval.context import assemble_context, shortest_path
from src.intelligence.retrieval.hybrid import (
    HybridRetriever,
    QueryEmbedding,
    reciprocal_rank_fusion,
)
from src.intelligence.retrieval.lexical import InMemoryIndex


def hit(kind, ref, score=1.0, **meta):
    return Hit(kind, ref, ref, meta, score)


def test_reciprocal_rank_fusion_rewards_agreement():
    vector = [hit("table", "a"), hit("table", "b"), hit("table", "c")]
    lexical = [hit("table", "c"), hit("table", "a")]
    fused = [h.ref for h, _ in reciprocal_rank_fusion([vector, lexical])]
    assert fused == ["a", "c", "b"]  # in both lists beats in one
    assert reciprocal_rank_fusion([]) == []
    assert [h.ref for h, _ in reciprocal_rank_fusion([vector])] == ["a", "b", "c"]


def test_the_in_memory_index_ranks_the_matching_table_first(toy_package):
    items = build_items(CatalogSnapshot.from_package(toy_package))
    index = InMemoryIndex(items)
    hits = index.search("which authors wrote books", 5)
    assert hits and hits[0].kind in ("table", "example", "relationship")
    assert any(h.ref == "authors" for h in hits)
    assert index.search("xyzzy plugh", 5) == []
    assert index.search("", 5) == []


def test_golden_questions_are_not_searchable(toy_package):
    snap = CatalogSnapshot.from_package(toy_package)
    hits = InMemoryIndex(build_items(snap)).search("How many loans are still open?", 20)
    assert all(h.kind != "example" or h.ref != "open_loans" for h in hits)


async def test_memory_retrieval_without_a_store(toy_package):
    snap = CatalogSnapshot.from_package(toy_package)
    retriever = HybridRetriever(None, FakeEmbedder())
    result = await retriever.retrieve(snap, "late fees on loans", None)
    assert result.mode == "memory" and result.best_similarity is None
    assert "loans" in [h.ref for h, _ in result.hits if h.kind == "table"]


async def test_the_query_embedding_is_computed_once():
    embedder = FakeEmbedder()
    query = QueryEmbedding(embedder, "how many books")
    first, second = await query.get(), await query.get()
    assert first == second and query.calls == 1 and len(embedder.calls) == 1


def test_join_path_adds_the_connecting_table(toy_package):
    snap = CatalogSnapshot.from_package(toy_package)
    from src.intelligence.retrieval.context import _adjacency

    assert shortest_path(_adjacency(snap), "authors", "loans") == ["authors", "books", "loans"]
    assert shortest_path(_adjacency(snap), "authors", "authors") == ["authors"]


def test_context_includes_the_link_table_between_two_distant_tables(toy_package):
    snap = llm_safe(CatalogSnapshot.from_package(toy_package))
    hits = [(hit("table", "authors"), 0.9), (hit("table", "loans"), 0.8)]
    bundle = assemble_context(snap, hits, budget_chars=20000)
    assert set(bundle.table_names) >= {"authors", "loans", "books"}
    assert any("books" in r and "authors" in r for r in bundle.relationships)


def test_context_respects_the_budget_and_never_includes_golden_examples(toy_package):
    snap = llm_safe(CatalogSnapshot.from_package(toy_package))
    hits = [(hit("example", "open_loans"), 0.9), (hit("example", "most_borrowed_books"), 0.8), (hit("table", "loans"), 0.7)]
    full = assemble_context(snap, hits, budget_chars=20000)
    assert full.example_ids == ["most_borrowed_books"]
    tiny = assemble_context(snap, hits, budget_chars=700)
    assert tiny.size < 1200 and tiny.table_names
    assert tiny.dropped_for_budget >= 0


def test_with_no_evidence_the_context_still_has_tables(toy_package):
    snap = llm_safe(CatalogSnapshot.from_package(toy_package))
    bundle = assemble_context(snap, [], budget_chars=20000)
    assert len(bundle.table_names) == 4 and bundle.hints

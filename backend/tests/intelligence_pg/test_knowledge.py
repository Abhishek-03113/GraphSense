"""Knowledge store, refresh, hybrid retrieval and the query log on a real PostgreSQL."""

import asyncio
import dataclasses

import psycopg2
import pytest
from sqlalchemy import text

from src.catalog import CatalogSnapshot
from src.catalog.model import GlossaryEntry
from src.config import override_settings
from src.intelligence.knowledge.hooks import refresh_knowledge as hook
from src.intelligence.knowledge.items import build_items
from src.intelligence.knowledge.refresh import knowledge_status, refresh_knowledge
from src.intelligence.knowledge.store import KnowledgeStore
from src.intelligence.providers import FakeEmbedder, NullEmbedder, ProviderUnavailable
from src.intelligence.querylog import LogEntry, QueryLog
from src.intelligence.retrieval.hybrid import HybridRetriever, QueryEmbedding

pytestmark = pytest.mark.integration

DATASET = "toy_library"


@pytest.fixture
async def store(app_engine):
    store = KnowledgeStore(app_engine)
    await store.delete_dataset(DATASET)
    yield store
    await store.delete_dataset(DATASET)
    await app_engine.dispose()


@pytest.fixture
def snap(toy_package):
    return CatalogSnapshot.from_package(toy_package)


def needs_vector(pg):
    if not pg.has_vector:
        pytest.skip("pgvector is not installed on the test server")


async def test_refresh_without_an_embedding_model_stores_text_only(store, snap):
    report = await refresh_knowledge(store, snap, NullEmbedder())
    items = build_items(snap)
    assert report.items == len(items) and report.inserted == len(items) and report.deleted == 0
    assert report.embedded == 0 and report.state == "ready" and report.embed_model == ""
    assert "no embedding model" in report.not_embedded_reason
    assert await store.count(DATASET) == len(items)


async def test_golden_examples_are_not_in_the_store(store, snap):
    await refresh_knowledge(store, snap, NullEmbedder())
    rows = await store.existing(DATASET)
    assert {r.kind for r in rows} <= {"table", "relationship", "glossary", "example", "profile", "value_set"}
    hits = await store.search_lexical(DATASET, ["loans", "open"], 50)
    assert all("How many loans are still open?" != h.text for h in hits)
    examples = [h for h in await store.search_lexical(DATASET, ["books", "borrowed", "authors"], 50) if h.kind == "example"]
    assert examples and all("sql" in h.metadata for h in examples)


async def test_refresh_is_idempotent_and_embeds_only_changes(pg, store, snap):
    needs_vector(pg)
    embedder = FakeEmbedder()
    first = await refresh_knowledge(store, snap, embedder)
    assert first.embedded == first.items and first.state == "ready" and first.embed_model == "fake-embed"
    calls = len(embedder.calls)

    again = await refresh_knowledge(store, snap, embedder)
    assert (again.inserted, again.deleted, again.kept) == (0, 0, first.items)
    assert len(embedder.calls) == calls  # nothing was embedded

    changed = dataclasses.replace(
        snap, glossary=(*snap.glossary[:-1], GlossaryEntry("new_rule", "A new rule", "Members may borrow ten books."))
    )
    third = await refresh_knowledge(store, changed, embedder)
    assert (third.inserted, third.deleted) == (1, 1)
    assert sum(n for _, n in embedder.calls[calls:]) == 1  # only the new item


async def test_a_new_embedding_model_re_embeds_everything(pg, store, snap):
    needs_vector(pg)
    await refresh_knowledge(store, snap, FakeEmbedder(model="m1", dims=32))
    report = await refresh_knowledge(store, snap, FakeEmbedder(model="m2", dims=64))
    assert report.inserted == report.items and report.deleted == report.items
    rows = await store.existing(DATASET)
    assert {(r.embed_model, r.dims) for r in rows} == {("m2", 64)}  # the size is stored per row
    assert (await knowledge_status(store, DATASET, FakeEmbedder(model="m2", dims=64), snap)).state == "ready"
    assert (await knowledge_status(store, DATASET, FakeEmbedder(model="m3"), snap)).state == "stale"


async def test_a_failing_embedder_keeps_text_and_reports_stale(pg, store, snap):
    embedder = FakeEmbedder()
    embedder.fail_with = ProviderUnavailable("down")
    report = await refresh_knowledge(store, snap, embedder)
    assert report.text_only == report.items and report.embedded == 0
    assert report.state == "stale" and report.warnings
    assert await store.count(DATASET) == report.items  # still searchable
    # later, with a working embedder, the text-only rows are upgraded in place
    embedder.fail_with = None
    upgraded = await refresh_knowledge(store, snap, embedder)
    if pg.has_vector:
        assert upgraded.embedded == upgraded.items and upgraded.state == "ready"


async def test_a_text_only_store_is_replaced_when_a_model_appears(pg, store, snap):
    needs_vector(pg)
    await refresh_knowledge(store, snap, NullEmbedder())
    report = await refresh_knowledge(store, snap, FakeEmbedder())
    assert report.deleted == report.items and report.embedded == report.items


async def test_no_empty_window_while_refreshing(pg, store, snap, app_engine):
    """A reader querying in a loop never sees the store empty or partly filled during forced refreshes."""
    needs_vector(pg)
    embedder = FakeEmbedder()
    await refresh_knowledge(store, snap, embedder)
    total = (await store.existing(DATASET)).__len__()
    reader = KnowledgeStore(app_engine)
    seen: list[int] = []
    lexical_empty = 0
    stop = asyncio.Event()

    async def read():
        nonlocal lexical_empty
        while not stop.is_set():
            seen.append(await reader.count(DATASET))
            if not await reader.search_lexical(DATASET, ["books", "loans"], 5):
                lexical_empty += 1
            await asyncio.sleep(0)

    task = asyncio.create_task(read())
    for _ in range(6):
        await refresh_knowledge(store, snap, embedder, force=True)
    stop.set()
    await task
    assert len(seen) > 10
    assert min(seen) == total == max(seen), f"saw counts {sorted(set(seen))}"
    assert lexical_empty == 0


async def test_hybrid_retrieval_ranks_by_meaning_and_words(pg, store, snap):
    needs_vector(pg)
    embedder = FakeEmbedder()
    await refresh_knowledge(store, snap, embedder)
    retriever = HybridRetriever(store, embedder)
    question = "Which books have been borrowed the most?"
    result = await retriever.retrieve(snap, question, QueryEmbedding(embedder, question))
    assert result.mode == "hybrid" and result.best_similarity is not None and result.best_similarity > 0.3
    top = [(h.kind, h.ref) for h, _ in result.hits[:4]]
    assert ("example", "most_borrowed_books") in top or ("table", "books") in top
    refs = {h.ref for h, _ in result.hits if h.kind == "table"}
    assert {"books", "loans"} <= refs

    off = await retriever.retrieve(snap, "solar system planets", QueryEmbedding(embedder, "solar system planets"))
    assert off.best_similarity is not None and off.best_similarity < 0.2  # nothing in the data resembles it


async def test_retrieval_is_text_only_without_an_embedder(store, snap):
    await refresh_knowledge(store, snap, NullEmbedder())
    retriever = HybridRetriever(store, NullEmbedder())
    result = await retriever.retrieve(snap, "authors and their books", QueryEmbedding(NullEmbedder(), "x"))
    assert result.mode == "lexical" and result.best_similarity is None
    assert result.hits and any(h.ref == "authors" for h, _ in result.hits)


async def test_retrieval_falls_back_to_memory_when_the_store_is_empty(store, snap):
    retriever = HybridRetriever(store, NullEmbedder())
    result = await retriever.retrieve(snap, "authors and their books", None)
    assert result.mode == "memory" and result.hits


async def test_retrieval_survives_a_broken_store(snap):
    from sqlalchemy.ext.asyncio import create_async_engine

    broken = KnowledgeStore(create_async_engine("postgresql+asyncpg://nobody@127.0.0.1:1/none"))
    result = await HybridRetriever(broken, NullEmbedder()).retrieve(snap, "books", None)
    assert result.mode == "memory" and result.hits and result.warnings


async def test_a_table_without_a_vector_column_still_works(pg, app_engine, snap):
    """The vector extension is optional: without it the store is full-text only."""
    async with app_engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS public.knowledge_novec"))
        await conn.execute(
            text(
                "CREATE TABLE public.knowledge_novec (id BIGSERIAL PRIMARY KEY, dataset_id TEXT NOT NULL, kind TEXT NOT NULL, "
                "ref TEXT NOT NULL, text TEXT NOT NULL, content_hash TEXT NOT NULL, embed_model TEXT NOT NULL DEFAULT '', "
                "dims INTEGER, metadata JSONB NOT NULL DEFAULT '{}', "
                "tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', replace(text, '_', ' '))) STORED, "
                "active BOOLEAN NOT NULL DEFAULT TRUE, "
                "CONSTRAINT uq_novec UNIQUE (dataset_id, kind, content_hash, embed_model))"
            )
        )
    store = KnowledgeStore(app_engine, table="public.knowledge_novec")
    assert await store.has_vector() is False
    embedder = FakeEmbedder()
    report = await refresh_knowledge(store, snap, embedder)
    assert report.state in ("stale", "ready") and await store.count(DATASET) == report.items
    result = await HybridRetriever(store, embedder).retrieve(snap, "authors and books", QueryEmbedding(embedder, "x"))
    assert result.mode == "lexical" and result.hits
    assert await store.search_vector(DATASET, [0.1] * 4, "fake-embed", 3) == []
    async with app_engine.begin() as conn:
        await conn.execute(text("DROP TABLE public.knowledge_novec"))


async def test_the_post_ingest_hook_refreshes_and_never_raises(pg, store, snap, toy_package):
    class Ctx:
        dataset_id = DATASET
        run_id = "r1"
        package = toy_package
        schema = "ds_toy_library"
        engine = None
        settings = None

    with override_settings(DATABASE_DSN=pg.app_dsn_sqlalchemy, EMBEDDING_PROVIDER="fake", EMBEDDING_DIMS=48):
        result = await hook.run(Ctx())
    assert result.status == "ok" and result.name == "knowledge"
    # The hook reads the live catalog, which adds profile-derived items to the package-only ones.
    assert result.details["items"] >= len(build_items(snap))
    assert hook.phase == "post_swap" and hook() is hook
    assert await store.count(DATASET) == result.details["items"]
    if pg.has_vector:
        assert result.details["embedded"] == result.details["items"]

    with override_settings(DATABASE_DSN="postgresql+asyncpg://nobody@127.0.0.1:1/none"):
        failed = await hook.run(Ctx())
    assert failed.status == "warning" and "failed" in failed.message


async def test_sensitive_values_never_reach_the_store(store, snap):
    from tests.test_ask_privacy import SECRET, snapshot_with_leaky_profile

    await refresh_knowledge(store, snapshot_with_leaky_profile(snap_package(snap)), NullEmbedder())
    async with store.engine.connect() as conn:
        found = await conn.scalar(
            text("SELECT COUNT(*) FROM app.knowledge_items WHERE text LIKE :p OR metadata::text LIKE :p"),
            {"p": f"%{SECRET}%"},
        )
    assert found == 0


def snap_package(snap):
    from src.datasets.registry import get_package

    return get_package("o2c") if snap.dataset_id == "o2c" else _toy()


def _toy():
    from src.datasets import load_package
    from tests.conftest import TOY_DIR

    return load_package(TOY_DIR)


# ---------------------------------------------------------------------------
# Query log
# ---------------------------------------------------------------------------


async def test_the_query_log_records_and_purges(pg, app_engine):
    log = QueryLog(app_engine)
    with override_settings(QUERY_LOG_ENABLED=True, QUERY_LOG_RETENTION_DAYS=90):
        query_id = await log.record(
            LogEntry(DATASET, "Which books are late?", sql="SELECT 1", validated=True, row_count=1, latency_ms=12,
                     prompt_version="v1", model="m", tokens=100)
        )
        assert query_id
        async with app_engine.begin() as conn:
            await conn.execute(
                text("INSERT INTO app.query_log (dataset_id, question, ts) VALUES (:d, 'ancient', now() - interval '120 days')"),
                {"d": DATASET},
            )
            await conn.execute(
                text("INSERT INTO app.query_log (dataset_id, question, ts) VALUES (:d, 'recent', now() - interval '10 days')"),
                {"d": DATASET},
            )
        removed = await log.purge()
        assert removed >= 1
        async with app_engine.connect() as conn:
            questions = {r[0] for r in await conn.execute(text("SELECT question FROM app.query_log WHERE dataset_id = :d"), {"d": DATASET})}
        assert "ancient" not in questions and {"recent", "Which books are late?"} <= questions
        assert await log.purge(older_than_days=0) >= 2  # an explicit period overrides the setting
    await app_engine.dispose()


async def test_a_background_log_returns_the_id_at_once_and_writes_that_row(pg, app_engine):
    log = QueryLog(app_engine, background=True)
    with override_settings(QUERY_LOG_ENABLED=True):
        query_id = await log.record(LogEntry(DATASET, "Written later?", sql="SELECT 1", validated=True))
        assert query_id and log._pending  # returned before the row was written
        await log.drain()
    async with app_engine.connect() as conn:
        question = await conn.scalar(
            text("SELECT question FROM app.query_log WHERE id = CAST(:i AS uuid)"), {"i": query_id}
        )
    assert question == "Written later?"
    with override_settings(QUERY_LOG_ENABLED=False):
        assert await log.record(LogEntry(DATASET, "q")) is None
    await app_engine.dispose()


async def test_logging_can_be_switched_off_and_never_raises(pg, app_engine):
    with override_settings(QUERY_LOG_ENABLED=False):
        assert await QueryLog(app_engine).record(LogEntry(DATASET, "q")) is None
    from sqlalchemy.ext.asyncio import create_async_engine

    broken = QueryLog(create_async_engine("postgresql+asyncpg://nobody@127.0.0.1:1/none"))
    with override_settings(QUERY_LOG_ENABLED=True):
        assert await broken.record(LogEntry(DATASET, "q")) is None
    await app_engine.dispose()


def test_the_migration_creates_what_the_code_expects(pg):
    conn = psycopg2.connect(pg.admin_dsn)
    cur = conn.cursor()
    cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'app' ORDER BY 1")
    assert [r[0] for r in cur.fetchall()] == ["eval_runs", "knowledge_items", "query_log"]
    cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema='app' AND table_name='knowledge_items'"
    )
    columns = {r[0] for r in cur.fetchall()}
    expected = {"dataset_id", "kind", "ref", "text", "content_hash", "embed_model", "dims", "metadata", "tsv", "active"}
    assert expected <= columns and ("embedding" in columns) == pg.has_vector
    conn.close()

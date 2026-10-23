"""The evaluation against a real PostgreSQL: read-only role, knowledge store, graph ids, eval_runs."""

import pytest

from src.catalog import CatalogSnapshot
from src.intelligence.eval.graph_ids import DbGraphIds
from src.intelligence.eval.replay import GoldenReplayLLM
from src.intelligence.eval.report import diff_metrics, load_metrics, store_report
from src.intelligence.eval.runner import Evaluator
from src.intelligence.knowledge.refresh import refresh_knowledge
from src.intelligence.knowledge.store import KnowledgeStore
from src.intelligence.providers import FakeEmbedder, NullEmbedder
from src.intelligence.retrieval.hybrid import HybridRetriever
from src.intelligence.sql.executor import ReadOnlyExecutor
from tests.ask_support import PackageCatalogSource

pytestmark = pytest.mark.integration


def evaluator(pg, ctx, app_engine, store) -> tuple[Evaluator, ReadOnlyExecutor]:
    embedder = FakeEmbedder()
    executor = ReadOnlyExecutor(dsn=pg.ro_dsn)
    return (
        Evaluator(
            mode="offline",
            llm=GoldenReplayLLM(),
            embedder=embedder,
            catalog=PackageCatalogSource(),
            executor=executor,
            retriever=HybridRetriever(store, embedder),
            scope_embedder=NullEmbedder(),
            graph_ids=DbGraphIds(app_engine, ctx),
            knowledge_texts=store.texts,
        ),
        executor,
    )


async def test_toy_package_scores_perfectly_with_a_populated_store(pg, toy_ctx, app_engine):
    store = KnowledgeStore(app_engine)
    await store.delete_dataset("toy_library")
    await refresh_knowledge(store, CatalogSnapshot.from_package(toy_ctx.package), FakeEmbedder())
    ev, executor = evaluator(pg, toy_ctx, app_engine, store)
    try:
        report = await ev.run(toy_ctx)
    finally:
        await executor.close()
        await store.delete_dataset("toy_library")
    assert report.score == 1.0, report.metrics
    assert report.leakage["stored_items"] > 0 and report.leakage["leaks"] == []
    assert report.metrics["entity_refs_checked"] > 0 and report.metrics["entity_validity"] == 1.0
    assert report.retrieval_modes == {("hybrid" if pg.has_vector else "lexical"): 5}


async def test_a_golden_question_written_into_the_store_is_caught(pg, toy_ctx, app_engine):
    from src.intelligence.knowledge.store import NewRow

    store = KnowledgeStore(app_engine)
    await store.delete_dataset("toy_library")
    await refresh_knowledge(store, CatalogSnapshot.from_package(toy_ctx.package), NullEmbedder())
    await store.replace(
        "toy_library",
        [NewRow("glossary", "tier-note", "A gold member is one who ... Which members hold a gold membership?", "h1")],
        [],
    )
    ev, executor = evaluator(pg, toy_ctx, app_engine, store)
    try:
        report = await ev.run(toy_ctx)
    finally:
        await executor.close()
        await store.delete_dataset("toy_library")
    assert report.metrics["golden_leaks"] >= 1 and report.score == 0.0
    assert any(x["example"] == "gold_members" and "stored item" in x["source"] for x in report.leakage["leaks"])


async def test_every_o2c_golden_query_passes_the_guard_and_runs_read_only(pg, o2c_ctx, app_engine):
    store = KnowledgeStore(app_engine)
    ev, executor = evaluator(pg, o2c_ctx, app_engine, store)
    try:
        report = await ev.run(o2c_ctx)
    finally:
        await executor.close()
    # The test database holds a handful of records, so only expectations about row counts may fail.
    assert report.golden_count >= 20
    assert report.metrics["sql_guard_acceptance"] == 1.0
    assert report.metrics["execution_success"] == 1.0
    assert report.metrics["result_correctness"] == 1.0
    assert report.metrics["golden_scope_lexical"] == 1.0
    assert report.metrics["guardrail_pass_rate"] == 1.0
    assert report.metrics["golden_leaks"] == 0
    assert report.read_only_role


async def test_runs_are_stored_and_can_be_compared(pg, toy_ctx, app_engine):
    store = KnowledgeStore(app_engine)
    ev, executor = evaluator(pg, toy_ctx, app_engine, store)
    try:
        report = await ev.run(toy_ctx)
    finally:
        await executor.close()
    run_id = await store_report(app_engine, report)
    stored = await load_metrics(app_engine, run_id)
    assert stored["result_correctness"] == 1.0
    assert await load_metrics(app_engine, "latest", "toy_library") == stored
    assert await load_metrics(app_engine, "00000000-0000-0000-0000-000000000000") is None
    assert {row[0] for row in diff_metrics(stored, report.metrics)} >= {"result_correctness", "golden_leaks"}
    async with app_engine.connect() as conn:
        from sqlalchemy import text

        row = (await conn.execute(text("SELECT mode, package_hash, report->>'dataset_id' FROM app.eval_runs WHERE id = CAST(:i AS uuid)"), {"i": run_id})).one()
    assert tuple(row) == ("offline", report.package_hash, "toy_library")
    await app_engine.dispose()

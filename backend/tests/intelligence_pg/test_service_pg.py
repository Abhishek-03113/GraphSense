"""The whole Ask pipeline on a real database, and entity ids compared with the graph's own."""

import pytest
from sqlalchemy import text

from src.catalog import CatalogSnapshot
from src.config import override_settings
from src.intelligence.entities import EntityExtractor
from src.intelligence.knowledge.refresh import refresh_knowledge
from src.intelligence.knowledge.store import KnowledgeStore
from src.intelligence.models import ValidatedSql
from src.intelligence.providers import FakeEmbedder, FakeLLM
from src.intelligence.querylog import QueryLog
from src.intelligence.retrieval.hybrid import HybridRetriever
from src.intelligence.service import AskService
from src.intelligence.sql.executor import ReadOnlyExecutor, search_path_for
from src.intelligence.sql.guard import SqlGuard
from src.intelligence.status import ai_status
from src.repositories.graph_sql import GraphSqlBuilder
from tests.ask_support import PackageCatalogSource, answer, draft

pytestmark = pytest.mark.integration


async def run_sql(pg, ctx, sql):
    """Validate and execute ``sql`` as the application would, with the read-only role."""
    snap = CatalogSnapshot.from_package(ctx.package)
    validated = SqlGuard().validate(sql, snap, schema_name=ctx.schema_name, max_rows=1000)
    assert isinstance(validated, ValidatedSql), getattr(validated, "message", "")
    executor = ReadOnlyExecutor(dsn=pg.ro_dsn)
    try:
        return validated, await executor.execute(ctx.schema_name, validated)
    finally:
        await executor.close()


async def test_the_full_pipeline_with_retrieval_log_and_the_read_only_role(pg, toy_ctx, app_engine):
    embedder = FakeEmbedder()
    snap = CatalogSnapshot.from_package(toy_ctx.package)
    store = KnowledgeStore(app_engine)
    await store.delete_dataset("toy_library")
    await refresh_knowledge(store, snap, embedder)
    executor = ReadOnlyExecutor(dsn=pg.ro_dsn)
    llm = FakeLLM(
        [
            draft("SELECT b.isbn, b.title, a.full_name FROM books b JOIN authors a ON a.author_id = b.author_id ORDER BY b.title"),
            answer("There are 3 books."),
        ]
    )
    service = AskService(
        llm=llm, embedder=embedder, catalog=PackageCatalogSource(), executor=executor,
        retriever=HybridRetriever(store, embedder), query_log=QueryLog(app_engine),
    )
    try:
        with override_settings(QUERY_LOG_ENABLED=True):
            result = await service.ask(toy_ctx, "Which books were written by which authors?", trace=True)
    finally:
        await executor.close()
        await store.delete_dataset("toy_library")
    assert result.ok, result.answer
    assert result.row_count >= 1 and {e.type for e in result.entities} == {"Book"}
    assert all(e.value for e in result.entities)
    assert result.trace["retrieval"]["mode"] == ("hybrid" if pg.has_vector else "lexical")
    assert result.query_id
    async with app_engine.connect() as conn:
        logged = (await conn.execute(text("SELECT question, validated, row_count, prompt_version FROM app.query_log WHERE id = CAST(:i AS uuid)"), {"i": result.query_id})).one()
    assert logged == ("Which books were written by which authors?", True, result.row_count, "v1")
    await app_engine.dispose()


async def test_an_unknown_function_never_reaches_the_database(pg, toy_ctx):
    service = AskService(
        llm=FakeLLM([draft("SELECT pg_read_file('/etc/passwd')")]),
        embedder=FakeEmbedder(), catalog=PackageCatalogSource(), executor=ReadOnlyExecutor(dsn=pg.ro_dsn),
    )
    try:
        result = await service.ask(toy_ctx, "Which books are there?")
    finally:
        await service.executor.close()
    assert result.error == "sql_rejected" and result.sql is None


async def test_a_real_timeout_is_a_category(pg, toy_ctx):
    sql = "SELECT COUNT(*) FROM generate_series(1, 100000000) a, generate_series(1, 100000000) b"
    executor = ReadOnlyExecutor(dsn=pg.ro_dsn)
    service = AskService(
        llm=FakeLLM([draft(sql), answer("x")]), embedder=FakeEmbedder(), catalog=PackageCatalogSource(), executor=executor
    )
    try:
        with override_settings(SQL_STATEMENT_TIMEOUT_MS=300):
            result = await service.ask(toy_ctx, "How many books are there in total?")
    finally:
        await executor.close()
    assert result.error == "sql_execution_error: timeout"


async def test_the_row_cap_marks_truncation_end_to_end(pg, toy_ctx):
    executor = ReadOnlyExecutor(dsn=pg.ro_dsn)
    service = AskService(
        llm=FakeLLM([draft("SELECT g.g AS isbn FROM generate_series(1, 500) AS g(g)"), answer("lots")]),
        embedder=FakeEmbedder(), catalog=PackageCatalogSource(), executor=executor,
    )
    try:
        with override_settings(SQL_MAX_ROWS=25):
            result = await service.ask(toy_ctx, "List every book isbn")
    finally:
        await executor.close()
    assert result.truncated and result.row_count == 25 and "truncated" in result.warnings
    assert "more" in result.summary


async def test_a_dataset_that_is_not_loaded_is_not_ready(pg, toy_ctx):
    import dataclasses

    ghost = dataclasses.replace(toy_ctx, schema_name="ds_not_loaded")
    executor = ReadOnlyExecutor(dsn=pg.ro_dsn)
    service = AskService(
        llm=FakeLLM([draft("SELECT b.title FROM books b")]), embedder=FakeEmbedder(), catalog=PackageCatalogSource(), executor=executor
    )
    try:
        result = await service.ask(ghost, "Which books are there?")
    finally:
        await executor.close()
    assert result.error == "dataset_not_ready"


def test_the_search_path_keeps_public_for_legacy_layouts():
    assert search_path_for("ds_o2c") == "ds_o2c, public"
    assert search_path_for(None) == "public"


# ---------------------------------------------------------------------------
# Every reference query runs; entities match the graph's ids
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("which", ["toy", "o2c"])
async def test_every_package_example_executes_after_validation(pg, which, toy_ctx, o2c_ctx):
    ctx = toy_ctx if which == "toy" else o2c_ctx
    snap = CatalogSnapshot.from_package(ctx.package)
    assert snap.examples
    for example in snap.examples:
        _, execution = await run_sql(pg, ctx, example.sql)
        assert execution.columns, example.id


async def graph_ids(pg, ctx):
    """``{NodeType}:{id}`` for every node the graph SQL can produce, straight from the database."""
    builder = GraphSqlBuilder(ctx.package.graph_dataset())
    ids: set[str] = set()
    conn = pg.connect()
    cur = conn.cursor()
    cur.execute(f'SET search_path = "{ctx.schema_name}"')
    for node in ctx.package.graph.node_types:
        cur.execute(builder.entities_query(node).replace(":limit", "100000"))
        ids |= {f"{node.key}:{row[0]}" for row in cur.fetchall()}
    conn.close()
    return ids


async def test_extracted_entities_match_the_node_ids_the_graph_serves(pg, o2c_ctx):
    """For every node type, selecting its id columns yields exactly the graph's ids."""
    extractor = EntityExtractor(o2c_ctx.package)
    served = await graph_ids(pg, o2c_ctx)
    assert served
    found: set[str] = set()
    for node in o2c_ctx.package.graph.node_types:
        columns = ", ".join(f"t.{c}" for c in node.id_columns)
        validated, execution = await run_sql(pg, o2c_ctx, f"SELECT {columns} FROM {node.table} t")
        entities, nodes = extractor.extract(list(validated.projections), execution.rows, max_rows=1000, max_entities=1000)
        own = {e.id for e in entities if e.type == node.key}
        expected = {i for i in served if i.startswith(f"{node.key}:")}
        assert own <= expected, (node.key, own - expected)
        assert own, f"no {node.key} entities extracted"
        assert [n.id for n in nodes] == [e.id for e in entities]
        found |= own
    assert found <= served


async def test_extracted_composite_ids_match_edge_endpoint_ids(pg, o2c_ctx):
    """The item end of an edge is written ``doc-item`` with the item stripped; so is an extracted entity."""
    builder = GraphSqlBuilder(o2c_ctx.package.graph_dataset())
    extractor = EntityExtractor(o2c_ctx.package)
    conn = pg.connect()
    cur = conn.cursor()
    cur.execute(f'SET search_path = "{o2c_ctx.schema_name}"')
    checked = 0
    for edge in o2c_ctx.package.graph.edge_types:
        cur.execute(builder.edge_select(edge))
        endpoints = {(r[1], r[0]) for r in cur.fetchall()} | {(r[3], r[2]) for r in cur.fetchall()}
        cur.execute(builder.edge_select(edge))
        for source_id, source_type, target_id, target_type, _ in cur.fetchall():
            endpoints |= {(source_type, source_id), (target_type, target_id)}
        for columns, node_type in ((edge.source_columns, edge.source), (edge.target_columns, edge.target)):
            cols = ", ".join(f"t.{c}" for c in columns)
            validated, execution = await run_sql(pg, o2c_ctx, f"SELECT {cols} FROM {edge.table} t")
            entities, _ = extractor.extract(list(validated.projections), execution.rows, max_rows=1000, max_entities=1000)
            mine = {e.value for e in entities if e.type == node_type}
            graph_side = {i for t, i in endpoints if t == node_type}
            assert mine and mine <= graph_side, (edge.key, node_type, sorted(mine - graph_side)[:3])
            checked += 1
    conn.close()
    assert checked >= 20


async def test_ai_status_reports_the_knowledge_state(pg, app_engine, toy_package):
    from src.config import override_settings as ovr

    snap = CatalogSnapshot.from_package(toy_package)
    store = KnowledgeStore(app_engine)
    await store.delete_dataset("toy_library")
    with ovr(GEMINI_API_KEY=__import__("pydantic").SecretStr(""), EMBEDDING_PROVIDER="fake"):
        missing = await ai_status("toy_library", app_engine)
        assert missing["knowledge"]["state"] == "missing" and missing["mode"] == "disabled"
        assert missing["llm_configured"] is False and missing["embeddings_configured"] is True
        await refresh_knowledge(store, snap, FakeEmbedder())
        ready = await ai_status("toy_library", app_engine)
    await store.delete_dataset("toy_library")
    if pg.has_vector:
        assert ready["knowledge"]["state"] == "ready" and ready["knowledge"]["embedded"] == ready["knowledge"]["items"]
    assert ready["knowledge"]["items"] > 0 and ready["knowledge"]["last_refresh"]
    unreachable = await ai_status("toy_library", __import__("sqlalchemy.ext.asyncio", fromlist=["x"]).create_async_engine("postgresql+asyncpg://x@127.0.0.1:1/x"))
    assert unreachable["knowledge"]["state"] == "missing"
    await app_engine.dispose()

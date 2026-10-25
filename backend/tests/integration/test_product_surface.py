"""What clients see around a dataset's lifecycle: not-ready graph routes, suggestions, last refresh."""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from src.config import reset_settings
from src.datasets.registry import get_package
from src.ingestion.runner import IngestOptions, ingest, prepare_refresh

pytestmark = pytest.mark.integration

TOY = {"X-GraphSense-Dataset": "toy_library"}
KNOWLEDGE_HOOK = "src.intelligence.knowledge.hooks:refresh_knowledge"

GRAPH_REQUESTS = [
    ("/api/graph/summary", {}),
    ("/api/graph/subgraphs", {"root_type": "Book", "root_id": "978-0", "depth": 2}),
    ("/api/graph/traces", {"doc_type": "Book", "doc_id": "978-0"}),
    ("/api/graph/flows/full/subgraph", {}),
    ("/api/graph/samples", {}),
    ("/api/graph/node-types/Book/entities", {}),
]


async def assert_not_ready(client):
    flow_id = get_package("toy_library").graph_dataset().flows[0].id
    for path, params in GRAPH_REQUESTS:
        params = {**params, **({"flow_id": flow_id} if path.endswith("/flow") else {})}
        res = await client.get(path, params=params, headers=TOY)
        assert res.status_code == 409, (path, res.text)
        body = res.json()
        assert body["code"] == "dataset_not_ready", path
        assert body["request_id"] == res.headers["X-Request-ID"]
        assert "relation" not in res.text and "ds_toy_library" not in res.text, path


async def test_graph_routes_on_a_dataset_that_was_never_loaded_answer_409(client):
    assert (await client.get("/api/datasets/toy_library/status")).json()["status"] == "empty"
    await assert_not_ready(client)
    # the failed queries did not poison the connection pool
    assert (await client.get("/api/graph/schema", headers=TOY)).status_code == 200
    assert (await client.get("/api/health")).status_code == 200


async def test_graph_routes_after_a_failed_first_load_answer_409(client, toy_root, db):
    (toy_root / "toy-library" / "loans" / "part-0001.jsonl").write_text("garbage\n")
    outcome = await asyncio.to_thread(ingest, "toy_library", IngestOptions(data_root=toy_root))
    assert outcome.status == "failed"
    assert (await client.get("/api/datasets/toy_library/status")).json()["status"] == "failed"
    await assert_not_ready(client)


async def test_graph_routes_work_once_the_data_is_loaded(client, toy_root):
    await asyncio.to_thread(ingest, "toy_library", IngestOptions(data_root=toy_root))
    res = await client.get("/api/graph/summary", headers=TOY)
    assert res.status_code == 200 and res.json()["nodes"]["Book"] == 3


async def test_suggested_questions_follow_the_data(client, toy_root):
    before = await client.get("/api/datasets/toy_library/suggested-questions")
    assert before.status_code == 200 and before.json() == {"dataset_id": "toy_library", "questions": []}

    await asyncio.to_thread(ingest, "toy_library", IngestOptions(data_root=toy_root))
    after = (await client.get("/api/datasets/toy_library/suggested-questions")).json()
    assert [q["text"] for q in after["questions"]] == [
        "Which books are borrowed most often?",
        "How many loans are overdue?",
        "Which authors have the most books?",
    ]


async def test_questions_needing_an_empty_table_are_hidden(client, toy_root, db):
    await asyncio.to_thread(ingest, "toy_library", IngestOptions(data_root=toy_root))
    db.sql("DELETE FROM ds_toy_library.loans")
    questions = (await client.get("/api/datasets/toy_library/suggested-questions")).json()["questions"]
    assert [q["text"] for q in questions] == ["Which authors have the most books?"]


async def test_unknown_dataset_has_no_suggestions(client):
    assert (await client.get("/api/datasets/nope/suggested-questions")).status_code == 404


async def test_last_refresh_is_the_latest_refresh_run_not_the_newest_item(client, toy_root, db, monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fake")
    monkeypatch.setenv("POST_INGEST_HOOKS", KNOWLEDGE_HOOK)
    reset_settings()

    first = await asyncio.to_thread(ingest, "toy_library", IngestOptions(data_root=toy_root))
    assert first.status.startswith("succeeded")
    knowledge = (await client.get("/api/datasets/toy_library/status")).json()["ai"]["knowledge"]
    assert knowledge["items"] > 0
    first_finished = db.scalar("SELECT finished_at FROM app.ingestion_runs WHERE id = :r", r=first.run_id)
    assert datetime.fromisoformat(knowledge["last_refresh"]) == first_finished

    # A refresh that finds nothing to change adds no items, so the newest item keeps its age.
    newest_item = db.scalar("SELECT max(created_at) FROM app.knowledge_items WHERE dataset_id = 'toy_library'")
    refresh = await asyncio.to_thread(lambda: prepare_refresh("toy_library", IngestOptions()).execute())
    assert refresh.kind == "refresh" and refresh.status.startswith("succeeded")
    assert db.scalar("SELECT max(created_at) FROM app.knowledge_items WHERE dataset_id = 'toy_library'") == newest_item

    knowledge = (await client.get("/api/datasets/toy_library/status")).json()["ai"]["knowledge"]
    refresh_finished = db.scalar("SELECT finished_at FROM app.ingestion_runs WHERE id = :r", r=refresh.run_id)
    assert datetime.fromisoformat(knowledge["last_refresh"]) == refresh_finished
    assert refresh_finished > first_finished
    assert datetime.fromisoformat(knowledge["last_refresh"]) > newest_item


async def test_last_refresh_ignores_runs_whose_knowledge_hook_did_not_run(client, toy_root, db, monkeypatch):
    monkeypatch.setenv("EMBEDDING_PROVIDER", "fake")
    reset_settings()
    # knowledge built outside any recorded run (as the CLI does) falls back to the newest item
    await asyncio.to_thread(ingest, "toy_library", IngestOptions(data_root=toy_root, hook_specs=[KNOWLEDGE_HOOK]))
    db.sql("DELETE FROM app.ingestion_runs")
    knowledge = (await client.get("/api/datasets/toy_library/status")).json()["ai"]["knowledge"]
    newest_item = db.scalar("SELECT max(created_at) FROM app.knowledge_items WHERE dataset_id = 'toy_library'")
    assert datetime.fromisoformat(knowledge["last_refresh"]) == newest_item

"""The chat endpoint's response shape and its error codes, without any LLM."""

import pytest
from fastapi.testclient import TestClient

from src.ai import chat as chat_module
from src.main import app

CLIENT = TestClient(app)

RESPONSE_FIELDS = {
    "answer", "sql", "data", "entities", "graph_nodes", "error", "row_count", "summary",
}


def ask(message: str) -> dict:
    res = CLIENT.post("/api/chat", json={"message": message})
    assert res.status_code == 200
    body = res.json()
    assert set(body) == RESPONSE_FIELDS
    return body


def test_off_topic_questions_are_rejected_with_the_guardrail_code():
    body = ask("write me a poem")
    assert body["error"] == "guardrail"
    assert body["answer"]
    assert body["data"] is None and body["entities"] == [] and body["graph_nodes"] == []


def test_missing_api_key_reports_not_configured(monkeypatch):
    monkeypatch.setattr(chat_module.ai_settings, "GEMINI_API_KEY", "")
    body = ask("How many invoices are there?")
    assert body["error"] == "not_configured"
    assert "GEMINI_API_KEY" in body["answer"]


def test_unexpected_failures_do_not_leak_internals(monkeypatch):
    monkeypatch.setattr(chat_module.ai_settings, "GEMINI_API_KEY", "test-key")

    def boom(_question: str) -> str:
        raise RuntimeError('relation "rag_embeddings" does not exist')

    monkeypatch.setattr(chat_module, "_retrieve_context", boom)
    body = ask("How many invoices are there?")
    assert body["error"] == "internal_error"
    assert "rag_embeddings" not in body["answer"]


def test_query_results_are_plain_json(monkeypatch):
    import datetime as dt
    from decimal import Decimal

    monkeypatch.setattr(chat_module.ai_settings, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(chat_module, "_retrieve_context", lambda _q: "context")
    monkeypatch.setattr(chat_module, "_generate_sql", lambda _q, _c: "SELECT 1")
    monkeypatch.setattr(
        chat_module,
        "_execute_sql",
        lambda _sql: (
            [{"billing_document": "90000001", "total": Decimal("1234.5000"), "day": dt.date(2025, 4, 3)}],
            ["billing_document", "total", "day"],
        ),
    )
    monkeypatch.setattr(
        chat_module,
        "_synthesize_response",
        lambda *_a: (
            "Based on 1 record found.",
            [{"id": "Invoice:90000001", "type": "Invoice", "label": "90000001"}],
        ),
    )
    body = ask("Show invoice 90000001")
    assert body["error"] is None
    assert body["data"] == [{"billing_document": "90000001", "total": 1234.5, "day": "2025-04-03"}]
    assert body["graph_nodes"] == [{"id": "Invoice:90000001", "type": "Invoice", "label": "90000001"}]
    assert body["entities"] == [{"id": "Invoice:90000001", "type": "Invoice", "value": "90000001"}]
    assert body["row_count"] == 1


@pytest.mark.parametrize("message", ["", "x" * 2001])
def test_invalid_messages_are_rejected_by_validation(message):
    assert CLIENT.post("/api/chat", json={"message": message}).status_code == 422

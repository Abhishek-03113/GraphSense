"""POST /api/chat: response compatibility, error codes, rate limit, and the retired training endpoint."""

import shutil

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from src.api.ratelimit import SlidingWindowLimiter, reset_chat_limiter
from src.config import override_settings
from src.intelligence import runtime
from src.intelligence.providers import FakeLLM, NullLLM, ProviderUnavailable
from src.intelligence.runtime import get_ask_service
from src.main import app
from tests.ask_support import StubExecutor, answer, draft, make_service, rows
from tests.conftest import TOY_DIR

ORIGINAL_FIELDS = {"answer", "sql", "data", "entities", "graph_nodes", "error", "row_count", "summary"}
ADDED_FIELDS = {"query_id", "mode", "columns", "truncated", "warnings", "assumptions", "suggestions"}


@pytest.fixture(autouse=True)
def _clean():
    reset_chat_limiter()
    runtime._service = None
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()
    reset_chat_limiter()
    runtime._service = None


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def toy_client(tmp_path, client):
    shutil.copytree(TOY_DIR, tmp_path / "toy_library")
    with override_settings(PACKAGES_DIR=tmp_path):
        yield client


def serve(llm, executor=None):
    service = make_service(llm, executor)
    app.dependency_overrides[get_ask_service] = lambda: service
    return service


def ask(client, message="Which books are there?", **kw):
    return client.post("/api/chat", json={"message": message}, headers={"X-GraphSense-Dataset": "toy_library"}, **kw)


def test_the_original_fields_are_kept_and_new_ones_are_additive(toy_client):
    serve(
        FakeLLM([draft("SELECT b.isbn, b.title FROM books b"), answer("Two books.")]),
        StubExecutor(rows(["isbn", "title"], ("111", "A"), ("222", "B"))),
    )
    response = ask(toy_client)
    body = response.json()
    assert response.status_code == 200
    assert set(body) == ORIGINAL_FIELDS | ADDED_FIELDS
    assert body["answer"] == "Two books." and body["error"] is None
    assert body["row_count"] == 2 and body["summary"] == "2 records found."
    assert body["data"] == [{"isbn": "111", "title": "A"}, {"isbn": "222", "title": "B"}]
    assert body["entities"][0] == {"id": "Book:111", "type": "Book", "value": "111"}
    assert body["graph_nodes"][0] == {"id": "Book:111", "type": "Book", "label": "111"}
    assert body["sql"].startswith("SELECT b.isbn, b.title FROM books AS b")
    assert body["mode"] == "degraded" and body["truncated"] is False
    assert [c["name"] for c in body["columns"]] == ["isbn", "title"]


def test_types_match_what_the_frontend_schema_reads(toy_client):
    """The Zod schema (frontend/src/lib/api/schemas.ts) wants these types; extra fields are ignored."""
    serve(FakeLLM([draft("SELECT b.title FROM books b"), answer()]), StubExecutor(rows(["title"], ("A",))))
    body = ask(toy_client).json()
    assert isinstance(body["answer"], str) and isinstance(body["row_count"], int) and isinstance(body["summary"], str)
    assert body["sql"] is None or isinstance(body["sql"], str)
    assert all(isinstance(e["id"], str) and isinstance(e["type"], str) for e in body["entities"])
    assert all(isinstance(n["id"], str) and isinstance(n["label"], str) for n in body["graph_nodes"])
    assert body["error"] is None


def test_an_error_keeps_the_original_shape(toy_client):
    serve(FakeLLM([draft("SELECT 1")]))
    body = ask(toy_client, "List the planets of the solar system").json()
    assert set(body) == ORIGINAL_FIELDS | ADDED_FIELDS
    assert body["error"] == "guardrail" and body["data"] is None and body["row_count"] == 0
    assert body["suggestions"]


def test_provider_failure_is_a_clean_code(toy_client):
    serve(FakeLLM([ProviderUnavailable("api key leaked: sk-123")]))
    response = ask(toy_client)
    assert response.status_code == 200 and response.json()["error"] == "provider_unavailable"
    assert "sk-123" not in response.text


def test_execution_errors_carry_a_category_not_database_text(toy_client):
    from src.intelligence.models import ExecutionError

    serve(FakeLLM([draft("SELECT b.title FROM books b")]), StubExecutor(ExecutionError("timeout", 'relation "x" secret')))
    body = ask(toy_client).json()
    assert body["error"] == "sql_execution_error: timeout"
    assert "secret" not in str(body)


def test_without_a_key_the_app_answers_not_configured_end_to_end(toy_client):
    """No dependency override: the real service is built from settings with no key."""
    with override_settings(OPENROUTER_API_KEY=SecretStr(""), QUERY_LOG_ENABLED=False):
        response = ask(toy_client, "Which books have been borrowed the most?")
    body = response.json()
    assert response.status_code == 200
    assert body["error"] == "not_configured" and body["mode"] == "disabled"
    assert "OPENROUTER_API_KEY" in body["answer"] and body["suggestions"]
    assert set(body) == ORIGINAL_FIELDS | ADDED_FIELDS


def test_the_service_is_built_once(toy_client):
    with override_settings(OPENROUTER_API_KEY=SecretStr(""), QUERY_LOG_ENABLED=False):
        assert get_ask_service() is get_ask_service()
        assert isinstance(get_ask_service().llm, NullLLM)


def test_the_message_is_validated(client):
    assert client.post("/api/chat", json={"message": ""}).status_code == 422
    assert client.post("/api/chat", json={"message": "x" * 2001}).status_code == 422
    assert client.post("/api/chat", json={}).status_code == 422


def test_an_unknown_dataset_is_404(client):
    response = client.post("/api/chat", json={"message": "hello there"}, headers={"X-GraphSense-Dataset": "nope"})
    assert response.status_code == 404


def test_training_is_gone(client):
    response = client.post("/api/chat/train")
    assert response.status_code == 410
    body = response.json()
    assert body["code"] == "gone" and "knowledge" in body["detail"].lower() and body["request_id"]


# ---------------------------------------------------------------------------
# Rate limit
# ---------------------------------------------------------------------------


def test_the_rate_limit_answers_with_a_stable_code(toy_client):
    serve(FakeLLM([draft("SELECT b.title FROM books b"), answer()]), StubExecutor(rows(["title"], ("A",))))
    with override_settings(CHAT_RATE_LIMIT_PER_MIN=2):
        assert ask(toy_client).status_code == 200
        assert ask(toy_client).status_code == 200
        limited = ask(toy_client)
    assert limited.status_code == 429
    body = limited.json()
    assert body["error"] == "rate_limited" and body["code"] == "rate_limited"
    assert body["detail"] == body["answer"] and body["request_id"]
    assert 1 <= int(limited.headers["retry-after"]) <= 60
    assert set(ORIGINAL_FIELDS) <= set(body)


def test_the_limiter_is_off_by_default(toy_client):
    serve(FakeLLM([draft("SELECT 1")]))
    for _ in range(5):
        assert ask(toy_client, "List the planets").status_code == 200


def test_clients_are_counted_separately_when_forwarded_addresses_are_trusted(toy_client):
    serve(FakeLLM([draft("SELECT 1")]))
    with override_settings(CHAT_RATE_LIMIT_PER_MIN=1, CHAT_RATE_LIMIT_TRUST_FORWARDED=True):
        one = {"X-GraphSense-Dataset": "toy_library", "X-Forwarded-For": "10.0.0.1, 10.9.9.9"}
        two = {"X-GraphSense-Dataset": "toy_library", "X-Forwarded-For": "10.0.0.2"}
        body = {"message": "List the planets"}
        assert toy_client.post("/api/chat", json=body, headers=one).status_code == 200
        assert toy_client.post("/api/chat", json=body, headers=two).status_code == 200
        assert toy_client.post("/api/chat", json=body, headers=one).status_code == 429


def test_forwarded_addresses_are_ignored_unless_trusted(toy_client):
    serve(FakeLLM([draft("SELECT 1")]))
    with override_settings(CHAT_RATE_LIMIT_PER_MIN=1):
        body = {"message": "List the planets"}
        first = toy_client.post("/api/chat", json=body, headers={"X-Forwarded-For": "1.1.1.1", "X-GraphSense-Dataset": "toy_library"})
        spoof = toy_client.post("/api/chat", json=body, headers={"X-Forwarded-For": "2.2.2.2", "X-GraphSense-Dataset": "toy_library"})
    assert first.status_code == 200 and spoof.status_code == 429


def test_sliding_window_behaviour():
    now = [0.0]
    limiter = SlidingWindowLimiter(2, window_s=60, clock=lambda: now[0])
    assert limiter.check("a") is None and limiter.check("a") is None
    wait = limiter.check("a")
    assert wait is not None and 59 <= wait <= 60
    assert limiter.check("b") is None  # another client is unaffected
    now[0] = 61
    assert limiter.check("a") is None  # the window slid
    assert SlidingWindowLimiter(0).check("a") is None  # 0 disables


def test_production_refuses_to_start_without_a_read_only_dsn():
    with override_settings(GRAPHSENSE_ENV="production", READONLY_DATABASE_DSN=None), pytest.raises(RuntimeError), TestClient(app):
        pass
    with override_settings(GRAPHSENSE_ENV="dev"), TestClient(app) as client:
        assert client.get("/api/health").status_code == 200

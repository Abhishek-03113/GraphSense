"""Request ids and the error envelope: no internal text ever reaches a response."""

import re

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.api.errors import install_error_handling
from src.db.session import get_db_session
from src.main import app

SECRET = 'relation "sales_order_headers" does not exist; password=hunter2'


def _mini_app() -> FastAPI:
    mini = FastAPI()
    install_error_handling(mini)

    @mini.get("/boom")
    async def boom():
        raise RuntimeError(SECRET)

    @mini.get("/teapot")
    async def teapot():
        raise HTTPException(status_code=404, detail="Unknown thing")

    @mini.get("/broken-gateway")
    async def broken_gateway():
        raise HTTPException(status_code=502, detail=SECRET)

    @mini.get("/ok")
    async def ok():
        return {"ok": True}

    return mini


@pytest.fixture
def client() -> TestClient:
    return TestClient(_mini_app(), raise_server_exceptions=False)


def test_unhandled_exception_returns_the_envelope_without_internals(client):
    res = client.get("/boom")
    assert res.status_code == 500
    body = res.json()
    assert body["detail"] == "Something went wrong."
    assert body["code"] == "internal_error"
    assert re.fullmatch(r"[0-9a-f]{32}", body["request_id"])
    assert res.headers["X-Request-ID"] == body["request_id"]
    assert SECRET not in res.text
    assert "hunter2" not in res.text


def test_5xx_http_exception_is_sanitised(client):
    res = client.get("/broken-gateway")
    assert res.status_code == 502
    assert res.json()["detail"] == "Something went wrong."
    assert "hunter2" not in res.text


def test_4xx_keeps_its_detail_and_gains_code_and_request_id(client):
    res = client.get("/teapot")
    assert res.status_code == 404
    body = res.json()
    assert body["detail"] == "Unknown thing"
    assert body["code"] == "not_found"
    assert body["request_id"] == res.headers["X-Request-ID"]


def test_successful_responses_carry_a_request_id(client):
    res = client.get("/ok")
    assert res.json() == {"ok": True}
    assert re.fullmatch(r"[0-9a-f]{32}", res.headers["X-Request-ID"])


def test_a_safe_inbound_request_id_is_kept_and_an_unsafe_one_replaced(client):
    assert client.get("/ok", headers={"X-Request-ID": "trace-123.abc"}).headers[
        "X-Request-ID"
    ] == "trace-123.abc"
    replaced = client.get("/ok", headers={"X-Request-ID": "bad id\twith spaces"})
    assert re.fullmatch(r"[0-9a-f]{32}", replaced.headers["X-Request-ID"])


def test_each_request_gets_its_own_id(client):
    assert client.get("/ok").headers["X-Request-ID"] != client.get("/ok").headers["X-Request-ID"]


# ---------------------------------------------------------------------------
# The real application
# ---------------------------------------------------------------------------


class _ExplodingSession:
    async def execute(self, *args, **kwargs):
        raise RuntimeError(SECRET)

    def begin_nested(self):
        raise RuntimeError(SECRET)


@pytest.fixture
def broken_db():
    async def fake_session():
        yield _ExplodingSession()

    app.dependency_overrides[get_db_session] = fake_session
    try:
        yield TestClient(app, raise_server_exceptions=False)
    finally:
        app.dependency_overrides.pop(get_db_session, None)


@pytest.mark.parametrize(
    "path,params",
    [
        ("/api/graph/summary", {}),
        ("/api/graph/subgraph", {"root_type": "Invoice", "root_id": "1", "depth": 2}),
        ("/api/graph/trace", {"doc_type": "Invoice", "doc_id": "1"}),
        ("/api/graph/flow", {"flow_id": "sales"}),
        ("/api/graph/full", {}),
        ("/api/graph/entities/Invoice", {}),
    ],
)
def test_graph_endpoints_never_leak_database_text(broken_db, path, params):
    res = broken_db.get(path, params=params)
    assert res.status_code == 500
    body = res.json()
    assert body["code"] == "internal_error"
    assert body["detail"] == "Something went wrong."
    assert body["request_id"] == res.headers["X-Request-ID"]
    assert "sales_order_headers" not in res.text and "hunter2" not in res.text


def test_unknown_flow_is_a_clean_404():
    res = TestClient(app).get("/api/graph/flow", params={"flow_id": "nope"})
    assert res.status_code == 404
    assert res.json()["detail"] == "Unknown flow: nope"
    assert res.json()["code"] == "not_found"


def test_validation_errors_keep_the_framework_shape():
    res = TestClient(app).get("/api/graph/flow")  # flow_id is required
    assert res.status_code == 422
    assert isinstance(res.json()["detail"], list)


def test_health_has_a_request_id():
    res = TestClient(app).get("/api/health")
    assert res.json() == {"status": "ok"}
    assert "X-Request-ID" in res.headers

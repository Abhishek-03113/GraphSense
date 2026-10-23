"""Request ids and the error envelope: no internal text ever reaches a response."""

import re
import socket
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import ProgrammingError
from starlette.responses import StreamingResponse

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

    @mini.get("/needs-int")
    async def needs_int(n: int):
        return {"n": n}

    @mini.get("/half")
    async def half():
        async def body():
            yield b"partial"
            raise RuntimeError(SECRET)

        return StreamingResponse(body())

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


def test_a_500_does_not_raise_into_the_server_and_the_next_request_works():
    # The default client re-raises server exceptions, as Starlette's own catch-all handler
    # does after replying.  Ours replies and swallows, so nothing propagates.
    client = TestClient(_mini_app())
    res = client.get("/boom")
    assert res.status_code == 500 and res.json()["code"] == "internal_error"
    assert client.get("/ok").json() == {"ok": True}
    assert client.get("/boom").status_code == 500
    assert client.get("/ok").status_code == 200


def test_a_failure_after_the_response_started_still_propagates():
    with pytest.raises(RuntimeError):
        TestClient(_mini_app()).get("/half")


def _serve(application: FastAPI):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(application, host="127.0.0.1", port=port, log_level="critical"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started
    return server, thread, port


def test_the_keep_alive_connection_survives_a_500():
    server, thread, port = _serve(_mini_app())
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}") as http:
            assert http.get("/boom").status_code == 500
            assert http.get("/ok").json() == {"ok": True}
            assert http.get("/boom").status_code == 500
            assert http.get("/ok").json() == {"ok": True}
            # all four requests used one pooled connection
            assert len(http._transport._pool.connections) == 1  # type: ignore[attr-defined]
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_validation_errors_get_the_envelope_and_keep_the_detail_list():
    res = TestClient(_mini_app()).get("/needs-int", params={"n": "abc"})
    assert res.status_code == 422
    body = res.json()
    assert body["code"] == "validation_error"
    assert isinstance(body["detail"], list) and body["detail"][0]["loc"] == ["query", "n"]
    assert re.fullmatch(r"[0-9a-f]{32}", body["request_id"])
    assert res.headers["X-Request-ID"] == body["request_id"]


# ---------------------------------------------------------------------------
# A dataset whose tables are not loaded
# ---------------------------------------------------------------------------


class _UndefinedTable(Exception):
    sqlstate = "42P01"


class _UndefinedColumn(Exception):
    sqlstate = "42703"


class _InvalidSchema(Exception):
    sqlstate = "3F000"


class _NoTablesSession:
    """Answers the search-path statement, then fails every query with ``error``."""

    def __init__(self, error: BaseException):
        self.error = error

    async def execute(self, statement, *args, **kwargs):
        if "set_config" in str(statement):
            return None
        raise self.error

    def begin_nested(self):
        class _Savepoint:
            async def __aenter__(self):
                return None

            async def __aexit__(self, *exc):
                return False

        return _Savepoint()


GRAPH_REQUESTS = [
    ("/api/graph/summary", {}),
    ("/api/graph/subgraph", {"root_type": "Invoice", "root_id": "1", "depth": 2}),
    ("/api/graph/trace", {"doc_type": "Invoice", "doc_id": "1"}),
    ("/api/graph/flow", {"flow_id": "sales"}),
    ("/api/graph/full", {}),
    ("/api/graph/entities/Invoice", {}),
]


def _db_error(origin: Exception) -> ProgrammingError:
    return ProgrammingError('SELECT 1 FROM "secret_table"', {}, origin)


@pytest.fixture
def failing_db():
    """A client whose database fails with the error given to the factory."""

    def make(origin: Exception) -> TestClient:
        async def fake_session():
            yield _NoTablesSession(_db_error(origin))

        app.dependency_overrides[get_db_session] = fake_session
        return TestClient(app, raise_server_exceptions=False)

    try:
        yield make
    finally:
        app.dependency_overrides.pop(get_db_session, None)


@pytest.mark.parametrize("path,params", GRAPH_REQUESTS)
def test_graph_routes_answer_409_dataset_not_ready_when_the_tables_are_missing(failing_db, path, params):
    res = failing_db(_UndefinedTable('relation "secret_table" does not exist')).get(path, params=params)
    assert res.status_code == 409
    body = res.json()
    assert body["code"] == "dataset_not_ready"
    assert body["detail"] == "This dataset's data hasn't been loaded yet."
    assert body["request_id"] == res.headers["X-Request-ID"]
    assert "secret_table" not in res.text


def test_a_missing_schema_is_dataset_not_ready_too(failing_db):
    res = failing_db(_InvalidSchema("schema does not exist")).get("/api/graph/summary")
    assert res.status_code == 409 and res.json()["code"] == "dataset_not_ready"


def test_other_database_errors_stay_500(failing_db):
    res = failing_db(_UndefinedColumn("column x does not exist")).get("/api/graph/summary")
    assert res.status_code == 500 and res.json()["code"] == "internal_error"
    assert "column x" not in res.text


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


def test_validation_errors_keep_the_framework_shape_and_gain_the_envelope():
    res = TestClient(app).get("/api/graph/flow")  # flow_id is required
    assert res.status_code == 422
    body = res.json()
    assert isinstance(body["detail"], list)
    assert body["code"] == "validation_error"
    assert body["request_id"] == res.headers["X-Request-ID"]


def test_health_has_a_request_id():
    res = TestClient(app).get("/api/health")
    assert res.json() == {"status": "ok"}
    assert "X-Request-ID" in res.headers

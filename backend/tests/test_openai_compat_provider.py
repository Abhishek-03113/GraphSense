"""OpenAI-compatible provider (OpenRouter and friends), the answer streamer and the chat socket."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from src.api.ratelimit import reset_chat_limiter
from src.config import override_settings
from src.intelligence import runtime
from src.intelligence.providers import FakeLLM, InvalidRequest, LLMRequest, ProviderUnavailable, RateLimited
from src.intelligence.providers.openai_compat import OpenAICompatEmbedder, OpenAICompatLLM
from src.intelligence.service import _AnswerStreamer
from src.main import app
from tests.ask_support import StubExecutor, answer, draft, make_service, rows
from tests.conftest import TOY_DIR


def llm_with(handler, **kw):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return OpenAICompatLLM(SecretStr("k"), "vendor/model", base_url="https://x/v1/", retry_delays_s=(0, 0), client=client, **kw)


def completion(text='{"answer": "hi"}', finish="stop"):
    return {
        "choices": [{"message": {"content": text}, "finish_reason": finish}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
    }


async def test_generate_sends_an_openai_request_and_reads_usage():
    seen = {}

    def handler(request):
        seen["url"], seen["auth"], seen["body"] = str(request.url), request.headers["authorization"], json.loads(request.content)
        return httpx.Response(200, json=completion())

    schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
    out = await llm_with(handler, reasoning_effort="low").generate(
        LLMRequest(prompt="p", system="s", max_output_tokens=99, json_schema=schema)
    )
    body = seen["body"]
    assert seen["url"] == "https://x/v1/chat/completions" and seen["auth"] == "Bearer k"
    assert body["model"] == "vendor/model" and body["max_tokens"] == 99 and body["reasoning"] == {"effort": "low"}
    assert body["messages"] == [{"role": "system", "content": "s"}, {"role": "user", "content": "p"}]
    assert body["response_format"]["json_schema"]["schema"] == schema and "stream" not in body
    assert out.parsed == {"answer": "hi"} and out.finish_reason == "stop"
    assert (out.usage.input_tokens, out.usage.output_tokens, out.usage.llm_calls) == (11, 7, 1)


async def test_streaming_hands_every_delta_to_the_callback():
    chunks = ['{"answer": "He', 'llo', '"}']
    lines = [f"data: {json.dumps({'choices': [{'delta': {'content': c}}]})}\n\n" for c in chunks]
    lines.insert(1, ": OPENROUTER PROCESSING\n\n")
    lines.append(f"data: {json.dumps({'choices': [{'delta': {}, 'finish_reason': 'stop'}], 'usage': {'prompt_tokens': 5, 'completion_tokens': 3}})}\n\n")
    lines.append("data: [DONE]\n\n")
    got = []

    async def on_text(piece):
        got.append(piece)

    def handler(request):
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(200, content="".join(lines).encode(), headers={"content-type": "text/event-stream"})

    out = await llm_with(handler).generate(LLMRequest(prompt="p", json_schema={"type": "object"}, on_text=on_text))
    assert got == chunks and out.text == '{"answer": "Hello"}' and out.parsed == {"answer": "Hello"}
    assert out.finish_reason == "stop" and out.usage.output_tokens == 3


@pytest.mark.parametrize(("status", "expected"), [(429, RateLimited), (400, InvalidRequest), (504, ProviderUnavailable)])
async def test_failures_become_provider_errors(status, expected):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(status, json={"error": {"message": "secret detail"}})

    with pytest.raises(expected) as raised:
        await llm_with(handler).generate(LLMRequest(prompt="p"))
    assert "secret" not in str(raised.value) and len(calls) == 1  # not retried


async def test_a_busy_model_is_retried():
    replies = [httpx.Response(503), httpx.Response(200, json=completion())]
    out = await llm_with(lambda request: replies.pop(0)).generate(LLMRequest(prompt="p"))
    assert out.text == '{"answer": "hi"}'


async def test_the_embedder_orders_vectors_by_index_and_learns_dims():
    def handler(request):
        assert json.loads(request.content)["input"] == ["a", "b"]
        return httpx.Response(200, json={"data": [{"index": 1, "embedding": [0, 1]}, {"index": 0, "embedding": [1, 0]}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    embedder = OpenAICompatEmbedder(SecretStr("k"), "m", base_url="https://x/v1", client=client)
    assert await embedder.embed(["a", "b"], task="query") == [[1.0, 0.0], [0.0, 1.0]]
    assert embedder.dims == 2


@pytest.mark.parametrize(
    "pieces",
    [
        ['{"answer": "Hello', ' world"}'],
        ['{"ans', 'wer":', ' "Hel', 'lo wor', 'ld", "x": 1}'],
        ['{"answer": "Hello wor\\', 'nld" }'.replace("nld", "ld")],
    ],
)
async def test_the_streamer_extracts_only_the_answer_text(pieces):
    got = []

    async def emit(text):
        got.append(text)

    streamer = _AnswerStreamer(emit)
    for piece in pieces:
        await streamer.feed(piece)
    text = "".join(got)
    assert text.startswith("Hello") and "}" not in text and '"' not in text


async def test_the_streamer_decodes_escapes_split_across_chunks():
    got = []

    async def emit(text):
        got.append(text)

    streamer = _AnswerStreamer(emit)
    for piece in ['{"answer": "a\\', 'nb \\u00', 'e9 \\"q\\""}']:
        await streamer.feed(piece)
    assert "".join(got) == 'a\nb é "q"'


# --- the socket -----------------------------------------------------------------


@pytest.fixture
def socket_client(tmp_path):
    import shutil

    reset_chat_limiter()
    runtime._service = None
    app.dependency_overrides.clear()
    shutil.copytree(TOY_DIR, tmp_path / "toy_library")
    with override_settings(PACKAGES_DIR=tmp_path):
        yield TestClient(app)
    reset_chat_limiter()
    runtime._service = None


def collect(ws):
    frames = []
    while True:
        frame = ws.receive_json()
        frames.append(frame)
        if frame["type"] in ("result", "error", "cancelled"):
            return frames


def test_the_socket_streams_progress_and_ends_with_the_rest_body(socket_client, monkeypatch):
    service = make_service(
        FakeLLM([draft("SELECT b.isbn, b.title FROM books b"), answer("Two books.")]),
        StubExecutor(rows(["isbn", "title"], ("111", "A"), ("222", "B"))),
    )
    monkeypatch.setattr("src.api.chat.get_ask_service", lambda: service)
    with socket_client.websocket_connect("/api/chat/ws?dataset=toy_library") as ws:
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
        ws.send_json({"type": "ask", "id": "q1", "message": "Which books are there?"})
        frames = collect(ws)
        stages = [f["stage"] for f in frames if f["type"] == "status"]
        assert stages == ["retrieving", "writing_query", "running_query", "answering"]
        assert all(f["id"] == "q1" for f in frames)
        final = frames[-1]
        assert final["type"] == "result" and final["result"]["answer"] == "Two books."
        assert final["result"]["row_count"] == 2
        # the connection stays usable for a second question
        ws.send_json({"type": "ask", "id": "q2", "message": "Which books are there?"})
        assert collect(ws)[-1]["id"] == "q2"


def test_the_socket_rejects_bad_frames_and_unknown_datasets(socket_client, monkeypatch):
    monkeypatch.setattr("src.api.chat.get_ask_service", lambda: make_service(FakeLLM(["x"]), None))
    with socket_client.websocket_connect("/api/chat/ws?dataset=toy_library") as ws:
        ws.send_json({"type": "ask", "id": "q1", "message": ""})
        assert ws.receive_json()["code"] == "bad_request"
        ws.send_json({"type": "nope"})
        assert ws.receive_json()["code"] == "bad_request"
    with pytest.raises(Exception):  # noqa: B017 - the server closes the handshake
        with socket_client.websocket_connect("/api/chat/ws?dataset=missing"):
            pass


def test_the_socket_refuses_a_foreign_origin(socket_client, monkeypatch):
    monkeypatch.setattr("src.api.chat.get_ask_service", lambda: make_service(FakeLLM(["x"]), None))
    with override_settings(CORS_ALLOW_ORIGINS=["https://app.example"]):
        with pytest.raises(Exception):  # noqa: B017
            with socket_client.websocket_connect("/api/chat/ws?dataset=toy_library", headers={"origin": "https://evil.example"}):
                pass
        with socket_client.websocket_connect("/api/chat/ws?dataset=toy_library", headers={"origin": "https://app.example"}) as ws:
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"

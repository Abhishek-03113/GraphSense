"""The Gemini provider against a stand-in SDK client: request shape, usage, and error translation."""

from types import SimpleNamespace

import pytest
from google.genai import errors
from pydantic import SecretStr

from src.intelligence.providers import (
    InvalidRequest,
    LLMRequest,
    NotConfigured,
    ProviderUnavailable,
    RateLimited,
)
from src.intelligence.providers.gemini import GeminiEmbedder, GeminiLLM


class FakeModels:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.response

    async def embed_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.1, 0.2, 0.3]) for _ in kwargs["contents"]])


def client_with(models):
    return SimpleNamespace(aio=SimpleNamespace(models=models))


class FlakyModels(FakeModels):
    """Fails with each of ``failures`` in turn, then answers."""

    def __init__(self, failures, response=None):
        super().__init__(response or reply())
        self.failures = list(failures)

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.failures:
            raise self.failures.pop(0)
        return self.response

    async def embed_content(self, **kwargs):
        if self.failures:
            self.calls.append(kwargs)
            raise self.failures.pop(0)
        return await super().embed_content(**kwargs)


def busy():
    return errors.APIError(503, {"error": {"message": "high demand"}})


def llm(models):
    provider = GeminiLLM(SecretStr("k"), "model-x", retry_delays_s=(0, 0))
    provider._client_instance = client_with(models)
    return provider


def reply(text='{"answer": "hi"}'):
    return SimpleNamespace(
        text=text,
        usage_metadata=SimpleNamespace(prompt_token_count=11, candidates_token_count=7),
        candidates=[SimpleNamespace(finish_reason="STOP")],
    )


async def test_generate_sends_the_model_and_schema_and_reads_usage():
    models = FakeModels(reply())
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
    out = await llm(models).generate(LLMRequest(prompt="p", system="s", max_output_tokens=99, json_schema=schema))
    call = models.calls[0]
    assert call["model"] == "model-x" and call["contents"] == "p"
    config = call["config"]
    assert config.system_instruction == "s" and config.max_output_tokens == 99
    assert config.response_mime_type == "application/json" and config.response_json_schema == schema
    assert out.parsed == {"answer": "hi"} and out.text == '{"answer": "hi"}'
    assert (out.usage.input_tokens, out.usage.output_tokens, out.usage.llm_calls) == (11, 7, 1)


async def test_plain_requests_do_not_ask_for_json():
    models = FakeModels(reply("hello"))
    out = await llm(models).generate(LLMRequest(prompt="p"))
    assert models.calls[0]["config"].response_mime_type is None and out.parsed is None


async def test_a_blocked_reply_is_empty_text_not_a_crash():
    class Blocked:
        usage_metadata = None
        candidates = ()

        @property
        def text(self):
            raise ValueError("blocked")

    out = await llm(FakeModels(Blocked())).generate(LLMRequest(prompt="p"))
    assert out.text == ""


@pytest.mark.parametrize(
    "error,expected",
    [
        (errors.APIError(429, {"error": {"message": "quota"}}), RateLimited),
        (errors.APIError(400, {"error": {"message": "bad"}}), InvalidRequest),
        (errors.APIError(500, {"error": {"message": "boom"}}), ProviderUnavailable),
        (errors.APIError(503, {"error": {"message": "down"}}), ProviderUnavailable),
        (TimeoutError(), ProviderUnavailable),
        (ConnectionError("reset"), ProviderUnavailable),
    ],
)
async def test_failures_become_provider_errors(error, expected):
    with pytest.raises(expected) as raised:
        await llm(FakeModels(error=error)).generate(LLMRequest(prompt="p"))
    assert "quota" not in str(raised.value) and "boom" not in str(raised.value)  # no provider text


async def test_a_busy_model_is_retried_until_it_answers():
    models = FlakyModels([busy(), errors.APIError(500, {})])
    out = await llm(models).generate(LLMRequest(prompt="p"))
    assert out.text == '{"answer": "hi"}' and len(models.calls) == 3


async def test_retries_give_up_after_the_last_attempt():
    models = FlakyModels([busy(), busy(), busy(), busy()])
    with pytest.raises(ProviderUnavailable):
        await llm(models).generate(LLMRequest(prompt="p"))
    assert len(models.calls) == 3


async def test_a_deadline_failure_is_not_retried():
    models = FlakyModels([errors.APIError(504, {})])
    with pytest.raises(ProviderUnavailable):
        await llm(models).generate(LLMRequest(prompt="p"))
    assert len(models.calls) == 1


async def test_thinking_is_switched_off_by_default():
    models = FakeModels(reply())
    await llm(models).generate(LLMRequest(prompt="p"))
    assert models.calls[0]["config"].thinking_config.thinking_budget == 0


@pytest.mark.parametrize("error", [errors.APIError(400, {}), errors.APIError(429, {}), TimeoutError()])
async def test_only_temporary_server_errors_are_retried(error):
    models = FlakyModels([error])
    with pytest.raises((InvalidRequest, RateLimited, ProviderUnavailable)):
        await llm(models).generate(LLMRequest(prompt="p"))
    assert len(models.calls) == 1


async def test_the_embedder_retries_a_busy_model():
    models = FlakyModels([busy()])
    embedder = GeminiEmbedder(SecretStr("k"), "m", retry_delays_s=(0, 0))
    embedder._client_instance = client_with(models)
    assert len(await embedder.embed(["x"], task="query")) == 1
    assert len(models.calls) == 2


async def test_no_key_means_not_configured():
    with pytest.raises(NotConfigured):
        await GeminiLLM(SecretStr(""), "m").generate(LLMRequest(prompt="p"))
    with pytest.raises(NotConfigured):
        await GeminiEmbedder(SecretStr(""), "m").embed(["x"], task="query")


async def test_embedder_uses_task_types_batches_and_learns_the_size():
    models = FakeModels()
    embedder = GeminiEmbedder(SecretStr("k"), "embed-x")
    embedder._client_instance = client_with(models)
    assert embedder.dims is None
    vectors = await embedder.embed([f"t{i}" for i in range(150)], task="document")
    assert len(vectors) == 150 and embedder.dims == 3
    assert [len(c["contents"]) for c in models.calls] == [100, 50]  # two batches
    assert models.calls[0]["config"].task_type == "RETRIEVAL_DOCUMENT"
    await embedder.embed(["q"], task="query")
    assert models.calls[-1]["config"].task_type == "RETRIEVAL_QUERY"
    assert await embedder.embed([], task="query") == []


async def test_embedder_requested_size_is_passed_on():
    models = FakeModels()
    embedder = GeminiEmbedder(SecretStr("k"), "embed-x", dims=64)
    embedder._client_instance = client_with(models)
    await embedder.embed(["x"], task="query")
    assert models.calls[0]["config"].output_dimensionality == 64


async def test_embedder_failure_is_translated():
    embedder = GeminiEmbedder(SecretStr("k"), "m")
    embedder._client_instance = client_with(FakeModels(error=errors.APIError(429, {})))
    with pytest.raises(RateLimited):
        await embedder.embed(["x"], task="query")


def test_the_api_key_is_never_in_a_repr():
    provider = GeminiLLM(SecretStr("super-secret-key"), "m")
    assert "super-secret-key" not in repr(provider) + repr(vars(provider))

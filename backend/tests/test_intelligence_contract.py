"""The provider contract: fakes, stand-ins, factory and AI mode."""

import pytest
from pydantic import SecretStr

from src.config import override_settings
from src.intelligence.models import AskResult, ErrorCode, ExecutionError, SqlRejected, Usage
from src.intelligence.providers import (
    FakeEmbedder,
    FakeLLM,
    LLMRequest,
    NotConfigured,
    NullEmbedder,
    NullLLM,
    ProviderUnavailable,
    build_providers,
)
from src.intelligence.providers.base import EmbeddingProvider, LLMProvider
from src.intelligence.providers.factory import compute_mode


async def test_fake_llm_follows_its_script_and_records_calls():
    llm = FakeLLM(["first", {"a": 1}, ProviderUnavailable("down")])
    schema = {"type": "object"}
    assert (await llm.generate(LLMRequest(prompt="p"))).text == "first"
    reply = await llm.generate(LLMRequest(prompt="q", json_schema=schema))
    assert reply.parsed == {"a": 1}
    assert reply.usage.llm_calls == 1 and reply.usage.input_tokens > 0
    with pytest.raises(ProviderUnavailable):
        await llm.generate(LLMRequest(prompt="r"))
    assert [c.prompt for c in llm.calls] == ["p", "q", "r"]


async def test_fake_llm_can_be_a_function():
    llm = FakeLLM(lambda req: f"echo {req.prompt}")
    assert (await llm.generate(LLMRequest(prompt="hi"))).text == "echo hi"


async def test_fake_embedder_is_deterministic_and_reflects_shared_words():
    emb = FakeEmbedder()
    a, b, c = await emb.embed(["books borrowed most", "which books are borrowed", "solar planets"], task="query")
    again = await emb.embed(["books borrowed most"], task="document")
    assert a == again[0]

    def cos(x, y):
        return sum(i * j for i, j in zip(x, y, strict=True))

    assert cos(a, a) == pytest.approx(1.0)
    assert cos(a, b) > 0.4
    assert abs(cos(a, c)) < 0.2
    assert emb.dims == 256


async def test_null_providers_raise_not_configured():
    with pytest.raises(NotConfigured):
        await NullLLM().generate(LLMRequest(prompt="x"))
    with pytest.raises(NotConfigured):
        await NullEmbedder().embed(["x"], task="query")
    assert NullEmbedder().dims is None


def test_protocols_are_satisfied():
    assert isinstance(FakeLLM(["x"]), LLMProvider)
    assert isinstance(FakeEmbedder(), EmbeddingProvider)
    assert isinstance(NullLLM(), LLMProvider)
    assert isinstance(NullEmbedder(), EmbeddingProvider)


def test_no_key_means_disabled_mode():
    with override_settings(GEMINI_API_KEY=SecretStr(""), LLM_PROVIDER="gemini", EMBEDDING_PROVIDER="gemini"):
        providers = build_providers()
    assert providers.mode == "disabled"
    assert isinstance(providers.llm, NullLLM) and isinstance(providers.embedder, NullEmbedder)


def test_key_means_full_mode_and_the_models_come_from_settings():
    with override_settings(
        LLM_PROVIDER="gemini", EMBEDDING_PROVIDER="gemini",
        GEMINI_API_KEY=SecretStr("k"), GEMINI_MODEL="m-llm", EMBEDDING_MODEL="m-embed", EMBEDDING_DIMS=64
    ):
        providers = build_providers()
    assert providers.mode == "full"
    assert (providers.llm.model, providers.embedder.model, providers.embedder.dims) == ("m-llm", "m-embed", 64)
    assert "k" not in repr(vars(providers.llm).get("_api_key"))  # SecretStr never shows its value


def test_openrouter_is_the_default_and_uses_one_key_for_both_models():
    with override_settings(
        OPENROUTER_API_KEY=SecretStr("k"), OPENROUTER_MODEL="vendor/llm", EMBEDDING_MODEL="vendor/embed"
    ):
        providers = build_providers()
    assert providers.mode == "full"
    assert (providers.llm.model, providers.embedder.model) == ("vendor/llm", "vendor/embed")
    assert providers.llm._base_url == "https://openrouter.ai/api/v1"


def test_any_openai_compatible_server_can_be_used():
    with override_settings(
        LLM_PROVIDER="openai_compatible", EMBEDDING_PROVIDER="none", LLM_BASE_URL="http://localhost:11434/v1/",
        LLM_API_KEY=SecretStr("k"), LLM_MODEL="llama3",
    ):
        providers = build_providers()
    assert providers.mode == "degraded"
    assert (providers.llm.model, providers.llm._base_url) == ("llama3", "http://localhost:11434/v1")


def test_llm_without_embeddings_is_degraded():
    with override_settings(LLM_PROVIDER="gemini", GEMINI_API_KEY=SecretStr("k"), EMBEDDING_PROVIDER="none"):
        assert build_providers().mode == "degraded"
    assert compute_mode(FakeLLM(["x"]), NullEmbedder()) == "degraded"
    assert compute_mode(NullLLM(), FakeEmbedder()) == "disabled"


def test_fake_embedder_can_be_selected_for_offline_runs():
    with override_settings(GEMINI_API_KEY=SecretStr(""), EMBEDDING_PROVIDER="fake", EMBEDDING_DIMS=None):
        providers = build_providers()
    assert isinstance(providers.embedder, FakeEmbedder)


def test_ask_result_error_field():
    assert AskResult(answer="x").error is None and AskResult(answer="x").ok
    guard = AskResult(answer="x", error_code=ErrorCode.GUARDRAIL)
    assert guard.error == "guardrail" and not guard.ok
    execution = AskResult(answer="x", error_code=ErrorCode.SQL_EXECUTION_ERROR, error_category="timeout")
    assert execution.error == "sql_execution_error: timeout"


def test_repairable_categories():
    assert SqlRejected("c", "m", "unknown_column").repairable
    assert not SqlRejected("c", "m", "policy").repairable
    assert ExecutionError("syntax").repairable
    assert not ExecutionError("timeout").repairable
    assert not ExecutionError("unknown_table", not_ready=True).repairable


def test_usage_adds_up():
    assert Usage(1, 2, 1, 0) + Usage(3, 4, 1, 2) == Usage(4, 6, 2, 2)
    assert Usage(1, 2).total_tokens == 3


def test_package_can_switch_row_values_off(package_copy):
    from src.datasets import load_package

    path = package_copy(edits={"package.yaml": ("locale: en", "locale: en\nllm_sees_rows: false")})
    assert load_package(path).llm_sees_rows is False


def test_row_values_reach_the_model_by_default(toy_package):
    assert toy_package.llm_sees_rows is True
    assert toy_package.sql.extra_functions == ()

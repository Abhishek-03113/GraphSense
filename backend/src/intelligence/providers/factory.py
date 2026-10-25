"""Build the configured providers and decide the AI mode.

``LLM_PROVIDER`` / ``EMBEDDING_PROVIDER`` pick the implementation (``openrouter``,
``openai_compatible``, ``gemini``, ``none``; ``fake`` for the embedder only, for offline checks).  A provider that
is named but has no credentials becomes the stand-in, so the application starts
and reports ``not_configured`` instead of failing.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import SecretStr

from src.config import Settings, get_settings
from src.intelligence.models import AiMode
from src.intelligence.providers.base import EmbeddingProvider, LLMProvider, is_configured
from src.intelligence.providers.fake import FakeEmbedder
from src.intelligence.providers.null import NullEmbedder, NullLLM
from src.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class Providers:
    llm: LLMProvider
    embedder: EmbeddingProvider

    @property
    def mode(self) -> AiMode:
        return compute_mode(self.llm, self.embedder)


def compute_mode(llm: object, embedder: object) -> AiMode:
    """``full`` (model and embeddings), ``degraded`` (model, text search only), ``disabled`` (no model)."""
    if not is_configured(llm):
        return "disabled"
    return "full" if is_configured(embedder) else "degraded"


_OPENAI_LIKE = ("openrouter", "openai_compatible")


def _llm_endpoint(s: Settings) -> tuple[str, str, SecretStr, dict[str, str]]:
    """``(base_url, model, key, extra headers)`` of the OpenAI-compatible language model."""
    from src.intelligence.providers.openai_compat import OPENROUTER_BASE_URL

    if s.LLM_PROVIDER.strip().lower() == "openrouter":
        # Optional attribution headers OpenRouter shows on its dashboards.
        return OPENROUTER_BASE_URL, s.OPENROUTER_MODEL, s.OPENROUTER_API_KEY, {"X-Title": "GraphSense"}
    return s.LLM_BASE_URL, s.LLM_MODEL, s.LLM_API_KEY, {}


def _key_variable(name: str) -> str:
    return "OPENROUTER_API_KEY" if name == "openrouter" else "LLM_API_KEY" if name == "openai_compatible" else "GEMINI_API_KEY"


def build_providers(settings: Settings | None = None) -> Providers:
    s = settings or get_settings()
    gemini_key = s.GEMINI_API_KEY

    llm_name = s.LLM_PROVIDER.strip().lower()
    llm_url, llm_model, llm_key, llm_headers = _llm_endpoint(s)
    if llm_name in _OPENAI_LIKE and llm_key.get_secret_value():
        from src.intelligence.providers.openai_compat import OpenAICompatLLM

        llm: LLMProvider = OpenAICompatLLM(
            llm_key, llm_model, base_url=llm_url, default_timeout_s=s.LLM_TIMEOUT_S,
            headers=llm_headers, reasoning_effort=s.LLM_REASONING_EFFORT.strip(),
        )
    elif llm_name == "gemini" and gemini_key.get_secret_value():
        from src.intelligence.providers.gemini import GeminiLLM

        llm = GeminiLLM(gemini_key, s.GEMINI_MODEL, default_timeout_s=s.LLM_TIMEOUT_S)
    else:
        if llm_name not in (*_OPENAI_LIKE, "gemini", "none", ""):
            logger.warning("Unknown LLM_PROVIDER %r; the language model is disabled", llm_name)
        llm = NullLLM(f"{_key_variable(llm_name)} is not set" if llm_name in (*_OPENAI_LIKE, "gemini") else "LLM_PROVIDER is none")

    embed_name = s.EMBEDDING_PROVIDER.strip().lower()
    if embed_name in _OPENAI_LIKE and (s.EMBEDDING_API_KEY.get_secret_value() or llm_key.get_secret_value()):
        from src.intelligence.providers.openai_compat import OpenAICompatEmbedder

        embedder: EmbeddingProvider = OpenAICompatEmbedder(
            s.EMBEDDING_API_KEY if s.EMBEDDING_API_KEY.get_secret_value() else llm_key,
            s.EMBEDDING_MODEL,
            base_url=s.EMBEDDING_BASE_URL or llm_url,
            dims=s.EMBEDDING_DIMS,
            headers=llm_headers,
        )
    elif embed_name == "gemini" and gemini_key.get_secret_value():
        from src.intelligence.providers.gemini import GeminiEmbedder

        embedder = GeminiEmbedder(gemini_key, s.EMBEDDING_MODEL, dims=s.EMBEDDING_DIMS)
    elif embed_name == "fake":
        embedder = FakeEmbedder(dims=s.EMBEDDING_DIMS or 256)
    else:
        if embed_name not in (*_OPENAI_LIKE, "gemini", "none", ""):
            logger.warning("Unknown EMBEDDING_PROVIDER %r; embeddings are disabled", embed_name)
        embedder = NullEmbedder(
            f"{_key_variable(embed_name)} is not set" if embed_name in (*_OPENAI_LIKE, "gemini") else "EMBEDDING_PROVIDER is none"
        )

    return Providers(llm=llm, embedder=embedder)

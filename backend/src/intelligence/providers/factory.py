"""Build the configured providers and decide the AI mode.

``LLM_PROVIDER`` / ``EMBEDDING_PROVIDER`` pick the implementation (``gemini``,
``none``; ``fake`` for the embedder only, for offline checks).  A provider that
is named but has no credentials becomes the stand-in, so the application starts
and reports ``not_configured`` instead of failing.
"""

from __future__ import annotations

from dataclasses import dataclass

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


def build_providers(settings: Settings | None = None) -> Providers:
    s = settings or get_settings()
    key = s.GEMINI_API_KEY

    llm_name = s.LLM_PROVIDER.strip().lower()
    if llm_name == "gemini" and key.get_secret_value():
        from src.intelligence.providers.gemini import GeminiLLM

        llm: LLMProvider = GeminiLLM(key, s.GEMINI_MODEL, default_timeout_s=s.LLM_TIMEOUT_S)
    else:
        if llm_name not in ("gemini", "none", ""):
            logger.warning("Unknown LLM_PROVIDER %r; the language model is disabled", llm_name)
        llm = NullLLM("GEMINI_API_KEY is not set" if llm_name == "gemini" else "LLM_PROVIDER is none")

    embed_name = s.EMBEDDING_PROVIDER.strip().lower()
    if embed_name == "gemini" and key.get_secret_value():
        from src.intelligence.providers.gemini import GeminiEmbedder

        embedder: EmbeddingProvider = GeminiEmbedder(key, s.EMBEDDING_MODEL, dims=s.EMBEDDING_DIMS)
    elif embed_name == "fake":
        embedder = FakeEmbedder(dims=s.EMBEDDING_DIMS or 256)
    else:
        if embed_name not in ("gemini", "none", ""):
            logger.warning("Unknown EMBEDDING_PROVIDER %r; embeddings are disabled", embed_name)
        embedder = NullEmbedder("GEMINI_API_KEY is not set" if embed_name == "gemini" else "EMBEDDING_PROVIDER is none")

    return Providers(llm=llm, embedder=embedder)

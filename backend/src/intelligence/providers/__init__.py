"""Language-model and embedding providers behind provider-neutral protocols."""

from src.intelligence.providers.base import (
    EmbeddingProvider,
    InvalidRequest,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    NotConfigured,
    ProviderError,
    ProviderUnavailable,
    RateLimited,
)
from src.intelligence.providers.factory import Providers, build_providers
from src.intelligence.providers.fake import FakeEmbedder, FakeLLM
from src.intelligence.providers.null import NullEmbedder, NullLLM, NullProvider

__all__ = [
    "EmbeddingProvider",
    "FakeEmbedder",
    "FakeLLM",
    "InvalidRequest",
    "LLMProvider",
    "LLMRequest",
    "LLMResponse",
    "NotConfigured",
    "NullEmbedder",
    "NullLLM",
    "NullProvider",
    "ProviderError",
    "ProviderUnavailable",
    "Providers",
    "RateLimited",
    "build_providers",
]

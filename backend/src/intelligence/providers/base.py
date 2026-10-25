"""Provider-neutral interfaces to a language model and an embedding model.

The pipeline only talks to these protocols.  ``OpenAICompatLLM`` (OpenRouter, OpenAI, ...) and
``GeminiLLM`` are the real implementations; ``NullLLM`` / ``NullEmbedder`` stand in when
nothing is configured and ``FakeLLM`` / ``FakeEmbedder`` serve tests and
offline checks.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

from src.intelligence.models import Usage

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ProviderError(Exception):
    """Base class of every provider failure.  Messages are for logs, never for clients."""


class NotConfigured(ProviderError):
    """No provider (or no credentials) is set up."""


class ProviderUnavailable(ProviderError):
    """The provider failed, timed out or could not be reached."""


class RateLimited(ProviderError):
    """The provider throttled the request."""


class InvalidRequest(ProviderError):
    """The provider rejected the request itself (bad input, blocked content)."""


# ---------------------------------------------------------------------------
# Language model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LLMRequest:
    prompt: str
    system: str = ""
    temperature: float = 0.0
    max_output_tokens: int | None = None
    timeout_s: float | None = None
    # JSON schema of the wanted answer; the provider is asked for JSON in that shape.
    json_schema: dict[str, Any] | None = None
    # When set, providers that can stream call it with each text delta as it arrives
    # (others ignore it and return the whole reply at the end).
    on_text: Callable[[str], Awaitable[None]] | None = field(default=None, compare=False, repr=False)


@dataclass(frozen=True)
class LLMResponse:
    text: str
    # The decoded JSON when ``json_schema`` was given and the text parsed.
    parsed: dict[str, Any] | None = None
    usage: Usage = field(default_factory=Usage)
    finish_reason: str | None = None


@runtime_checkable
class LLMProvider(Protocol):
    name: str
    model: str

    async def generate(self, req: LLMRequest) -> LLMResponse: ...


# ---------------------------------------------------------------------------
# Embedding model
# ---------------------------------------------------------------------------

EmbedTask = Literal["document", "query"]


@runtime_checkable
class EmbeddingProvider(Protocol):
    name: str
    model: str

    @property
    def dims(self) -> int | None:
        """Vector size, once known (``None`` until the first call for providers that discover it)."""
        ...

    async def embed(self, texts: Sequence[str], *, task: EmbedTask) -> list[list[float]]: ...


def is_configured(provider: object) -> bool:
    """False for the stand-ins used when nothing is configured."""
    return not getattr(provider, "is_null", False)

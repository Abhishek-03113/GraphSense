"""Stand-ins used when no model is configured: every call raises :class:`NotConfigured`."""

from __future__ import annotations

from collections.abc import Sequence

from src.intelligence.providers.base import EmbedTask, LLMRequest, LLMResponse, NotConfigured


class NullLLM:
    name = "none"
    model = ""
    is_null = True

    def __init__(self, reason: str = "no language model is configured") -> None:
        self.reason = reason

    async def generate(self, req: LLMRequest) -> LLMResponse:
        raise NotConfigured(self.reason)


class NullEmbedder:
    name = "none"
    model = ""
    is_null = True

    def __init__(self, reason: str = "no embedding model is configured") -> None:
        self.reason = reason

    @property
    def dims(self) -> int | None:
        return None

    async def embed(self, texts: Sequence[str], *, task: EmbedTask) -> list[list[float]]:
        raise NotConfigured(self.reason)


# The design calls the stand-in ``NullProvider``.
NullProvider = NullLLM

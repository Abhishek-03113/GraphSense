"""Deterministic providers for tests, CI and offline evaluation.

``FakeLLM`` answers from a script, so a test decides exactly what the "model"
says on each call (including failures).  ``FakeEmbedder`` turns text into a
bag-of-words vector with hashing: two texts that share words are close, texts
that share none are orthogonal.  That is enough to exercise retrieval ranking
and the scope check without a network.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from src.intelligence.models import Usage
from src.intelligence.providers.base import EmbedTask, LLMRequest, LLMResponse

# A scripted step is a reply text, a ready response, a JSON-able dict, or an exception to raise.
Step = str | dict | LLMResponse | BaseException
Script = Sequence[Step] | Callable[[LLMRequest], Step]


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


@dataclass
class FakeLLM:
    """A scripted language model.

    ``script`` is either a list of steps consumed in order (the last step repeats
    once the list is used up) or a function ``request -> step``.  Every request is
    kept in ``calls`` for assertions.
    """

    script: Script = ()
    name: str = "fake"
    model: str = "fake-llm"
    calls: list[LLMRequest] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._cursor = 0

    def _next(self, req: LLMRequest) -> Step:
        if callable(self.script):
            return self.script(req)
        steps = list(self.script)
        if not steps:
            raise AssertionError("FakeLLM has no scripted reply left")
        step = steps[min(self._cursor, len(steps) - 1)]
        self._cursor += 1
        return step

    async def generate(self, req: LLMRequest) -> LLMResponse:
        self.calls.append(req)
        step = self._next(req)
        if isinstance(step, BaseException):
            raise step
        if isinstance(step, LLMResponse):
            return step
        text = json.dumps(step) if isinstance(step, dict) else str(step)
        parsed: dict[str, Any] | None = None
        if req.json_schema is not None:
            try:
                value = json.loads(text)
                parsed = value if isinstance(value, dict) else None
            except ValueError:
                parsed = None
        usage = Usage(
            input_tokens=_approx_tokens(req.prompt + req.system),
            output_tokens=_approx_tokens(text),
            llm_calls=1,
        )
        return LLMResponse(text=text, parsed=parsed, usage=usage, finish_reason="stop")

    @property
    def call_count(self) -> int:
        return len(self.calls)


_WORD = re.compile(r"[a-z0-9]+")


def _stem(word: str) -> str:
    for suffix in ("ies", "es", "s"):
        if len(word) > len(suffix) + 2 and word.endswith(suffix):
            return word[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return word


class FakeEmbedder:
    """Hash-based bag-of-words embeddings (unit length, deterministic)."""

    name = "fake"

    def __init__(self, dims: int = 256, model: str = "fake-embed") -> None:
        self._dims = dims
        self.model = model
        self.calls: list[tuple[str, int]] = []
        self.fail_with: BaseException | None = None

    @property
    def dims(self) -> int:
        return self._dims

    def vector(self, text: str) -> list[float]:
        vec = [0.0] * self._dims
        for raw in _WORD.findall(text.lower()):
            word = _stem(raw)
            digest = hashlib.blake2b(word.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self._dims
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[index] += sign
        norm = math.sqrt(sum(x * x for x in vec))
        if norm == 0:
            return vec
        return [x / norm for x in vec]

    async def embed(self, texts: Sequence[str], *, task: EmbedTask) -> list[list[float]]:
        if self.fail_with is not None:
            raise self.fail_with
        self.calls.append((task, len(texts)))
        return [self.vector(t) for t in texts]

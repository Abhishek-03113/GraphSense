"""Language models for offline evaluation: no network, fully predictable.

``GoldenReplayLLM`` answers the SQL-writing prompt with the reference query of the question
being evaluated, so everything *around* the model (retrieval, scope check, the SQL guard, the
read-only execution, entity extraction, answer assembly) is exercised with a model that is never
wrong.  ``RefusingLLM`` declines every question: it lets the scope check run on its own, without
spending a model call, because a question that passes the scope check ends with a refusal.
"""

from __future__ import annotations

import json
from typing import Any

from src.intelligence.models import Usage
from src.intelligence.prompts import render
from src.intelligence.providers.base import LLMRequest, LLMResponse


def _tokens(text: str) -> int:
    return max(1, len(text) // 4)


class _ScriptedLLM:
    name = "replay"
    model = "offline-replay"

    def __init__(self) -> None:
        self.calls = 0

    def _reply(self, req: LLMRequest) -> dict[str, Any]:
        raise NotImplementedError

    async def generate(self, req: LLMRequest) -> LLMResponse:
        self.calls += 1
        payload = self._reply(req)
        text = json.dumps(payload)
        usage = Usage(
            input_tokens=_tokens(req.prompt + req.system),
            output_tokens=_tokens(text),
            llm_calls=1,
        )
        return LLMResponse(text=text, parsed=payload, usage=usage, finish_reason="stop")


class GoldenReplayLLM(_ScriptedLLM):
    """Replies with ``self.sql`` whenever it is asked to write a query."""

    model = "golden-replay"

    def __init__(self) -> None:
        super().__init__()
        self.sql: str | None = None

    def _reply(self, req: LLMRequest) -> dict[str, Any]:
        if req.json_schema == render.ANSWER_SCHEMA:
            return {"answer": "Reference query replayed."}
        return {"can_answer": self.sql is not None, "sql": self.sql, "assumptions": [], "refusal_reason": None}


class RefusingLLM(_ScriptedLLM):
    """Says it cannot answer.  Used to test the scope check alone."""

    model = "refusal"

    def _reply(self, req: LLMRequest) -> dict[str, Any]:
        if req.json_schema == render.ANSWER_SCHEMA:
            return {"answer": "Not answered."}
        return {"can_answer": False, "sql": None, "assumptions": [], "refusal_reason": "evaluation: scope check only"}

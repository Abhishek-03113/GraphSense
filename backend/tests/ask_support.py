"""Helpers for testing the Ask layer without a database or a network."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from src.datasets.context import DatasetContext
from src.datasets.models import DatasetPackage
from src.intelligence.catalog_access import PackageCatalogSource
from src.intelligence.models import ExecutionError, ExecutionResult, ValidatedSql
from src.intelligence.providers import FakeEmbedder, FakeLLM, NullEmbedder
from src.intelligence.service import AskService


def draft(sql: str | None, *, can_answer: bool = True, assumptions: Sequence[str] = (), reason: str | None = None) -> str:
    return json.dumps(
        {"can_answer": can_answer, "sql": sql, "assumptions": list(assumptions), "refusal_reason": reason}
    )


def answer(text: str = "Here is the answer.") -> str:
    return json.dumps({"answer": text})


class StubExecutor:
    """Returns scripted results, in order (the last one repeats); an exception is raised instead of returned."""

    def __init__(self, *outcomes: ExecutionResult | ExecutionError) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple[str | None, ValidatedSql]] = []

    async def execute(self, schema_name: str | None, validated: ValidatedSql) -> ExecutionResult:
        self.calls.append((schema_name, validated))
        outcome = self.outcomes[min(len(self.calls) - 1, len(self.outcomes) - 1)]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def rows(columns: Sequence[str], *data: Sequence[Any], types: Sequence[str] | None = None, truncated: bool = False):
    return ExecutionResult(
        columns=tuple(columns),
        column_types=tuple(types or ["text"] * len(columns)),
        rows=[tuple(r) for r in data],
        truncated=truncated,
    )


def context(package: DatasetPackage) -> DatasetContext:
    return DatasetContext(id=package.id, schema_name=package.schema_name, package=package)


def make_service(
    llm: FakeLLM,
    executor: StubExecutor | None = None,
    *,
    embedder: Any = None,
    **kwargs: Any,
) -> AskService:
    return AskService(
        llm=llm,
        embedder=embedder if embedder is not None else NullEmbedder(),
        catalog=PackageCatalogSource(),
        executor=executor,
        **kwargs,
    )


def with_embedder() -> FakeEmbedder:
    return FakeEmbedder()

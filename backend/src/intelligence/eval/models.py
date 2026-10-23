"""What an evaluation run produces: per-question results, metrics and the report."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any, Literal

Mode = Literal["offline", "live"]

# Bump when the shape of the JSON report changes.
REPORT_VERSION = 1


@dataclass
class RetrievalResult:
    tables_expected: list[str] = field(default_factory=list)
    tables_retrieved: list[str] = field(default_factory=list)
    table_recall: float | None = None
    examples_retrieved: list[str] = field(default_factory=list)
    examples_relevant: int = 0
    example_hit: bool | None = None
    mode: str | None = None


@dataclass
class EntityResult:
    count: int = 0
    problems: list[str] = field(default_factory=list)


@dataclass
class CaseResult:
    """One golden question."""

    id: str
    question: str
    tags: list[str] = field(default_factory=list)
    # The reference query itself.
    guard_accepted: bool = False
    guard_message: str = ""
    reference_ok: bool = False
    reference_rows: int | None = None
    expectation_problems: list[str] = field(default_factory=list)
    # The question run through the whole pipeline.
    scope_ok: bool = False
    scope_lexical: bool = False  # the vocabulary alone puts the question in scope
    error: str | None = None
    sql_valid: bool = False  # a query was accepted by the guard and ran
    first_try_ok: bool = False
    attempts: int = 0
    refused: bool = False  # the model said it could not answer, or the question was out of scope
    generated_sql: str | None = None
    match: bool | None = None
    match_superset: bool | None = None
    match_reason: str = ""
    retrieval: RetrievalResult = field(default_factory=RetrievalResult)
    entities: EntityResult = field(default_factory=EntityResult)
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class GuardrailResult:
    question: str
    expect: str
    got: str
    passed: bool
    reason: str = ""
    similarity: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class EvalReport:
    version: int
    dataset_id: str
    mode: Mode
    started_at: str
    duration_s: float
    package_version: str
    package_hash: str
    prompt_version: str
    model: str
    embedding_model: str
    retrieval_modes: dict[str, int]
    read_only_role: bool
    golden_count: int
    guardrail_case_count: int
    metrics: dict[str, float | int | None]
    gated: list[str]
    score: float | None
    leakage: dict[str, Any]
    cases: list[CaseResult]
    guardrail_cases: list[GuardrailResult]
    notes: list[str] = field(default_factory=list)
    # Filled in by the caller once a threshold is applied.
    fail_under: float | None = None
    passed: bool | None = None
    run_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        data = dataclasses.asdict(self)
        data["cases"] = [c.as_dict() for c in self.cases]
        data["guardrail_cases"] = [g.as_dict() for g in self.guardrail_cases]
        return data

"""Run a dataset's golden questions and guardrail cases through :class:`AskService` and measure.

Two modes share one code path:

* **offline**: the language model is a replay of each question's reference query and the
  embedder is the hash-based fake, so the run needs no key and no network.  It proves that the
  parts around the model work for this dataset: the right context is retrieved, every reference
  query passes the SQL guard and runs under the read-only role, the pipeline returns the same rows
  as the reference query, extracted entities are real graph records, the scope check lets the
  golden questions in and keeps the guardrail cases out, and no golden question can be retrieved.
* **live**: the configured model writes the SQL.  The headline metric is *execution accuracy*:
  the rows the pipeline returns equal the rows of the reference query (order, column names and
  float noise ignored), not whether the SQL text matches.

The runner takes its collaborators as arguments (catalog source, executor, retriever, graph id
source), so the unit tests drive it with stubs and no database.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.catalog import CatalogSnapshot
from src.config import Settings, get_settings
from src.datasets.context import DatasetContext
from src.datasets.models import ExampleSpec
from src.intelligence.catalog_access import CatalogSource, llm_safe
from src.intelligence.eval import metrics as m
from src.intelligence.eval.compare import compare_results
from src.intelligence.eval.graph_ids import GraphIdSource
from src.intelligence.eval.models import (
    REPORT_VERSION,
    CaseResult,
    EntityResult,
    EvalReport,
    GuardrailResult,
    Mode,
    RetrievalResult,
)
from src.intelligence.eval.replay import GoldenReplayLLM, RefusingLLM
from src.intelligence.guardrails.scope import ScopeVocabulary
from src.intelligence.knowledge.items import build_items
from src.intelligence.models import ErrorCode, ExecutionError, SqlRejected
from src.intelligence.prompts import render
from src.intelligence.providers.base import EmbeddingProvider, LLMProvider, is_configured
from src.intelligence.retrieval.hybrid import HybridRetriever
from src.intelligence.service import AskService, SqlExecutor
from src.intelligence.sql.guard import SqlGuard
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Metrics a run is judged by (the lowest of them is the run's score), per mode.
OFFLINE_GATED = (
    "sql_guard_acceptance",
    "execution_success",
    "expectation_pass_rate",
    "result_correctness",
    "golden_scope_lexical",
    "entity_validity",
    "guardrail_pass_rate",
    "retrieval_table_recall",
)
LIVE_GATED = ("execution_accuracy", "guardrail_accuracy")

KnowledgeTexts = Callable[[str], Awaitable[list[tuple[str, str, str]]]]


class _FixedCatalog:
    """Hands every question the same snapshot, so a run cannot change underneath itself."""

    def __init__(self, snapshot: CatalogSnapshot) -> None:
        self._snapshot = snapshot

    async def get_snapshot(self, ctx: DatasetContext) -> CatalogSnapshot:
        return self._snapshot


@dataclass
class EvalOptions:
    only: tuple[str, ...] = ()  # run only these golden ids
    limit: int | None = None  # run at most this many golden questions
    pause_s: float = 0.0  # wait between live questions (provider rate limits)


class Evaluator:
    """Evaluates one dataset.  Build it with the pieces for the mode, then ``await run(ctx)``."""

    def __init__(
        self,
        *,
        mode: Mode,
        llm: LLMProvider,
        embedder: EmbeddingProvider,
        catalog: CatalogSource,
        executor: SqlExecutor,
        retriever: HybridRetriever | None = None,
        scope_embedder: EmbeddingProvider | None = None,
        graph_ids: GraphIdSource | None = None,
        knowledge_texts: KnowledgeTexts | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.mode: Mode = mode
        self.llm = llm
        self.embedder = embedder
        self.catalog = catalog
        self.executor = executor
        self.retriever = retriever or HybridRetriever(None, embedder)
        # Embedder behind the guardrail cases.  Offline it is a stand-in without vectors, so the
        # scope check is decided by the vocabulary alone (hashed word vectors say nothing about meaning).
        self.scope_embedder = scope_embedder if scope_embedder is not None else embedder
        self.graph_ids = graph_ids
        self.knowledge_texts = knowledge_texts
        self._settings = settings

    @property
    def settings(self) -> Settings:
        return self._settings or get_settings()

    # ------------------------------------------------------------------

    async def run(self, ctx: DatasetContext, options: EvalOptions | None = None) -> EvalReport:
        options = options or EvalOptions()
        started = time.perf_counter()
        started_at = datetime.now(UTC).isoformat(timespec="seconds")
        package = ctx.package
        snapshot = await self.catalog.get_snapshot(ctx)
        fixed = _FixedCatalog(snapshot)
        table_names = {t.name for t in snapshot.tables}
        goldens = [e for e in package.semantics.examples if e.role == "golden"]
        selected = [g for g in goldens if not options.only or g.id in options.only]
        if options.limit is not None:
            selected = selected[: options.limit]
        notes: list[str] = []
        if options.only:
            unknown = sorted(set(options.only) - {g.id for g in goldens})
            if unknown:
                notes.append(f"unknown golden id(s) ignored: {', '.join(unknown)}")

        service = AskService(
            llm=self.llm,
            embedder=self.embedder,
            catalog=fixed,
            executor=self.executor,
            retriever=self.retriever,
            settings=self._settings,
        )
        # Guardrail cases never need the model to write SQL: a refusing stand-in lets a question
        # that passes the scope check end quietly, without a (paid) model call.
        scope_service = AskService(
            llm=RefusingLLM(),
            embedder=self.scope_embedder,
            catalog=fixed,
            executor=self.executor,
            retriever=HybridRetriever(self.retriever.store, self.scope_embedder),
            settings=self._settings,
        )

        vocabulary = ScopeVocabulary.build(package, snapshot)
        leakage = await self._leakage(snapshot, goldens)
        few_shot_tables = {e.id: m.tables_in_sql(e.sql, table_names) for e in snapshot.few_shot_examples()}
        node_types = {n.key for n in package.graph.node_types}

        cases: list[CaseResult] = []
        for index, golden in enumerate(selected):
            if index and options.pause_s:
                await asyncio.sleep(options.pause_s)
            case = await self._run_golden(
                ctx, service, snapshot, golden, goldens, table_names, few_shot_tables, node_types, leakage
            )
            case.scope_lexical = bool(vocabulary.matches(golden.question))
            cases.append(case)
            logger.info("eval %s: %s match=%s error=%s", ctx.id, golden.id, case.match, case.error)

        guardrail = await self._run_guardrail_cases(ctx, scope_service)

        retrieval_modes: dict[str, int] = {}
        for case in cases:
            if case.retrieval.mode:
                retrieval_modes[case.retrieval.mode] = retrieval_modes.get(case.retrieval.mode, 0) + 1

        if cases and all(c.error == ErrorCode.DATASET_NOT_READY for c in cases):
            notes.append("the dataset's tables are not loaded: run `graphsense ingest` first")
        degraded = bool(getattr(self.executor, "degraded", False))
        if degraded:
            notes.append("READONLY_DATABASE_DSN is not set: generated SQL ran with the application role")

        metrics = self._metrics(cases, guardrail, leakage)
        gated = [g for g in (OFFLINE_GATED if self.mode == "offline" else LIVE_GATED) if metrics.get(g) is not None]
        scores = [float(metrics[g]) for g in gated]
        score = min(scores) if scores else None
        if leakage["leaks"]:
            score = 0.0

        return EvalReport(
            version=REPORT_VERSION,
            dataset_id=ctx.id,
            mode=self.mode,
            started_at=started_at,
            duration_s=round(time.perf_counter() - started, 2),
            package_version=snapshot.package_version,
            package_hash=snapshot.package_hash,
            prompt_version=render.PROMPT_VERSION,
            model=getattr(self.llm, "model", "") or "",
            embedding_model=getattr(self.embedder, "model", "") if is_configured(self.embedder) else "",
            retrieval_modes=retrieval_modes,
            read_only_role=not degraded,
            golden_count=len(cases),
            guardrail_case_count=len(guardrail),
            metrics=metrics,
            gated=gated,
            score=m.round_or_none(score),
            leakage=leakage,
            cases=cases,
            guardrail_cases=guardrail,
            notes=notes,
        )

    # ------------------------------------------------------------------
    # One golden question
    # ------------------------------------------------------------------

    async def _run_golden(
        self,
        ctx: DatasetContext,
        service: AskService,
        snapshot: CatalogSnapshot,
        golden: ExampleSpec,
        goldens: list[ExampleSpec],
        table_names: set[str],
        few_shot_tables: dict[str, set[str]],
        node_types: set[str],
        leakage: dict[str, Any],
    ) -> CaseResult:
        settings = self.settings
        case = CaseResult(id=golden.id, question=golden.question, tags=list(golden.tags))

        # 1. The reference query on its own: guard, read-only execution, declared expectations.
        reference_rows: list[tuple] | None = None
        checked = SqlGuard().validate(
            golden.sql,
            snapshot,
            schema_name=ctx.schema_name,
            max_rows=settings.SQL_MAX_ROWS,
            extra_functions=tuple(ctx.package.sql.extra_functions),
        )
        if isinstance(checked, SqlRejected):
            case.guard_message = f"{checked.code}: {checked.message}"[:300]
        else:
            case.guard_accepted = True
            try:
                reference = await self.executor.execute(ctx.schema_name, checked)
            except ExecutionError as err:
                case.guard_message = f"reference query failed: {err.category}"
            else:
                case.reference_ok = True
                case.reference_rows = len(reference.rows)
                reference_rows = [tuple(r) for r in reference.rows]
                case.expectation_problems = m.expectation_problems(golden.expect, reference.columns, len(reference.rows))

        # 2. The question through the whole pipeline.
        replay = self.llm if isinstance(self.llm, GoldenReplayLLM) else None
        if replay is not None:
            replay.sql = golden.sql
        try:
            result = await service.ask(ctx, golden.question, trace=True)
        finally:
            if replay is not None:
                replay.sql = None

        trace = result.trace or {}
        attempts = trace.get("attempts") or []
        case.error = result.error
        case.scope_ok = result.error_code != ErrorCode.GUARDRAIL
        case.refused = result.error_code in (ErrorCode.GUARDRAIL, ErrorCode.SQL_GENERATION_FAILED)
        case.attempts = len(attempts)
        case.sql_valid = any(a.get("outcome") == "ok" for a in attempts)
        case.first_try_ok = bool(attempts) and attempts[0].get("outcome") == "ok"
        if result.sql and result.sql != golden.sql:
            case.generated_sql = result.sql
        case.latency_ms = result.timings.total_ms
        case.input_tokens = result.usage.input_tokens
        case.output_tokens = result.usage.output_tokens

        # 3. Does the pipeline's answer equal the reference answer?
        if result.ok and reference_rows is not None:
            names = [c.name for c in result.columns]
            candidate = [tuple((row or {}).get(n) for n in names) for row in (result.rows or [])]
            comparison = compare_results(reference_rows, candidate)
            case.match = comparison.equal
            case.match_superset = comparison.superset
            case.match_reason = comparison.reason
        elif reference_rows is not None:
            case.match = False
            case.match_superset = False
            case.match_reason = result.error or "no answer"

        # 4. What retrieval brought back.
        expected_tables = sorted(m.tables_in_sql(golden.sql, table_names))
        info = trace.get("retrieval") or {}
        retrieved_tables = list(info.get("tables") or [])
        retrieved_examples = list(info.get("examples") or [])
        hit = m.example_hit(expected_tables, retrieved_examples, few_shot_tables)
        case.retrieval = RetrievalResult(
            tables_expected=expected_tables,
            tables_retrieved=retrieved_tables,
            table_recall=m.recall(expected_tables, retrieved_tables),
            examples_retrieved=retrieved_examples,
            examples_relevant=hit.relevant,
            example_hit=hit.hit,
            mode=info.get("mode"),
        )
        # A golden question must never come back as retrieved knowledge.
        seen = [(f"retrieval for {golden.id!r}", h.get("ref", "")) for h in info.get("hits") or []]
        for leak in m.find_id_leaks(goldens, seen):
            leakage["leaks"].append({"example": leak.example_id, "source": leak.source, "what": leak.what})

        # 5. Entities highlighted for the graph.
        if result.entities:
            known = None
            if self.graph_ids is not None:
                known = await self.graph_ids.ids({e.type for e in result.entities if e.type in node_types})
            case.entities = EntityResult(
                count=len(result.entities),
                problems=m.entity_problems(result.entities, node_types, known),
            )
        return case

    # ------------------------------------------------------------------
    # Guardrail cases
    # ------------------------------------------------------------------

    async def _run_guardrail_cases(self, ctx: DatasetContext, service: AskService) -> list[GuardrailResult]:
        results = []
        for case in ctx.package.semantics.vocabulary.guardrail_cases:
            answer = await service.ask(ctx, case.question, trace=True)
            got = "reject" if answer.error_code == ErrorCode.GUARDRAIL else "allow"
            scope = (answer.trace or {}).get("scope") or {}
            results.append(
                GuardrailResult(
                    question=case.question,
                    expect=case.expect,
                    got=got,
                    passed=got == case.expect,
                    reason=str(scope.get("reason") or ("screened" if got == "reject" else "")),
                    similarity=m.round_or_none(scope.get("similarity")),
                )
            )
        return results

    # ------------------------------------------------------------------
    # Leakage
    # ------------------------------------------------------------------

    async def _leakage(self, snapshot: CatalogSnapshot, goldens: list[ExampleSpec]) -> dict[str, Any]:
        """Golden questions must be in no knowledge item, built or stored."""
        texts: list[tuple[str, str]] = []
        refs: list[tuple[str, str]] = []
        built = build_items(llm_safe(snapshot))
        for item in built:
            texts.append((f"built item {item.kind}:{item.ref}", item.text))
            refs.append((f"built item {item.kind}:{item.ref}", item.ref))
        stored = 0
        if self.knowledge_texts is not None:
            try:
                rows = await self.knowledge_texts(snapshot.dataset_id)
            except Exception as exc:  # noqa: BLE001 - an unreachable store must not stop the run
                logger.warning("Could not read the knowledge store for the leakage check (%s)", type(exc).__name__)
                rows = []
            stored = len(rows)
            for kind, ref, body in rows:
                texts.append((f"stored item {kind}:{ref}", body))
                refs.append((f"stored item {kind}:{ref}", ref))
        report = m.find_leaks(goldens, texts)
        leaks = [*report.leaks, *m.find_id_leaks(goldens, refs)]
        return {
            "built_items": len(built),
            "stored_items": stored,
            "leaks": [{"example": x.example_id, "source": x.source, "what": x.what} for x in leaks],
        }

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def _metrics(
        self, cases: list[CaseResult], guardrail: list[GuardrailResult], leakage: dict[str, Any]
    ) -> dict[str, float | int | None]:
        r = m.round_or_none
        entity_refs = sum(c.entities.count for c in cases)
        entity_bad = sum(len(c.entities.problems) for c in cases)
        latencies = [float(c.latency_ms) for c in cases]
        tokens = [c.input_tokens + c.output_tokens for c in cases]
        # Cases with a reference result are the ones that can be judged for correctness.
        judged = [c for c in cases if c.reference_ok]
        correctness = r(m.rate(c.match for c in judged))
        out: dict[str, float | int | None] = {
            "sql_guard_acceptance": r(m.rate(c.guard_accepted for c in cases)),
            "execution_success": r(m.rate(c.sql_valid for c in cases)),
            "expectation_pass_rate": r(m.rate(not c.expectation_problems for c in cases if c.reference_ok)),
            "golden_scope_lexical": r(m.rate(c.scope_lexical for c in cases)),
            "golden_scope_acceptance": r(m.rate(c.scope_ok for c in cases)),
            "entity_validity": r((entity_refs - entity_bad) / entity_refs) if entity_refs else None,
            "entity_refs_checked": entity_refs,
            "guardrail_pass_rate": r(m.rate(g.passed for g in guardrail)),
            "retrieval_table_recall": r(m.mean(c.retrieval.table_recall for c in cases)),
            "retrieval_table_full_rate": r(
                m.rate(c.retrieval.table_recall >= 1.0 for c in cases if c.retrieval.table_recall is not None)
            ),
            "retrieval_example_hit_rate": r(m.rate(c.retrieval.example_hit for c in cases)),
            "refusal_rate": r(m.rate(c.refused for c in cases)),
            "repair_rate": r(m.rate(c.attempts > 1 for c in cases)),
            "latency_p50_ms": m.percentile(latencies, 0.5),
            "latency_p95_ms": m.percentile(latencies, 0.95),
            "tokens_total": sum(tokens),
            "tokens_per_question": r(m.mean(float(t) for t in tokens)),
            "golden_leaks": len(leakage["leaks"]),
        }
        if self.mode == "offline":
            out["result_correctness"] = correctness
        else:
            out["execution_accuracy"] = correctness
            out["execution_accuracy_lenient"] = r(m.rate(c.match_superset for c in judged))
            out["sql_validity"] = r(m.rate(c.sql_valid for c in cases))
            out["guardrail_accuracy"] = out["guardrail_pass_rate"]
            out["first_try_rate"] = r(m.rate(c.first_try_ok for c in cases))
        return out

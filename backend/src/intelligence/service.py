"""``AskService``: answer a natural-language question about one dataset.

This is the single entry point of the Ask layer.  Callers (the HTTP endpoint, the
evaluation harness, the CLI) hand it a :class:`DatasetContext` and a question and get
an :class:`AskResult`; they never talk to providers, the database or the knowledge
store directly.

Pipeline::

    screen -> scope check -> retrieve -> write SQL -> validate -> run (read only)
           -> [repair on syntax/column/table/type errors] -> extract entities -> answer

Expected failures (out of scope, no model key, a query that cannot run, a provider that
is down) never raise: they come back as an ``AskResult`` with ``error_code`` set.
"""

from __future__ import annotations

import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from src.catalog import CatalogSnapshot
from src.config import Settings, get_settings
from src.datasets.context import DatasetContext
from src.intelligence.catalog_access import CatalogSource, llm_safe
from src.intelligence.entities import EntityExtractor
from src.intelligence.guardrails.injection import screen
from src.intelligence.guardrails.scope import ScopeVocabulary, decide
from src.intelligence.models import (
    AiMode,
    AskResult,
    ErrorCode,
    ExecutionError,
    ExecutionResult,
    ResultColumn,
    SqlRejected,
    Usage,
    ValidatedSql,
)
from src.intelligence.privacy import build_llm_view
from src.intelligence.prompts import render
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
    is_configured,
)
from src.intelligence.providers.factory import compute_mode
from src.intelligence.querylog import LogEntry, QueryLog
from src.intelligence.retrieval.context import ContextBundle, assemble_context
from src.intelligence.retrieval.hybrid import HybridRetriever, QueryEmbedding, Retrieval
from src.intelligence.sql.guard import SqlGuard
from src.utils.logger import get_logger
from src.utils.serialization import json_value

logger = get_logger(__name__)

NOT_CONFIGURED_MESSAGE = (
    "Questions can't be answered yet because the language model isn't set up on this server. "
    "Add an API key for the configured provider (for example OPENROUTER_API_KEY) to the backend configuration and restart it."
)
MAX_SUGGESTIONS = 4
MAX_REFUSAL_CHARS = 240


# Progress of one question, sent to clients that listen: ``{"type": "status", "stage": ...}``
# and ``{"type": "delta", "text": ...}`` (a piece of the answer as it is written).
Emit = Callable[[dict[str, Any]], Awaitable[None]]


class _AnswerStreamer:
    """Pulls the text of the ``answer`` string out of a JSON reply as it streams in."""

    _KEY = re.compile(r'"answer"\s*:\s*"')
    _ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "/": "/", '"': '"', "\\": "\\"}

    def __init__(self, emit: Callable[[str], Awaitable[None]]) -> None:
        self._emit = emit
        self._buffer = ""
        self._open = False
        self._done = False
        self._pending_escape = ""

    async def feed(self, chunk: str) -> None:
        if self._done:
            return
        self._buffer += chunk
        if not self._open:
            match = self._KEY.search(self._buffer)
            if not match:
                return
            self._buffer = self._buffer[match.end():]
            self._open = True
        text, self._buffer = self._buffer, ""
        out: list[str] = []
        i = 0
        text = self._pending_escape + text
        self._pending_escape = ""
        while i < len(text):
            ch = text[i]
            if ch == '"':
                self._done = True
                break
            if ch == "\\":
                if i + 1 >= len(text):
                    self._pending_escape = ch
                    break
                nxt = text[i + 1]
                if nxt == "u":
                    if i + 6 > len(text):
                        self._pending_escape = text[i:]
                        break
                    try:
                        out.append(chr(int(text[i + 2 : i + 6], 16)))
                    except ValueError:
                        pass
                    i += 6
                    continue
                out.append(self._ESCAPES.get(nxt, nxt))
                i += 2
                continue
            out.append(ch)
            i += 1
        if out:
            await self._emit("".join(out))


class SqlExecutor(Protocol):
    async def execute(self, schema_name: str, validated: ValidatedSql) -> ExecutionResult: ...


@dataclass
class _Run:
    """Mutable state of one question while it moves through the pipeline."""

    question: str
    result: AskResult
    started: float
    usage: Usage = field(default_factory=Usage)
    sql: str | None = None
    validated_ok: bool = False
    attempts: list[dict[str, Any]] | None = None
    suggestions: list[str] = field(default_factory=list)
    emit: Emit | None = None


def _ms(since: float) -> int:
    return int((time.perf_counter() - since) * 1000)


def _clean_reason(text: str | None) -> str:
    cleaned = re.sub(r"[\x00-\x1f]+", " ", text or "").strip()
    return cleaned[:MAX_REFUSAL_CHARS]


class AskService:
    def __init__(
        self,
        *,
        llm: LLMProvider,
        embedder: EmbeddingProvider,
        catalog: CatalogSource,
        guard: SqlGuard | None = None,
        executor: SqlExecutor | None = None,
        retriever: HybridRetriever | None = None,
        query_log: QueryLog | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.llm = llm
        self.embedder = embedder
        self.catalog = catalog
        self.guard = guard or SqlGuard()
        self.executor = executor
        self.retriever = retriever or HybridRetriever(None, embedder)
        self.query_log = query_log
        self._settings = settings
        self._vocab: dict[tuple, ScopeVocabulary] = {}
        self._extractors: dict[tuple, EntityExtractor] = {}

    # --- configuration ----------------------------------------------------

    @property
    def settings(self) -> Settings:
        return self._settings or get_settings()

    @property
    def mode(self) -> AiMode:
        return compute_mode(self.llm, self.embedder)

    def _get_executor(self) -> SqlExecutor:
        if self.executor is None:
            from src.intelligence.sql.executor import ReadOnlyExecutor

            self.executor = ReadOnlyExecutor()
        return self.executor

    # --- entry point ------------------------------------------------------

    async def ask(
        self,
        ctx: DatasetContext,
        question: str,
        *,
        trace: bool = False,
        client_id: str | None = None,
        emit: Emit | None = None,
    ) -> AskResult:
        """Answer ``question`` about the dataset ``ctx``.

        Never raises for expected failures; ``trace=True`` adds retrieval and attempt
        detail for evaluation.  ``client_id`` is only used for logging.  ``emit`` receives
        progress events while the question is worked on (see :data:`Emit`); its failures are ignored.
        """
        run = _Run(
            question=question, result=AskResult(answer="", mode=self.mode), started=time.perf_counter(), emit=emit
        )
        if trace:
            run.result.trace = {"attempts": [], "prompt_version": render.PROMPT_VERSION}
            run.attempts = run.result.trace["attempts"]
        try:
            await self._ask(ctx, run)
        except ProviderError as exc:
            self._provider_failure(run, exc)
        except Exception:
            logger.exception("Unexpected failure while answering a question")
            self._fail(run, ErrorCode.INTERNAL_ERROR, "An unexpected error occurred while processing your question. Please try again.")
        result = run.result
        result.usage = run.usage
        result.timings.total_ms = _ms(run.started)
        await self._log(ctx, run)
        return result

    async def _event(self, run: _Run, **event: Any) -> None:
        if run.emit is None:
            return
        try:
            await run.emit(event)
        except Exception:  # noqa: BLE001 - a listener that went away must not stop the answer
            logger.debug("Progress listener failed", exc_info=True)
            run.emit = None

    # --- pipeline -----------------------------------------------------------

    async def _ask(self, ctx: DatasetContext, run: _Run) -> None:
        result, question = run.result, run.question
        settings = self.settings
        package = ctx.package

        try:
            snapshot = await self.catalog.get_snapshot(ctx)
        except Exception:
            logger.exception("Catalog unavailable for %s", ctx.id)
            self._fail(run, ErrorCode.DATASET_NOT_READY, "This dataset isn't ready to answer questions yet.")
            return
        safe = llm_safe(snapshot)
        suggestions = [q.text for q in package.semantics.suggested_questions][:MAX_SUGGESTIONS]
        run.suggestions = suggestions
        cache_key = (ctx.id, package.content_hash, snapshot.run_id)

        # 1. hygiene and injection
        t = time.perf_counter()
        screening = screen(question)
        if screening.blocked:
            message = screening.message or snapshot.vocabulary.render_out_of_scope()
            self._fail(run, ErrorCode.GUARDRAIL, message, suggestions)
            result.timings.guardrails_ms = _ms(t)
            return

        # 2. scope: a vocabulary hit needs no embedding; otherwise similarity decides
        vocab = self._vocab.get(cache_key)
        if vocab is None:
            self._vocab = {k: v for k, v in self._vocab.items() if k[0] != ctx.id}
            vocab = self._vocab[cache_key] = ScopeVocabulary.build(package, snapshot)
        query = QueryEmbedding(self.embedder, question)
        retrieval: Retrieval | None = None
        if not vocab.matches(question):
            retrieval = await self.retriever.retrieve(safe, question, query)
            decision = decide(
                vocab, question, best_similarity=retrieval.best_similarity,
                min_similarity=snapshot.vocabulary.min_similarity,
            )
        else:
            decision = decide(vocab, question, best_similarity=None, min_similarity=1.0)
        result.timings.guardrails_ms = _ms(t)
        if result.trace is not None:
            result.trace["scope"] = {"in_scope": decision.in_scope, "reason": decision.reason,
                                     "matched": list(decision.matched), "similarity": decision.similarity}
        if not decision.in_scope:
            self._fail(run, ErrorCode.GUARDRAIL, snapshot.vocabulary.render_out_of_scope(), suggestions)
            return

        # 3. no model: say so (the graph and everything else keep working)
        if not is_configured(self.llm):
            self._fail(run, ErrorCode.NOT_CONFIGURED, NOT_CONFIGURED_MESSAGE, suggestions)
            return

        # 4. retrieval
        await self._event(run, type="status", stage="retrieving")
        t = time.perf_counter()
        if retrieval is None:
            retrieval = await self.retriever.retrieve(safe, question, query)
        run.usage = run.usage + Usage(embed_calls=query.calls)
        if query.failed is not None:
            result.warnings.append("embeddings_unavailable")
        result.warnings.extend(w.replace(" ", "_") for w in retrieval.warnings)
        context = assemble_context(safe, retrieval.hits, budget_chars=settings.RETRIEVAL_CONTEXT_CHARS)
        result.timings.retrieval_ms = _ms(t)
        if result.trace is not None:
            result.trace["retrieval"] = {
                "mode": retrieval.mode,
                "tables": list(context.table_names),
                "examples": list(context.example_ids),
                "best_similarity": retrieval.best_similarity,
                "hits": [{"kind": h.kind, "ref": h.ref, "score": round(s, 5)} for h, s in retrieval.hits[:30]],
            }

        # 5-6. write, validate, run; repair when the failure is something the model can fix
        outcome = await self._write_and_run(ctx, run, safe, snapshot, context)
        if outcome is None:
            return
        validated, execution = outcome

        # 7. describe the result, find graph entities, write the answer
        await self._finish(ctx, run, snapshot, validated, execution, package.llm_sees_rows)

    async def _write_and_run(
        self,
        ctx: DatasetContext,
        run: _Run,
        safe: CatalogSnapshot,
        snapshot: CatalogSnapshot,
        context: ContextBundle,
    ) -> tuple[ValidatedSql, ExecutionResult] | None:
        settings = self.settings
        result = run.result
        cap = settings.SQL_MAX_ROWS
        extra = tuple(ctx.package.sql.extra_functions)

        await self._event(run, type="status", stage="writing_query")
        t = time.perf_counter()
        prompt = render.render_sql_generation(
            dataset_name=snapshot.name,
            dataset_description=snapshot.description,
            scope_summary=snapshot.vocabulary.scope_summary,
            hints=context.hints,
            tables=context.tables,
            relationships=context.relationships,
            glossary=context.glossary,
            examples=context.examples,
            question=run.question,
            row_cap=cap,
        )
        draft = await self._draft(run, prompt)
        result.timings.generation_ms += _ms(t)
        if draft is None or not draft.can_answer or not (draft.sql or "").strip():
            reason = _clean_reason(draft.refusal_reason) if draft else ""
            message = self._generation_failed_message(snapshot)
            if reason:
                message = f"{message} ({reason})"
            self._fail(run, ErrorCode.SQL_GENERATION_FAILED, message, run.suggestions)
            return None
        result.assumptions = [a for a in draft.assumptions if a][:5]
        sql_text = draft.sql or ""

        repairs_left = settings.SQL_REPAIR_ATTEMPTS
        last_error: ExecutionError | None = None
        while True:
            t = time.perf_counter()
            checked = self.guard.validate(
                sql_text, snapshot, schema_name=ctx.schema_name, max_rows=cap, extra_functions=extra
            )
            result.timings.validation_ms += _ms(t)
            problem: str | None = None
            if isinstance(checked, SqlRejected):
                self._note(run, sql_text, f"rejected:{checked.code}")
                if not checked.repairable:
                    self._fail(
                        run, ErrorCode.SQL_REJECTED,
                        "That question needs a query that isn't allowed here. Only read-only lookups of this dataset are supported.",
                    )
                    return None
                problem = checked.message
            else:
                run.sql = checked.sql
                await self._event(run, type="status", stage="running_query")
                t = time.perf_counter()
                try:
                    execution = await self._get_executor().execute(ctx.schema_name, checked)
                except ExecutionError as err:
                    result.timings.execution_ms += _ms(t)
                    self._note(run, checked.sql, f"error:{err.category}")
                    if err.not_ready:
                        self._fail(run, ErrorCode.DATASET_NOT_READY, "This dataset's data isn't loaded yet.")
                        return None
                    if not err.repairable:
                        self._execution_failed(run, err.category, checked.sql)
                        return None
                    problem = self._execution_problem(err.category, checked, snapshot)
                    last_error = err
                else:
                    result.timings.execution_ms += _ms(t)
                    self._note(run, checked.sql, "ok")
                    run.validated_ok = True
                    return checked, execution

            # something the model can fix
            if repairs_left <= 0:
                if isinstance(checked, SqlRejected):
                    self._fail(run, ErrorCode.SQL_GENERATION_FAILED, self._generation_failed_message(snapshot), run.suggestions)
                else:
                    self._execution_failed(run, last_error.category if last_error else "other", checked.sql)
                return None
            repairs_left -= 1
            t = time.perf_counter()
            repair = render.render_repair(
                dataset_name=snapshot.name,
                hints=context.hints,
                tables=context.tables,
                relationships=context.relationships,
                question=run.question,
                failed_sql=sql_text if isinstance(checked, SqlRejected) else checked.sql,
                problem=problem or "",
                row_cap=cap,
            )
            fixed = await self._draft(run, repair)
            result.timings.generation_ms += _ms(t)
            if fixed is None or not fixed.can_answer or not (fixed.sql or "").strip():
                self._fail(run, ErrorCode.SQL_GENERATION_FAILED, self._generation_failed_message(snapshot), run.suggestions)
                return None
            sql_text = fixed.sql or ""
            result.assumptions = [a for a in fixed.assumptions if a][:5] or result.assumptions

    # --- finishing ----------------------------------------------------------

    async def _finish(
        self,
        ctx: DatasetContext,
        run: _Run,
        snapshot: CatalogSnapshot,
        validated: ValidatedSql,
        execution: ExecutionResult,
        sees_rows: bool,
    ) -> None:
        result = run.result
        columns = self._describe_columns(snapshot, validated, execution)
        names = list(execution.columns)
        result.sql = validated.sql
        result.columns = columns
        result.rows = [{n: json_value(v) for n, v in zip(names, row, strict=False)} for row in execution.rows]
        result.row_count = len(execution.rows)
        result.truncated = execution.truncated
        result.summary = self._summary(result.row_count, execution.truncated, validated)

        extractor = self._extractor(ctx)
        result.entities, result.graph_nodes = extractor.extract(list(validated.projections), execution.rows)

        view = build_llm_view(
            validated=validated,
            columns=names,
            column_types=execution.column_types,
            rows=execution.rows,
            result_columns=columns,
            snapshot=snapshot,
            truncated=execution.truncated,
            sees_rows=sees_rows,
            max_rows=min(self.settings.SYNTHESIS_MAX_ROWS, validated.row_cap),
        )
        await self._event(run, type="status", stage="answering")
        t = time.perf_counter()
        answer = await self._synthesise(run, validated, view)
        result.timings.synthesis_ms = _ms(t)
        result.answer = answer or self._templated_answer(result.row_count, execution.truncated, validated)
        if not answer:
            result.warnings.append("answer_unavailable")
        if execution.truncated:
            result.warnings.append("truncated")

    async def _synthesise(self, run: _Run, validated: ValidatedSql, view: Any) -> str | None:
        prompt = render.render_synthesis(
            question=run.question,
            sql=validated.sql,
            row_count=view.row_count,
            row_cap=validated.row_cap,
            truncated=view.truncated,
            withheld=view.withheld,
            rows_hidden=view.rows_hidden,
            statistics=view.statistics,
            headers=view.headers,
            rows=view.rows,
            rows_shown=view.rows_shown,
        )
        try:
            on_text = None
            if run.emit is not None:
                async def relay(piece: str) -> None:
                    await self._event(run, type="delta", text=piece)

                on_text = _AnswerStreamer(relay).feed
            response = await self._generate(
                run, prompt, render.ANSWER_SCHEMA, max_tokens=1024, on_text=on_text
            )
            answer = render.parse_answer(response)
            if answer is None:
                logger.warning(
                    "Answer reply unusable (finish_reason=%s, %d chars); retrying once with a larger cap",
                    response.finish_reason,
                    len(response.text),
                )
                response = await self._generate(run, prompt, render.ANSWER_SCHEMA, max_tokens=4096)
                answer = render.parse_answer(response)
        except ProviderError as exc:
            logger.warning(
                "Answer synthesis failed (%s: %s); returning the data with a standard sentence", type(exc).__name__, exc
            )
            return None
        return answer

    # --- model calls --------------------------------------------------------

    async def _generate(
        self, run: _Run, prompt: render.RenderedPrompt, schema: dict[str, Any], *, max_tokens: int = 2048,
        extra_user: str = "", on_text: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        response = await self.llm.generate(
            LLMRequest(
                prompt=prompt.prompt + extra_user,
                system=prompt.system,
                temperature=0.0,
                max_output_tokens=max_tokens,
                timeout_s=self.settings.LLM_TIMEOUT_S,
                json_schema=schema,
                on_text=on_text,
            )
        )
        run.usage = run.usage + Usage(response.usage.input_tokens, response.usage.output_tokens, 1, 0)
        if run.result.trace is not None:
            run.result.trace.setdefault("prompt_chars", 0)
            run.result.trace["prompt_chars"] += len(prompt.prompt) + len(prompt.system)
        return response

    async def _draft(self, run: _Run, prompt: render.RenderedPrompt) -> render.SqlDraft | None:
        """The model's structured SQL answer; one re-ask when it is not in the agreed shape."""
        response = await self._generate(run, prompt, render.SQL_DRAFT_SCHEMA)
        draft = render.parse_draft(response)
        if draft is not None:
            return draft
        reminder = (
            "\n\nYour previous answer was not a JSON object of the required shape. "
            "Answer again with only that JSON object."
        )
        response = await self._generate(run, prompt, render.SQL_DRAFT_SCHEMA, extra_user=reminder)
        return render.parse_draft(response)

    # --- helpers --------------------------------------------------------------

    def _extractor(self, ctx: DatasetContext) -> EntityExtractor:
        key = (ctx.id, ctx.package.content_hash)
        found = self._extractors.get(key)
        if found is None:
            self._extractors = {k: v for k, v in self._extractors.items() if k[0] != ctx.id}
            found = self._extractors[key] = EntityExtractor(ctx.package)
        return found

    @staticmethod
    def _describe_columns(
        snapshot: CatalogSnapshot, validated: ValidatedSql, execution: ExecutionResult
    ) -> list[ResultColumn]:
        out = []
        for i, name in enumerate(execution.columns):
            projection = validated.projections[i] if len(validated.projections) == len(execution.columns) else None
            direct = projection.direct if projection else None
            role = labels = table = column = None
            if direct is not None:
                try:
                    info = snapshot.table(direct.table).column(direct.column)
                    role = info.role
                    labels = dict(info.value_labels) or None
                    table, column = direct.table, direct.column
                except KeyError:
                    pass
            out.append(ResultColumn(name=name, role=role, value_labels=labels, table=table, column=column))
        return out

    @staticmethod
    def _generation_failed_message(snapshot: CatalogSnapshot) -> str:
        scope = snapshot.vocabulary.scope_summary
        about = f" ({scope})" if scope else ""
        return (
            "I wasn't able to turn that into a query. Could you rephrase it or be more specific about "
            f"which records{about} you're asking about?"
        )

    @staticmethod
    def _summary(row_count: int, truncated: bool, validated: ValidatedSql) -> str:
        if row_count == 0:
            return "No matching records found."
        if truncated:
            return f"Showing the first {validated.row_cap} results — there are more."
        if validated.user_limit is not None and row_count >= validated.user_limit:
            return f"Showing top {row_count} results — there may be more."
        return f"{row_count} record{'s' if row_count != 1 else ''} found."

    @staticmethod
    def _templated_answer(row_count: int, truncated: bool, validated: ValidatedSql) -> str:
        if row_count == 0:
            return "I couldn't find any records that match that. Try widening the question a little."
        noun = "record" if row_count == 1 else "records"
        more = f" (the first {validated.row_cap} are shown)" if truncated else ""
        where = "it's" if row_count == 1 else "they're"
        return f"I found {row_count} matching {noun}{more}, and {where} in the table below."

    @staticmethod
    def _execution_problem(category: str, validated: ValidatedSql, snapshot: CatalogSnapshot) -> str:
        used = [t for t in validated.tables if snapshot.has_table(t)][:6]
        listing = "; ".join(
            f"{t}({', '.join(f'{c.name} {c.data_type}' for c in snapshot.table(t).columns)})" for t in used
        )
        text = {
            "syntax": "The database could not parse the query (syntax error).",
            "unknown_column": "The database says a column in the query does not exist.",
            "unknown_table": "The database says a table in the query does not exist.",
            "type": (
                "The database reported a type problem (comparing or combining incompatible types, "
                "an invalid cast, an invalid date or a division by zero)."
            ),
        }.get(category, "The database could not run the query.")
        return f"{text} Columns and types of the tables used: {listing}." if listing else text

    def _note(self, run: _Run, sql: str, outcome: str) -> None:
        if run.attempts is not None:
            run.attempts.append({"sql": sql, "outcome": outcome})

    def _execution_failed(self, run: _Run, category: str, sql: str) -> None:
        text = (
            "The lookup took too long. Try narrowing the question, for example to one item or a shorter period."
            if category == "timeout"
            else "The data lookup didn't run. Rephrasing the question, or narrowing it down, often helps."
        )
        run.result.sql = sql
        self._fail(run, ErrorCode.SQL_EXECUTION_ERROR, text, category=category)

    def _fail(
        self,
        run: _Run,
        code: str,
        message: str,
        suggestions: list[str] | None = None,
        *,
        category: str | None = None,
    ) -> None:
        result = run.result
        result.error_code = code
        result.error_category = category
        result.answer = message
        if suggestions:
            result.suggestions = list(suggestions)

    def _provider_failure(self, run: _Run, exc: ProviderError) -> None:
        logger.warning("Provider failure (%s)", type(exc).__name__)
        if isinstance(exc, NotConfigured):
            self._fail(run, ErrorCode.NOT_CONFIGURED, NOT_CONFIGURED_MESSAGE)
        elif isinstance(exc, RateLimited):
            self._fail(run, ErrorCode.RATE_LIMITED, "The language model is busy right now. Please try again in a moment.")
        elif isinstance(exc, ProviderUnavailable | InvalidRequest):
            self._fail(run, ErrorCode.PROVIDER_UNAVAILABLE, "The language model service isn't responding right now. Please try again in a moment.")
        else:
            self._fail(run, ErrorCode.PROVIDER_UNAVAILABLE, "The language model service isn't responding right now. Please try again in a moment.")

    async def _log(self, ctx: DatasetContext, run: _Run) -> None:
        if self.query_log is None:
            return
        result = run.result
        query_id = await self.query_log.record(
            LogEntry(
                dataset_id=ctx.id,
                question=run.question,
                sql=run.sql,
                validated=run.validated_ok,
                error_code=result.error,
                row_count=result.row_count if run.validated_ok else None,
                latency_ms=result.timings.total_ms,
                prompt_version=render.PROMPT_VERSION,
                model=getattr(self.llm, "model", None) or None,
                tokens=result.usage.total_tokens or None,
            )
        )
        result.query_id = query_id

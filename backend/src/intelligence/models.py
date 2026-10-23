"""Types shared by the Ask pipeline: what goes in, what comes out, and the error codes.

Nothing here knows about a particular dataset or provider.  These are plain
dataclasses so they can be built, compared and serialised without a database or
network.  The HTTP layer (``src/api/chat.py``) turns an :class:`AskResult` into
the ``/api/chat`` response.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Error codes
# ---------------------------------------------------------------------------


class ErrorCode:
    """Stable ``error`` values of ``POST /api/chat``.  Clients may match on these."""

    GUARDRAIL = "guardrail"  # the question is outside the dataset's scope (or hostile)
    NOT_CONFIGURED = "not_configured"  # no language model key on this server
    SQL_GENERATION_FAILED = "sql_generation_failed"  # the model could not write a query
    SQL_REJECTED = "sql_rejected"  # the written query broke a safety rule
    SQL_EXECUTION_ERROR = "sql_execution_error"  # sent as "sql_execution_error: <category>"
    PROVIDER_UNAVAILABLE = "provider_unavailable"  # the model provider failed or timed out
    RATE_LIMITED = "rate_limited"  # too many questions (or the provider throttled us)
    DATASET_NOT_READY = "dataset_not_ready"  # the dataset's tables are not loaded yet
    INTERNAL_ERROR = "internal_error"


# Category suffix of ``sql_execution_error``.  Never raw database text.
ExecutionCategory = Literal["timeout", "syntax", "unknown_column", "unknown_table", "type", "other"]
# Why the guard or the database refused a query; all but ``policy`` can be repaired by the model.
RejectCategory = Literal["syntax", "unknown_column", "unknown_table", "type", "policy"]

AiMode = Literal["full", "degraded", "disabled"]


# ---------------------------------------------------------------------------
# Usage and timings
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Usage:
    """Provider usage of one request (summed over its calls)."""

    input_tokens: int = 0
    output_tokens: int = 0
    llm_calls: int = 0
    embed_calls: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.llm_calls + other.llm_calls,
            self.embed_calls + other.embed_calls,
        )

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class Timings:
    """Milliseconds spent per stage."""

    guardrails_ms: int = 0
    retrieval_ms: int = 0
    generation_ms: int = 0
    validation_ms: int = 0
    execution_ms: int = 0
    synthesis_ms: int = 0
    total_ms: int = 0

    def as_dict(self) -> dict[str, int]:
        return dict(self.__dict__)


# ---------------------------------------------------------------------------
# SQL validation and execution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SourceColumn:
    """A base-table column a result column is read from.

    ``instance`` tells apart two uses of the same table in one query (a self
    join), so two columns are only combined into one composite id when they come
    from the same row of the same table instance.
    """

    instance: str
    table: str
    column: str


@dataclass(frozen=True)
class Projection:
    """One output column of a validated query and where its values come from."""

    name: str
    # Every base column the expression reads.
    sources: tuple[SourceColumn, ...] = ()
    # Set when the output is a plain (possibly cast) copy of one base column.
    direct: SourceColumn | None = None
    # An aggregate or window expression: it summarises rows rather than showing them.
    aggregate: bool = False
    # The expression is a literal or has no column inputs.
    constant: bool = False
    # Lower-case name of the outermost aggregate function (``count``, ``sum``, ``max`` ...), if any.
    agg: str | None = None
    # Lower-case names of every column the expression mentions, however they resolved.  A second,
    # name-based view of the inputs, so masking does not depend on lineage being exact.
    names: tuple[str, ...] = ()

    @property
    def reveals_input(self) -> bool:
        """False when the output cannot show a stored value (a constant or a plain count)."""
        return not (self.constant or self.agg == "count")


@dataclass(frozen=True)
class ValidatedSql:
    """A query that passed every safety rule, rewritten to what will actually run."""

    sql: str
    original: str
    tables: tuple[str, ...]
    projections: tuple[Projection, ...]
    # Rows returned to the caller at most; the query itself fetches ``row_cap + 1`` to detect more.
    row_cap: int
    # LIMIT of the executed statement.
    fetch_limit: int
    # LIMIT written by the model, when there was a usable one.
    user_limit: int | None = None
    # No GROUP BY and every output is an aggregate: the result is a summary, not records.
    aggregate_only: bool = False


@dataclass(frozen=True)
class SqlRejected:
    """A query the guard refused.  ``message`` is safe to show to a model and to log."""

    code: str
    message: str
    category: RejectCategory = "policy"

    @property
    def repairable(self) -> bool:
        return self.category != "policy"


@dataclass(frozen=True)
class ExecutionResult:
    columns: tuple[str, ...]
    # Postgres type name per column (``int4``, ``numeric``, ``text`` ...).
    column_types: tuple[str, ...]
    rows: list[tuple[Any, ...]]
    # More rows existed than the row cap.
    truncated: bool = False
    elapsed_ms: int = 0


class ExecutionError(Exception):
    """A query failed in the database.  ``category`` is safe to expose; the message is not."""

    def __init__(self, category: ExecutionCategory, detail: str = "", *, not_ready: bool = False):
        super().__init__(detail or category)
        self.category: ExecutionCategory = category
        self.detail = detail  # raw text for the log only
        self.not_ready = not_ready  # the dataset's tables do not exist yet

    @property
    def repairable(self) -> bool:
        return self.category in ("syntax", "unknown_column", "unknown_table", "type") and not self.not_ready


# ---------------------------------------------------------------------------
# The answer
# ---------------------------------------------------------------------------


@dataclass
class ResultColumn:
    """Description of one result column for display."""

    name: str
    label: str | None = None
    role: str | None = None
    # code -> label, when the column holds coded values.
    value_labels: dict[str, str] | None = None
    # Base table and column when the output is a plain copy of one.
    table: str | None = None
    column: str | None = None


@dataclass
class EntityRef:
    """A record in the result that exists in the graph.  ``id`` is ``<NodeType>:<id>``."""

    id: str
    type: str
    value: str


@dataclass
class GraphNodeRef:
    id: str
    type: str
    label: str


@dataclass
class AskResult:
    answer: str
    sql: str | None = None
    rows: list[dict[str, Any]] | None = None
    columns: list[ResultColumn] = field(default_factory=list)
    entities: list[EntityRef] = field(default_factory=list)
    graph_nodes: list[GraphNodeRef] = field(default_factory=list)
    error_code: str | None = None
    # Suffix for ``sql_execution_error`` (timeout, syntax, ...).
    error_category: str | None = None
    row_count: int = 0
    truncated: bool = False
    summary: str = ""
    assumptions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Suggested questions, set when the question could not be answered.
    suggestions: list[str] = field(default_factory=list)
    query_id: str | None = None
    mode: AiMode = "disabled"
    timings: Timings = field(default_factory=Timings)
    usage: Usage = field(default_factory=Usage)
    # Debug and evaluation detail (retrieved tables, attempts); only set when asked for.
    trace: dict[str, Any] | None = None

    @property
    def error(self) -> str | None:
        """The value of the ``error`` field of ``/api/chat``."""
        if self.error_code == ErrorCode.SQL_EXECUTION_ERROR and self.error_category:
            return f"{self.error_code}: {self.error_category}"
        return self.error_code

    @property
    def ok(self) -> bool:
        return self.error_code is None

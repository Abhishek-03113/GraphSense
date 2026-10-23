"""What a language model may see of a query result.

Two rules, applied before *every* call to a provider:

1. **Sensitive columns never go to the provider.**  A result column that reads a column
   marked ``sensitive`` in the package is dropped from the rows used to write the answer.
   Masking uses the lineage of the query (which base columns an output reads) and,
   as a second net, the names of the columns the expression mentions.  A plain ``COUNT``
   cannot reveal a stored value and is allowed.
2. **``llm_sees_rows = false``** (a per-dataset switch): no row values at all.  The model
   gets the shape of the result (row count, column names) and aggregate statistics of
   numeric and date columns, and a single-row result made only of aggregates.

The rows shown to the user are not affected; only what leaves for the provider is.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from src.catalog import CatalogSnapshot
from src.intelligence.catalog_access import sensitive_columns
from src.intelligence.models import Projection, ResultColumn, ValidatedSql
from src.utils.serialization import json_value

_NUMERIC_TYPES = {"int2", "int4", "int8", "numeric", "float4", "float8", "money"}
_TEMPORAL_TYPES = {"date", "timestamp", "timestamptz", "time", "timetz"}
# Aggregates whose result is a statistic rather than one of the stored values.
_SUMMARY_AGGS = {"count", "sum", "avg", "stddev", "stddevpop", "stddevsamp", "variance", "var", "varpop", "varsamp"}
_ID_LIKE_ROLES = {"id", "item_number", "reference", "code", "name", "text"}


def masked_columns(
    validated: ValidatedSql,
    columns: Sequence[str],
    snapshot: CatalogSnapshot,
) -> frozenset[int]:
    """Indexes of result columns that read a sensitive column and so must not leave the server."""
    sensitive = sensitive_columns(snapshot)
    if not sensitive:
        return frozenset()
    projections = validated.projections
    if len(projections) != len(columns):
        # The query's shape is not what we analysed (schema drift): hide everything we cannot vouch for.
        return frozenset(range(len(columns)))
    sensitive_names = {c for (t, c) in sensitive if t in set(validated.tables)}
    masked = set()
    for i, p in enumerate(projections):
        if not p.reveals_input:
            continue
        if any((s.table, s.column) in sensitive for s in p.sources) or p.direct is not None and (p.direct.table, p.direct.column) in sensitive or sensitive_names and any(n in sensitive_names for n in p.names):
            masked.add(i)
    return frozenset(masked)


def _label(value: Any, labels: dict[str, str] | None) -> str:
    text = str(json_value(value))
    if labels and text in labels:
        return f"{labels[text]} ({text})"
    return text


@dataclass
class LlmResultView:
    """The result as the model will be shown it."""

    row_count: int
    truncated: bool
    # Columns withheld because they hold sensitive data.
    withheld: list[str] = field(default_factory=list)
    # Row values as text, one list per row; empty when the dataset forbids row values.
    headers: list[str] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    # Aggregate statistics per column when rows are not shown.
    statistics: list[str] = field(default_factory=list)
    rows_hidden: bool = False
    rows_shown: int = 0


def build_llm_view(
    *,
    validated: ValidatedSql,
    columns: Sequence[str],
    column_types: Sequence[str],
    rows: Sequence[Sequence[Any]],
    result_columns: Sequence[ResultColumn],
    snapshot: CatalogSnapshot,
    truncated: bool,
    sees_rows: bool,
    max_rows: int,
) -> LlmResultView:
    masked = masked_columns(validated, columns, snapshot)
    visible = [i for i in range(len(columns)) if i not in masked]
    view = LlmResultView(
        row_count=len(rows),
        truncated=truncated,
        withheld=[columns[i] for i in sorted(masked)],
        headers=[columns[i] for i in visible],
    )
    if not visible:
        view.rows_hidden = True
        return view

    if sees_rows or _only_summaries(validated, visible, snapshot):
        # Rows (or a one-row summary) may be shown.
        for row in rows[:max_rows]:
            view.rows.append(
                [_label(row[i], result_columns[i].value_labels if i < len(result_columns) else None) for i in visible]
            )
        view.rows_shown = len(view.rows)
        return view

    view.rows_hidden = True
    for i in visible:
        stat = _column_statistic(
            columns[i],
            column_types[i] if i < len(column_types) else "",
            [r[i] for r in rows],
            validated.projections[i] if i < len(validated.projections) else None,
            snapshot,
        )
        if stat:
            view.statistics.append(stat)
    return view


def _source_type(p: Projection, snapshot: CatalogSnapshot) -> str:
    for s in p.sources[:1]:
        try:
            return snapshot.table(s.table).column(s.column).data_type
        except KeyError:
            return ""
    return ""


def _only_summaries(validated: ValidatedSql, visible: list[int], snapshot: CatalogSnapshot) -> bool:
    """A single row made only of statistics (counts, sums, averages, min/max of numbers or dates)."""
    if not validated.aggregate_only:
        return False
    for i in visible:
        if i >= len(validated.projections):
            return False
        p = validated.projections[i]
        if p.constant:
            continue
        if p.agg in _SUMMARY_AGGS:
            continue
        if p.agg in ("min", "max"):
            kind = _source_type(p, snapshot)
            if kind.startswith(("decimal", "integer", "bigint", "date", "timestamp", "time")):
                continue
        return False
    return True


def _column_statistic(
    name: str, pg_type: str, values: list[Any], projection: Projection | None, snapshot: CatalogSnapshot
) -> str:
    present = [v for v in values if v is not None]
    # A column that copies identifying data (ids, codes, names) says nothing in aggregate.
    if projection is not None and projection.direct is not None:
        try:
            role = snapshot.table(projection.direct.table).column(projection.direct.column).role
        except KeyError:
            role = None
        if role in _ID_LIKE_ROLES:
            return f"{name}: {len({str(v) for v in present})} distinct values, {len(values) - len(present)} empty"
    if pg_type in _NUMERIC_TYPES and present:
        numbers = [Decimal(str(v)) for v in present]
        total = sum(numbers, Decimal(0))
        return (
            f"{name}: numeric, min {_fmt(min(numbers))}, max {_fmt(max(numbers))}, "
            f"sum {_fmt(total)}, average {_fmt(total / len(numbers))}, {len(present)} values"
        )
    if pg_type in _TEMPORAL_TYPES and present:
        low, high = min(present), max(present)
        return f"{name}: from {_iso(low)} to {_iso(high)}, {len(present)} values"
    if pg_type == "bool" and present:
        return f"{name}: {sum(1 for v in present if v)} true, {sum(1 for v in present if not v)} false"
    return f"{name}: {len({str(v) for v in present})} distinct values, {len(values) - len(present)} empty"


def _fmt(value: Decimal) -> str:
    rounded = round(value, 4)
    text = f"{rounded:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def _iso(value: Any) -> str:
    return value.isoformat() if isinstance(value, dt.date | dt.datetime | dt.time) else str(value)

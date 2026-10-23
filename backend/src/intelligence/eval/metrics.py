"""The measurements of an evaluation run, as small pure functions.

None of these touches a database, a model or a dataset by name, so every one of them is
unit-tested on its own (``tests/test_eval_metrics.py``).
"""

from __future__ import annotations

import math
import re
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

# ---------------------------------------------------------------------------
# Rates and percentiles
# ---------------------------------------------------------------------------


def rate(flags: Iterable[bool | None]) -> float | None:
    """Share of ``True`` among the flags that are not ``None``; ``None`` when there are none."""
    counted = [f for f in flags if f is not None]
    if not counted:
        return None
    return sum(1 for f in counted if f) / len(counted)


def mean(values: Iterable[float | None]) -> float | None:
    counted = [v for v in values if v is not None]
    if not counted:
        return None
    return sum(counted) / len(counted)


def percentile(values: Sequence[float], q: float) -> float | None:
    """The ``q`` quantile (0..1) by the nearest-rank method; ``None`` for no values."""
    if not values:
        return None
    if not 0.0 <= q <= 1.0:
        raise ValueError("q must be between 0 and 1")
    ordered = sorted(values)
    rank = max(1, math.ceil(q * len(ordered)))
    return float(ordered[rank - 1])


def round_or_none(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------


def tables_in_sql(sql: str, known: Collection[str]) -> set[str]:
    """The base tables a query reads (names in ``known`` only; common table expressions excluded)."""
    try:
        tree = sqlglot.parse_one(sql, read="postgres")
    except SqlglotError:
        return set()
    if tree is None:
        return set()
    ctes = {cte.alias for cte in tree.find_all(exp.CTE)}
    found = {t.name for t in tree.find_all(exp.Table) if isinstance(t.this, exp.Identifier)}
    return {name for name in found if name in known and name not in ctes}


def recall(expected: Collection[str], retrieved: Collection[str]) -> float | None:
    """Share of ``expected`` that is in ``retrieved``; ``None`` when nothing was expected."""
    if not expected:
        return None
    return len(set(expected) & set(retrieved)) / len(set(expected))


@dataclass(frozen=True)
class ExampleHit:
    """Whether a retrieved few-shot example is useful for a question."""

    relevant: int  # few-shot examples in the package that share a table with the reference query
    retrieved_relevant: int  # of those, how many were retrieved
    hit: bool | None  # at least one relevant example came back; None when none exist


def example_hit(
    expected_tables: Collection[str],
    retrieved_ids: Collection[str],
    example_tables: dict[str, set[str]],
) -> ExampleHit:
    """Few-shot examples count as relevant when they query a table the reference query also reads.

    ``example_tables`` maps each few-shot example id to the tables its SQL reads.
    """
    wanted = set(expected_tables)
    relevant = {eid for eid, tables in example_tables.items() if tables & wanted}
    if not relevant:
        return ExampleHit(0, 0, None)
    got = relevant & set(retrieved_ids)
    return ExampleHit(len(relevant), len(got), bool(got))


# ---------------------------------------------------------------------------
# Expectations declared next to a reference query
# ---------------------------------------------------------------------------


class _Expect(Protocol):
    min_rows: int | None
    max_rows: int | None
    columns_include: Sequence[str]


def expectation_problems(expect: _Expect | None, columns: Sequence[str], row_count: int) -> list[str]:
    """What is wrong with a reference result compared with its ``expect`` block (empty when fine)."""
    if expect is None:
        return []
    problems: list[str] = []
    if expect.min_rows is not None and row_count < expect.min_rows:
        problems.append(f"{row_count} rows, expected at least {expect.min_rows}")
    if expect.max_rows is not None and row_count > expect.max_rows:
        problems.append(f"{row_count} rows, expected at most {expect.max_rows}")
    present = {c.lower() for c in columns}
    missing = [c for c in expect.columns_include if c.lower() not in present]
    if missing:
        problems.append(f"missing column(s) {missing}")
    return problems


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


class _Entity(Protocol):
    id: str
    type: str
    value: str


def entity_problems(
    entities: Sequence[_Entity],
    node_types: Collection[str],
    known_ids: dict[str, Collection[str]] | None = None,
) -> list[str]:
    """Why an extracted entity is not a valid graph record (one message per bad entity).

    Valid means: a registered node type, an id written ``<type>:<value>``, a value that is not
    empty, and (when ``known_ids`` is given) a record the graph really has.
    """
    problems: list[str] = []
    for entity in entities:
        if entity.type not in node_types:
            problems.append(f"{entity.id}: unknown node type {entity.type!r}")
        elif not entity.value or not entity.value.strip():
            problems.append(f"{entity.id}: empty value")
        elif entity.id != f"{entity.type}:{entity.value}":
            problems.append(f"{entity.id}: id does not match type and value")
        elif known_ids is not None and entity.value not in known_ids.get(entity.type, ()):
            problems.append(f"{entity.id}: no such record in the graph")
    return problems


# ---------------------------------------------------------------------------
# Leakage: golden questions must never be retrievable
# ---------------------------------------------------------------------------

_PUNCT = re.compile(r"[^a-z0-9]+")


def squash(text: str) -> str:
    """Lower-case words joined by single spaces (punctuation and case do not matter)."""
    return _PUNCT.sub(" ", text.lower()).strip()


@dataclass(frozen=True)
class Leak:
    example_id: str
    source: str  # where it was found, for example "knowledge item example:foo"
    what: str  # "question" | "sql" | "id"


@dataclass
class LeakReport:
    checked: int = 0
    leaks: list[Leak] = field(default_factory=list)

    @property
    def clean(self) -> bool:
        return not self.leaks

    def as_dict(self) -> dict[str, Any]:
        return {
            "checked_texts": self.checked,
            "leaks": [{"example": leak.example_id, "source": leak.source, "what": leak.what} for leak in self.leaks],
        }


class _Golden(Protocol):
    id: str
    question: str
    sql: str


def find_id_leaks(goldens: Sequence[_Golden], refs: Iterable[tuple[str, str]]) -> list[Leak]:
    """Golden ids that appear as the reference of a knowledge item or a retrieval hit.

    ``refs`` are pairs of ``(source, ref)``.
    """
    ids = {g.id for g in goldens}
    return [Leak(ref, source, "id") for source, ref in refs if ref in ids]


def find_leaks(goldens: Sequence[_Golden], texts: Iterable[tuple[str, str]]) -> LeakReport:
    """Golden questions, reference queries or ids that appear in ``texts`` (pairs of ``(source, text)``).

    A question leaks when its words appear, in order, inside an item.  A reference query leaks
    when its normalised text appears.  Comparison ignores case, punctuation and spacing.
    """
    report = LeakReport()
    questions = {g.id: squash(g.question) for g in goldens}
    queries = {g.id: squash(g.sql) for g in goldens}
    for source, text in texts:
        report.checked += 1
        flat = squash(text)
        for example_id, question in questions.items():
            if question and question in flat:
                report.leaks.append(Leak(example_id, source, "question"))
            elif queries[example_id] and queries[example_id] in flat:
                report.leaks.append(Leak(example_id, source, "sql"))
    return report

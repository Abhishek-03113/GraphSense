"""The retrievable knowledge of a dataset: what the Ask layer searches before writing SQL.

Items are derived from a catalog snapshot (the package, plus profile statistics when
the live catalog is available).  They are always built from the *language-model-safe*
view of the snapshot, so a column marked ``sensitive`` contributes its name and
description but never a value (no sample, no top value, no label, no range).

``golden`` examples are evaluation material and are never turned into items.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Literal

from src.catalog import CatalogSnapshot
from src.catalog.model import ColumnInfo, TableInfo
from src.intelligence.catalog_access import llm_safe

Kind = Literal["table", "relationship", "glossary", "example", "profile", "value_set"]
KINDS: tuple[Kind, ...] = ("table", "relationship", "glossary", "example", "profile", "value_set")

MAX_LABELLED_VALUES = 40
MAX_TOP_VALUES = 8


@dataclass(frozen=True)
class KnowledgeItem:
    kind: Kind
    ref: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        """Identity of the content: changes when the kind, reference or text changes."""
        payload = f"{self.kind}\x00{self.ref}\x00{self.text}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _percent(rate: float) -> str:
    return f"{rate * 100:.0f}%"


def column_line(col: ColumnInfo) -> str:
    """One line describing a column, as shown to the model."""
    parts = [f"{col.name} {col.data_type}"]
    flags = []
    if col.is_pk:
        flags.append("primary key")
    if col.role:
        flags.append(col.role)
    if col.refs:
        flags.append(f"references {col.refs}")
    if flags:
        parts.append(f"({', '.join(flags)})")
    line = " ".join(parts)
    if col.description:
        line += f": {col.description}"
    if col.currency_column:
        line += f" Currency in {col.currency_column}."
    if col.normalize:
        line += " Stored normalised."
    labels = _label_text(col)
    if labels:
        line += f" Values: {labels}."
    return line


def _label_text(col: ColumnInfo) -> str:
    """Coded values with their meaning; empty for sensitive columns (their labels were cleared)."""
    if col.value_labels:
        pairs = list(col.value_labels.items())[:MAX_LABELLED_VALUES]
        return ", ".join(f"{code} = {label}" for code, label in pairs)
    if col.top_values:
        shown = col.top_values[:MAX_TOP_VALUES]
        return ", ".join(f"{v.value} = {v.label}" if v.label else v.value for v in shown)
    return ""


def table_text(table: TableInfo) -> str:
    head = f"Table {table.name}"
    if table.description:
        head += f": {table.description}"
    lines = [head]
    if table.grain:
        lines.append(f"One row per {table.grain}.")
    if table.primary_key:
        lines.append(f"Primary key: {', '.join(table.primary_key)}.")
    lines.append("Columns:")
    lines.extend(f"- {column_line(c)}" for c in table.columns if not c.hidden)
    return "\n".join(lines)


def profile_text(table: TableInfo) -> str | None:
    """Data profile of a table, from live statistics.  ``None`` when there are none."""
    notes = []
    for col in table.columns:
        if col.hidden or col.sensitive:
            continue
        bits = []
        if col.null_rate is not None and col.null_rate > 0.0:
            bits.append(f"{_percent(col.null_rate)} empty")
        if col.distinct_count is not None:
            bits.append(f"{col.distinct_count} distinct")
        if col.min_value is not None and col.max_value is not None and col.min_value != col.max_value:
            bits.append(f"from {col.min_value} to {col.max_value}")
        top = _label_text(col) if col.top_values and not col.value_labels else ""
        if top:
            bits.append(f"common: {top}")
        if bits:
            notes.append(f"- {col.name}: {', '.join(bits)}")
    if table.row_count is None and not notes:
        return None
    head = f"Profile of {table.name}"
    if table.row_count is not None:
        head += f": {table.row_count} rows"
    return "\n".join([head, *notes])


def build_items(snapshot: CatalogSnapshot) -> list[KnowledgeItem]:
    """Every item for ``snapshot``, deterministic and without duplicates."""
    safe = llm_safe(snapshot)
    items: list[KnowledgeItem] = []

    for table in safe.tables:
        items.append(
            KnowledgeItem("table", table.name, table_text(table), {"tables": [table.name]})
        )
        profile = profile_text(table)
        if profile:
            items.append(KnowledgeItem("profile", table.name, profile, {"tables": [table.name]}))

    for rel in safe.relationships:
        ref = f"{rel.from_table}({','.join(rel.from_columns)})->{rel.to_table}({','.join(rel.to_columns)})"
        text = f"{rel.from_table} joins {rel.to_table} on {rel.expression}."
        if rel.cardinality:
            text += f" Cardinality {rel.cardinality.replace('_', ' ')}."
        if rel.description:
            text += f" {rel.description}"
        if rel.match_rate is not None:
            text += f" {_percent(rel.match_rate)} of {rel.from_table} rows find a match."
        items.append(KnowledgeItem("relationship", ref, text, {"tables": [rel.from_table, rel.to_table]}))

    for entry in safe.glossary:
        items.append(
            KnowledgeItem("glossary", entry.id, f"{entry.title}. {entry.text}", {"tables": list(entry.tables)})
        )

    # Few-shot examples only: the question is searched, the query rides along as metadata.
    for example in safe.few_shot_examples():
        items.append(KnowledgeItem("example", example.id, example.question, {"sql": example.sql}))

    seen_sets: set[str] = set()
    for table in safe.tables:
        for col in table.columns:
            if col.value_set and col.value_labels and col.value_set not in seen_sets:
                seen_sets.add(col.value_set)
                pairs = "; ".join(f"{code} = {label}" for code, label in col.value_labels.items())
                items.append(
                    KnowledgeItem(
                        "value_set",
                        col.value_set,
                        f"Coded values of {table.name}.{col.name}: {pairs}.",
                        {"tables": [table.name]},
                    )
                )

    unique: dict[tuple[str, str], KnowledgeItem] = {}
    for item in items:
        unique.setdefault((item.kind, item.ref), item)
    return list(unique.values())

"""Turn ranked knowledge hits into the context shown to the model, within a size budget.

The tables chosen are the best-ranked ones plus the tables that connect them (shortest
join path over the relationships), so a question that spans several tables gets the link
table too.  The context is built from the language-model-safe view of the snapshot.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field

from src.catalog import CatalogSnapshot
from src.catalog.model import TableInfo
from src.intelligence.knowledge.items import table_text
from src.intelligence.knowledge.store import Hit
from src.intelligence.text import clip

MAX_TABLES = 10
SEED_TABLES = 6
MAX_EXAMPLES = 3
MAX_GLOSSARY = 5
PATH_ANCHORS = 4
MAX_PATH_LENGTH = 4


@dataclass
class ContextBundle:
    tables: list[str] = field(default_factory=list)  # rendered table descriptions
    table_names: list[str] = field(default_factory=list)
    relationships: list[str] = field(default_factory=list)
    glossary: list[str] = field(default_factory=list)
    examples: list[dict[str, str]] = field(default_factory=list)
    example_ids: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    dropped_for_budget: int = 0

    @property
    def size(self) -> int:
        return (
            sum(len(t) for t in self.tables)
            + sum(len(r) for r in self.relationships)
            + sum(len(g) for g in self.glossary)
            + sum(len(e["question"]) + len(e["sql"]) for e in self.examples)
        )


def _tables_in_sql(sql: str, names: list[str]) -> list[str]:
    return [n for n in names if re.search(rf"\b{re.escape(n)}\b", sql, flags=re.IGNORECASE)]


def _adjacency(snapshot: CatalogSnapshot) -> dict[str, set[str]]:
    graph: dict[str, set[str]] = {t.name: set() for t in snapshot.tables}
    for rel in snapshot.relationships:
        if rel.from_table in graph and rel.to_table in graph:
            graph[rel.from_table].add(rel.to_table)
            graph[rel.to_table].add(rel.from_table)
    return graph


def shortest_path(graph: dict[str, set[str]], start: str, goal: str, max_length: int = MAX_PATH_LENGTH) -> list[str]:
    """Tables on a shortest join path from ``start`` to ``goal`` (inclusive), or ``[]``."""
    if start == goal:
        return [start]
    queue: deque[list[str]] = deque([[start]])
    seen = {start}
    while queue:
        path = queue.popleft()
        if len(path) > max_length:
            continue
        for neighbour in sorted(graph.get(path[-1], ())):
            if neighbour in seen:
                continue
            if neighbour == goal:
                return [*path, neighbour]
            seen.add(neighbour)
            queue.append([*path, neighbour])
    return []


def rank_tables(snapshot: CatalogSnapshot, hits: list[tuple[Hit, float]]) -> list[str]:
    """Tables ordered by the evidence in the hits (a table item counts most)."""
    names = [t.name for t in snapshot.tables]
    scores: dict[str, float] = {}
    sql_by_example = {e.id: e.sql for e in snapshot.few_shot_examples()}
    for hit, score in hits:
        if hit.kind == "table":
            mentioned = [hit.ref] if hit.ref in names else []
            weight = 1.0
        elif hit.kind == "example":
            mentioned = _tables_in_sql(sql_by_example.get(hit.ref, str(hit.metadata.get("sql", ""))), names)
            weight = 0.5
        else:
            mentioned = [t for t in hit.metadata.get("tables", []) if t in names]
            weight = 0.6
        for table in mentioned:
            scores[table] = scores.get(table, 0.0) + score * weight
    return sorted(scores, key=lambda t: (-scores[t], t))


def select_tables(snapshot: CatalogSnapshot, ranked: list[str]) -> list[str]:
    """Top tables, then the tables that join them, up to ``MAX_TABLES``."""
    names = [t.name for t in snapshot.tables]
    if not ranked:
        return names[:MAX_TABLES]
    chosen = list(ranked[:SEED_TABLES])
    graph = _adjacency(snapshot)
    anchors = ranked[:PATH_ANCHORS]
    for i, a in enumerate(anchors):
        for b in anchors[i + 1 :]:
            for table in shortest_path(graph, a, b):
                if table not in chosen and len(chosen) < MAX_TABLES:
                    chosen.append(table)
    return chosen[:MAX_TABLES]


def _compact(table: TableInfo) -> str:
    """A shorter description for tables that do not fit in full: names and types only."""
    cols = ", ".join(f"{c.name} {c.data_type}" for c in table.columns if not c.hidden)
    return f"Table {table.name}: {clip(table.description, 120)}\nColumns: {cols}"


def assemble_context(
    snapshot: CatalogSnapshot,
    hits: list[tuple[Hit, float]],
    *,
    budget_chars: int,
) -> ContextBundle:
    """Context for the SQL prompt.  ``snapshot`` must be the language-model-safe view."""
    bundle = ContextBundle(hints=list(snapshot.hints))
    selected = select_tables(snapshot, rank_tables(snapshot, hits))
    used = 0

    for name in selected:
        table = snapshot.table(name)
        rendered = table_text(table)
        if used + len(rendered) > budget_chars * 0.7:
            rendered = _compact(table)
        if used + len(rendered) > budget_chars * 0.85:
            bundle.dropped_for_budget += 1
            continue
        bundle.tables.append(rendered)
        bundle.table_names.append(name)
        used += len(rendered)

    chosen = set(bundle.table_names)
    for rel in snapshot.relationships:
        if rel.from_table in chosen and rel.to_table in chosen:
            line = f"{rel.from_table} -> {rel.to_table}: {rel.expression}"
            if rel.cardinality:
                line += f" ({rel.cardinality.replace('_', ' ')})"
            if rel.description:
                line += f". {rel.description}"
            if used + len(line) <= budget_chars:
                bundle.relationships.append(line)
                used += len(line)

    examples = {e.id: e for e in snapshot.few_shot_examples()}
    glossary = {g.id: g for g in snapshot.glossary}
    for hit, _ in hits:
        if hit.kind == "example" and hit.ref in examples and len(bundle.examples) < MAX_EXAMPLES:
            ex = examples[hit.ref]
            if used + len(ex.sql) + len(ex.question) <= budget_chars:
                bundle.examples.append({"question": ex.question, "sql": ex.sql.strip()})
                bundle.example_ids.append(ex.id)
                used += len(ex.sql) + len(ex.question)
        elif hit.kind == "glossary" and hit.ref in glossary and len(bundle.glossary) < MAX_GLOSSARY:
            entry = glossary[hit.ref]
            line = f"{entry.title}: {entry.text}"
            if used + len(line) <= budget_chars:
                bundle.glossary.append(line)
                used += len(line)
    # Generated notes about normalised columns apply to every selected table.
    for entry in snapshot.glossary:
        if "generated" in entry.tags and set(entry.tables) & chosen:
            line = f"{entry.title}: {entry.text}"
            if line not in bundle.glossary and used + len(line) <= budget_chars:
                bundle.glossary.append(line)
                used += len(line)
    return bundle

"""The joins a dataset package implies.

Three sources, strongest first:

1. ``declared`` - ``semantics/relationships.yaml``.
2. ``declared`` - a column's ``refs: table.column`` (single-column joins).
3. ``graph_edge`` - derived from the graph's edge definitions.

A weaker source is dropped when a stronger one already joins the same pair of
tables from the same columns, so an author can override what the graph
implies (for example when the graph keys on a different but equal column).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.datasets.models import DatasetPackage

JoinKind = Literal["declared", "graph_edge"]


@dataclass(frozen=True)
class Join:
    from_table: str
    from_columns: tuple[str, ...]
    to_table: str
    to_columns: tuple[str, ...]
    kind: JoinKind
    cardinality: str | None = None
    description: str = ""

    @property
    def expression(self) -> str:
        return " AND ".join(
            f"{self.from_table}.{a} = {self.to_table}.{b}"
            for a, b in zip(self.from_columns, self.to_columns, strict=True)
        )

    @property
    def identity(self) -> tuple[str, tuple[str, ...], str, tuple[str, ...]]:
        return (self.from_table, self.from_columns, self.to_table, self.to_columns)


def declared_joins(pkg: DatasetPackage) -> list[Join]:
    joins = [
        Join(r.from_table, r.from_columns, r.to_table, r.to_columns, "declared", r.cardinality, r.description)
        for r in pkg.semantics.relationships
    ]
    for table in pkg.tables:
        for col in table.columns:
            if not col.refs:
                continue
            to_table, to_col = col.refs.split(".")
            target_pk = pkg.table(to_table).primary_key if pkg.has_table(to_table) else ()
            joins.append(
                Join(
                    table.table,
                    (col.name,),
                    to_table,
                    (to_col,),
                    "declared",
                    "many_to_one" if target_pk == (to_col,) else None,
                    f"{table.table}.{col.name} refers to {to_table}.{to_col}.",
                )
            )
    return joins


def graph_edge_joins(pkg: DatasetPackage) -> list[Join]:
    """Joins implied by edge definitions whose table is one of the two node tables."""
    nodes = {n.key: n for n in pkg.graph.node_types}
    joins: list[Join] = []
    for edge in pkg.graph.edge_types:
        source, target = nodes.get(edge.source), nodes.get(edge.target)
        if source is None or target is None:
            continue
        label = f"Graph edge {edge.key}: {edge.description}"
        if edge.table == target.table and edge.table != source.table:
            joins.append(
                Join(edge.table, edge.source_columns, source.table, source.id_columns, "graph_edge", "many_to_one", label)
            )
        elif edge.table == source.table and edge.table != target.table:
            joins.append(
                Join(edge.table, edge.target_columns, target.table, target.id_columns, "graph_edge", "many_to_one", label)
            )
    return joins


def package_relationships(pkg: DatasetPackage) -> list[Join]:
    """All joins, deduplicated; definition order is kept (declared first, then graph edges)."""
    result: list[Join] = []
    seen: set[tuple] = set()
    strong: set[tuple[str, tuple[str, ...], str]] = set()
    for join in declared_joins(pkg):
        if join.identity in seen:
            continue
        seen.add(join.identity)
        strong.add((join.from_table, join.from_columns, join.to_table))
        result.append(join)
    for join in graph_edge_joins(pkg):
        if join.identity in seen or (join.from_table, join.from_columns, join.to_table) in strong:
            continue
        seen.add(join.identity)
        result.append(join)
    return result

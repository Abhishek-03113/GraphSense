"""Which graph records appear in a query result?

A deterministic replacement for asking the language model to list entities.
The mapping from a database column to a node type comes from the dataset's graph
definition, so the ids produced here are exactly the ids the graph API serves:

* a column that is the single id column of a node type (``books.isbn`` -> Book);
* an endpoint column of an edge (``loans.member_id`` is the Member side of BORROWED);
* a column named by ``entity_refs`` in the package;
* a composite id (document + item): when both columns come from the same row of
  the same table, the id is ``<doc>-<item without leading zeros>`` as in the graph SQL;
* as a last resort, for an expression that is neither an aggregate nor a constant, the
  package's ``entity_column_hints`` (column-name substrings).

Lineage (``sql/lineage.py``) says which base column an output column copies, so an
alias such as ``AS book_id`` does not matter and ``COUNT(*) AS book_count`` is never mistaken for a book.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

from src.datasets.models import DatasetPackage
from src.intelligence.models import EntityRef, GraphNodeRef, Projection
from src.utils.serialization import json_value

_LEADING_ZEROS = re.compile(r"^0+")


def graph_item_number(value: str) -> str:
    """The item part of a composite id, exactly as the graph SQL writes it (``norm()`` there)."""
    return _LEADING_ZEROS.sub("", value)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    converted = json_value(value)
    text = str(converted).strip()
    return text or None


class EntityExtractor:
    """Built once per package; thread-safe (read-only after construction)."""

    def __init__(self, package: DatasetPackage) -> None:
        dataset = package.graph_dataset()
        self._single: dict[tuple[str, str], str] = {}
        self._composite: dict[tuple[str, str, str], str] = {}
        self._hints = dataset.entity_column_hints

        def put_single(table: str, column: str, node_type: str) -> None:
            self._single.setdefault((table, column), node_type)

        # Priority: a node's own id column, then explicit references, then edge endpoints.
        for node in dataset.node_types:
            if len(node.id_columns) == 1:
                put_single(node.table, node.id_columns[0], node.key)
            else:
                self._composite.setdefault((node.table, node.id_columns[0], node.id_columns[1]), node.key)
        for ref in dataset.entity_refs:
            put_single(ref.table, ref.column, ref.node_type)
        for edge in dataset.edge_types:
            for columns, node_type in ((edge.source_columns, edge.source), (edge.target_columns, edge.target)):
                if len(columns) == 1:
                    put_single(edge.table, columns[0], node_type)
                else:
                    self._composite.setdefault((edge.table, columns[0], columns[1]), node_type)

    @property
    def node_types(self) -> frozenset[str]:
        return frozenset(self._single.values()) | frozenset(self._composite.values())

    def extract(
        self,
        projections: Sequence[Projection],
        rows: Sequence[Sequence[Any]],
        *,
        max_rows: int = 100,
        max_entities: int = 100,
        skip_columns: frozenset[int] = frozenset(),
    ) -> tuple[list[EntityRef], list[GraphNodeRef]]:
        """Entities and graph nodes for the first ``max_rows`` rows.

        ``skip_columns`` are result columns that must not contribute (masked sensitive columns).
        """
        found: dict[str, EntityRef] = {}

        # Plan once per query: which columns map where.
        singles: list[tuple[int, str]] = []
        by_instance: dict[str, dict[tuple[str, str], int]] = {}
        fallback: list[tuple[int, str]] = []
        for i, p in enumerate(projections):
            if i in skip_columns:
                continue
            d = p.direct
            if d is not None:
                node_type = self._single.get((d.table, d.column))
                if node_type:
                    singles.append((i, node_type))
                by_instance.setdefault(d.instance, {})[(d.table, d.column)] = i
            elif not p.aggregate and not p.constant:
                lowered = p.name.lower()
                for needle, node_type in self._hints:
                    if needle in lowered:
                        fallback.append((i, node_type))
                        break
        composites: list[tuple[int, int, str]] = []
        for columns in by_instance.values():
            for (table, doc, item), node_type in self._composite.items():
                if (table, doc) in columns and (table, item) in columns:
                    composites.append((columns[(table, doc)], columns[(table, item)], node_type))

        def add(node_type: str, value: str | None) -> None:
            if value is None or len(found) >= max_entities:
                return
            ident = f"{node_type}:{value}"
            if ident not in found:
                found[ident] = EntityRef(id=ident, type=node_type, value=value)

        for row in rows[:max_rows]:
            for i, node_type in singles:
                add(node_type, _text(row[i]) if i < len(row) else None)
            for doc_i, item_i, node_type in composites:
                if doc_i < len(row) and item_i < len(row):
                    doc, item = _text(row[doc_i]), _text(row[item_i])
                    if doc is not None and item is not None:
                        add(node_type, f"{doc}-{graph_item_number(item)}")
            for i, node_type in fallback:
                add(node_type, _text(row[i]) if i < len(row) else None)
            if len(found) >= max_entities:
                break

        entities = list(found.values())
        nodes = [GraphNodeRef(id=e.id, type=e.type, label=e.value) for e in entities]
        return entities, nodes

"""SQL generation for a ``GraphDataset``.

Turns the declarative node/edge definitions into the SQL the repository runs.
All composite ids ("doc-item") go through ``composite()`` so cross-document
references match regardless of zero-padding differences.
"""

from __future__ import annotations

from collections.abc import Sequence

from src.domain.graph_schema import EdgeTypeDef, GraphDataset, NodeTypeDef

# Column names of every edge row; the repository relies on this exact shape.
EDGE_COLUMNS = "source_id, source_type, target_id, target_type, type"


# SQL helper: normalize an item-number column by stripping leading zeros.
# Cross-document FK references use short numbers (e.g. '10') while source
# tables use zero-padded numbers (e.g. '000010').  Wrapping every item
# column with norm() produces a canonical composite ID that matches
# regardless of which table the value originates from.
def norm(col: str) -> str:
    """Returns a SQL expression that strips leading zeros from *col*."""
    return f"REGEXP_REPLACE({col}::text, '^0+', '')"


def composite(doc_col: str, item_col: str) -> str:
    """Returns a SQL expression for a normalized composite ID: 'doc-item'."""
    return f"({doc_col}::text || '-' || {norm(item_col)})"


def edge_id(edge: EdgeTypeDef) -> str:
    """Unique identifier of an edge definition (``key`` alone may be shared)."""
    return f"{edge.key}:{edge.source}>{edge.target}"


class GraphSqlBuilder:
    """Generates the node and edge SQL for one dataset."""

    def __init__(self, dataset: GraphDataset):
        self.dataset = dataset

    # ------------------------------------------------------------------
    # Edges
    # ------------------------------------------------------------------

    @staticmethod
    def _endpoint(alias: str, columns: Sequence[str]) -> str:
        if len(columns) == 1:
            return f"{alias}.{columns[0]}"
        return composite(f"{alias}.{columns[0]}", f"{alias}.{columns[1]}")

    def edge_select(self, edge: EdgeTypeDef) -> str:
        """One edge definition as a SELECT yielding ``EDGE_COLUMNS``."""
        source = self._endpoint(edge.alias, edge.source_columns)
        target = self._endpoint(edge.alias, edge.target_columns)
        distinct = "DISTINCT " if edge.distinct else ""
        where = ""
        if edge.not_null:
            checks = " AND ".join(f"{edge.alias}.{c} IS NOT NULL" for c in edge.not_null)
            where = f"\nWHERE {checks}"
        return (
            f"SELECT {distinct}\n"
            f"    {source}::text AS source_id,\n"
            f"    '{edge.source}'::text AS source_type,\n"
            f"    {target}::text AS target_id,\n"
            f"    '{edge.target}'::text AS target_type,\n"
            f"    '{edge.key}'::text AS type\n"
            f"FROM {edge.table} {edge.alias}{where}"
        )

    def edge_selects(self) -> dict[str, str]:
        """edge id -> SELECT, in dataset definition order."""
        return {edge_id(e): self.edge_select(e) for e in self.dataset.edge_types}

    def edges_union(self) -> str:
        """Every edge definition combined with UNION ALL."""
        return "\n\nUNION ALL\n\n".join(self.edge_selects().values())

    def edge_selects_for_keys(self, keys: Sequence[str]) -> tuple[list[str], list[str]]:
        """SELECTs for the given edge type keys (in the order given).

        Returns ``(selects, unknown_keys)``; a key shared by several
        definitions contributes all of them.
        """
        selects = []
        unknown = []
        for key in keys:
            edges = self.dataset.edge_types_for(key)
            if not edges:
                unknown.append(key)
            selects.extend(self.edge_select(e) for e in edges)
        return selects, unknown

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    @staticmethod
    def id_expression(node: NodeTypeDef) -> str:
        """Unqualified SQL expression for a node's id within its own table."""
        if len(node.id_columns) == 1:
            return node.id_columns[0]
        doc, item = node.id_columns
        return f"{doc} || '-' || {norm(item)}"

    @staticmethod
    def count_query(node: NodeTypeDef) -> str:
        if node.count_distinct:
            cols = ", ".join(node.id_columns)
            source = f"(SELECT DISTINCT {cols} FROM {node.table})"
        else:
            source = node.table
        return f"SELECT COUNT(*) FROM {source} AS _t"

    def entities_query(self, node: NodeTypeDef) -> str:
        return f"SELECT DISTINCT {self.id_expression(node)}::text FROM {node.table} LIMIT :limit"

"""SQL generation for a ``GraphDataset``.

Turns the declarative node/edge definitions into the SQL the repository runs.
An id made of several columns is written by ``composite()``, so a node's own id
and every edge endpoint that refers to it are built the same way.
"""

from __future__ import annotations

from collections.abc import Sequence

from src.domain.graph_schema import EdgeTypeDef, GraphDataset, NodeTypeDef

# Column names of every edge row; the repository relies on this exact shape.
EDGE_COLUMNS = "source_id, source_type, target_id, target_type, type"


# Joins the parts of a composite id: ``<first>-<second>[-<third>...]``.
ID_SEPARATOR = "-"


def composite(columns: Sequence[str]) -> str:
    """SQL expression for an id made of several columns, joined with ``ID_SEPARATOR``.

    Values are used exactly as stored.  Making both sides of a reference agree
    (e.g. item numbers without leading zeros) is the package's job: each column
    declares its ``normalize`` steps and ingestion applies them.
    """
    sep = f" || '{ID_SEPARATOR}' || "
    return "(" + sep.join(f"{col}::text" for col in columns) + ")"


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
        return composite([f"{alias}.{col}" for col in columns])

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

    def traversal_expand_filter(self) -> str:
        """Extra WHERE terms for the traversal step: do not expand through terminal types.

        The root is always expanded, so tracing from a party record still works.
        Empty when the dataset has no terminal types.
        """
        keys = self.dataset.terminal_node_keys
        if not keys:
            return ""
        listed = ", ".join(f"'{k}'" for k in keys)
        return f"AND (t.depth = 0 OR t.type NOT IN ({listed}))"

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    @staticmethod
    def id_expression(node: NodeTypeDef, alias: str | None = None) -> str:
        """SQL expression for a node's id within its own table (qualified by ``alias`` if given)."""
        prefix = f"{alias}." if alias else ""
        if len(node.id_columns) == 1:
            return f"{prefix}{node.id_columns[0]}"
        return composite([f"{prefix}{col}" for col in node.id_columns])

    @staticmethod
    def count_query(node: NodeTypeDef) -> str:
        if node.count_distinct:
            cols = ", ".join(node.id_columns)
            source = f"(SELECT DISTINCT {cols} FROM {node.table})"
        else:
            source = node.table
        return f"SELECT COUNT(*) FROM {source} AS _t"

    def entities_query(self, node: NodeTypeDef) -> str:
        # ORDER BY makes the sample (and so the listing) the same on every call.
        return (
            f"SELECT DISTINCT {self.id_expression(node)}::text FROM {node.table} "
            f"ORDER BY 1 LIMIT :limit"
        )

    # ------------------------------------------------------------------
    # Record details
    # ------------------------------------------------------------------

    # Output names of the id and label columns in the details query.
    DETAIL_ID = "_gs_id"
    DETAIL_LABEL = "_gs_label"

    @staticmethod
    def leading_values(node: NodeTypeDef, node_id: str) -> list[str]:
        """Values the first id column can hold for the composite id ``node_id`` (empty for plain ids).

        A part may itself contain ``ID_SEPARATOR``, so the id does not say where
        the first part ends: every split that leaves a part for each remaining
        column is a candidate.  They only narrow the lookup; the exact id check follows.
        """
        if len(node.id_columns) == 1:
            return []
        pieces = node_id.split(ID_SEPARATOR)
        last = len(pieces) - (len(node.id_columns) - 1)
        return [ID_SEPARATOR.join(pieces[:end]) for end in range(1, last + 1)]

    def details_query(self, node: NodeTypeDef, node_ids: Sequence[str]) -> tuple[str, dict]:
        """One statement fetching properties and label for many records of a type.

        Every identifier comes from the validated dataset definition; ids and
        lookup filter values travel as bound parameters.  Tables may hold
        several rows per id (e.g. line-item tables), so one row per id is
        kept, chosen deterministically.
        """
        alias = "t"
        id_expr = self.id_expression(node, alias)
        select = [f"{id_expr}::text AS {self.DETAIL_ID}"]
        select += [f"{alias}.{col}" for col in node.detail_columns]

        params: dict = {"ids": list(node_ids)}
        if node.label_column:
            select.append(f"{alias}.{node.label_column} AS {self.DETAIL_LABEL}")
        elif node.label_lookup:
            lk = node.label_lookup
            conds = [f"l.{lk.match_column} = {alias}.{node.id_columns[0]}"]
            for index, (column, value) in enumerate(lk.filters):
                conds.append(f"l.{column} = :lf{index}")
                params[f"lf{index}"] = value
            select.append(
                f"(SELECT l.{lk.label_column} FROM {lk.table} l WHERE {' AND '.join(conds)} "
                f"LIMIT 1) AS {self.DETAIL_LABEL}"
            )

        where = f"{id_expr} = ANY(CAST(:ids AS text[]))"
        if len(node.id_columns) > 1:
            # Narrow on the indexed first column; the exact id check follows.
            where = f"{alias}.{node.id_columns[0]}::text = ANY(CAST(:docs AS text[])) AND {where}"
            params["docs"] = sorted({v for i in node_ids for v in self.leading_values(node, i)})

        order = [self.DETAIL_ID] + [f"{alias}.{col}" for col in node.detail_columns]
        return (
            f"SELECT DISTINCT ON ({self.DETAIL_ID})\n    "
            + ",\n    ".join(select)
            + f"\nFROM {node.table} {alias}\nWHERE {where}\nORDER BY "
            + ", ".join(order),
            params,
        )

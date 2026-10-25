"""SQL generation for a ``GraphDataset``.

Turns the declarative node/edge definitions into the SQL the repository runs.
An id made of several columns is written by ``composite()``, so a node's own id
and every edge endpoint that refers to it are built the same way.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

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

    def edge_select(self, edge: EdgeTypeDef, conditions: Sequence[str] = ()) -> str:
        """One edge definition as a SELECT yielding ``EDGE_COLUMNS`` (``conditions`` are ANDed to its WHERE)."""
        source = self._endpoint(edge.alias, edge.source_columns)
        target = self._endpoint(edge.alias, edge.target_columns)
        distinct = "DISTINCT " if edge.distinct else ""
        where = ""
        checks = [f"{edge.alias}.{c} IS NOT NULL" for c in edge.not_null] + list(conditions)
        if checks:
            where = f"\nWHERE {' AND '.join(checks)}"
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
    # Traversal
    # ------------------------------------------------------------------
    #
    # A subgraph is walked one hop at a time: each hop asks only for the edges
    # touching the records found by the previous one, so every lookup goes
    # through the indexes on the edge columns instead of reading every edge.

    def _id_param(self, node_type: str) -> str:
        return f"ids_{self.dataset.node_keys.index(node_type)}"

    def _matches(self, alias: str, columns: Sequence[str], param: str) -> str:
        """``alias.columns`` is one of the ids bound as ``:param``.

        A composite id is first narrowed on its leading column (``:param_lead``)
        so the lookup can use the index; the exact id check follows.
        """
        where = f"{self._endpoint(alias, columns)}::text = ANY(CAST(:{param} AS text[]))"
        if len(columns) > 1:
            where = f"{alias}.{columns[0]}::text = ANY(CAST(:{param}_lead AS text[])) AND {where}"
        return where

    def _id_params(self, records: Mapping[str, Sequence[str]]) -> dict:
        params: dict = {}
        for node_type, ids in records.items():
            node = self.dataset.get_node_type(node_type)
            if node is None:
                continue
            param = self._id_param(node_type)
            params[param] = list(ids)
            if len(node.id_columns) > 1:
                params[f"{param}_lead"] = sorted({v for i in ids for v in self.leading_values(node, i)})
        return params

    def neighbours_query(self, frontier: Mapping[str, Sequence[str]]) -> tuple[str | None, dict]:
        """Every edge with an endpoint among ``frontier`` (node type -> ids), as ``EDGE_COLUMNS``.

        ``None`` when no edge definition touches the frontier's types.
        """
        blocks = []
        for edge in self.dataset.edge_types:
            if edge.source in frontier:
                blocks.append(self.edge_select(
                    edge, [self._matches(edge.alias, edge.source_columns, self._id_param(edge.source))]
                ))
            if edge.target in frontier:
                blocks.append(self.edge_select(
                    edge, [self._matches(edge.alias, edge.target_columns, self._id_param(edge.target))]
                ))
        if not blocks:
            return None, {}
        return "\n\nUNION ALL\n\n".join(blocks), self._id_params(frontier)

    def edges_between_query(self, records: Mapping[str, Sequence[str]]) -> tuple[str | None, dict]:
        """Every edge whose two endpoints are among ``records``, de-duplicated and in a total order.

        ``None`` when no edge definition connects the records' types.
        """
        blocks = [
            self.edge_select(edge, [
                self._matches(edge.alias, edge.source_columns, self._id_param(edge.source)),
                self._matches(edge.alias, edge.target_columns, self._id_param(edge.target)),
            ])
            for edge in self.dataset.edge_types
            if edge.source in records and edge.target in records
        ]
        if not blocks:
            return None, {}
        union = "\n\nUNION ALL\n\n".join(blocks)
        sql = (
            f"SELECT DISTINCT {EDGE_COLUMNS}\nFROM (\n{union}\n) AS ge\n"
            "ORDER BY source_type, source_id, target_type, target_id, type"
        )
        return sql, self._id_params(records)

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

    def edge_count(self, edge: EdgeTypeDef) -> str:
        """The number of rows ``edge_select(edge)`` yields, without building their ids."""
        if edge.distinct:
            return f"SELECT COUNT(*) FROM ({self.edge_select(edge)}) AS _d"
        where = ""
        if edge.not_null:
            where = " WHERE " + " AND ".join(f"{edge.alias}.{c} IS NOT NULL" for c in edge.not_null)
        return f"SELECT COUNT(*) FROM {edge.table} {edge.alias}{where}"

    def summary_query(self) -> str:
        """Node counts (kind 0, in definition order) and edge counts per key (kind 1, by key), as one statement."""
        parts = [
            f"SELECT 0 AS kind, {index} AS ord, '{node.key}'::text AS key, ({self.count_query(node)}) AS n"
            for index, node in enumerate(self.dataset.node_types)
        ]
        if self.dataset.edge_types:
            counts = " UNION ALL ".join(
                f"SELECT '{edge.key}'::text AS type, ({self.edge_count(edge)}) AS n" for edge in self.dataset.edge_types
            )
            parts.append(f"SELECT 1, 0, type, SUM(n) FROM ({counts}) AS _edges GROUP BY type")
        return "SELECT kind, key, n FROM (\n" + "\nUNION ALL\n".join(parts) + "\n) AS _summary ORDER BY kind, ord, key"

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

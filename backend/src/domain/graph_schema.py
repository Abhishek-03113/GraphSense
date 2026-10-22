"""Declarative description of a graph dataset.

A dataset is a set of node types, edge types and flows.  Everything the graph
layer needs - the product-facing metadata served by ``GET /api/graph/schema``
as well as the table/column mapping the repository turns into SQL - lives in
these definitions, so plugging in a new dataset means writing a definition
module (see ``src/domain/datasets/o2c.py``) rather than editing repository SQL.

Identifier-like fields (type keys, table and column names) are validated on
construction because the repository interpolates them into SQL text.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from src.domain.graph_models import (
    AccentName,
    FlowDefinition,
    GraphSchemaResponse,
    NodeCategory,
    SchemaDomain,
    SchemaEdgeType,
    SchemaNodeType,
)

_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_TABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")
_COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _check(pattern: re.Pattern, value: str, what: str) -> str:
    if not pattern.match(value):
        raise ValueError(f"invalid {what}: {value!r}")
    return value


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class NodeTypeDef(_Frozen):
    """One kind of entity in the graph, backed by one table."""

    # --- presentation (served by /api/graph/schema) -----------------------
    key: str
    label: str
    plural: str
    description: str
    category: NodeCategory = "other"
    accent: Optional[AccentName] = None
    icon: Optional[str] = None
    is_primary: bool = False
    display_properties: Tuple[str, ...] = ()

    # --- query mapping (used by the repository) ---------------------------
    table: str
    # One column for a plain id, or two (document, item) for a composite id
    # rendered as ``doc-item`` with the item number zero-stripped.
    id_columns: Tuple[str, ...]
    # Count distinct ids rather than rows (multi-row-per-document tables).
    count_distinct: bool = False

    @field_validator("key")
    @classmethod
    def _valid_key(cls, v: str) -> str:
        return _check(_KEY, v, "node type key")

    @field_validator("table")
    @classmethod
    def _valid_table(cls, v: str) -> str:
        return _check(_TABLE, v, "table name")

    @field_validator("id_columns", "display_properties")
    @classmethod
    def _valid_columns(cls, v: Tuple[str, ...]) -> Tuple[str, ...]:
        for col in v:
            _check(_COLUMN, col, "column name")
        return v

    @field_validator("id_columns")
    @classmethod
    def _id_arity(cls, v: Tuple[str, ...]) -> Tuple[str, ...]:
        if len(v) not in (1, 2):
            raise ValueError("id_columns must have one (plain) or two (composite) columns")
        return v


class EdgeTypeDef(_Frozen):
    """One directed relationship between two node types, derived from a table.

    ``key`` is the ``type`` value emitted on graph edges.  It need not be
    unique: several definitions may share a key (e.g. ``HAS_ITEM``), each with
    its own source/target pair and table.
    """

    # --- presentation (served by /api/graph/schema) -----------------------
    key: str
    label: str
    source: str
    target: str
    description: str

    # --- query mapping (used by the repository) ---------------------------
    table: str
    alias: str
    # One column for a plain id, or two (document, item) for a composite id.
    source_columns: Tuple[str, ...]
    target_columns: Tuple[str, ...]
    # Rows where any of these columns is NULL are skipped.
    not_null: Tuple[str, ...] = ()
    distinct: bool = False

    @field_validator("key", "source", "target")
    @classmethod
    def _valid_key(cls, v: str) -> str:
        return _check(_KEY, v, "type key")

    @field_validator("table")
    @classmethod
    def _valid_table(cls, v: str) -> str:
        return _check(_TABLE, v, "table name")

    @field_validator("alias")
    @classmethod
    def _valid_alias(cls, v: str) -> str:
        return _check(_COLUMN, v, "table alias")

    @field_validator("source_columns", "target_columns", "not_null")
    @classmethod
    def _valid_columns(cls, v: Tuple[str, ...]) -> Tuple[str, ...]:
        for col in v:
            _check(_COLUMN, col, "column name")
        return v

    @field_validator("source_columns", "target_columns")
    @classmethod
    def _id_arity(cls, v: Tuple[str, ...]) -> Tuple[str, ...]:
        if len(v) not in (1, 2):
            raise ValueError("endpoint columns must have one (plain) or two (composite) columns")
        return v


class GraphDataset(_Frozen):
    """A complete graph definition: domain metadata, types and flows."""

    id: str
    name: str
    description: str
    node_types: Tuple[NodeTypeDef, ...]
    edge_types: Tuple[EdgeTypeDef, ...]
    flows: Tuple[FlowDefinition, ...] = ()
    # Ordered (column-name substring, node type key) pairs used to recognise
    # entity references in tabular query results.  First match wins.
    entity_column_hints: Tuple[Tuple[str, str], ...] = ()

    @field_validator("id")
    @classmethod
    def _valid_id(cls, v: str) -> str:
        return _check(re.compile(r"^[a-z][a-z0-9_]*$"), v, "dataset id")

    @model_validator(mode="after")
    def _consistent(self) -> "GraphDataset":
        node_keys = [n.key for n in self.node_types]
        if len(set(node_keys)) != len(node_keys):
            raise ValueError("duplicate node type keys")
        known = set(node_keys)

        seen_edges = set()
        for e in self.edge_types:
            if e.source not in known or e.target not in known:
                raise ValueError(
                    f"edge {e.key}: source/target {e.source}->{e.target} is not a registered node type"
                )
            ident = (e.key, e.source, e.target)
            if ident in seen_edges:
                raise ValueError(f"duplicate edge definition {ident}")
            seen_edges.add(ident)

        flow_ids = [f.id for f in self.flows]
        if len(set(flow_ids)) != len(flow_ids):
            raise ValueError("duplicate flow ids")
        edge_keys = {e.key for e in self.edge_types}
        for f in self.flows:
            for t in f.node_types:
                if t not in known:
                    raise ValueError(f"flow {f.id}: unknown node type {t}")
            for k in f.edge_types:
                if k not in edge_keys:
                    raise ValueError(f"flow {f.id}: unknown edge type {k}")

        for _, node_key in self.entity_column_hints:
            if node_key not in known:
                raise ValueError(f"entity hint targets unknown node type {node_key}")

        return self

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    @property
    def node_keys(self) -> List[str]:
        return [n.key for n in self.node_types]

    def get_node_type(self, key: str) -> Optional[NodeTypeDef]:
        for n in self.node_types:
            if n.key == key:
                return n
        return None

    def edge_types_for(self, key: str) -> List[EdgeTypeDef]:
        """All edge definitions that emit ``key`` as their type, in definition order."""
        return [e for e in self.edge_types if e.key == key]

    def get_flow(self, flow_id: str) -> Optional[FlowDefinition]:
        for f in self.flows:
            if f.id == flow_id:
                return f
        return None

    def flows_by_id(self) -> Dict[str, FlowDefinition]:
        return {f.id: f for f in self.flows}

    # ------------------------------------------------------------------
    # Client-facing description
    # ------------------------------------------------------------------

    def to_schema_response(self) -> GraphSchemaResponse:
        """The payload of ``GET /api/graph/schema`` (no SQL mapping, no counts)."""
        return GraphSchemaResponse(
            domain=SchemaDomain(id=self.id, name=self.name, description=self.description),
            node_types=[
                SchemaNodeType(
                    key=n.key,
                    label=n.label,
                    plural=n.plural,
                    description=n.description,
                    category=n.category,
                    accent=n.accent,
                    icon=n.icon,
                    is_primary=n.is_primary,
                    display_properties=list(n.display_properties),
                )
                for n in self.node_types
            ],
            edge_types=[
                SchemaEdgeType(
                    key=e.key,
                    label=e.label,
                    source=e.source,
                    target=e.target,
                    description=e.description,
                )
                for e in self.edge_types
            ],
            flows=list(self.flows),
        )

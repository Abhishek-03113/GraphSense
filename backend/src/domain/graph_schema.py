"""Declarative description of a graph dataset.

A dataset is a set of node types, edge types and flows.  Everything the graph
layer needs - the product-facing metadata served by ``GET /api/graph/schema``
as well as the table/column mapping the repository turns into SQL - lives in
these definitions, so plugging in a new dataset means writing its ``graph.yaml``
(see ``src/datasets`` and ``dataset_packages/``) rather than editing repository SQL.

Identifier-like fields (type keys, table and column names) are validated on
construction because the repository interpolates them into SQL text.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.domain.graph_models import (
    AccentName,
    FlowDefinition,
    GraphSchemaResponse,
    SchemaDomain,
    SchemaEdgeType,
    SchemaNodeType,
)

_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_TABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)?$")
_COLUMN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_CATEGORY = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


def _check(pattern: re.Pattern, value: str, what: str) -> str:
    if not pattern.match(value):
        raise ValueError(f"invalid {what}: {value!r}")
    return value


class _Frozen(BaseModel):
    # forbid: a misspelt key in a dataset package must fail loudly, not be ignored.
    model_config = ConfigDict(frozen=True, extra="forbid")


class EntityRef(_Frozen):
    """A single column that holds the id of a node type but is not part of a node or edge definition.

    Example: ``orders.shipment_ref`` holds a Shipment id.  Used to
    recognise entities in tabular query results.
    """

    table: str
    column: str
    node_type: str

    @field_validator("table")
    @classmethod
    def _valid_table(cls, v: str) -> str:
        return _check(_TABLE, v, "entity ref table")

    @field_validator("column")
    @classmethod
    def _valid_column(cls, v: str) -> str:
        return _check(_COLUMN, v, "entity ref column")

    @field_validator("node_type")
    @classmethod
    def _valid_node_type(cls, v: str) -> str:
        return _check(_KEY, v, "entity ref node type")


class LabelLookup(_Frozen):
    """A natural name that lives in another table (e.g. a product description).

    The lookup row is the one in ``table`` whose ``match_column`` equals the
    node's id column and that satisfies every ``(column, value)`` in
    ``filters`` (values are bound as parameters, never interpolated).  The name
    is used as the node label and is also exposed as a property keyed by
    ``label_column``.
    """

    table: str
    match_column: str
    label_column: str
    filters: tuple[tuple[str, str], ...] = ()

    @field_validator("table")
    @classmethod
    def _valid_table(cls, v: str) -> str:
        return _check(_TABLE, v, "lookup table name")

    @field_validator("match_column", "label_column")
    @classmethod
    def _valid_column(cls, v: str) -> str:
        return _check(_COLUMN, v, "lookup column name")

    @field_validator("filters")
    @classmethod
    def _valid_filters(cls, v: tuple[tuple[str, str], ...]) -> tuple[tuple[str, str], ...]:
        for column, _ in v:
            _check(_COLUMN, column, "lookup filter column")
        return v


class NodeTypeDef(_Frozen):
    """One kind of entity in the graph, backed by one table."""

    # --- presentation (served by /api/graph/schema) -----------------------
    key: str
    label: str
    plural: str
    description: str
    # Free-form grouping label for clients (e.g. "document", "party"); it has no
    # effect on queries.  Traversal behaviour is set by ``terminal``.
    category: str = "other"
    accent: AccentName | None = None
    icon: str | None = None
    is_primary: bool = False
    display_properties: tuple[str, ...] = ()

    # --- query mapping (used by the repository) ---------------------------
    table: str
    # One column for a plain id, or several for a composite id rendered as the
    # values joined with "-" (``<first>-<second>...``), exactly as stored.
    id_columns: tuple[str, ...]
    # Shared reference records (one party or catalogue item is linked to a great
    # many others): traversal reaches them but does not expand through them,
    # otherwise a trace of one record would pull in everything that refers to it.
    terminal: bool = False
    # Count distinct ids rather than rows (multi-row-per-document tables).
    count_distinct: bool = False

    # --- record details (served on Node.properties / entity listings) -----
    # Columns exposed as properties in addition to ``display_properties``.
    property_columns: tuple[str, ...] = ()
    # Column of ``table`` holding a natural name for the record (e.g. a
    # party's full name).  Becomes ``Node.label``; ``id`` is unaffected.
    label_column: str | None = None
    # Alternative to ``label_column`` when the name lives in another table.
    label_lookup: LabelLookup | None = None

    @field_validator("key")
    @classmethod
    def _valid_key(cls, v: str) -> str:
        return _check(_KEY, v, "node type key")

    @field_validator("table")
    @classmethod
    def _valid_table(cls, v: str) -> str:
        return _check(_TABLE, v, "table name")

    @field_validator("category")
    @classmethod
    def _valid_category(cls, v: str) -> str:
        return _check(_CATEGORY, v, "node category")

    @field_validator("id_columns", "display_properties", "property_columns")
    @classmethod
    def _valid_columns(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        for col in v:
            _check(_COLUMN, col, "column name")
        return v

    @field_validator("label_column")
    @classmethod
    def _valid_label_column(cls, v: str | None) -> str | None:
        return v if v is None else _check(_COLUMN, v, "label column name")

    @field_validator("id_columns")
    @classmethod
    def _id_arity(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if not v:
            raise ValueError("id_columns must name at least one column")
        if len(set(v)) != len(v):
            raise ValueError("id_columns must not repeat a column")
        return v

    @model_validator(mode="after")
    def _label_source(self) -> NodeTypeDef:
        if self.label_column and self.label_lookup:
            raise ValueError("use either label_column or label_lookup, not both")
        if self.label_lookup and len(self.id_columns) != 1:
            raise ValueError("label_lookup needs a plain (single column) id")
        return self

    @property
    def detail_columns(self) -> tuple[str, ...]:
        """Columns of ``table`` exposed as properties, in display order, without duplicates.

        ``display_properties`` that are produced by ``label_lookup`` rather than
        by the table itself are excluded (see ``detail_keys``).
        """
        derived = self.label_lookup.label_column if self.label_lookup else None
        cols = (*self.display_properties, *self.property_columns)
        return tuple(c for c in dict.fromkeys(cols) if c != derived)

    @property
    def detail_keys(self) -> tuple[str, ...]:
        """Every property key a record of this type can carry."""
        derived = (self.label_lookup.label_column,) if self.label_lookup else ()
        return tuple(dict.fromkeys((*self.display_properties, *self.property_columns, *derived)))


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
    # The columns holding the endpoint's id, one per id column of that node type, in the same order.
    source_columns: tuple[str, ...]
    target_columns: tuple[str, ...]
    # Rows where any of these columns is NULL are skipped.
    not_null: tuple[str, ...] = ()
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
    def _valid_columns(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        for col in v:
            _check(_COLUMN, col, "column name")
        return v

    @field_validator("source_columns", "target_columns")
    @classmethod
    def _id_arity(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if not v:
            raise ValueError("endpoint columns must name at least one column")
        return v


class GraphDataset(_Frozen):
    """A complete graph definition: domain metadata, types and flows."""

    id: str
    name: str
    description: str
    node_types: tuple[NodeTypeDef, ...]
    edge_types: tuple[EdgeTypeDef, ...]
    flows: tuple[FlowDefinition, ...] = ()
    # Ordered (column-name substring, node type key) pairs used to recognise
    # entity references in tabular query results.  First match wins.
    entity_column_hints: tuple[tuple[str, str], ...] = ()
    # Single columns that hold the id of a node type (see ``EntityRef``).
    entity_refs: tuple[EntityRef, ...] = ()
    # Package version, served as ``domain.version``.
    version: str = ""
    # Labels of coded values, ``table -> column -> code -> label``.  Supplied by the
    # dataset package; only used to describe node properties to clients.
    value_labels: dict[str, dict[str, dict[str, str]]] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def _valid_id(cls, v: str) -> str:
        return _check(re.compile(r"^[a-z][a-z0-9_]*$"), v, "dataset id")

    @model_validator(mode="after")
    def _consistent(self) -> GraphDataset:
        node_keys = [n.key for n in self.node_types]
        if len(set(node_keys)) != len(node_keys):
            raise ValueError("duplicate node type keys")
        known = set(node_keys)
        arity = {n.key: len(n.id_columns) for n in self.node_types}

        seen_edges = set()
        for e in self.edge_types:
            if e.source not in known or e.target not in known:
                raise ValueError(
                    f"edge {e.key}: {e.source}->{e.target} is not between registered node types"
                )
            # An endpoint with a different number of columns could never match the node's id.
            for side, node_key, columns in (("source", e.source, e.source_columns), ("target", e.target, e.target_columns)):
                if len(columns) != arity[node_key]:
                    raise ValueError(
                        f"edge {e.key} {e.source}->{e.target}: {side}_columns has {len(columns)} column(s), "
                        f"the id of {node_key} has {arity[node_key]}"
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

        for ref in self.entity_refs:
            if ref.node_type not in known:
                raise ValueError(f"entity ref targets unknown node type {ref.node_type}")

        return self

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    @property
    def node_keys(self) -> list[str]:
        return [n.key for n in self.node_types]

    @property
    def terminal_node_keys(self) -> list[str]:
        """Types a traversal reaches but does not expand through (``NodeTypeDef.terminal``)."""
        return [n.key for n in self.node_types if n.terminal]

    def get_node_type(self, key: str) -> NodeTypeDef | None:
        for n in self.node_types:
            if n.key == key:
                return n
        return None

    def edge_types_for(self, key: str) -> list[EdgeTypeDef]:
        """All edge definitions that emit ``key`` as their type, in definition order."""
        return [e for e in self.edge_types if e.key == key]

    def get_flow(self, flow_id: str) -> FlowDefinition | None:
        for f in self.flows:
            if f.id == flow_id:
                return f
        return None

    # ------------------------------------------------------------------
    # Client-facing description
    # ------------------------------------------------------------------

    def node_value_labels(self, node: NodeTypeDef) -> dict[str, dict[str, str]]:
        """``property -> code -> label`` for the properties of ``node`` that are coded."""
        by_column = self.value_labels.get(node.table, {})
        return {
            key: dict(by_column[key]) for key in node.detail_keys if key in by_column and by_column[key]
        }

    def to_schema_response(self) -> GraphSchemaResponse:
        """The payload of ``GET /api/graph/schema`` (no SQL mapping, no counts)."""
        return GraphSchemaResponse(
            domain=SchemaDomain(
                id=self.id, name=self.name, description=self.description, version=self.version
            ),
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
                    value_labels=self.node_value_labels(n),
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

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class FlowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    description: str
    node_types: list[str]
    edge_types: list[str]


class FlowListResponse(BaseModel):
    flows: list[FlowDefinition]


class Node(BaseModel):
    id: str
    type: str
    label: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)


class Edge(BaseModel):
    id: str
    source: str
    target: str
    type: str
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphSummaryResponse(BaseModel):
    nodes: dict[str, int]
    edges: dict[str, int]


class GraphSubgraphResponse(BaseModel):
    nodes: list[Node]
    edges: list[Edge]


class GraphEntityResponse(BaseModel):
    type: str
    # Each entity is {"id": "...", "label": "...", <display property>: value, ...}.
    entities: list[dict[str, Any]]


# ---------------------------------------------------------------------------
# GET /api/graph/schema — dataset description for clients
# ---------------------------------------------------------------------------

NodeCategory = Literal["party", "document", "item", "master", "finance", "other"]

AccentName = Literal[
    "red", "orange", "yellow", "green", "mint", "teal", "cyan",
    "blue", "indigo", "purple", "pink", "brown", "gray",
]


class SchemaDomain(BaseModel):
    id: str
    name: str
    description: str
    # Version of the dataset package this description comes from.
    version: str = ""
    # True only for a generic placeholder domain that has no name of its own.
    # A dataset package always has a name, so the server reports False.
    is_default: bool = False


class SchemaNodeType(BaseModel):
    key: str
    label: str
    plural: str
    description: str
    category: NodeCategory
    accent: AccentName | None = None
    icon: str | None = None
    is_primary: bool
    display_properties: list[str] = Field(default_factory=list)
    # Coded properties: property -> {code: label}. Only labels the package
    # author is confident about are served (see confidence in value_sets).
    value_labels: dict[str, dict[str, str]] = Field(default_factory=dict)


class SchemaEdgeType(BaseModel):
    key: str
    label: str
    source: str
    target: str
    description: str


class GraphSchemaResponse(BaseModel):
    domain: SchemaDomain
    node_types: list[SchemaNodeType]
    edge_types: list[SchemaEdgeType]
    flows: list[FlowDefinition]

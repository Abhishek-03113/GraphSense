from typing import Dict, List, Literal, Optional, Any
from pydantic import BaseModel, ConfigDict, Field


class FlowDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    description: str
    node_types: List[str]
    edge_types: List[str]


class FlowListResponse(BaseModel):
    flows: List[FlowDefinition]

class Node(BaseModel):
    id: str
    type: str
    label: Optional[str] = None
    properties: Dict[str, Any] = Field(default_factory=dict)

class Edge(BaseModel):
    id: str
    source: str
    target: str
    type: str
    properties: Dict[str, Any] = Field(default_factory=dict)

class GraphSummaryResponse(BaseModel):
    nodes: Dict[str, int]
    edges: Dict[str, int]

class GraphSubgraphResponse(BaseModel):
    nodes: List[Node]
    edges: List[Edge]

class GraphEntityResponse(BaseModel):
    type: str
    # Each entity is {"id": "...", "label": "...", <display property>: value, ...}.
    entities: List[Dict[str, Any]]


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
    accent: Optional[AccentName] = None
    icon: Optional[str] = None
    is_primary: bool
    display_properties: List[str] = Field(default_factory=list)
    # Coded properties: property -> {code: label}. Only labels the package
    # author is confident about are served (see confidence in value_sets).
    value_labels: Dict[str, Dict[str, str]] = Field(default_factory=dict)


class SchemaEdgeType(BaseModel):
    key: str
    label: str
    source: str
    target: str
    description: str


class GraphSchemaResponse(BaseModel):
    domain: SchemaDomain
    node_types: List[SchemaNodeType]
    edge_types: List[SchemaEdgeType]
    flows: List[FlowDefinition]

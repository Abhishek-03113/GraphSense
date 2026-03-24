from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field

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
    entities: List[Dict[str, str]]  # List of {"id": "...", "label": "..."}

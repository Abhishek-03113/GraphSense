
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_dataset_context, get_dataset_db
from src.datasets.context import DatasetContext
from src.domain.graph_models import (
    FlowListResponse,
    GraphEntityResponse,
    GraphSchemaResponse,
    GraphSubgraphResponse,
    GraphSummaryResponse,
)
from src.repositories.graph_repository import GraphRepository

router = APIRouter(prefix="/api/graph", tags=["graph"])

# Every endpoint works on one dataset: the one named by the X-GraphSense-Dataset header
# or ?dataset=, else the default dataset (see src/api/deps.py).
#
# Failures are not caught here: the application-level handler logs the
# exception with the request id and answers with the generic error envelope,
# so no database text can leak into a response (see src/api/errors.py).


def get_repository(
    db: AsyncSession = Depends(get_dataset_db),
    ctx: DatasetContext = Depends(get_dataset_context),
) -> GraphRepository:
    return GraphRepository(db, ctx.package.graph_dataset())


@router.get("/summary", response_model=GraphSummaryResponse)
async def get_graph_summary(repo: GraphRepository = Depends(get_repository)):
    """Returns an overview of the dataset sizes (node and edge counts)."""
    return await repo.get_summary()


@router.get("/subgraph", response_model=GraphSubgraphResponse)
async def get_graph_subgraph(
    root_type: str = Query(..., description="Type of the root node (e.g., SalesOrder)"),
    root_id: str = Query(..., description="ID of the root node"),
    depth: int = Query(1, ge=1, le=5, description="Depth of relationships to traverse"),
    repo: GraphRepository = Depends(get_repository),
):
    """Returns nodes and edges reachable from the root in graph form."""
    return await repo.get_subgraph(root_type, root_id, depth)


@router.get("/schema", response_model=GraphSchemaResponse)
async def get_graph_schema(ctx: DatasetContext = Depends(get_dataset_context)):
    """Describes the active dataset: domain, node types, edge types and flows.

    Counts are not included; join with /summary. Needs no database access.
    """
    return ctx.package.graph_dataset().to_schema_response()


@router.get("/flows", response_model=FlowListResponse)
async def list_flows(ctx: DatasetContext = Depends(get_dataset_context)):
    """Returns the predefined flow definitions of the active dataset."""
    return FlowListResponse(flows=list(ctx.package.graph_dataset().flows))


@router.get("/flow", response_model=GraphSubgraphResponse)
async def get_flow(
    flow_id: str = Query(..., description="Flow identifier (e.g., full_o2c, sales, billing)"),
    limit: int = Query(50, ge=1, le=200, description="Max nodes per edge bucket"),
    repo: GraphRepository = Depends(get_repository),
):
    """Returns a sampled subgraph for a predefined flow of the active dataset."""
    if repo.dataset.get_flow(flow_id) is None:
        raise HTTPException(status_code=404, detail=f"Unknown flow: {flow_id}")
    return await repo.get_flow(flow_id, limit)


@router.get("/trace", response_model=GraphSubgraphResponse)
async def trace_document(
    doc_type: str = Query(..., description="Type of the document to trace (e.g., Invoice)"),
    doc_id: str = Query(..., description="ID of the document"),
    depth: int = Query(4, ge=1, le=5, description="Traversal depth"),
    repo: GraphRepository = Depends(get_repository),
):
    """Traces the full lifecycle (all connected entities) for a given document."""
    return await repo.get_subgraph(doc_type, doc_id, depth)


@router.get("/full", response_model=GraphSubgraphResponse)
async def get_full_graph(
    node_limit: int = Query(20, ge=1, le=500, description="Max entities sampled per node type"),
    type_filter: str | None = Query(None, description="Comma-separated node types to include"),
    repo: GraphRepository = Depends(get_repository),
):
    """Returns a sampled knowledge graph across all entity types."""
    types = [t.strip() for t in type_filter.split(",")] if type_filter else None
    return await repo.get_full_graph(node_limit, types)


@router.get("/entities/{node_type}", response_model=GraphEntityResponse)
async def get_entities(
    node_type: str,
    limit: int = Query(50, ge=1, le=100),
    repo: GraphRepository = Depends(get_repository),
):
    """Returns a sample of entity IDs for a given type."""
    return await repo.get_entities(node_type, limit)

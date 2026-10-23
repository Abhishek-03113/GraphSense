from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from src.api.deps import get_dataset_context
from src.datasets.context import DatasetContext
from src.db.session import get_db_session
from src.domain.graph_models import GraphSummaryResponse, GraphSubgraphResponse, GraphEntityResponse, FlowListResponse, GraphSchemaResponse
from src.repositories.graph_repository import GraphRepository
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/graph", tags=["graph"])

# Every endpoint works on one dataset: the one named by the X-GraphSense-Dataset header
# or ?dataset=, else the default dataset (see src/api/deps.py).
#
# Failures are not caught here: the application-level handler logs the
# exception with the request id and answers with the generic error envelope,
# so no database text can leak into a response (see src/api/errors.py).


@router.get("/summary", response_model=GraphSummaryResponse)
async def get_graph_summary(
    db: AsyncSession = Depends(get_db_session),
    ctx: DatasetContext = Depends(get_dataset_context),
):
    """Returns an overview of the dataset sizes (node and edge counts)."""
    logger.info("API /summary — called")
    repo = GraphRepository(db, ctx.package.graph_dataset())
    result = await repo.get_summary()
    logger.info(
        "API /summary — responding with %d node types, %d edge types",
        len(result.nodes), len(result.edges),
    )
    return result

@router.get("/subgraph", response_model=GraphSubgraphResponse)
async def get_graph_subgraph(
    root_type: str = Query(..., description="Type of the root node (e.g., SalesOrder)"),
    root_id: str = Query(..., description="ID of the root node"),
    depth: int = Query(1, ge=1, le=5, description="Depth of relationships to traverse"),
    db: AsyncSession = Depends(get_db_session),
    ctx: DatasetContext = Depends(get_dataset_context),
):
    """Returns nodes and edges reachable from the root in graph form."""
    logger.info("API /subgraph — root_type=%s root_id=%s depth=%d", root_type, root_id, depth)
    repo = GraphRepository(db, ctx.package.graph_dataset())
    result = await repo.get_subgraph(root_type, root_id, depth)
    logger.info("API /subgraph — returning nodes=%d edges=%d", len(result.nodes), len(result.edges))
    return result

@router.get("/schema", response_model=GraphSchemaResponse)
async def get_graph_schema(ctx: DatasetContext = Depends(get_dataset_context)):
    """Describes the active dataset: domain, node types, edge types and flows.

    Counts are not included; join with /summary. Needs no database access.
    """
    dataset = ctx.package.graph_dataset()
    logger.info(
        "API /schema — dataset=%s node_types=%d edge_types=%d flows=%d",
        dataset.id, len(dataset.node_types), len(dataset.edge_types), len(dataset.flows),
    )
    return dataset.to_schema_response()

@router.get("/flows", response_model=FlowListResponse)
async def list_flows(ctx: DatasetContext = Depends(get_dataset_context)):
    """Returns the predefined flow definitions of the active dataset."""
    flows = list(ctx.package.graph_dataset().flows)
    logger.info("API /flows — returning %d flow definitions", len(flows))
    return FlowListResponse(flows=flows)

@router.get("/flow", response_model=GraphSubgraphResponse)
async def get_flow(
    flow_id: str = Query(..., description="Flow identifier (e.g., full_o2c, sales, billing)"),
    limit: int = Query(50, ge=1, le=200, description="Max nodes per edge bucket"),
    db: AsyncSession = Depends(get_db_session),
    ctx: DatasetContext = Depends(get_dataset_context),
):
    """Returns a sampled subgraph for a predefined flow of the active dataset."""
    logger.info("API /flow — flow_id=%s limit=%d", flow_id, limit)
    if ctx.package.graph_dataset().get_flow(flow_id) is None:
        logger.warning("API /flow — unknown flow_id=%s", flow_id)
        raise HTTPException(status_code=404, detail=f"Unknown flow: {flow_id}")
    repo = GraphRepository(db, ctx.package.graph_dataset())
    result = await repo.get_flow(flow_id, limit)
    logger.info("API /flow — flow_id=%s returning nodes=%d edges=%d", flow_id, len(result.nodes), len(result.edges))
    return result

@router.get("/trace", response_model=GraphSubgraphResponse)
async def trace_document(
    doc_type: str = Query(..., description="Type of the document to trace (e.g., Invoice)"),
    doc_id: str = Query(..., description="ID of the document"),
    depth: int = Query(4, ge=1, le=5, description="Traversal depth"),
    db: AsyncSession = Depends(get_db_session),
    ctx: DatasetContext = Depends(get_dataset_context),
):
    """Traces the full lifecycle (all connected entities) for a given document."""
    logger.info("API /trace — doc_type=%s doc_id=%s depth=%d", doc_type, doc_id, depth)
    repo = GraphRepository(db, ctx.package.graph_dataset())
    result = await repo.get_subgraph(doc_type, doc_id, depth)
    logger.info("API /trace — returning nodes=%d edges=%d", len(result.nodes), len(result.edges))
    return result

@router.get("/full", response_model=GraphSubgraphResponse)
async def get_full_graph(
    node_limit: int = Query(20, ge=1, le=500, description="Max entities sampled per node type"),
    type_filter: Optional[str] = Query(None, description="Comma-separated node types to include"),
    db: AsyncSession = Depends(get_db_session),
    ctx: DatasetContext = Depends(get_dataset_context),
):
    """Returns a sampled knowledge graph across all entity types."""
    logger.info("API /full — node_limit=%d type_filter=%s", node_limit, type_filter)
    types = [t.strip() for t in type_filter.split(",")] if type_filter else None
    repo = GraphRepository(db, ctx.package.graph_dataset())
    result = await repo.get_full_graph(node_limit, types)
    logger.info("API /full — returning nodes=%d edges=%d", len(result.nodes), len(result.edges))
    return result

@router.get("/entities/{node_type}", response_model=GraphEntityResponse)
async def get_entities(
    node_type: str,
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session),
    ctx: DatasetContext = Depends(get_dataset_context),
):
    """Returns a sample of entity IDs for a given type."""
    logger.info("API /entities — node_type=%s limit=%d", node_type, limit)
    repo = GraphRepository(db, ctx.package.graph_dataset())
    result = await repo.get_entities(node_type, limit)
    logger.info("API /entities — node_type=%s returning %d entities", node_type, len(result.entities))
    return result

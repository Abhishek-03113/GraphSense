from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.session import get_db_session
from src.domain.graph_models import GraphSummaryResponse, GraphSubgraphResponse, GraphEntityResponse, FlowListResponse, FlowDefinition
from src.domain.flow_definitions import FLOW_DEFINITIONS
from src.repositories.graph_repository import GraphRepository
from src.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/graph", tags=["graph"])

@router.get("/summary", response_model=GraphSummaryResponse)
async def get_graph_summary(db: AsyncSession = Depends(get_db_session)):
    """Returns an overview of the dataset sizes (node and edge counts)."""
    logger.info("API /summary — called")
    repo = GraphRepository(db)
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
    db: AsyncSession = Depends(get_db_session)
):
    """Returns nodes and edges reachable from the root in graph form."""
    logger.info("API /subgraph — root_type=%s root_id=%s depth=%d", root_type, root_id, depth)
    repo = GraphRepository(db)
    try:
        result = await repo.get_subgraph(root_type, root_id, depth)
        logger.info("API /subgraph — returning nodes=%d edges=%d", len(result.nodes), len(result.edges))
        return result
    except Exception as e:
        logger.error("API /subgraph — FAILED: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/flows", response_model=FlowListResponse)
async def list_flows():
    """Returns the available predefined O2C flow definitions."""
    flows = [FlowDefinition(**defn) for defn in FLOW_DEFINITIONS.values()]
    logger.info("API /flows — returning %d flow definitions", len(flows))
    return FlowListResponse(flows=flows)

@router.get("/flow", response_model=GraphSubgraphResponse)
async def get_flow(
    flow_id: str = Query(..., description="Flow identifier (e.g., full_o2c, sales, billing)"),
    limit: int = Query(50, ge=1, le=200, description="Max nodes per edge bucket"),
    db: AsyncSession = Depends(get_db_session)
):
    """Returns a sampled subgraph for a predefined O2C flow."""
    logger.info("API /flow — flow_id=%s limit=%d", flow_id, limit)
    if flow_id not in FLOW_DEFINITIONS:
        logger.warning("API /flow — unknown flow_id=%s", flow_id)
        raise HTTPException(status_code=404, detail=f"Unknown flow: {flow_id}")
    repo = GraphRepository(db)
    try:
        result = await repo.get_flow(flow_id, limit)
        logger.info("API /flow — flow_id=%s returning nodes=%d edges=%d", flow_id, len(result.nodes), len(result.edges))
        return result
    except Exception as e:
        logger.error("API /flow — flow_id=%s FAILED: %s", flow_id, e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/trace", response_model=GraphSubgraphResponse)
async def trace_document(
    doc_type: str = Query(..., description="Type of the document to trace (e.g., Invoice)"),
    doc_id: str = Query(..., description="ID of the document"),
    depth: int = Query(4, ge=1, le=5, description="Traversal depth"),
    db: AsyncSession = Depends(get_db_session)
):
    """Traces the full O2C lifecycle for a given document."""
    logger.info("API /trace — doc_type=%s doc_id=%s depth=%d", doc_type, doc_id, depth)
    repo = GraphRepository(db)
    try:
        result = await repo.get_subgraph(doc_type, doc_id, depth)
        logger.info("API /trace — returning nodes=%d edges=%d", len(result.nodes), len(result.edges))
        return result
    except Exception as e:
        logger.error("API /trace — FAILED: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/full", response_model=GraphSubgraphResponse)
async def get_full_graph(
    node_limit: int = Query(20, ge=1, le=100, description="Max entities sampled per node type"),
    type_filter: Optional[str] = Query(None, description="Comma-separated node types to include"),
    db: AsyncSession = Depends(get_db_session)
):
    """Returns a sampled knowledge graph across all entity types."""
    logger.info("API /full — node_limit=%d type_filter=%s", node_limit, type_filter)
    types = [t.strip() for t in type_filter.split(",")] if type_filter else None
    repo = GraphRepository(db)
    try:
        result = await repo.get_full_graph(node_limit, types)
        logger.info("API /full — returning nodes=%d edges=%d", len(result.nodes), len(result.edges))
        return result
    except Exception as e:
        logger.error("API /full — FAILED: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/entities/{node_type}", response_model=GraphEntityResponse)
async def get_entities(
    node_type: str,
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session)
):
    """Returns a sample of entity IDs for a given type."""
    logger.info("API /entities — node_type=%s limit=%d", node_type, limit)
    repo = GraphRepository(db)
    result = await repo.get_entities(node_type, limit)
    logger.info("API /entities — node_type=%s returning %d entities", node_type, len(result.entities))
    return result

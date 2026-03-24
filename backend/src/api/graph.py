from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.session import get_db_session
from src.domain.graph_models import GraphSummaryResponse, GraphSubgraphResponse, GraphEntityResponse
from src.repositories.graph_repository import GraphRepository

router = APIRouter(prefix="/api/graph", tags=["graph"])

@router.get("/summary", response_model=GraphSummaryResponse)
async def get_graph_summary(db: AsyncSession = Depends(get_db_session)):
    """Returns an overview of the dataset sizes (node and edge counts)."""
    repo = GraphRepository(db)
    return await repo.get_summary()

@router.get("/subgraph", response_model=GraphSubgraphResponse)
async def get_graph_subgraph(
    root_type: str = Query(..., description="Type of the root node (e.g., SalesOrder)"),
    root_id: str = Query(..., description="ID of the root node"),
    depth: int = Query(1, ge=1, le=3, description="Depth of relationships to traverse"),
    db: AsyncSession = Depends(get_db_session)
):
    """Returns nodes and edges reachable from the root in graph form."""
    repo = GraphRepository(db)
    try:
        return await repo.get_subgraph(root_type, root_id, depth)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/entities/{node_type}", response_model=GraphEntityResponse)
async def get_entities(
    node_type: str,
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db_session)
):
    """Returns a sample of entity IDs for a given type."""
    repo = GraphRepository(db)
    return await repo.get_entities(node_type, limit)

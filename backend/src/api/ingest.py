from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel
import os
from ..ingestion.jsonl_loader import ingest_data
import structlog

router = APIRouter(prefix="/api/ingest", tags=["ingestion"])
logger = structlog.get_logger()

class IngestRequest(BaseModel):
    data_dir: str = "/Users/techverito/DodgeAI/data/sap-o2c-data"

@router.post("")
async def trigger_ingestion(request: IngestRequest, background_tasks: BackgroundTasks):
    """Trigger data ingestion as a background task."""
    if not os.path.exists(request.data_dir):
        raise HTTPException(status_code=400, detail=f"Data directory not found: {request.data_dir}")
    
    background_tasks.add_task(ingest_data, request.data_dir)
    return {"message": "Ingestion started in background"}

"""Chat API endpoint for the conversational query interface."""

from pydantic import BaseModel, Field
from fastapi import APIRouter

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


class GraphNodeRef(BaseModel):
    id: str    # "{type}:{value}", e.g. "Invoice:90000001"
    type: str  # e.g. "Invoice"
    label: str # e.g. "90000001"


class ChatResponseModel(BaseModel):
    answer: str
    sql: str | None = None
    data: list[dict] | None = None
    entities: list[dict] = Field(default_factory=list)
    graph_nodes: list[GraphNodeRef] = Field(default_factory=list)
    error: str | None = None
    row_count: int = 0
    summary: str = ""


class TrainResponse(BaseModel):
    status: str
    counts: dict[str, int]


@router.post("", response_model=ChatResponseModel)
async def handle_chat(request: ChatRequest):
    """Process a natural language question about the O2C dataset."""
    from src.ai.chat import chat

    result = chat(request.message)
    return ChatResponseModel(
        answer=result.answer,
        sql=result.sql,
        data=result.data,
        entities=result.entities,
        graph_nodes=[GraphNodeRef(**n) for n in result.graph_nodes],
        error=result.error,
        row_count=result.row_count,
        summary=result.summary,
    )


@router.post("/train", response_model=TrainResponse)
async def train_model():
    """Trigger (re-)training of the RAG pipeline with DDL, docs, and SQL pairs."""
    from src.ai.training import train_all

    counts = train_all()
    return TrainResponse(status="ok", counts=counts)

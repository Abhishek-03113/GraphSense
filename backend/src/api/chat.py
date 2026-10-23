"""Chat API: ask a question about the dataset in plain language.

``POST /api/chat`` keeps the original eight response fields (``answer``, ``sql``,
``data``, ``entities``, ``graph_nodes``, ``error``, ``row_count``, ``summary``);
the rest are additive.  ``error`` is ``null`` or a stable code: ``guardrail``,
``not_configured``, ``sql_generation_failed``, ``sql_rejected``,
``sql_execution_error: <timeout|syntax|unknown_column|unknown_table|type|other>``,
``provider_unavailable``, ``rate_limited``, ``dataset_not_ready`` or ``internal_error``.
Internal detail (SQL errors, provider messages) is logged, never returned.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.api.deps import get_dataset_context
from src.api.errors import REQUEST_ID_HEADER, current_request_id
from src.api.ratelimit import client_address, get_chat_limiter
from src.datasets.context import DatasetContext
from src.intelligence.models import AskResult, ErrorCode
from src.intelligence.runtime import get_ask_service
from src.intelligence.service import AskService

router = APIRouter(prefix="/api/chat", tags=["chat"])

RATE_LIMITED_MESSAGE = "You're asking questions faster than they can be answered. Please wait a moment and try again."


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


class GraphNodeRef(BaseModel):
    id: str  # "{type}:{value}", e.g. "Book:978-0"
    type: str
    label: str


class EntityRefModel(BaseModel):
    id: str
    type: str
    value: str


class ChatColumn(BaseModel):
    name: str
    label: str | None = None
    role: str | None = None
    value_labels: dict[str, str] | None = None


class ChatResponseModel(BaseModel):
    # --- the original fields ---------------------------------------------
    answer: str
    sql: str | None = None
    data: list[dict[str, Any]] | None = None
    entities: list[EntityRefModel] = Field(default_factory=list)
    graph_nodes: list[GraphNodeRef] = Field(default_factory=list)
    error: str | None = None
    row_count: int = 0
    summary: str = ""
    # --- additive fields -------------------------------------------------
    query_id: str | None = None
    mode: str = "disabled"  # full | degraded | disabled
    columns: list[ChatColumn] = Field(default_factory=list)
    truncated: bool = False
    warnings: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


def to_response(result: AskResult) -> ChatResponseModel:
    return ChatResponseModel(
        answer=result.answer,
        sql=result.sql,
        data=result.rows,
        entities=[EntityRefModel(id=e.id, type=e.type, value=e.value) for e in result.entities],
        graph_nodes=[GraphNodeRef(id=n.id, type=n.type, label=n.label) for n in result.graph_nodes],
        error=result.error,
        row_count=result.row_count,
        summary=result.summary,
        query_id=result.query_id,
        mode=result.mode,
        columns=[
            ChatColumn(name=c.name, label=c.label, role=c.role, value_labels=c.value_labels) for c in result.columns
        ],
        truncated=result.truncated,
        warnings=result.warnings,
        assumptions=result.assumptions,
        suggestions=result.suggestions,
    )


@router.post("", response_model=ChatResponseModel)
async def handle_chat(
    body: ChatRequest,
    request: Request,
    ctx: DatasetContext = Depends(get_dataset_context),
    service: AskService = Depends(get_ask_service),
):
    """Answer a natural-language question about the selected dataset."""
    address = client_address(request)
    retry_after = get_chat_limiter().check(address)
    if retry_after is not None:
        request_id = current_request_id(request)
        content = ChatResponseModel(
            answer=RATE_LIMITED_MESSAGE, error=ErrorCode.RATE_LIMITED, mode=service.mode
        ).model_dump()
        # The envelope fields let clients that only know the common error shape cope too.
        content.update({"detail": RATE_LIMITED_MESSAGE, "code": ErrorCode.RATE_LIMITED, "request_id": request_id})
        headers = {"Retry-After": str(max(1, int(retry_after + 0.999)))}
        if request_id:
            headers[REQUEST_ID_HEADER] = request_id
        return JSONResponse(status_code=429, content=content, headers=headers)

    result = await service.ask(ctx, body.message, client_id=address)
    return to_response(result)


@router.post("/train", include_in_schema=True)
async def train_model():
    """Gone: knowledge is refreshed after ingestion or with ``graphsense knowledge refresh``."""
    raise HTTPException(
        status_code=410,
        detail="Training was replaced. Knowledge is refreshed automatically after a data load; "
        "operators can run `graphsense knowledge refresh <dataset>`.",
    )

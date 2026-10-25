"""Chat API: ask a question about the dataset in plain language.

``POST /api/chat/messages`` keeps the original eight response fields (``answer``, ``sql``,
``data``, ``entities``, ``graph_nodes``, ``error``, ``row_count``, ``summary``);
the rest are additive.  ``error`` is ``null`` or a stable code: ``guardrail``,
``not_configured``, ``sql_generation_failed``, ``sql_rejected``,
``sql_execution_error: <timeout|syntax|unknown_column|unknown_table|type|other>``,
``provider_unavailable``, ``rate_limited``, ``dataset_not_ready`` or ``internal_error``.
Internal detail (SQL errors, provider messages) is logged, never returned.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.api.deps import get_dataset_context
from src.api.errors import REQUEST_ID_HEADER, current_request_id
from src.api.ratelimit import client_address, get_chat_limiter
from src.config import get_settings
from src.datasets.context import DatasetContext
from src.datasets.errors import UnknownDatasetError
from src.datasets.registry import default_dataset_id, get_package
from src.intelligence.models import AskResult, ErrorCode
from src.intelligence.runtime import get_ask_service
from src.utils.logger import get_logger
from src.intelligence.service import AskService

logger = get_logger(__name__)
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


@router.post("/messages", response_model=ChatResponseModel)
async def handle_chat(
    body: ChatRequest,
    request: Request,
    ctx: Annotated[DatasetContext, Depends(get_dataset_context)],
    service: Annotated[AskService, Depends(get_ask_service)],
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


def _origin_allowed(origin: str | None) -> bool:
    """Browsers do not apply CORS to WebSockets, so the server checks the Origin itself."""
    if not origin:
        return True  # not a browser
    allowed = get_settings().cors_origins()
    return "*" in allowed or origin in allowed


@router.websocket("/ws")
async def chat_socket(websocket: WebSocket):
    """Ask over one long-lived connection, with progress and the answer streamed back.

    Client -> server (JSON text frames)::

        {"type": "ask", "id": "<client id>", "message": "..."}
        {"type": "cancel", "id": "<client id>"}
        {"type": "ping"}

    Server -> client, every frame except ``pong`` carries the ``id`` of the question::

        {"type": "status", "id": ..., "stage": "retrieving|writing_query|running_query|answering"}
        {"type": "delta",  "id": ..., "text": "..."}      # a piece of the answer
        {"type": "result", "id": ..., "result": <same body as POST /api/chat/messages>}
        {"type": "error",  "id": ..., "code": "...", "detail": "..."}
        {"type": "cancelled", "id": ...}

    The dataset is chosen with ``?dataset=`` when connecting.  One question runs at a time
    per connection; ``result`` replaces whatever the deltas built up.
    """
    if not _origin_allowed(websocket.headers.get("origin")):
        await websocket.close(code=1008)
        return
    dataset_id = websocket.query_params.get("dataset") or default_dataset_id()
    try:
        package = get_package(dataset_id)
    except UnknownDatasetError:
        await websocket.close(code=1008, reason="unknown dataset")
        return
    ctx = DatasetContext(id=package.id, schema_name=package.schema_name, package=package)
    service = get_ask_service()
    address = client_address(websocket)  # type: ignore[arg-type]
    await websocket.accept()

    send_lock = asyncio.Lock()
    current: tuple[str, asyncio.Task] | None = None

    async def send(frame: dict[str, Any]) -> None:
        async with send_lock:
            await websocket.send_json(frame)

    async def run(question_id: str, message: str) -> None:
        retry_after = get_chat_limiter().check(address)
        if retry_after is not None:
            limited = ChatResponseModel(
                answer=RATE_LIMITED_MESSAGE, error=ErrorCode.RATE_LIMITED, mode=service.mode
            ).model_dump()
            await send({"type": "result", "id": question_id, "result": limited,
                        "retry_after": max(1, int(retry_after + 0.999))})
            return

        async def emit(event: dict[str, Any]) -> None:
            await send({**event, "id": question_id})

        try:
            result = await service.ask(ctx, message, client_id=address, emit=emit)
            await send({"type": "result", "id": question_id, "result": to_response(result).model_dump()})
        except asyncio.CancelledError:
            with contextlib.suppress(Exception):
                await send({"type": "cancelled", "id": question_id})
            raise
        except WebSocketDisconnect:
            raise
        except Exception:
            logger.exception("Chat socket failed while answering")
            await send({"type": "error", "id": question_id, "code": ErrorCode.INTERNAL_ERROR,
                        "detail": "An unexpected error occurred while processing your question. Please try again."})

    try:
        while True:
            try:
                frame = await websocket.receive_json()
            except ValueError:
                await send({"type": "error", "id": None, "code": "bad_request", "detail": "Send JSON frames."})
                continue
            kind = frame.get("type") if isinstance(frame, dict) else None
            question_id = str(frame.get("id", "")) if isinstance(frame, dict) else ""
            if kind == "ping":
                await send({"type": "pong"})
            elif kind == "cancel":
                if current and current[0] == question_id and not current[1].done():
                    current[1].cancel()
            elif kind == "ask":
                message = frame.get("message")
                if not question_id or not isinstance(message, str) or not 1 <= len(message) <= 2000:
                    await send({"type": "error", "id": question_id or None, "code": "bad_request",
                                "detail": "An ask needs an id and a message of 1 to 2000 characters."})
                elif current and not current[1].done():
                    await send({"type": "error", "id": question_id, "code": "busy",
                                "detail": "Wait for the current question to finish."})
                else:
                    current = (question_id, asyncio.create_task(run(question_id, message)))
            else:
                await send({"type": "error", "id": question_id or None, "code": "bad_request",
                            "detail": "Unknown frame type."})
    except WebSocketDisconnect:
        pass
    finally:
        if current and not current[1].done():
            current[1].cancel()
            with contextlib.suppress(BaseException):
                await current[1]

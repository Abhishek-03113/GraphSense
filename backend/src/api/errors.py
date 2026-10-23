"""Request ids and the API error envelope.

Every response carries an ``X-Request-ID`` header.  Failures are reported as::

    {"detail": "<short human text>", "code": "<stable machine code>", "request_id": "<id>"}

``detail`` keeps its place as a plain string so clients that only read
``detail`` keep working.  Internal error text (SQL, driver messages, stack
traces) never reaches a response; it goes to the log together with the
request id so an operator can find it.
"""

from __future__ import annotations

import re
import uuid
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.utils.logger import get_logger, request_id_var

logger = get_logger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
INTERNAL_ERROR_DETAIL = "Something went wrong."

# An inbound id is only trusted when it cannot be used to forge log lines.
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

_STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    410: "gone",
    413: "payload_too_large",
    422: "validation_error",
    429: "rate_limited",
}


def error_code_for(status_code: int) -> str:
    """Stable machine code for an HTTP status."""
    if status_code in _STATUS_CODES:
        return _STATUS_CODES[status_code]
    if status_code >= 500:
        return "internal_error"
    return "error"


def current_request_id(request: Request) -> str | None:
    state = request.scope.get("state") or {}
    return state.get("request_id")


class RequestIdMiddleware:
    """Assigns a request id, exposes it to handlers and logs, and echoes it in the response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        inbound = ""
        for name, value in scope.get("headers") or []:
            if name == b"x-request-id":
                inbound = value.decode("latin-1")
                break
        request_id = inbound if _SAFE_REQUEST_ID.match(inbound) else uuid.uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        token = request_id_var.set(request_id)

        async def send_with_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [
                    (k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"
                ]
                headers.append((REQUEST_ID_HEADER.lower().encode(), request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            request_id_var.reset(token)


def _envelope(
    status_code: int,
    detail: str,
    code: str,
    request_id: str | None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    out_headers = dict(headers or {})
    if request_id:
        out_headers[REQUEST_ID_HEADER] = request_id
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail, "code": code, "request_id": request_id},
        headers=out_headers,
    )


async def _http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    request_id = current_request_id(request)
    if exc.status_code >= 500:
        logger.error(
            "HTTP %d on %s %s: %s", exc.status_code, request.method, request.url.path, exc.detail
        )
        return _envelope(
            exc.status_code, INTERNAL_ERROR_DETAIL, "internal_error", request_id, exc.headers
        )
    if isinstance(exc.detail, str) and exc.detail:
        detail = exc.detail
    else:
        detail = HTTPStatus(exc.status_code).phrase
    return _envelope(
        exc.status_code, detail, error_code_for(exc.status_code), request_id, exc.headers
    )


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = current_request_id(request)
    logger.error(
        "Unhandled %s on %s %s",
        type(exc).__name__,
        request.method,
        request.url.path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    return _envelope(500, INTERNAL_ERROR_DETAIL, "internal_error", request_id)


def install_error_handling(app: FastAPI) -> None:
    """Register the request id middleware and the error handlers on ``app``."""
    app.add_middleware(RequestIdMiddleware)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unhandled_exception_handler)

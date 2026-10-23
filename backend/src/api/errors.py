"""Request ids and the API error envelope.

Every response carries an ``X-Request-ID`` header.  Failures are reported as::

    {"detail": "<short human text>", "code": "<stable machine code>", "request_id": "<id>"}

``detail`` keeps its place as a plain string so clients that only read
``detail`` keep working.  Internal error text (SQL, driver messages, stack
traces) never reaches a response; it goes to the log together with the
request id so an operator can find it.

Two cases have their own shape or status:

* Request validation failures answer 422 with ``code: "validation_error"``; ``detail`` stays
  FastAPI's list of problems.
* A dataset whose tables are not loaded answers 409 ``dataset_not_ready`` (see
  :mod:`src.storage.readiness`).

Unexpected exceptions are turned into the generic 500 envelope by
:class:`CatchAllMiddleware`, which does not re-raise.  Starlette's own catch-all handler
sends the reply and then re-raises so the server can log it; uvicorn then drops the
keep-alive connection, which a browser sees as a failed follow-up request.
"""

from __future__ import annotations

import re
import uuid
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware import Middleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.storage.readiness import DATASET_NOT_READY_MESSAGE, DatasetNotReady, is_missing_relation
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


async def _validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """422 with the envelope fields; ``detail`` stays FastAPI's list of problems."""
    request_id = current_request_id(request)
    headers = {REQUEST_ID_HEADER: request_id} if request_id else None
    return JSONResponse(
        status_code=422,
        content={
            "detail": jsonable_encoder(exc.errors()),
            "code": "validation_error",
            "request_id": request_id,
        },
        headers=headers,
    )


def _dataset_not_ready(request_id: str | None) -> JSONResponse:
    return _envelope(409, DATASET_NOT_READY_MESSAGE, "dataset_not_ready", request_id)


def _log_unhandled(method: str, path: str, exc: BaseException) -> None:
    logger.error(
        "Unhandled %s on %s %s",
        type(exc).__name__,
        method,
        path,
        exc_info=(type(exc), exc, exc.__traceback__),
    )


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Backstop for errors raised outside :class:`CatchAllMiddleware` (it normally gets there first)."""
    request_id = current_request_id(request)
    if is_missing_relation(exc):
        return _dataset_not_ready(request_id)
    _log_unhandled(request.method, request.url.path, exc)
    return _envelope(500, INTERNAL_ERROR_DETAIL, "internal_error", request_id)


async def _database_exception_handler(request: Request, exc: DBAPIError) -> JSONResponse:
    """Graph queries on a dataset with no loaded tables are 409, other database errors are 500."""
    return await _unhandled_exception_handler(request, exc)


async def _dataset_not_ready_handler(request: Request, exc: DatasetNotReady) -> JSONResponse:
    return _dataset_not_ready(current_request_id(request))


class CatchAllMiddleware:
    """Turns any uncaught exception into the 500 envelope and does not re-raise it.

    It sits innermost (inside CORS, so the error reply carries CORS headers too) and
    only sees what the exception handlers did not take.  When the response has already
    started there is nothing sensible left to send, so the exception propagates and the
    server closes the connection.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = False

        async def tracking_send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception as exc:
            if started:
                raise
            request_id = (scope.get("state") or {}).get("request_id")
            if is_missing_relation(exc):
                response = _dataset_not_ready(request_id)
            else:
                _log_unhandled(scope.get("method", "?"), scope.get("path", "?"), exc)
                response = _envelope(500, INTERNAL_ERROR_DETAIL, "internal_error", request_id)
            await response(scope, receive, send)


def install_error_handling(app: FastAPI) -> None:
    """Register the request id middleware, the catch-all and the error handlers on ``app``."""
    app.add_middleware(RequestIdMiddleware)
    # Innermost on purpose: wrapped by CORS and the request id, however the app was configured.
    app.user_middleware.append(Middleware(CatchAllMiddleware))
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _validation_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(DatasetNotReady, _dataset_not_ready_handler)  # type: ignore[arg-type]
    app.add_exception_handler(DBAPIError, _database_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unhandled_exception_handler)

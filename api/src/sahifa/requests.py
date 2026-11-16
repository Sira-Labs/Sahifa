"""A reference on every answer, and the last guard for unexpected errors (spec 023).

Every HTTP answer carries `X-Request-ID`. An error no handler took is logged as `api.error`
with that reference and answered with a 500 that names it, so the person at the screen can
give the operator something to search the log for.
"""

from __future__ import annotations

import json
import re
import uuid

import structlog
from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .logging import get_logger

log = get_logger("sahifa")

REQUEST_ID_HEADER = "X-Request-ID"
# What a caller (a proxy in front of Sahifa) may set: anything else is replaced, so no line
# break or oversized value reaches the log or the answer.
ACCEPTED_ID = re.compile(r"[A-Za-z0-9._-]{8,64}")
INTERNAL_ERROR_MESSAGE = (
    "Sahifa hit an error it did not expect. "
    "Whoever runs this install finds it in the API's log under the reference."
)
DETAIL_CHARS = 300


def request_id_of(headers: Headers) -> str:
    """The caller's reference when it has the accepted form, else a new one."""
    given = headers.get(REQUEST_ID_HEADER, "")
    return given if ACCEPTED_ID.fullmatch(given) else uuid.uuid4().hex


def internal_error_body(request_id: str) -> bytes:
    return json.dumps(
        {"detail": "internal_error", "message": INTERNAL_ERROR_MESSAGE, "request_id": request_id}
    ).encode()


class RequestIdMiddleware:
    """Puts the reference on every HTTP answer, binds it to the log lines of the request, and
    logs and answers what no handler took."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = request_id_of(Headers(scope=scope))
        scope.setdefault("state", {})["request_id"] = request_id
        # The path only: a query string may carry what a person typed.
        where = {"request_id": request_id, "method": scope["method"], "path": scope["path"]}
        status = 0

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        with structlog.contextvars.bound_contextvars(request_id=request_id):
            try:
                await self.app(scope, receive, send_with_id)
            except Exception as e:  # the last guard: whatever no handler took
                detail = str(e)[:DETAIL_CHARS]
                log.error("api.error", **where, error=type(e).__name__, detail=detail, exc_info=True)
                if status:
                    # The answer has started (a stream): nothing more can be said to the caller.
                    raise
                body = internal_error_body(request_id)
                await send_with_id(
                    {
                        "type": "http.response.start",
                        "status": 500,
                        "headers": [
                            (b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode()),
                        ],
                    }
                )
                await send({"type": "http.response.body", "body": body})
                return
            if status >= 500:
                log.error("api.error", **where, status=status)

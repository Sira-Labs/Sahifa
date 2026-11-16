"""The request reference and the last guard for unexpected errors (spec 023)."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route
from starlette.types import ASGIApp

from sahifa import requests as requests_module
from sahifa.main import create_app
from sahifa.requests import ACCEPTED_ID, REQUEST_ID_HEADER, RequestIdMiddleware
from sahifa.security import MB, BodyLimitMiddleware, SecurityHeadersMiddleware
from sahifa.settings import Settings

HEX_ID = re.compile(r"[0-9a-f]{32}")


class ErrorLog:
    """Stands in for the module's logger and keeps what was logged as an error."""

    def __init__(self) -> None:
        self.lines: list[dict[str, Any]] = []

    def error(self, event: str, **fields: Any) -> None:
        self.lines.append({"event": event, **fields})


@pytest.fixture
def errors(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    recorder = ErrorLog()
    monkeypatch.setattr(requests_module, "log", recorder)
    return recorder.lines


async def fine(request: Request) -> Response:
    return JSONResponse({"request_id": request.state.request_id})


async def boom(request: Request) -> Response:
    raise RuntimeError("the disk said no")


async def unavailable(request: Request) -> Response:
    return JSONResponse({"detail": "down"}, status_code=503)


async def broken_stream(request: Request) -> Response:
    async def parts() -> AsyncIterator[bytes]:
        yield b"first"
        raise RuntimeError("cut off")

    return StreamingResponse(parts())


def small_app() -> ASGIApp:
    """The middleware order of the real app: headers outside, the reference, then a limit."""
    app = Starlette(
        routes=[
            Route("/fine", fine, methods=["GET", "POST"]),
            Route("/boom", boom),
            Route("/unavailable", unavailable),
            Route("/stream", broken_stream),
        ]
    )
    app.add_middleware(
        BodyLimitMiddleware,
        default_bytes=10,
        limits={},
        disk_dir=Path("."),
        disk_paths=frozenset(),
        min_free_bytes=0,
    )
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, docs_enabled=False)
    return app


def client_for(app: ASGIApp) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_every_answer_has_a_reference() -> None:
    async with client_for(small_app()) as c:
        ok = await c.get("/fine")
        missing = await c.get("/nowhere")
    assert HEX_ID.fullmatch(ok.headers[REQUEST_ID_HEADER])
    assert ok.json() == {"request_id": ok.headers[REQUEST_ID_HEADER]}
    assert missing.status_code == 404 and HEX_ID.fullmatch(missing.headers[REQUEST_ID_HEADER])
    assert ok.headers[REQUEST_ID_HEADER] != missing.headers[REQUEST_ID_HEADER]


@pytest.mark.parametrize(
    ("given", "kept"),
    [
        ("proxy-7f3a9c21", True),
        ("0123456789abcdef0123456789abcdef", True),
        ("a.b_c-d1", True),
        ("short", False),
        ("x" * 65, False),
        ("has a space in it", False),
        ("semi;colon-and-more", False),
        ("", False),
    ],
)
async def test_callers_reference_is_kept_or_replaced(given: str, kept: bool) -> None:
    async with client_for(small_app()) as c:
        r = await c.get("/fine", headers={REQUEST_ID_HEADER: given})
    answered = r.headers[REQUEST_ID_HEADER]
    assert (answered == given) is kept
    assert ACCEPTED_ID.fullmatch(answered)


async def test_unexpected_error_is_answered_and_logged(errors: list[dict[str, Any]]) -> None:
    async with client_for(small_app()) as c:
        r = await c.get("/boom?email=someone@example.com")
    assert r.status_code == 500
    reference = r.headers[REQUEST_ID_HEADER]
    body = r.json()
    assert body["detail"] == "internal_error" and body["request_id"] == reference
    assert "reference" in body["message"] and "disk" not in r.text
    assert r.headers["x-content-type-options"] == "nosniff"
    assert len(errors) == 1
    line = errors[0]
    assert line["event"] == "api.error" and line["request_id"] == reference
    assert (line["method"], line["path"], line["error"]) == ("GET", "/boom", "RuntimeError")
    assert line["detail"] == "the disk said no" and line["exc_info"] is True
    assert "someone@example.com" not in str(line)


async def test_error_status_without_exception_is_logged(errors: list[dict[str, Any]]) -> None:
    async with client_for(small_app()) as c:
        r = await c.get("/unavailable")
        await c.get("/fine")
        await c.get("/nowhere")
    assert errors == [
        {
            "event": "api.error",
            "request_id": r.headers[REQUEST_ID_HEADER],
            "method": "GET",
            "path": "/unavailable",
            "status": 503,
        }
    ]


async def test_limits_answer_with_a_reference() -> None:
    async with client_for(small_app()) as c:
        r = await c.post("/fine", content=b"x" * 11)
    assert r.status_code == 413 and HEX_ID.fullmatch(r.headers[REQUEST_ID_HEADER])


async def test_an_error_after_the_answer_started_is_logged_and_raised(errors: list[dict[str, Any]]) -> None:
    async with client_for(small_app()) as c:
        with pytest.raises(RuntimeError, match="cut off"):
            await c.get("/stream")
    assert [(line["event"], line["path"]) for line in errors] == [("api.error", "/stream")]


async def test_the_app_answers_with_a_reference(tmp_path: Path) -> None:
    """The real app, without a database: the public routes and a refused one carry it."""
    app = create_app(Settings(data_dir=tmp_path, env="dev", rate_limits=False))
    async with client_for(app) as c:
        version = await c.get("/api/version", headers={REQUEST_ID_HEADER: "from-the-proxy-1"})
        too_large = await c.post("/api/scans/demo", content=b"x" * (MB + 1))
    assert version.headers[REQUEST_ID_HEADER] == "from-the-proxy-1"
    assert too_large.status_code == 413 and HEX_ID.fullmatch(too_large.headers[REQUEST_ID_HEADER])

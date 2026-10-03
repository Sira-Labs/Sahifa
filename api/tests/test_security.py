"""Security baseline (spec 012): response headers, request size and free disk, upload content
and names, rate limits."""

from __future__ import annotations

import io
import json
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
from starlette.types import ASGIApp

from sahifa import security
from sahifa.db.migrate import upgrade
from sahifa.main import create_app
from sahifa.security import (
    MB,
    BodyLimitMiddleware,
    Bucket,
    RateLimiter,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    bucket_of,
    key_of,
)
from sahifa.services.uploads import clean_file_name, content_matches
from sahifa.settings import Settings

from .conftest import CSRF, DB_URL, needs_db

# --- A small app to test each middleware alone ---------------------------------------------


async def echo(request: Request) -> Response:
    """Reads the whole body like a form parser would; a failed read becomes a 400, as FastAPI does."""
    try:
        body = await request.body()
    except Exception:  # FastAPI answers "There was an error parsing the body"
        return JSONResponse({"detail": "There was an error parsing the body"}, status_code=400)
    return JSONResponse({"bytes": len(body)})


async def cached(request: Request) -> Response:
    return JSONResponse({"ok": True}, headers={"cache-control": "max-age=5"})


def bare() -> Starlette:
    return Starlette(
        routes=[
            Route("/api/echo", echo, methods=["GET", "POST"]),
            Route("/api/scans/upload", echo, methods=["POST"]),
            Route("/api/cached", cached),
            Route("/api/docs", cached),
            Route("/healthz", cached),
        ]
    )


def client_for(app: ASGIApp, client: tuple[str, int] = ("203.0.113.7", 1234)) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app, client=client), base_url="http://t")


async def test_api_headers_are_added_and_route_values_kept() -> None:
    async with client_for(SecurityHeadersMiddleware(bare(), docs_enabled=False)) as c:
        r = await c.get("/api/echo")
        assert r.headers["cache-control"] == "no-store"
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["referrer-policy"] == "no-referrer"
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
        assert (await c.get("/api/cached")).headers["cache-control"] == "max-age=5"
        assert (await c.get("/missing")).headers["x-frame-options"] == "DENY"
        assert "content-security-policy" in (await c.get("/api/docs")).headers
    async with client_for(SecurityHeadersMiddleware(bare(), docs_enabled=True)) as c:
        docs = await c.get("/api/docs")
        assert "content-security-policy" not in docs.headers and docs.headers["x-frame-options"] == "DENY"


def limited(free: int = 10 * 1024 * MB, **kw: Any) -> ASGIApp:
    options: dict[str, Any] = {
        "default_bytes": 100,
        "limits": {"/api/scans/upload": 1000},
        "disk_dir": Path("."),
        "disk_paths": frozenset({"/api/scans/upload"}),
        "min_free_bytes": 500,
        "disk_usage": lambda _p: free,
    } | kw
    return SecurityHeadersMiddleware(BodyLimitMiddleware(bare(), **options), docs_enabled=False)


async def test_declared_body_over_the_limit_is_refused_at_once() -> None:
    async with client_for(limited()) as c:
        assert (await c.post("/api/echo", content=b"x" * 100)).json() == {"bytes": 100}
        r = await c.post("/api/echo", content=b"x" * 101)
        assert r.status_code == 413 and r.json()["detail"] == "too_large"
        assert r.headers["cache-control"] == "no-store"
        assert (await c.post("/api/scans/upload", content=b"x" * 1000)).status_code == 200
        r = await c.post("/api/scans/upload", content=b"x" * 1001)
        assert r.status_code == 413 and r.json()["limit_mb"] == round(1000 / MB, 2)


async def test_streamed_body_is_cut_off_at_the_limit() -> None:
    sent = 0

    async def chunks() -> AsyncIterator[bytes]:
        nonlocal sent
        for _ in range(50):
            sent += 1
            yield b"y" * 60

    async with client_for(limited()) as c:
        r = await c.post("/api/echo", content=chunks())
        # Over the limit after two chunks; the app's 400 for the cut-off body becomes a 413.
        assert r.status_code == 413 and r.json()["detail"] == "too_large"
        assert sent < 50


async def test_low_disk_refuses_an_upload_before_reading_it() -> None:
    async with client_for(limited(free=1200)) as c:
        r = await c.post("/api/scans/upload", content=b"x" * 800)
        assert r.status_code == 507 and r.json()["detail"] == "insufficient_storage"
        assert (await c.post("/api/scans/upload", content=b"x" * 700)).status_code == 200
        # Other routes do not check the disk.
        assert (await c.post("/api/echo", content=b"x" * 10)).status_code == 200


def test_rate_limiter_spends_and_refills() -> None:
    now = [0.0]
    limiter = RateLimiter({"read": Bucket(limit=3, period_s=60)}, clock=lambda: now[0])
    assert [limiter.take("read", "k") for _ in range(3)] == [0, 0, 0]
    assert limiter.take("read", "k") == pytest.approx(20.0)
    assert limiter.take("read", "other") == 0
    now[0] = 20.0
    assert limiter.take("read", "k") == 0
    assert limiter.take("read", "k") == pytest.approx(20.0)


def test_rate_limiter_forgets_refilled_keys() -> None:
    now = [0.0]
    limiter = RateLimiter({"read": Bucket(limit=2, period_s=10)}, clock=lambda: now[0])
    limiter.MAX_KEYS = 3
    for k in "abc":
        limiter.take("read", k)
    now[0] = 100.0
    limiter.take("read", "d")
    assert set(limiter.states) == {("read", "d")}


def test_buckets_and_keys() -> None:
    exempt = frozenset({"/healthz", "/api/version", "/api/auth/backchannel-logout"})
    assert bucket_of("GET", "/healthz", exempt) is None
    assert bucket_of("GET", "/api/version", exempt) is None
    assert bucket_of("POST", "/api/auth/backchannel-logout", exempt) is None
    assert bucket_of("GET", "/assets/app.js", exempt) is None
    assert bucket_of("GET", "/api/auth/login", exempt) == "auth"
    assert bucket_of("GET", "/api/auth/callback", exempt) == "auth"
    assert bucket_of("POST", "/api/scans", exempt) == "scans"
    assert bucket_of("POST", "/api/scans/upload", exempt) == "scans"
    assert bucket_of("PUT", "/api/connections/x/schedule", exempt) == "write"
    assert bucket_of("GET", "/api/scans", exempt) == "read"

    signed_in = {
        "type": "http",
        "client": ("198.51.100.1", 1),
        "headers": [(b"cookie", b"a=1; __Host-sahifa_session=tok")],
    }
    kind, key = key_of(signed_in, "read")
    assert kind == "session" and "tok" not in key and key.startswith("s:")
    assert key_of(signed_in, "auth") == ("address", "a:198.51.100.1")
    assert key_of({"type": "http", "client": ("198.51.100.1", 1), "headers": []}, "read") == (
        "address",
        "a:198.51.100.1",
    )
    assert key_of({"type": "http", "client": None, "headers": []}, "read") == ("address", "a:unknown")


async def test_rate_limit_answers_429_with_retry_after() -> None:
    limiter = RateLimiter({"read": Bucket(limit=2, period_s=60), "auth": Bucket(limit=1, period_s=60)})
    app = SecurityHeadersMiddleware(
        RateLimitMiddleware(bare(), limiter=limiter, exempt=frozenset({"/healthz"})), docs_enabled=False
    )
    async with client_for(app) as c:
        assert [(await c.get("/api/echo")).status_code for _ in range(2)] == [200, 200]
        r = await c.get("/api/echo")
        assert r.status_code == 429 and r.headers["retry-after"] == "30"
        assert r.json() == {
            "detail": "rate_limited",
            "retry_after": 30,
            "message": "Too many requests, try again in 30 s.",
        }
        assert r.headers["cache-control"] == "no-store"
        assert [(await c.get("/healthz")).status_code for _ in range(5)] == [200] * 5
    # Another address has its own bucket.
    async with client_for(app, client=("203.0.113.8", 1)) as c:
        assert (await c.get("/api/echo")).status_code == 200


# --- Upload checks ----------------------------------------------------------------------------


def test_clean_file_name() -> None:
    assert clean_file_name("orders.csv") == "orders.csv"
    assert clean_file_name("C:\\Users\\ana\\orders.csv") == "orders.csv"
    assert clean_file_name("../../etc/passwd.csv") == "passwd.csv"
    assert clean_file_name("in\u202evoice\x07s\n.csv") == "invoices.csv"
    assert clean_file_name("Ünïcödé 名前 ج.csv") == "Ünïcödé 名前 ج.csv"
    long = clean_file_name("a" * 300 + ".parquet")
    assert len(long) == 200 and long.endswith(".parquet")
    assert clean_file_name(None) == clean_file_name("\x00\x01") == "file"


def test_content_matches(tmp_path: Path) -> None:
    def file(name: str, data: bytes) -> Path:
        path = tmp_path / name
        path.write_bytes(data)
        return path

    assert content_matches(file("a.csv", b"id,name\n1,x\n"), ".csv")
    assert not content_matches(file("b.csv", b"MZ\x90\x00\x03"), ".csv")
    assert not content_matches(file("c.csv", "id,name\n".encode("utf-16")), ".csv")
    assert content_matches(file("d.parquet", b"PAR1" + b"\x00" * 20 + b"PAR1"), ".parquet")
    assert not content_matches(file("e.parquet", b"id,name\n1,x\n"), ".parquet")
    assert not content_matches(file("f.parquet", b"PAR1" + b"\x00" * 20), ".parquet")
    assert not content_matches(file("g.parquet", b"PAR1"), ".parquet")


# --- The app ---------------------------------------------------------------------------------


@pytest.fixture
def upgraded() -> Iterator[None]:
    assert DB_URL
    upgrade(DB_URL)
    yield


async def app_client(tmp_path: Path, **overrides: Any) -> tuple[LifespanManager, AsyncClient]:
    assert DB_URL
    app = create_app(Settings(database_url=DB_URL, data_dir=tmp_path, commit="test", **overrides))
    return LifespanManager(app), AsyncClient(
        transport=ASGITransport(app=app), base_url="http://t", headers=CSRF
    )


@needs_db
async def test_the_app_sends_headers_and_hides_docs_when_asked(tmp_path: Path, upgraded: None) -> None:
    life, c = await app_client(tmp_path)
    async with life, c:
        r = await c.get("/api/version")
        assert r.headers["cache-control"] == "no-store" and r.headers["x-frame-options"] == "DENY"
        assert (await c.get("/api/docs")).status_code == 200
        assert (await c.get("/api/openapi.json")).status_code == 200
    life, c = await app_client(tmp_path, api_docs=False)
    async with life, c:
        assert (await c.get("/api/docs")).status_code == 404
        assert (await c.get("/api/openapi.json")).status_code == 404
    assert Settings(env="prod").docs_enabled is False
    assert Settings(env="prod", api_docs=True).docs_enabled is True
    assert Settings().docs_enabled is True


def upload(name: str, data: bytes) -> list[tuple[str, tuple[str, io.BytesIO, str]]]:
    return [("files", (name, io.BytesIO(data), "application/octet-stream"))]


@needs_db
async def test_uploads_are_checked_before_and_after_arrival(
    tmp_path: Path, upgraded: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    life, c = await app_client(tmp_path, max_upload_total_mb=1, rate_limits=False)
    uploads = tmp_path / "uploads"
    async with life, c:
        big = await c.post("/api/scans/upload", files=upload("big.csv", b"a,b\n" + b"1,2\n" * 300_000))
        assert big.status_code == 413 and big.json()["detail"] == "too_large"

        fake = await c.post("/api/scans/upload", files=upload("orders.parquet", b"id,name\n1,x\n"))
        assert fake.status_code == 415
        assert fake.json()["detail"]["code"] == "content_mismatch"
        assert fake.json()["detail"]["file"] == "orders.parquet"
        binary = await c.post("/api/scans/upload", files=upload("orders.csv", b"MZ\x90\x00binary"))
        assert binary.status_code == 415 and "UTF-8" in binary.json()["detail"]["message"]
        assert list(uploads.iterdir()) == []

        # httpx itself escapes control characters in the name; the bidi override reaches the API.
        ok = await c.post("/api/scans/upload", files=upload("../in\u202evoices.csv", b"id,name\n1,x\n"))
        assert ok.status_code == 202, ok.text
        assert ok.json()["files"] == ["invoices.csv"]

        monkeypatch.setattr(security.shutil, "disk_usage", lambda _p: type("U", (), {"free": 10 * MB})())
        full = await c.post("/api/scans/upload", files=upload("x.csv", b"id\n1\n"))
        assert full.status_code == 507 and full.json()["detail"] == "insufficient_storage"


@needs_db
async def test_scans_per_hour_and_the_off_switch(tmp_path: Path, upgraded: None) -> None:
    life, c = await app_client(tmp_path, rate_scans_per_hour=1)
    async with life, c:
        missing = {"connection_id": "00000000-0000-4000-8000-000000000000"}
        assert (await c.post("/api/scans", json=missing)).status_code == 404
        limited = await c.post("/api/scans", json=missing)
        assert limited.status_code == 429 and int(limited.headers["retry-after"]) > 3000
        assert json.loads(limited.text)["detail"] == "rate_limited"
        assert [(await c.get("/healthz")).status_code for _ in range(30)] == [200] * 30
    life, c = await app_client(tmp_path, rate_scans_per_hour=1, rate_limits=False)
    async with life, c:
        missing = {"connection_id": "00000000-0000-4000-8000-000000000000"}
        assert [(await c.post("/api/scans", json=missing)).status_code for _ in range(3)] == [404, 404, 404]


# --- The web image's Caddyfile ------------------------------------------------------------

CADDYFILE = Path(__file__).resolve().parents[2] / "deploy" / "caddy" / "Caddyfile"


def test_caddyfile_sends_the_baseline_headers() -> None:
    text = CADDYFILE.read_text()
    for header in (
        "Content-Security-Policy \"default-src 'self';",
        "frame-ancestors 'none'",
        'X-Content-Type-Options "nosniff"',
        'Referrer-Policy "strict-origin-when-cross-origin"',
        'Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=(), usb=()"',
        'Cross-Origin-Opener-Policy "same-origin"',
        'Cross-Origin-Resource-Policy "same-origin"',
        'X-Frame-Options "DENY"',
        'Strict-Transport-Security "max-age=31536000"',
        "-Server",
        'header @assets Cache-Control "public, max-age=31536000, immutable"',
        'header @html Cache-Control "no-cache"',
        "trusted_proxies static private_ranges",
    ):
        assert header in text, header
    # The CSP allows no inline or remote scripts.
    csp = text.split('Content-Security-Policy "', 1)[1].split('"', 1)[0]
    assert "script-src 'self';" in csp and "unsafe-eval" not in csp and "http" not in csp

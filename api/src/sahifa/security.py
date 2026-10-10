"""Security baseline of the API (spec 012): response headers, request size and free-disk
limits, and rate limits.

All three are pure ASGI middleware, so they act before FastAPI parses a body: an upload that
is too large, or one more than its sender may start, is refused before the multipart parser
spools it to disk.
"""

from __future__ import annotations

import hashlib
import math
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .auth.deps import SESSION_COOKIE
from .logging import get_logger

log = get_logger("sahifa.security")

MB = 1024 * 1024
BODY_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Sent on every API response that has not set its own value. The docs page (when served) loads
# Swagger UI from a CDN, so it keeps no CSP of ours.
API_HEADERS: dict[str, str] = {
    "cache-control": "no-store",
    "x-content-type-options": "nosniff",
    "referrer-policy": "no-referrer",
    "x-frame-options": "DENY",
    "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
}
DOCS_PATHS = frozenset({"/api/docs", "/api/docs/oauth2-redirect"})


class SecurityHeadersMiddleware:
    """Adds `API_HEADERS` to every HTTP response, keeping any value a route set itself."""

    def __init__(self, app: ASGIApp, *, docs_enabled: bool) -> None:
        self.app = app
        self.docs_enabled = docs_enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        skip_csp = self.docs_enabled and scope["path"] in DOCS_PATHS

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in API_HEADERS.items():
                    if name == "content-security-policy" and skip_csp:
                        continue
                    if name not in headers:
                        headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)


class _BodyTooLargeError(Exception):
    """Raised from `receive` when a body passes its limit."""


class BodyLimitMiddleware:
    """Limits request bodies: `limits` per path, `default_bytes` elsewhere.

    A declared `Content-Length` over the limit is refused at once; a body without one is
    counted as it streams and cut off at the limit. Either way the answer is 413 `too_large`,
    whatever the app made of the cut-off body (FastAPI turns a failed parse into a 400). For
    `disk_paths`, a declared size that would leave less than `min_free_bytes` free under
    `disk_dir` is refused with 507 before any byte is read."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        default_bytes: int,
        limits: dict[str, int],
        disk_dir: Path,
        disk_paths: frozenset[str],
        min_free_bytes: int,
        disk_usage: Callable[[Path], int] | None = None,
    ) -> None:
        self.app = app
        self.default_bytes = default_bytes
        self.limits = limits
        self.disk_dir = disk_dir
        self.disk_paths = disk_paths
        self.min_free_bytes = min_free_bytes
        self.free_bytes = disk_usage or (lambda p: shutil.disk_usage(p).free)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in BODY_METHODS:
            await self.app(scope, receive, send)
            return
        path: str = scope["path"]
        limit = self.limits.get(path, self.default_bytes)
        declared = _content_length(Headers(scope=scope))
        if declared is not None and declared > limit:
            await self._too_large(scope, receive, send, limit)
            return
        if path in self.disk_paths:
            free = self.free_bytes(self.disk_dir)
            if free - (declared or 0) < self.min_free_bytes:
                log.warning("upload.disk_full", free_mb=free // MB, declared_mb=(declared or 0) // MB)
                body = {"detail": "insufficient_storage", "message": "The server is low on disk space."}
                await JSONResponse(status_code=507, content=body)(scope, receive, send)
                return

        seen = 0
        exceeded = False
        started = False

        async def counted() -> Message:
            nonlocal seen, exceeded
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    exceeded = True
                    raise _BodyTooLargeError
            return message

        async def guarded(message: Message) -> None:
            nonlocal started
            # Once the body passed the limit, whatever the app answers is replaced by the 413.
            if exceeded:
                return
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, counted, guarded)
        except _BodyTooLargeError:
            exceeded = True
        if exceeded and not started:
            await self._too_large(scope, receive, send, limit)

    async def _too_large(self, scope: Scope, receive: Receive, send: Send, limit: int) -> None:
        log.info("request.too_large", path=scope["path"], limit_mb=round(limit / MB, 2))
        body = {
            "detail": "too_large",
            "limit_mb": round(limit / MB, 2),
            "message": f"The request is larger than {_mb_text(limit)}.",
        }
        await JSONResponse(status_code=413, content=body, headers={"connection": "close"})(
            scope, receive, send
        )


def _content_length(headers: Headers) -> int | None:
    raw = headers.get("content-length")
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


def _mb_text(n: int) -> str:
    mb = n / MB
    return f"{mb:g} MB" if mb >= 1 else f"{n // 1024} KB"


@dataclass
class Bucket:
    """A rule: `limit` requests per `period_s`, refilled continuously."""

    limit: int
    period_s: float


@dataclass
class _State:
    tokens: float
    at: float


class RateLimiter:
    """Token buckets per (rule, key), in this process. `clock` is injectable for tests."""

    MAX_KEYS = 50_000

    def __init__(self, buckets: dict[str, Bucket], clock: Callable[[], float] = time.monotonic) -> None:
        self.buckets = buckets
        self.clock = clock
        self.states: dict[tuple[str, str], _State] = {}

    def take(self, bucket: str, key: str) -> float:
        """Spend one token; 0 when allowed, else the seconds until one is free."""
        rule = self.buckets[bucket]
        rate = rule.limit / rule.period_s
        now = self.clock()
        state = self.states.get((bucket, key))
        if state is None:
            if len(self.states) >= self.MAX_KEYS:
                self._prune(now)
            state = self.states[(bucket, key)] = _State(tokens=float(rule.limit), at=now)
        else:
            state.tokens = min(float(rule.limit), state.tokens + (now - state.at) * rate)
            state.at = now
        if state.tokens >= 1:
            state.tokens -= 1
            return 0.0
        return (1 - state.tokens) / rate

    def _prune(self, now: float) -> None:
        """Forget keys whose bucket has refilled: they hold no information."""
        for k, s in list(self.states.items()):
            rule = self.buckets[k[0]]
            if s.tokens + (now - s.at) * rule.limit / rule.period_s >= rule.limit:
                del self.states[k]


UPLOAD_PATH = "/api/scans/upload"
AUTH_FLOW_PATHS = frozenset({"/api/auth/login", "/api/auth/passkey/add", "/api/auth/callback"})
# Trying invitation tokens (spec 020): a bucket of its own, per session like the others.
INVITATION_PATHS = frozenset({"/api/invitations/lookup", "/api/invitations/accept"})
SCAN_PATHS = frozenset({"/api/scans", UPLOAD_PATH})


def bucket_of(method: str, path: str, exempt: frozenset[str]) -> str | None:
    """The rule a request counts against, or None when it is not limited."""
    if path in exempt or not path.startswith("/api/"):
        return None
    if path in AUTH_FLOW_PATHS:
        return "auth"
    if path in INVITATION_PATHS:
        return "invitations"
    if method == "POST" and path in SCAN_PATHS:
        return "scans"
    if method in BODY_METHODS:
        return "write"
    return "read"


def key_of(scope: Scope, bucket: str) -> tuple[str, str]:
    """(kind, key): the session for signed-in requests, else the client address. The sign-in
    flow always counts by address. The session token is hashed, never kept."""
    if bucket != "auth":
        token = Headers(scope=scope).get("cookie")
        if token:
            session = _cookie(token, SESSION_COOKIE)
            if session:
                return "session", "s:" + hashlib.sha256(session.encode()).hexdigest()[:32]
    client = scope.get("client")
    return "address", "a:" + (client[0] if client else "unknown")


def _cookie(header: str, name: str) -> str | None:
    for part in header.split(";"):
        k, _, v = part.strip().partition("=")
        if k == name and v:
            return v
    return None


class RateLimitMiddleware:
    """Answers 429 `rate_limited` with `Retry-After` once a key used up its bucket."""

    def __init__(self, app: ASGIApp, *, limiter: RateLimiter, exempt: frozenset[str]) -> None:
        self.app = app
        self.limiter = limiter
        self.exempt = exempt

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            bucket = bucket_of(scope["method"], scope["path"], self.exempt)
            if bucket is not None:
                kind, key = key_of(scope, bucket)
                wait = self.limiter.take(bucket, key)
                if wait > 0:
                    retry = max(1, math.ceil(wait))
                    log.warning("rate.limited", bucket=bucket, key_kind=kind, path=scope["path"])
                    body = {
                        "detail": "rate_limited",
                        "retry_after": retry,
                        "message": f"Too many requests, try again in {retry} s.",
                    }
                    response = JSONResponse(
                        status_code=429, content=body, headers={"retry-after": str(retry)}
                    )
                    await response(scope, receive, send)
                    return
        await self.app(scope, receive, send)


def default_buckets(scans_per_hour: int) -> dict[str, Bucket]:
    """The rules of spec 012."""
    return {
        "auth": Bucket(limit=20, period_s=60),
        "invitations": Bucket(limit=20, period_s=60),
        "scans": Bucket(limit=scans_per_hour, period_s=3600),
        "write": Bucket(limit=120, period_s=60),
        "read": Bucket(limit=1200, period_s=60),
    }

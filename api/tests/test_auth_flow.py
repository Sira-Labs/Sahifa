"""The sign-in end to end (spec 006): the api in oidc mode against the fake IdP and the test
database. Ported from Tabayyun's `tests/db/test_auth_flow.py`, without orgs and memberships:
access follows `SAHIFA_ADMIN_EMAIL` and `SAHIFA_ALLOWED_EMAILS`."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from joserfc.jwk import RSAKey
from sqlalchemy import text
from sqlalchemy.engine import Engine

from sahifa.auth import SESSION_COOKIE, OidcClient
from sahifa.db.migrate import upgrade
from sahifa.main import create_app
from sahifa.settings import Settings

from .conftest import CSRF, DB_URL, needs_db, owner_engine
from .fake_idp import CLIENT_SECRET, ISSUER, FakeIdp, unsigned

pytestmark = needs_db

PUBLIC = "https://sahifa.test"
ADMIN = "owner@example.org"
ALLOWED = "ana@example.org"
OTHER = "other@example.org"
OTHER_KEY = RSAKey.generate_key(2048, parameters={"kid": "k1"}, private=True)


@dataclass
class Env:
    """The fake IdP, the default app, an app factory and a direct connection for setup."""

    idp: FakeIdp
    app: FastAPI
    make: Callable[..., Any]
    owner: Engine


def auth_settings(tmp_path: Path, **overrides: Any) -> Settings:
    """Test settings in oidc mode against the fake IdP."""
    assert DB_URL
    values: dict[str, Any] = {
        "database_url": DB_URL,
        "data_dir": tmp_path,
        "commit": "test",
        "auth_mode": "oidc",
        "public_url": PUBLIC,
        "oidc_issuer": ISSUER,
        "oidc_client_secret": CLIENT_SECRET,
        "session_secret": "test-session-secret-0123456789abcdef",
        "admin_email": ADMIN,
        "allowed_emails": ALLOWED,
        **overrides,
    }
    return Settings(**values)


@pytest.fixture
async def env(tmp_path: Path) -> AsyncIterator[Env]:
    """Empty auth tables, the fake IdP and apps with their lifespan running."""
    assert DB_URL
    upgrade(DB_URL)
    owner = owner_engine()
    with owner.connect() as conn:
        conn.execute(text("TRUNCATE login_flows, sessions"))
        # Check events (spec 007) refer to users and keep their actor when a user goes.
        conn.execute(text("DELETE FROM users"))
    idp = FakeIdp()
    async with AsyncExitStack() as stack:

        async def make(oidc: OidcClient | None = None, **overrides: Any) -> FastAPI:
            """An app in oidc mode (unless overridden); `oidc` replaces the fake IdP's client."""
            settings = auth_settings(tmp_path, **overrides)
            client = oidc or (idp.client() if settings.resolved_auth_mode == "oidc" else None)
            app = create_app(settings, oidc=client)
            await stack.enter_async_context(LifespanManager(app))
            return app

        yield Env(idp=idp, app=await make(), make=make, owner=owner)
    owner.dispose()


def browser(app: FastAPI, *, csrf: bool = True) -> AsyncClient:
    """A client on the public https origin (the cookies are Secure) that keeps cookies."""
    return AsyncClient(transport=ASGITransport(app=app), base_url=PUBLIC, headers=CSRF if csrf else {})


def sql(env: Env, statement: str, **params: Any) -> Any:
    """Run one statement directly and return the result's rows."""
    with env.owner.connect() as conn:
        result = conn.execute(text(statement), params)
        return result.all() if result.returns_rows else None


def method_claims(method: str) -> dict[str, Any]:
    """What Keycloak puts in the token for each method (Tabayyun spec 013, implementation notes)."""
    return {"amr": ["passkey"]} if method == "passkey" else {"identity_provider": method}


async def start(c: AsyncClient, method: str, next_path: str | None = None) -> httpx.Response:
    """The first leg: `/api/auth/login`, which answers with the redirect to the IdP."""
    params = {"method": method} | ({"next": next_path} if next_path else {})
    return await c.get("/api/auth/login", params=params)


async def sign_in(
    env: Env,
    c: AsyncClient,
    method: str = "google",
    email: str = ADMIN,
    next_path: str | None = None,
    sub: str | None = None,
    **claims: Any,
) -> httpx.Response:
    """The whole browser round trip; `claims` override the ID token's."""
    started = await start(c, method, next_path)
    assert started.status_code == 302, started.text
    signer = claims.pop("signer", None)
    callback, _ = env.idp.authorize(
        started.headers["location"],
        email=email,
        sub=sub or f"kc-{email}",
        signer=signer,
        **(method_claims(method) | claims),
    )
    return await c.get(callback)


def live_sessions(env: Env) -> int:
    """Sessions not revoked, across all users."""
    return int(sql(env, "SELECT count(*) FROM sessions WHERE revoked_at IS NULL")[0][0])


@pytest.mark.parametrize("method", ["google", "github", "passkey"])
async def test_full_login_per_method(env: Env, method: str) -> None:
    """Each method signs the admin in: cookie, /me, and the protected routes."""
    async with browser(env.app) as c:
        done = await sign_in(env, c, method, next_path="/scans/new?tab=connection")
        assert done.status_code == 302 and done.headers["location"] == "/scans/new?tab=connection"
        cookie = done.headers["set-cookie"]
        assert SESSION_COOKIE in cookie and "HttpOnly" in cookie and "Secure" in cookie
        assert "samesite=lax" in cookie.lower() and "Path=/" in cookie
        me = (await c.get("/api/auth/me")).json()
        assert me["mode"] == "oidc" and me["user"]["email"] == ADMIN and me["admin"] is True
        assert me["sign_in_method"] == method and me["user"]["display_name"] == "Owner"
        assert (await c.get("/api/scans")).status_code == 200
        assert (await c.get("/api/connections")).status_code == 200
    row = sql(env, "SELECT sign_in_method, idp_sid, id_token IS NOT NULL FROM sessions")
    assert row == [(method, f"sid-kc-{ADMIN}", True)]


async def test_anonymous_requests(env: Env) -> None:
    """Without a session: 401 on protected routes, while version, health and options answer."""
    async with browser(env.app) as c:
        for path in ("/api/scans", "/api/connections", "/api/auth/me", "/api/auth/sessions"):
            response = await c.get(path)
            assert response.status_code == 401 and response.json() == {"detail": "not_authenticated"}, path
        upload = await c.post("/api/scans/upload", files=[("files", ("a.csv", b"a\n1\n", "text/csv"))])
        assert upload.status_code == 401
        assert (await c.get("/api/version")).status_code == 200
        assert (await c.get("/healthz")).status_code == 200
        options = (await c.get("/api/auth/options")).json()
        assert options == {
            "mode": "oidc",
            "methods": ["google", "github", "passkey"],
            "account_url": f"{ISSUER}/account",
        }
        forged = await c.get("/api/scans", headers={"Cookie": f"{SESSION_COOKIE}=forged-token"})
        assert forged.status_code == 401


def _bad_signature(claims: dict[str, Any]) -> str:
    """The claims signed with a foreign key under the realm's key id."""
    return FakeIdp().sign(claims, key=OTHER_KEY)


@pytest.mark.parametrize(
    ("case", "method", "claims", "status", "code"),
    [
        ("wrong_nonce", "google", {"nonce": "other"}, 400, "invalid_token"),
        ("wrong_audience", "google", {"aud": "other", "azp": "other"}, 400, "invalid_token"),
        ("bad_signature", "google", {"signer": _bad_signature}, 400, "invalid_token"),
        ("alg_none", "google", {"signer": unsigned}, 400, "invalid_token"),
        ("email_unverified", "google", {"email_verified": False}, 400, "invalid_token"),
        ("passkey_without_amr", "passkey", {"amr": None}, 400, "passkey_required"),
        ("passkey_with_password", "passkey", {"amr": ["pwd"]}, 400, "passkey_required"),
        ("google_via_github", "google", {"identity_provider": "github"}, 400, "invalid_token"),
    ],
)
async def test_callback_rejects_tokens(
    env: Env, case: str, method: str, claims: dict[str, Any], status: int, code: str
) -> None:
    """Each token failure gives its status and code, and creates no session."""
    async with browser(env.app) as c:
        done = await sign_in(env, c, method, **claims)
        assert (done.status_code, code in done.text) == (status, True), case
        assert SESSION_COOKIE not in done.headers.get("set-cookie", "")
    assert live_sessions(env) == 0
    assert sql(env, "SELECT count(*) FROM login_flows")[0][0] == 0


async def test_login_flow_is_single_use(env: Env) -> None:
    """State mismatch, an expired flow, a reused flow and a missing cookie give 400
    `login_expired`; a cancelled sign-in and an IdP error their own codes."""
    async with browser(env.app) as c:
        started = await start(c, "google")
        callback, _ = env.idp.authorize(
            started.headers["location"], email=ADMIN, sub="kc", **method_claims("google")
        )
        forged = callback.replace("state=", "state=x")
        assert "login_expired" in (await c.get(forged)).text
        assert "login_expired" in (await c.get(callback)).text  # the flow went with the first try

        started = await start(c, "google")
        callback, _ = env.idp.authorize(
            started.headers["location"], email=ADMIN, sub="kc", **method_claims("google")
        )
        sql(env, "UPDATE login_flows SET created_at = now() - interval '11 minutes'")
        assert (await c.get(callback)).status_code == 400

        started = await start(c, "google")
        state = parse_qs(urlsplit(started.headers["location"]).query)["state"][0]
        cancelled = await c.get("/api/auth/callback", params={"state": state, "error": "access_denied"})
        assert cancelled.status_code == 400 and "login_cancelled" in cancelled.text

        started = await start(c, "google")
        callback, _ = env.idp.authorize(
            started.headers["location"], email=ADMIN, sub="kc", **method_claims("google")
        )
        env.idp.grants.clear()  # the IdP no longer knows the code
        assert (await c.get(callback)).status_code == 502

        started = await start(c, "google")
        callback, _ = env.idp.authorize(
            started.headers["location"], email=ADMIN, sub="kc", **method_claims("google")
        )
    async with browser(env.app) as other:  # another browser has no flow cookie
        assert "login_expired" in (await other.get(callback)).text
    assert live_sessions(env) == 0

    async with browser(env.app) as c:
        assert (await sign_in(env, c)).status_code == 302
    assert live_sessions(env) == 1


async def test_next_and_methods(env: Env) -> None:
    """`next` outside the site becomes `/`; a disabled or unknown method gives 400."""
    async with browser(env.app) as c:
        for target in ("https://evil.example", "//evil.example", "/\\evil.example"):
            assert (await sign_in(env, c, next_path=target)).headers["location"] == "/"
    limited = await env.make(sign_in_methods="google,passkey")
    async with browser(limited) as c:
        assert (await start(c, "github")).status_code == 400
        assert (await start(c, "password")).status_code == 400
        assert (await c.get("/api/auth/options")).json()["methods"] == ["google", "passkey"]


async def test_unknown_email_gets_no_access(env: Env) -> None:
    """An address that is neither the admin's nor allowed gets a session and 403 `no_access`;
    an allowed address gets in without being admin; access follows the settings."""
    async with browser(env.app) as c:
        await sign_in(env, c, "github", email=OTHER)
        me = await c.get("/api/auth/me")
        assert me.status_code == 403
        body = me.json()
        assert body["detail"] == "no_access" and body["email"] == OTHER
        assert "Ask a workspace admin" in body["message"]
        scans = await c.get("/api/scans")
        assert scans.status_code == 403 and scans.json()["detail"] == "no_access"
        assert (await c.get("/api/auth/sessions")).status_code == 200  # devices stay reachable
    async with browser(env.app) as c:
        await sign_in(env, c, "google", email=ALLOWED)
        me = (await c.get("/api/auth/me")).json()
        assert me["user"]["email"] == ALLOWED and me["admin"] is False
        assert (await c.get("/api/scans")).status_code == 200
    widened = await env.make(allowed_emails=f"{ALLOWED},{OTHER.upper()}")
    async with browser(widened) as c:
        await sign_in(env, c, "google", email=OTHER)
        assert (await c.get("/api/scans")).status_code == 200


async def test_identity_links_by_email(env: Env) -> None:
    """A new identity with a known email is the same user; a known identity arriving with an
    email another user holds is refused with 409 `account_conflict`."""
    async with browser(env.app) as c:
        await sign_in(env, c, email=ADMIN, sub="kc-1")
        await sign_in(env, c, email=ADMIN.upper(), sub="kc-2")
        await sign_in(env, c, email=ALLOWED, sub="kc-3")
        clash = await sign_in(env, c, email=ALLOWED, sub="kc-2")
        assert clash.status_code == 409 and "account_conflict" in clash.text
    users = sql(env, "SELECT email, subject FROM users ORDER BY email")
    assert users == [(ALLOWED, "kc-3"), (ADMIN, "kc-2")]


async def test_idle_and_absolute_expiry(env: Env) -> None:
    """Revoked, idle-expired and absolute-expired sessions each give 401."""
    for change in (
        "UPDATE sessions SET revoked_at = now()",
        "UPDATE sessions SET last_seen_at = now() - interval '13 hours'",
        "UPDATE sessions SET expires_at = now() - interval '1 second'",
    ):
        async with browser(env.app) as c:
            await sign_in(env, c)
            assert (await c.get("/api/auth/me")).status_code == 200
            sql(env, change)
            assert (await c.get("/api/auth/me")).status_code == 401, change
            assert (await c.get("/api/scans")).status_code == 401, change


async def test_session_lifetimes_follow_the_settings(env: Env) -> None:
    """The absolute lifetime sets `expires_at` and the cookie's max-age."""
    short = await env.make(session_absolute="1h")
    async with browser(short) as c:
        done = await sign_in(env, c)
        assert "Max-Age=3600" in done.headers["set-cookie"]
    left = sql(env, "SELECT expires_at - created_at FROM sessions")[0][0]
    assert left.total_seconds() == 3600


async def test_devices_list_and_revoke(env: Env) -> None:
    """Users list and revoke only their own sessions; revoke-others keeps the current one."""
    async with browser(env.app) as c1, browser(env.app) as c2, browser(env.app) as c3:
        await sign_in(env, c1, "google")
        await sign_in(env, c2, "passkey")
        await sign_in(env, c3, "github", email=ALLOWED)
        devices = (await c1.get("/api/auth/sessions")).json()
        assert len(devices) == 2 and sum(d["current"] for d in devices) == 1
        assert set(devices[0]) == {
            "id", "current", "sign_in_method", "created_at", "last_seen_at", "user_agent", "ip_address"
        }  # fmt: skip
        assert {d["sign_in_method"] for d in devices} == {"google", "passkey"}
        foreign = (await c3.get("/api/auth/sessions")).json()[0]["id"]
        assert (await c1.delete(f"/api/auth/sessions/{foreign}")).status_code == 404
        assert (await c1.delete(f"/api/auth/sessions/{uuid.uuid4()}")).status_code == 404
        assert (await c3.get("/api/auth/me")).status_code == 200  # untouched

        assert (await c1.post("/api/auth/sessions/revoke-others")).status_code == 204
        assert (await c2.get("/api/auth/me")).status_code == 401
        remaining = (await c1.get("/api/auth/sessions")).json()
        assert [d["current"] for d in remaining] == [True]

        own = remaining[0]["id"]
        revoked = await c1.delete(f"/api/auth/sessions/{own}")
        assert revoked.status_code == 204 and SESSION_COOKIE in revoked.headers["set-cookie"]
        assert (await c1.get("/api/auth/me")).status_code == 401


async def test_logout_revokes_and_returns_end_session(env: Env) -> None:
    """Logout revokes the session and returns the end-session URL with the ID token hint."""
    async with browser(env.app) as c:
        await sign_in(env, c)
        id_token = sql(env, "SELECT id_token FROM sessions")[0][0]
        out = await c.post("/api/auth/logout")
        url = out.json()["logout_url"]
        query = parse_qs(urlsplit(url).query)
        assert url.startswith(f"{ISSUER}/protocol/openid-connect/logout?")
        assert query["id_token_hint"] == [id_token] and query["post_logout_redirect_uri"] == [f"{PUBLIC}/"]
        assert (await c.get("/api/auth/me")).status_code == 401
        again = (await c.post("/api/auth/logout")).json()["logout_url"]
        assert "id_token_hint" not in parse_qs(urlsplit(again).query)
    assert live_sessions(env) == 0


async def test_backchannel_logout_revokes_by_sid(env: Env) -> None:
    """A logout token revokes the sessions of its sid, or of its sub; no CSRF header needed;
    an invalid token gives 400."""
    async with browser(env.app) as c1, browser(env.app) as c2, browser(env.app, csrf=False) as idp_side:
        await sign_in(env, c1, sid="s1")
        await sign_in(env, c2, "passkey", sid="s2")
        hook = "/api/auth/backchannel-logout"
        bad = await idp_side.post(hook, data={"logout_token": env.idp.logout_token(sid="s1", nonce="n")})
        assert bad.status_code == 400
        assert (await idp_side.post(hook, data={"logout_token": "garbage"})).status_code == 400
        ok = await idp_side.post(hook, data={"logout_token": env.idp.logout_token(sid="s1")})
        assert ok.status_code == 200 and ok.headers["cache-control"] == "no-store"
        assert (await c1.get("/api/auth/me")).status_code == 401
        assert (await c2.get("/api/auth/me")).status_code == 200
        by_sub = await idp_side.post(hook, data={"logout_token": env.idp.logout_token(sub=f"kc-{ADMIN}")})
        assert by_sub.status_code == 200
        assert (await c2.get("/api/auth/me")).status_code == 401


async def test_csrf_on_the_app(env: Env) -> None:
    """Unsafe requests without the header or from a foreign origin get 403 `csrf`."""
    async with browser(env.app, csrf=False) as c:
        await sign_in(env, c)
        assert (await c.post("/api/auth/logout")).json() == {"detail": "csrf"}
        assert (await c.post("/api/scans", json={})).status_code == 403
        foreign = await c.post("/api/auth/logout", headers=CSRF | {"Origin": "https://evil.example"})
        assert foreign.status_code == 403
        same = await c.post("/api/auth/logout", headers=CSRF | {"Origin": PUBLIC})
        assert same.status_code == 200


async def test_idp_unavailable_only_affects_login(env: Env) -> None:
    """With the IdP down, login answers 503 and the rest of the api keeps working."""

    def refuse(request: httpx.Request) -> httpx.Response:
        """An IdP that cannot be reached."""
        raise httpx.ConnectError("down", request=request)

    down = await env.make(
        oidc=OidcClient(
            ISSUER, "sahifa-api", CLIENT_SECRET, httpx.AsyncClient(transport=httpx.MockTransport(refuse))
        )
    )
    async with browser(down) as c:
        assert (await start(c, "google")).status_code == 503
        assert (await c.get("/api/version")).status_code == 200
        assert (await c.post("/api/auth/logout")).json() == {"logout_url": "/"}


@pytest.mark.parametrize("mode", ["dev", "proxy"])
async def test_dev_and_proxy_modes_have_no_login(env: Env, mode: str) -> None:
    """dev and proxy: /me is the fixed principal, the IdP routes answer 404, no cookie needed."""
    app = await env.make(auth_mode=mode)
    async with browser(app) as c:
        me = (await c.get("/api/auth/me")).json()
        assert me["mode"] == mode and me["sign_in_method"] == mode and me["user"]["email"] is None
        assert (await c.get("/api/auth/login", params={"method": "google"})).status_code == 404
        assert (await c.get("/api/auth/options")).json() == {"mode": mode, "methods": [], "account_url": None}
        assert (await c.get("/api/auth/sessions")).json() == []
        assert (await c.post("/api/auth/logout")).json() == {"logout_url": "/"}
        assert (await c.get("/api/scans")).status_code == 200
        assert (await c.post("/api/auth/backchannel-logout", data={"logout_token": "x"})).status_code == 404


async def test_session_older_than_a_minute_is_touched(env: Env) -> None:
    """A request after the touch interval refreshes `last_seen_at` and still succeeds."""
    async with browser(env.app) as c:
        await sign_in(env, c)
        sql(env, "UPDATE sessions SET last_seen_at = now() - interval '5 minutes'")
        assert (await c.get("/api/auth/me")).status_code == 200
        assert (await c.get("/api/scans")).status_code == 200
        fresh = sql(env, "SELECT now() - last_seen_at < interval '1 minute' FROM sessions")[0][0]
        assert fresh is True


async def test_add_passkey_runs_the_keycloak_action(env: Env) -> None:
    """`/api/auth/passkey/add` re-authenticates with the session's method, asks Keycloak for
    the passkey registration and lands on the account page with the action's status; the new
    session replaces the browser's old one."""
    async with browser(env.app) as c:
        assert (await c.get("/api/auth/passkey/add")).status_code == 401
        await sign_in(env, c, "github")
        started = await c.get("/api/auth/passkey/add")
        assert started.status_code == 302
        query = parse_qs(urlsplit(started.headers["location"]).query)
        assert query["kc_action"] == ["webauthn-register-passwordless"]
        assert query["kc_idp_hint"] == ["github"] and query["prompt"] == ["login"]
        assert query["login_hint"] == [ADMIN]
        callback, _ = env.idp.authorize(
            started.headers["location"], email=ADMIN, sub=f"kc-{ADMIN}", **method_claims("github")
        )
        done = await c.get(f"{callback}&kc_action_status=success")
        assert done.status_code == 302 and done.headers["location"] == "/settings/account?passkey=success"
        assert (await c.get("/api/auth/me")).json()["sign_in_method"] == "github"
    assert live_sessions(env) == 1


async def test_unknown_action_status_is_ignored(env: Env) -> None:
    """Only Keycloak's own `kc_action_status` values reach the redirect."""
    async with browser(env.app) as c:
        started = await start(c, "google", "/scans")
        callback, _ = env.idp.authorize(
            started.headers["location"], email=ADMIN, sub=f"kc-{ADMIN}", **method_claims("google")
        )
        done = await c.get(f"{callback}&kc_action_status=%2F%2Fevil.example")
        assert done.status_code == 302 and done.headers["location"] == "/scans"


async def test_add_passkey_as_another_account_is_refused(env: Env) -> None:
    """When "Add a passkey" comes back as someone else, the browser keeps its own session and
    is not switched to the other account; an action result without a session is refused too."""
    async with browser(env.app) as c:
        await sign_in(env, c, "google")
        started = await c.get("/api/auth/passkey/add")
        callback, _ = env.idp.authorize(
            started.headers["location"], email=ALLOWED, sub=f"kc-{ALLOWED}", **method_claims("google")
        )
        refused = await c.get(f"{callback}&kc_action_status=success")
        assert refused.status_code == 409 and "account_mismatch" in refused.text
        assert (await c.get("/api/auth/me")).json()["user"]["email"] == ADMIN
    assert live_sessions(env) == 1
    assert sql(env, "SELECT count(*) FROM users WHERE email = :e", e=ALLOWED)[0][0] == 0

    async with browser(env.app) as c:
        started = await start(c, "google")
        callback, _ = env.idp.authorize(
            started.headers["location"], email=ADMIN, sub=f"kc-{ADMIN}", **method_claims("google")
        )
        assert (await c.get(f"{callback}&kc_action_status=success")).status_code == 409

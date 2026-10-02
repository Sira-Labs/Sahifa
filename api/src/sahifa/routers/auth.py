"""Sign-in, session and device endpoints under `/api/auth` (spec 006).

None of these routes needs `current_user`: they establish who the caller is. In `dev` and
`proxy` mode there is no sign-in: `/me` describes the fixed principal, the options list no
methods and the IdP routes answer 404. Ported from Tabayyun's `routers/auth.py`.
"""

from __future__ import annotations

import html
import ipaddress
import uuid
from datetime import datetime
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Form, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from ..auth import store
from ..auth.deps import (
    LOGIN_COOKIE,
    SESSION_COOKIE,
    NoAccessError,
    current_session,
    factory_of,
    require_session,
    session_secret,
    settings_of,
    signed_in,
)
from ..auth.oidc import IdpError, IdpUnavailableError, InvalidTokenError, OidcClient
from ..auth.store import EmailTakenError, Flow
from ..auth.tokens import new_token, safe_next, token_hash
from ..logging import get_logger
from ..settings import Settings

log = get_logger("sahifa.auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])

CALLBACK_PATH = "/api/auth/callback"
BACKCHANNEL_PATH = "/api/auth/backchannel-logout"
FLOW_COOKIE_MAX_AGE_S = 600
USER_AGENT_MAX = 512
# Keycloak's required action that registers a passwordless WebAuthn credential (a passkey).
PASSKEY_ACTION = "webauthn-register-passwordless"
ACCOUNT_PATH = "/settings/account"
# `kc_action_status` values Keycloak returns after an application-initiated action.
ACTION_STATUSES = frozenset({"success", "cancelled", "error"})
NO_STORE = {"Cache-Control": "no-store"}


class OptionsOut(BaseModel):
    """`GET /api/auth/options`: what the sign-in page offers."""

    mode: str
    methods: list[str]
    account_url: str | None


class UserOut(BaseModel):
    """The signed-in person; `id` and `email` are null in dev and proxy mode."""

    id: str | None
    email: str | None
    display_name: str


class MeOut(BaseModel):
    """`GET /api/auth/me`."""

    mode: str
    user: UserOut
    sign_in_method: str
    admin: bool


class DeviceOut(BaseModel):
    """One signed-in browser of the user; never tokens."""

    id: str
    current: bool
    sign_in_method: str
    created_at: datetime
    last_seen_at: datetime
    user_agent: str | None
    ip_address: str | None


class LogoutOut(BaseModel):
    """Where the browser goes to end the IdP session too."""

    logout_url: str


def _oidc(request: Request) -> OidcClient:
    """The app's OIDC client; 404 in dev and proxy mode, where there is no sign-in."""
    client: OidcClient | None = request.app.state.oidc
    if client is None:
        raise HTTPException(status_code=404, detail="oidc_disabled")
    return client


def _public_url(settings: Settings) -> str:
    """The public URL without a trailing slash (set whenever the OIDC client exists)."""
    return (settings.public_url or "").rstrip("/")


def _set_cookie(response: Response, name: str, value: str, max_age: int) -> None:
    """Set a `__Host-` cookie: HttpOnly, Secure, SameSite=Lax, Path=/."""
    response.set_cookie(name, value, max_age=max_age, path="/", secure=True, httponly=True, samesite="lax")


def _clear_cookie(response: Response, name: str) -> None:
    """Expire a cookie set by `_set_cookie` (same attributes, as `__Host-` requires)."""
    response.delete_cookie(name, path="/", secure=True, httponly=True, samesite="lax")


def _failure(status: int, code: str) -> HTMLResponse:
    """A failed callback: the browser is mid-navigation, so a short page with a way back."""
    safe = html.escape(code)
    body = (
        "<!doctype html><meta charset='utf-8'><title>Sign-in failed</title>"
        f"<p>Sign-in failed ({safe}).</p><p><a href='/login'>Sign in again</a></p>"
    )
    response = HTMLResponse(body, status_code=status, headers=NO_STORE)
    _clear_cookie(response, LOGIN_COOKIE)
    return response


def _client_ip(request: Request) -> str | None:
    """The client's IP from `X-Real-IP` behind the proxy, else the peer; informational only."""
    for candidate in (request.headers.get("x-real-ip"), request.client.host if request.client else None):
        if candidate:
            try:
                return str(ipaddress.ip_address(candidate.strip()))
            except ValueError:
                continue
    return None


def method_proven(method: str, claims: dict[str, Any]) -> bool:
    """Whether the ID token proves the sign-in method the flow asked for.

    Only that method's claim counts: within one Keycloak session the other one can be stale
    (Tabayyun spec 013, implementation notes). `kc_idp_hint` only routes, so a Google flow
    could return through GitHub; the `identity_provider` claim tells.
    """
    if method == "passkey":
        amr = claims.get("amr")
        return isinstance(amr, list) and "passkey" in amr
    return claims.get("identity_provider") == method


@router.get("/options", response_model=OptionsOut)
async def options(request: Request) -> OptionsOut:
    """The auth mode, the sign-in buttons (none outside oidc mode) and the account console."""
    settings = settings_of(request)
    oidc: OidcClient | None = request.app.state.oidc
    if oidc is None:
        return OptionsOut(mode=settings.resolved_auth_mode, methods=[], account_url=None)
    return OptionsOut(
        mode="oidc", methods=list(settings.enabled_sign_in_methods), account_url=f"{oidc.issuer}/account"
    )


@router.get("/login")
async def login(
    request: Request, method: Annotated[str, Query()], next: Annotated[str | None, Query()] = None
) -> Response:
    """Start a sign-in: store the flow and send the browser to the IdP."""
    oidc = _oidc(request)
    settings = settings_of(request)
    if method not in settings.enabled_sign_in_methods:
        raise HTTPException(status_code=400, detail="unknown_method")
    return await _start_flow(request, oidc, method=method, next_path=safe_next(next))


@router.get("/passkey/add")
async def add_passkey(request: Request) -> Response:
    """Register a passkey: a fresh sign-in with the session's method, then Keycloak's passkey
    registration (an application-initiated action), back to the account page.

    Keycloak's account console asks for a recent sign-in before it adds a credential, and in
    this realm that re-authentication can only offer a passkey, which a first-time user has
    not got; starting from here re-authenticates through Google or GitHub instead.
    """
    oidc = _oidc(request)
    settings = settings_of(request)
    current = await require_session(request)
    if current.sign_in_method not in settings.enabled_sign_in_methods:
        raise HTTPException(status_code=400, detail="unknown_method")
    return await _start_flow(
        request,
        oidc,
        method=current.sign_in_method,
        next_path=ACCOUNT_PATH,
        action=PASSKEY_ACTION,
        login_hint=current.email,
    )


async def _start_flow(
    request: Request,
    oidc: OidcClient,
    *,
    method: str,
    next_path: str,
    action: str | None = None,
    login_hint: str | None = None,
) -> Response:
    """Store a login flow and send the browser to the IdP's authorization endpoint."""
    settings = settings_of(request)
    flow = Flow(
        state=new_token(),
        nonce=new_token(),
        code_verifier=new_token(),
        method=method,
        next_path=next_path,
    )
    try:
        url = await oidc.authorization_url(
            method=method,
            state=flow.state,
            nonce=flow.nonce,
            code_verifier=flow.code_verifier,
            redirect_uri=_public_url(settings) + CALLBACK_PATH,
            action=action,
            login_hint=login_hint,
        )
    except IdpUnavailableError as exc:
        raise HTTPException(status_code=503, detail="idp_unavailable") from exc
    flow_token = new_token()
    async with factory_of(request)() as db, db.begin():
        await store.create_flow(db, token_hash(session_secret(settings), flow_token), flow)
    response = RedirectResponse(url, status_code=302, headers=NO_STORE)
    _set_cookie(response, LOGIN_COOKIE, flow_token, FLOW_COOKIE_MAX_AGE_S)
    return response


async def _take_flow(request: Request, state: str | None) -> Flow | None:
    """The flow of this browser when it is fresh and its state matches; it is deleted either
    way, in its own transaction (single use)."""
    flow_token = request.cookies.get(LOGIN_COOKIE)
    if not flow_token:
        return None
    async with factory_of(request)() as db, db.begin():
        taken = await store.take_flow(db, token_hash(session_secret(settings_of(request)), flow_token))
    if taken is None or not taken[1] or state is None or taken[0].state != state:
        return None
    return taken[0]


class _AccountMismatchError(Exception):
    """An application-initiated action came back signed in as a user other than the browser's."""


@router.get("/callback")
async def callback(
    request: Request,
    state: Annotated[str | None, Query()] = None,
    code: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
    kc_action_status: Annotated[str | None, Query()] = None,
) -> Response:
    """Finish a sign-in: check the flow and the ID token, link the user, start a session."""
    oidc = _oidc(request)
    settings = settings_of(request)
    flow = await _take_flow(request, state)
    if flow is None:
        log.info("auth.denied", reason="login_expired")
        return _failure(400, "login_expired")
    if error is not None or not code:
        log.info("auth.denied", reason="idp_redirect_error", method=flow.method, error=(error or "")[:64])
        return _failure(400, "login_cancelled" if error == "access_denied" else "idp_error")

    try:
        tokens = await oidc.exchange_code(
            code=code, code_verifier=flow.code_verifier, redirect_uri=_public_url(settings) + CALLBACK_PATH
        )
        id_token = str(tokens["id_token"])
        claims = await oidc.validate_id_token(id_token, nonce=flow.nonce)
    except IdpUnavailableError:
        return _failure(503, "idp_unavailable")
    except IdpError as exc:
        log.warning("auth.denied", reason="idp_error", method=flow.method, idp_error=exc.code[:64])
        return _failure(502, "idp_error")
    except InvalidTokenError as exc:
        log.info("auth.denied", reason="invalid_token", method=flow.method, detail=exc.reason)
        return _failure(400, "invalid_token")
    if not method_proven(flow.method, claims):
        reason = "passkey_required" if flow.method == "passkey" else "invalid_token"
        log.info("auth.denied", reason=reason, method=flow.method, detail="method_claim")
        return _failure(400, reason)

    previous = await current_session(request)
    action_ran = kc_action_status in ACTION_STATUSES
    session_token = new_token()
    try:
        async with factory_of(request)() as db, db.begin():
            user = await store.login(
                db,
                issuer=oidc.issuer,
                subject=str(claims["sub"]),
                email=str(claims["email"]),
                display_name=str(claims.get("name") or ""),
            )
            if action_ran and (previous is None or previous.user_id != user.user_id):
                # "Add a passkey" re-authenticated as someone else: no account switch here.
                raise _AccountMismatchError
            await store.create_session(
                db,
                id_hash=token_hash(session_secret(settings), session_token),
                user_id=user.user_id,
                sign_in_method=flow.method,
                idp_sid=str(claims["sid"]) if claims.get("sid") else None,
                id_token=id_token,
                ip_address=_client_ip(request),
                user_agent=(request.headers.get("user-agent") or "")[:USER_AGENT_MAX] or None,
                absolute=settings.session_absolute,
                idle=settings.session_idle,
            )
            if previous is not None:
                # The new cookie replaces this browser's old session; revoke it in the same
                # transaction rather than orphan it.
                await store.revoke(db, previous.id, user_id=previous.user_id)
    except EmailTakenError:
        log.warning("auth.denied", reason="email_taken", method=flow.method)
        return _failure(409, "account_conflict")
    except _AccountMismatchError:
        log.warning("auth.denied", reason="account_mismatch", method=flow.method)
        return _failure(409, "account_mismatch")
    access = settings.has_access(user.email)
    log.info("auth.login", user_id=str(user.user_id), method=flow.method, access=access)
    if not access:
        # A session anyway, so the web app can say who is signed in ("No access yet").
        log.info("auth.denied", reason="no_access", user_id=str(user.user_id), method=flow.method)
    next_path = flow.next_path
    if action_ran:
        log.info("auth.action", user_id=str(user.user_id), status=kc_action_status)
        next_path += ("&" if "?" in next_path else "?") + urlencode({"passkey": kc_action_status})
    response = RedirectResponse(next_path, status_code=302, headers=NO_STORE)
    _clear_cookie(response, LOGIN_COOKIE)
    _set_cookie(response, SESSION_COOKIE, session_token, int(settings.session_absolute.total_seconds()))
    return response


@router.get("/me", response_model=MeOut)
async def me(request: Request) -> MeOut:
    """Who is signed in, how, and whether they are the admin.

    401 without a session; 403 `no_access` (with the email, for the "No access yet" page) for
    an address that is not admitted.
    """
    principal = await signed_in(request)
    if principal.mode == "oidc" and not settings_of(request).has_access(principal.email):
        raise NoAccessError(principal.email)
    return MeOut(
        mode=principal.mode,
        user=UserOut(
            id=str(principal.user_id) if principal.user_id else None,
            email=principal.email,
            display_name=principal.display_name,
        ),
        sign_in_method=principal.sign_in_method,
        admin=principal.admin,
    )


@router.get("/sessions", response_model=list[DeviceOut])
async def list_devices(request: Request) -> list[DeviceOut]:
    """The user's signed-in browsers; empty in dev and proxy mode."""
    settings = settings_of(request)
    if settings.resolved_auth_mode != "oidc":
        return []
    current = await require_session(request)
    async with factory_of(request)() as db, db.begin():
        rows = await store.list_sessions(db, current.user_id, idle=settings.session_idle)
    return [
        DeviceOut(
            id=str(row.id),
            current=row.id == current.id,
            sign_in_method=row.sign_in_method,
            created_at=row.created_at,
            last_seen_at=row.last_seen_at,
            user_agent=row.user_agent,
            ip_address=str(row.ip_address) if row.ip_address is not None else None,
        )
        for row in rows
    ]


@router.delete("/sessions/{session_id}", status_code=204)
async def revoke_device(request: Request, session_id: uuid.UUID) -> Response:
    """Sign out one of the user's browsers; the current one clears its cookie too."""
    current = await require_session(request)
    async with factory_of(request)() as db, db.begin():
        revoked = await store.revoke(db, session_id, user_id=current.user_id)
    if not revoked:
        raise HTTPException(status_code=404, detail="session not found")
    log.info(
        "auth.session_revoked",
        user_id=str(current.user_id),
        reason="device",
        current=session_id == current.id,
    )
    response = Response(status_code=204)
    if session_id == current.id:
        _clear_cookie(response, SESSION_COOKIE)
    return response


@router.post("/sessions/revoke-others", status_code=204)
async def revoke_other_devices(request: Request) -> Response:
    """Sign out every other browser of the user."""
    current = await require_session(request)
    async with factory_of(request)() as db, db.begin():
        count = await store.revoke_user_sessions(db, current.user_id, keep=current.id)
    log.info("auth.session_revoked", user_id=str(current.user_id), reason="others", count=count)
    return Response(status_code=204)


@router.post("/logout", response_model=LogoutOut)
async def logout(request: Request) -> JSONResponse:
    """Revoke the session, clear the cookie and return the IdP's end-session URL."""
    oidc: OidcClient | None = request.app.state.oidc
    session = await current_session(request)
    if session is not None:
        async with factory_of(request)() as db, db.begin():
            await store.revoke(db, session.id, user_id=session.user_id)
        log.info("auth.logout", user_id=str(session.user_id), method=session.sign_in_method)
    logout_url = "/"
    if oidc is not None:
        try:
            logout_url = (
                await oidc.end_session_url(
                    id_token_hint=session.id_token if session else None,
                    post_logout_redirect_uri=_public_url(settings_of(request)) + "/",
                )
                or "/"
            )
        except IdpUnavailableError:
            # Signed out here anyway; the IdP session ends at its own idle timeout.
            logout_url = "/"
    response = JSONResponse({"logout_url": logout_url}, headers=NO_STORE)
    _clear_cookie(response, SESSION_COOKIE)
    return response


@router.post("/backchannel-logout")
async def backchannel_logout(request: Request, logout_token: Annotated[str, Form()]) -> Response:
    """OIDC back-channel logout from the IdP: revoke the sessions of its `sid` (or `sub`)."""
    oidc = _oidc(request)
    try:
        claims = await oidc.validate_logout_token(logout_token)
    except InvalidTokenError as exc:
        log.info("auth.denied", reason="invalid_logout_token", detail=exc.reason)
        return JSONResponse(status_code=400, content={"detail": "invalid_token"}, headers=NO_STORE)
    except IdpUnavailableError:
        return JSONResponse(status_code=503, content={"detail": "idp_unavailable"}, headers=NO_STORE)
    async with factory_of(request)() as db, db.begin():
        count = await store.revoke_by_idp(
            db,
            issuer=oidc.issuer,
            sid=str(claims["sid"]) if claims.get("sid") else None,
            subject=str(claims["sub"]) if claims.get("sub") else None,
        )
    log.info("auth.session_revoked", reason="backchannel", count=count)
    return Response(status_code=200, headers=NO_STORE)

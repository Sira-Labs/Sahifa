"""Request dependencies of the sign-in (spec 006): the current session and `current_user`.

The session is looked up once per request, in its own short transaction, and kept on
`request.state`. Access comes from workspace memberships (spec 016, `access.py`): the admin
email and members get in, every other signed-in person gets 403 `no_access`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..db import Database
from ..logging import get_logger
from ..settings import Settings
from . import store
from .store import CurrentSession
from .tokens import token_hash

log = get_logger("sahifa.auth")

SESSION_COOKIE = "__Host-sahifa_session"
LOGIN_COOKIE = "__Host-sahifa_login"
_STATE_KEY = "sahifa_auth_session"


@dataclass(frozen=True)
class Principal:
    """Who a request acts for.

    `oidc`: a signed-in user with access. `dev`: the local developer, no sign-in. `proxy`: the
    single principal behind HTTP basic auth at the proxy, which Sahifa cannot tell apart.
    """

    mode: str
    sign_in_method: str
    display_name: str
    email: str | None = None
    user_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    admin: bool = False


def actor_of(principal: Principal) -> str:
    """Who an event names, as text that outlives the user: the email, or `dev` / `proxy`."""
    return principal.email if principal.mode == "oidc" and principal.email else principal.mode


DEV_PRINCIPAL = Principal(mode="dev", sign_in_method="dev", display_name="Developer", admin=True)
PROXY_PRINCIPAL = Principal(mode="proxy", sign_in_method="proxy", display_name="Basic auth", admin=True)


class NoAccessError(Exception):
    """Signed in, but neither the admin email nor a member of any workspace."""

    def __init__(self, email: str | None) -> None:
        super().__init__(email)
        self.email = email


def no_access_body(email: str | None) -> dict[str, str | None]:
    """The 403 body: a code for the web app, the email and a sentence for people."""
    who = f" as {email}" if email else ""
    return {
        "detail": "no_access",
        "email": email,
        "message": f"You are signed in{who}, but this address has no access to this Sahifa yet. "
        "Ask a workspace admin for an invitation link.",
    }


def settings_of(request: Request) -> Settings:
    """The app's settings."""
    settings: Settings = request.app.state.settings
    return settings


def factory_of(request: Request) -> async_sessionmaker[AsyncSession]:
    """The app's session factory."""
    db: Database = request.app.state.db
    return db.sessions


def session_secret(settings: Settings) -> str:
    """The HMAC key of session and flow tokens; oidc mode refuses to start without one."""
    if settings.session_secret is None:
        raise RuntimeError("SAHIFA_SESSION_SECRET is required with SAHIFA_AUTH_MODE=oidc")
    return settings.session_secret.get_secret_value()


async def current_session(request: Request) -> CurrentSession | None:
    """The request's live session, or None (always None outside oidc mode)."""
    if hasattr(request.state, _STATE_KEY):
        cached: CurrentSession | None = getattr(request.state, _STATE_KEY)
        return cached
    settings = settings_of(request)
    token = request.cookies.get(SESSION_COOKIE)
    found: CurrentSession | None = None
    if token and settings.resolved_auth_mode == "oidc":
        async with factory_of(request)() as db, db.begin():
            found = await store.find_session(
                db, token_hash(session_secret(settings), token), idle=settings.session_idle
            )
    setattr(request.state, _STATE_KEY, found)
    return found


async def require_session(request: Request) -> CurrentSession:
    """The live session; 401 `not_authenticated` without one."""
    found = await current_session(request)
    if found is None:
        raise HTTPException(status_code=401, detail="not_authenticated")
    return found


async def signed_in(request: Request) -> Principal:
    """The principal of a signed-in request, with or without access; 401 without a session."""
    settings = settings_of(request)
    mode = settings.resolved_auth_mode
    if mode == "dev":
        return DEV_PRINCIPAL
    if mode == "proxy":
        return PROXY_PRINCIPAL
    session = await require_session(request)
    return Principal(
        mode="oidc",
        sign_in_method=session.sign_in_method,
        display_name=session.display_name,
        email=session.email,
        user_id=session.user_id,
        session_id=session.id,
        admin=settings.is_admin(session.email),
    )


async def current_user(request: Request) -> Principal:
    """The principal every protected route acts for: 401 `not_authenticated` without a
    session, 403 `no_access` without any workspace (spec 006 behaviour 4, spec 016)."""
    from .access import current_access

    return (await current_access(request)).principal

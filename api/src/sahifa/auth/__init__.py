"""Sign-in for the web app (spec 006, ADR-0010): OIDC against the Keycloak realm as a
backend-for-frontend, sessions in Postgres behind an HttpOnly cookie, and the CSRF guard.
Ported from Tabayyun's `tabayyun.auth` (Tabayyun spec 013) without orgs and memberships."""

from __future__ import annotations

from ..settings import Settings
from .csrf import CsrfMiddleware
from .deps import (
    LOGIN_COOKIE,
    SESSION_COOKIE,
    NoAccessError,
    Principal,
    current_session,
    current_user,
    no_access_body,
    require_session,
)
from .oidc import OidcClient


def build_oidc(settings: Settings) -> OidcClient | None:
    """The OIDC client in oidc mode, None in dev and proxy mode.

    Outside prod (where `prod_problems` already checked them) a missing setting stops the
    start too, naming it, rather than failing at the first sign-in.
    """
    if settings.resolved_auth_mode != "oidc":
        return None
    missing = [
        name
        for name, value in (
            ("SAHIFA_PUBLIC_URL", settings.public_url),
            ("SAHIFA_OIDC_ISSUER", settings.oidc_issuer),
            ("SAHIFA_OIDC_CLIENT_SECRET", settings.oidc_client_secret),
            ("SAHIFA_SESSION_SECRET", settings.session_secret),
        )
        if not value
    ]
    if missing or settings.oidc_issuer is None or settings.oidc_client_secret is None:
        raise RuntimeError(f"SAHIFA_AUTH_MODE=oidc needs {', '.join(missing)}")
    return OidcClient(
        settings.oidc_issuer, settings.oidc_client_id, settings.oidc_client_secret.get_secret_value()
    )


__all__ = [
    "LOGIN_COOKIE",
    "SESSION_COOKIE",
    "CsrfMiddleware",
    "NoAccessError",
    "OidcClient",
    "Principal",
    "build_oidc",
    "current_session",
    "current_user",
    "no_access_body",
    "require_session",
]

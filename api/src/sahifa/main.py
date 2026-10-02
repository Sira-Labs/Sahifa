"""FastAPI application: lifespan (schema guard, interrupted scans, env connections), the
sign-in (spec 006) and routes."""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from . import __version__
from .auth import CsrfMiddleware, NoAccessError, OidcClient, build_oidc, current_user, no_access_body
from .db import Database
from .db.migrate import head_revision
from .logging import configure, get_logger
from .routers import assets, auth, checks, connections, health, scans
from .services.connections import register_from_env
from .services.scans import ScanRunner, mark_interrupted
from .settings import Settings, get_settings, prod_problems

log = get_logger("sahifa")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    db = Database(settings.database_url)
    app.state.db = db
    app.state.runner = ScanRunner(db.sessions, settings)
    app.state.schema_revision = None
    try:
        async with db.sessions() as s:
            revision = (await s.execute(text("SELECT version_num FROM alembic_version"))).scalar()
            app.state.schema_revision = revision
            if revision != head_revision():
                log.error("db.schema_mismatch", database=revision, image=head_revision())
                sys.exit(3)
            interrupted = await mark_interrupted(s)
            if interrupted:
                log.warning("scan.interrupted", count=interrupted)
            await register_from_env(s)
    except SQLAlchemyError as e:
        # An unreachable database degrades /healthz instead of crashing the process.
        log.error("db.unavailable", error=str(e)[:300])
    log.info(
        "api.start",
        version=__version__,
        commit=settings.commit,
        schema=app.state.schema_revision,
        auth_mode=settings.resolved_auth_mode,
    )
    if settings.resolved_auth_mode == "proxy" and settings.oidc_issuer:
        log.warning("auth.mode", detail="SAHIFA_OIDC_ISSUER is set but SAHIFA_AUTH_MODE resolves to proxy")
    yield
    await app.state.runner.drain()
    oidc: OidcClient | None = app.state.oidc
    if oidc is not None:
        await oidc.aclose()
    await db.dispose()


def create_app(settings: Settings | None = None, *, oidc: OidcClient | None = None) -> FastAPI:
    """Build the app. `oidc` replaces the client built from the settings (tests serve a fake
    identity provider through it)."""
    settings = settings or get_settings()
    configure(settings.log_level)
    problems = prod_problems(settings)
    if problems:
        log.error("refusing to start in prod: " + "; ".join(problems))
        raise SystemExit(f"refusing to start in prod: {problems}")
    oidc = oidc or build_oidc(settings)
    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    app = FastAPI(
        title="Sahifa",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.oidc = oidc
    app.add_middleware(
        CsrfMiddleware, public_url=settings.public_url, exempt_paths=frozenset({auth.BACKCHANNEL_PATH})
    )

    @app.exception_handler(NoAccessError)
    async def no_access(request: Request, exc: NoAccessError) -> JSONResponse:
        """Signed in without access: 403 with a code, the email and a sentence (spec 006)."""
        return JSONResponse(status_code=403, content=no_access_body(exc.email))

    # Public: health, version and the sign-in itself. Everything else acts for a user.
    app.include_router(health.router)
    app.include_router(auth.router)
    protected = [Depends(current_user)]
    app.include_router(connections.router, dependencies=protected)
    app.include_router(scans.router, dependencies=protected)
    app.include_router(assets.router, dependencies=protected)
    app.include_router(checks.router, dependencies=protected)
    return app


def __getattr__(name: str) -> FastAPI:
    # `uvicorn sahifa.main:app` builds the app lazily, so importing this module (tests, the
    # migration CLI) does not read the environment.
    if name == "app":
        return create_app()
    raise AttributeError(name)

"""FastAPI application: lifespan (schema guard, interrupted scans, env connections, the job
queue or the inline upload clean-up and due schedules), the sign-in (spec 006) and routes."""

from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text, update
from sqlalchemy.exc import SQLAlchemyError

from . import __version__, jobs
from .auth import CsrfMiddleware, NoAccessError, OidcClient, build_oidc, current_user, no_access_body
from .auth.access import ForbiddenRoleError, WorkspaceRequiredError
from .db import Database
from .db.migrate import head_revision
from .db.models import Organisation
from .logging import configure, get_logger
from .routers import (
    assets,
    auth,
    checks,
    connections,
    findings,
    health,
    history,
    scans,
    schedules,
    workspaces,
)
from .security import (
    MB,
    UPLOAD_PATH,
    BodyLimitMiddleware,
    RateLimiter,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
    default_buckets,
)
from .services.connections import register_from_env
from .services.scans import ScanRunner, mark_interrupted
from .services.uploads import clean_uploads
from .settings import Settings, get_settings, prod_problems

log = get_logger("sahifa")
EXIT_RLS = 4
CLEAN_FIRST_S = 60
CLEAN_EVERY_S = 3600
SCHEDULES_EVERY_S = 60.0


async def clean_uploads_hourly(db: Database, settings: Settings) -> None:
    """Inline mode: the upload clean-up the worker runs hourly in queue mode (spec 008)."""
    await asyncio.sleep(CLEAN_FIRST_S)
    while True:
        try:
            await clean_uploads(db.system, settings)
        except Exception as e:
            log.error("uploads.clean_failed", error=str(e)[:300])
        await asyncio.sleep(CLEAN_EVERY_S)


async def run_schedules_every_minute(db: Database, settings: Settings, runner: ScanRunner) -> None:
    """Inline mode: the due-schedule job the worker runs every minute in queue mode (spec 010),
    at the start of each minute."""
    while True:
        await asyncio.sleep(SCHEDULES_EVERY_S - time.time() % SCHEDULES_EVERY_S)
        try:
            await jobs.run_due_schedules(db.system, settings, runner=runner)
        except Exception as e:
            log.error("schedule.run_failed", error=str(e)[:300])


async def check_rls(db: Database, settings: Settings) -> None:
    """Row-level security (spec 016) does not bind a superuser or BYPASSRLS login unless it can
    switch to `sahifa_app`: prod refuses to start (exit 4), dev warns."""
    if not await db.bypasses_rls():
        return
    detail = "the database login bypasses row-level security and cannot switch to sahifa_app"
    if settings.env == "prod":
        log.error("db.rls_bypassed", detail=detail)
        sys.exit(EXIT_RLS)
    log.warning("db.rls_bypassed", detail=detail)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    db = Database(settings.database_url)
    app.state.db = db
    app.state.runner = ScanRunner(db.system, settings)
    app.state.schema_revision = None
    try:
        async with db.system() as s:
            revision = (await s.execute(text("SELECT version_num FROM alembic_version"))).scalar()
            app.state.schema_revision = revision
            if revision != head_revision():
                log.error("db.schema_mismatch", database=revision, image=head_revision())
                sys.exit(3)
            await check_rls(db, settings)
            await s.execute(update(Organisation).values(name=settings.org_name))
            # In queue mode the reaper owns interrupted scans (spec 008).
            if settings.scan_execution == "inline":
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
        scan_execution=settings.scan_execution,
    )
    if settings.resolved_auth_mode == "proxy" and settings.oidc_issuer:
        log.warning("auth.mode", detail="SAHIFA_OIDC_ISSUER is set but SAHIFA_AUTH_MODE resolves to proxy")
    async with AsyncExitStack() as stack:
        if settings.scan_execution == "queue":
            await stack.enter_async_context(jobs.opened(settings, "api"))
        else:
            cleaner = asyncio.create_task(clean_uploads_hourly(db, settings))
            stack.callback(cleaner.cancel)
            scheduler = asyncio.create_task(run_schedules_every_minute(db, settings, app.state.runner))
            stack.callback(scheduler.cancel)
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
    docs = settings.docs_enabled
    app = FastAPI(
        title="Sahifa",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs" if docs else None,
        openapi_url="/api/openapi.json" if docs else None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.state.oidc = oidc
    # Outermost last (spec 012): headers on every answer, then size and disk, then rate limits,
    # then the CSRF guard, all before FastAPI parses a body.
    app.add_middleware(
        CsrfMiddleware, public_url=settings.public_url, exempt_paths=frozenset({auth.BACKCHANNEL_PATH})
    )
    if settings.rate_limits:
        app.state.limiter = RateLimiter(default_buckets(settings.rate_scans_per_hour))
        app.add_middleware(
            RateLimitMiddleware,
            limiter=app.state.limiter,
            exempt=frozenset({"/healthz", "/api/version", auth.BACKCHANNEL_PATH}),
        )
    app.add_middleware(
        BodyLimitMiddleware,
        default_bytes=MB,
        limits={UPLOAD_PATH: settings.max_upload_total_mb * MB},
        disk_dir=settings.uploads_dir,
        disk_paths=frozenset({UPLOAD_PATH}),
        min_free_bytes=settings.min_free_disk_mb * MB,
    )
    app.add_middleware(SecurityHeadersMiddleware, docs_enabled=docs)

    @app.exception_handler(NoAccessError)
    async def no_access(request: Request, exc: NoAccessError) -> JSONResponse:
        """Signed in without access: 403 with a code, the email and a sentence (spec 006)."""
        return JSONResponse(status_code=403, content=no_access_body(exc.email))

    @app.exception_handler(ForbiddenRoleError)
    async def forbidden_role(request: Request, exc: ForbiddenRoleError) -> JSONResponse:
        """The caller's role in the workspace is too low for the action (spec 016)."""
        return JSONResponse(status_code=403, content=exc.body())

    @app.exception_handler(WorkspaceRequiredError)
    async def workspace_required(request: Request, exc: WorkspaceRequiredError) -> JSONResponse:
        """The caller may act in several workspaces and named none (spec 016)."""
        return JSONResponse(
            status_code=422,
            content={
                "detail": "workspace_required",
                "message": "You work in several workspaces; choose the one this belongs to.",
            },
        )

    # Public: health, version and the sign-in itself. Everything else acts for a user.
    app.include_router(health.router)
    app.include_router(auth.router)
    protected = [Depends(current_user)]
    app.include_router(connections.router, dependencies=protected)
    app.include_router(schedules.router, dependencies=protected)
    app.include_router(scans.router, dependencies=protected)
    app.include_router(assets.router, dependencies=protected)
    app.include_router(checks.router, dependencies=protected)
    app.include_router(findings.router, dependencies=protected)
    app.include_router(history.router, dependencies=protected)
    app.include_router(workspaces.router, dependencies=protected)
    return app


def __getattr__(name: str) -> FastAPI:
    # `uvicorn sahifa.main:app` builds the app lazily, so importing this module (tests, the
    # migration CLI) does not read the environment.
    if name == "app":
        return create_app()
    raise AttributeError(name)

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
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from . import __version__, jobs
from .auth import CsrfMiddleware, NoAccessError, OidcClient, build_oidc, current_user, no_access_body
from .db import Database
from .db.migrate import head_revision
from .logging import configure, get_logger
from .routers import assets, auth, checks, connections, findings, health, scans, schedules
from .services.connections import register_from_env
from .services.scans import ScanRunner, mark_interrupted
from .services.uploads import clean_uploads
from .settings import Settings, get_settings, prod_problems

log = get_logger("sahifa")
CLEAN_FIRST_S = 60
CLEAN_EVERY_S = 3600
SCHEDULES_EVERY_S = 60.0


async def clean_uploads_hourly(db: Database, settings: Settings) -> None:
    """Inline mode: the upload clean-up the worker runs hourly in queue mode (spec 008)."""
    await asyncio.sleep(CLEAN_FIRST_S)
    while True:
        try:
            await clean_uploads(db.sessions, settings)
        except Exception as e:
            log.error("uploads.clean_failed", error=str(e)[:300])
        await asyncio.sleep(CLEAN_EVERY_S)


async def run_schedules_every_minute(db: Database, settings: Settings, runner: ScanRunner) -> None:
    """Inline mode: the due-schedule job the worker runs every minute in queue mode (spec 010),
    at the start of each minute."""
    while True:
        await asyncio.sleep(SCHEDULES_EVERY_S - time.time() % SCHEDULES_EVERY_S)
        try:
            await jobs.run_due_schedules(db.sessions, settings, runner=runner)
        except Exception as e:
            log.error("schedule.run_failed", error=str(e)[:300])


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
    app.include_router(schedules.router, dependencies=protected)
    app.include_router(scans.router, dependencies=protected)
    app.include_router(assets.router, dependencies=protected)
    app.include_router(checks.router, dependencies=protected)
    app.include_router(findings.router, dependencies=protected)
    return app


def __getattr__(name: str) -> FastAPI:
    # `uvicorn sahifa.main:app` builds the app lazily, so importing this module (tests, the
    # migration CLI) does not read the environment.
    if name == "app":
        return create_app()
    raise AttributeError(name)

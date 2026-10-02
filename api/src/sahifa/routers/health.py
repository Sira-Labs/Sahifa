"""Liveness and version (spec 004); the deploy check reads both (wait-live.sh).

`workers` lists the connected workers by commit (spec 008): the connections to this database
named `sahifa-worker/<commit>` in `pg_stat_activity`.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import __version__
from ..deps import session, settings
from ..settings import Settings

router = APIRouter()

WORKERS = text(
    "SELECT substr(application_name, length('sahifa-worker/') + 1) AS commit, count(*) AS connections"
    " FROM pg_stat_activity"
    " WHERE datname = current_database() AND application_name LIKE 'sahifa-worker/%'"
    " GROUP BY 1 ORDER BY 1"
)


@router.get("/healthz")
async def healthz(db: AsyncSession = Depends(session)) -> dict[str, Any]:
    workers: list[dict[str, Any]] = []
    try:
        await db.execute(text("SELECT 1"))
        database = "ok"
    except (SQLAlchemyError, OSError):
        database = "unavailable"
    if database == "ok":
        try:
            rows = (await db.execute(WORKERS)).all()
            workers = [{"commit": commit, "connections": int(n)} for commit, n in rows]
        except (SQLAlchemyError, OSError):
            workers = []
    return {
        "status": "ok" if database == "ok" else "degraded",
        "database": database,
        "version": __version__,
        "workers": workers,
    }


@router.get("/api/version")
async def version(request: Request, cfg: Settings = Depends(settings)) -> dict[str, Any]:
    return {
        "version": __version__,
        "commit": cfg.commit,
        "schema_revision": getattr(request.app.state, "schema_revision", None),
    }

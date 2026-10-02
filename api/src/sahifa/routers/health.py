"""Liveness and version (spec 004); the deploy check reads both (wait-live.sh)."""

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


@router.get("/healthz")
async def healthz(db: AsyncSession = Depends(session)) -> dict[str, Any]:
    try:
        await db.execute(text("SELECT 1"))
        database = "ok"
    except (SQLAlchemyError, OSError):
        database = "unavailable"
    # `workers` lists worker commits once the worker exists (spec 007); empty until then.
    return {"status": "ok" if database == "ok" else "degraded", "database": database,
            "version": __version__, "workers": []}


@router.get("/api/version")
async def version(request: Request, cfg: Settings = Depends(settings)) -> dict[str, Any]:
    return {"version": __version__, "commit": cfg.commit,
            "schema_revision": getattr(request.app.state, "schema_revision", None)}

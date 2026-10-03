"""Score history of a store and of a table (spec 011), read-only."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Asset, Connection, ScoreRecord
from ..deps import session
from ..schemas import History, HistoryPoint
from ..services.history import HISTORY_DEFAULT, HISTORY_MAX, anchor, history

router = APIRouter(prefix="/api", tags=["history"])

NOT_IN_HISTORY = {
    "detail": "scan_not_in_history",
    "message": "That scan has no score here: it failed, is not finished, or belongs to another store.",
}


def _points(rows: list[tuple[ScoreRecord, str]]) -> History:
    return History(
        points=[
            HistoryPoint(
                scan_id=r.scan_id,
                finished_at=r.measured_at,
                trigger=trigger,
                overall=r.overall,
                low=r.low,
                high=r.high,
                checks=r.checks,
                dimensions=r.dimensions,
            )
            for r, trigger in rows
        ]
    )


async def _read(
    db: AsyncSession,
    *,
    connection_id: uuid.UUID,
    asset_id: uuid.UUID | None,
    limit: int,
    scan_id: uuid.UUID | None,
) -> History | JSONResponse:
    until: ScoreRecord | None = None
    if scan_id is not None:
        until = await anchor(db, scan_id, connection_id=connection_id, asset_id=asset_id)
        if until is None:
            return JSONResponse(status_code=404, content=NOT_IN_HISTORY)
    return _points(
        await history(db, connection_id=connection_id, asset_id=asset_id, limit=limit, until=until)
    )


@router.get("/connections/{connection_id}/history", response_model=History)
async def store_history(
    connection_id: uuid.UUID,
    limit: int = Query(HISTORY_DEFAULT, ge=1, le=HISTORY_MAX),
    scan_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(session),
) -> History | JSONResponse:
    """The store's score over its last `limit` successful scans, oldest first, ending at
    `scan_id` when given."""
    if await db.get(Connection, connection_id) is None:
        raise HTTPException(404, "connection not found")
    return await _read(db, connection_id=connection_id, asset_id=None, limit=limit, scan_id=scan_id)


@router.get("/assets/{asset_id}/history", response_model=History)
async def asset_history(
    asset_id: uuid.UUID,
    limit: int = Query(HISTORY_DEFAULT, ge=1, le=HISTORY_MAX),
    scan_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(session),
) -> History | JSONResponse:
    """One table's score over its last `limit` successful scans, as for the store."""
    asset = await db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(404, "asset not found")
    return await _read(db, connection_id=asset.connection_id, asset_id=asset.id, limit=limit, scan_id=scan_id)

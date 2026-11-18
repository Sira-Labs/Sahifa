"""Measure history of a column (spec 024), read-only."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Asset, AssetColumn
from ..deps import session
from ..schemas import MeasureHistory, MeasurePoint
from ..services.measures import MEASURES_DEFAULT, MEASURES_MAX, measure_history

router = APIRouter(prefix="/api", tags=["measures"])

COLUMN_NOT_FOUND = {
    "detail": "column_not_found",
    "message": "This table has no column of that name, now or in its history.",
}


@router.get("/assets/{asset_id}/measures", response_model=MeasureHistory)
async def column_measures(
    asset_id: uuid.UUID,
    column: str = Query(min_length=1, max_length=1000),
    limit: int = Query(MEASURES_DEFAULT, ge=1, le=MEASURES_MAX),
    db: AsyncSession = Depends(session),
) -> MeasureHistory | JSONResponse:
    """What the last `limit` successful scans measured on one column of a table, oldest
    first. A column without history yet answers with no points."""
    asset = await db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(404, "asset not found")
    rows = await measure_history(db, asset_id=asset.id, column=column, limit=limit)
    if not rows:
        known = await db.scalar(
            select(AssetColumn.name).where(AssetColumn.asset_id == asset.id, AssetColumn.name == column)
        )
        if known is None:
            return JSONResponse(status_code=404, content=COLUMN_NOT_FOUND)
    return MeasureHistory(
        asset_id=asset.id,
        column=column,
        points=[
            MeasurePoint(
                scan_id=r.scan_id,
                finished_at=r.measured_at,
                trigger=trigger,
                rows=r.rows,
                population=r.population,
                sampled=r.sampled,
                measures=r.measures,
            )
            for r, trigger in rows
        ],
    )

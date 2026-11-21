"""Measure history of a column (spec 024) and its anomaly thresholds (spec 025), read-only."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sahifa_core.anomaly import DEFAULT_RATE
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Asset, AssetColumn
from ..deps import session
from ..schemas import MeasureHistory, MeasurePoint, MeasureThreshold, MeasureThresholds
from ..services.measures import (
    MEASURES_DEFAULT,
    MEASURES_MAX,
    THRESHOLD_HISTORY,
    measure_history,
    measure_thresholds,
)

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


@router.get("/assets/{asset_id}/measures/thresholds", response_model=MeasureThresholds)
async def column_thresholds(
    asset_id: uuid.UUID,
    column: str = Query(min_length=1, max_length=1000),
    rate: float = Query(DEFAULT_RATE, ge=0.01, le=0.5),
    db: AsyncSession = Depends(session),
) -> MeasureThresholds | JSONResponse:
    """Per measure of a column: whether the newest scan's value is unusual given the scans
    before it, and the interval the next scan's value is expected in, at the false-alarm
    rate `rate` (one ordinary reading in twenty by default)."""
    asset = await db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(404, "asset not found")
    rows = await measure_history(db, asset_id=asset.id, column=column, limit=THRESHOLD_HISTORY)
    if not rows:
        known = await db.scalar(
            select(AssetColumn.name).where(AssetColumn.asset_id == asset.id, AssetColumn.name == column)
        )
        if known is None:
            return JSONResponse(status_code=404, content=COLUMN_NOT_FOUND)
        return MeasureThresholds(asset_id=asset.id, column=column, rate=rate, period=None, measures={})
    period, found = measure_thresholds([record for record, _ in rows], rate=rate)
    return MeasureThresholds(
        asset_id=asset.id,
        column=column,
        rate=rate,
        period=period,
        measures={name: MeasureThreshold(**body) for name, body in found.items()},
    )

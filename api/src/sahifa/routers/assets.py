"""Assets (spec 007): the tables, views and file sets each scan of a connection stored."""

from __future__ import annotations

import base64
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, literal, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from ..auth.access import Access
from ..db.models import CHECK_STATUSES, Asset, AssetColumn, Check
from ..deps import access, session
from ..schemas import AssetDetail, AssetOut, CheckCounts, ColumnOut, Page

router = APIRouter(prefix="/api/assets", tags=["assets"])

# Ordered and paged by (namespace, name), the asset's identity; the label is for display only.
ORDER = (Asset.namespace, Asset.name, Asset.id)


def _cursor(asset: Asset) -> str:
    raw = json.dumps([asset.namespace, asset.name, str(asset.id)]).encode()
    return base64.urlsafe_b64encode(raw).decode()


def _after(cursor: str) -> tuple[str, str, uuid.UUID]:
    try:
        namespace, name, aid = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return str(namespace), str(name), uuid.UUID(aid)
    except (ValueError, TypeError) as e:
        raise HTTPException(422, "invalid cursor") from e


async def _counts(db: AsyncSession, ids: list[uuid.UUID]) -> dict[uuid.UUID, CheckCounts]:
    """Checks per status of each asset."""
    counts = {i: CheckCounts() for i in ids}
    if ids:
        rows = await db.execute(
            select(Check.asset_id, Check.status, func.count())
            .where(Check.asset_id.in_(ids))
            .group_by(Check.asset_id, Check.status)
        )
        for asset_id, status, n in rows.all():
            if status in CHECK_STATUSES:
                setattr(counts[asset_id], status, int(n))
    return counts


def to_out(asset: Asset, counts: CheckCounts) -> AssetOut:
    return AssetOut(
        id=asset.id,
        connection_id=asset.connection_id,
        namespace=asset.namespace,
        name=asset.name,
        label=asset.label,
        kind=asset.kind,
        row_count=asset.row_count,
        last_scan_id=asset.last_scan_id,
        checks=counts,
    )


@router.get("", response_model=Page[AssetOut])
async def list_assets(
    connection_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    workspace_id: uuid.UUID | None = None,
    db: AsyncSession = Depends(session),
    caller: Access = Depends(access),
) -> Page[AssetOut]:
    stmt = select(Asset).order_by(*ORDER).limit(limit + 1)
    if connection_id is not None:
        stmt = stmt.where(Asset.connection_id == connection_id)
    if workspace_id is not None:
        stmt = stmt.where(Asset.workspace_id == workspace_id)
    if cursor:
        namespace, name, aid = _after(cursor)
        stmt = stmt.where(tuple_(*ORDER) > tuple_(literal(namespace), literal(name), literal(aid)))
    rows = list(await db.scalars(stmt))
    page = rows[:limit]
    counts = await _counts(db, [a.id for a in page])
    nxt = _cursor(rows[limit - 1]) if len(rows) > limit else None
    return Page[AssetOut](
        items=[caller.stamp(to_out(a, counts[a.id]), a.workspace_id) for a in page], next_cursor=nxt
    )


@router.get("/{asset_id}", response_model=AssetDetail)
async def get_asset(
    asset_id: uuid.UUID, db: AsyncSession = Depends(session), caller: Access = Depends(access)
) -> AssetDetail:
    asset = await db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(404, "asset not found")
    counts = await _counts(db, [asset.id])
    columns = await db.scalars(
        select(AssetColumn)
        .where(AssetColumn.asset_id == asset.id)
        .order_by(AssetColumn.position, AssetColumn.name)
    )
    return AssetDetail(
        **caller.stamp(to_out(asset, counts[asset.id]), asset.workspace_id).model_dump(),
        columns=[
            ColumnOut(
                name=c.name,
                position=c.position,
                physical_type=c.physical_type,
                logical_type=c.logical_type,
                semantic_type=c.semantic_type,
                role=c.role,
            )
            for c in columns
        ],
    )

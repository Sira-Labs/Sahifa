"""Score history (spec 011): the scores each successful scan writes, and reading them back."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sahifa_core.models import label_of
from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import Scan, ScoreRecord

HISTORY_DEFAULT = 30
HISTORY_MAX = 100


def checks_of(score: dict[str, Any]) -> int:
    """The checks a score evaluated: the sum over its dimensions."""
    return sum(int(d.get("checks") or 0) for d in (score.get("dimensions") or {}).values())


def _record(
    score: dict[str, Any],
    *,
    scan_id: uuid.UUID,
    connection_id: uuid.UUID,
    asset_id: uuid.UUID | None,
    at: datetime,
) -> ScoreRecord:
    return ScoreRecord(
        scan_id=scan_id,
        connection_id=connection_id,
        asset_id=asset_id,
        measured_at=at,
        overall=score.get("overall"),
        low=score.get("low"),
        high=score.get("high"),
        checks=checks_of(score),
        dimensions=score.get("dimensions") or {},
    )


def score_records(
    report: dict[str, Any],
    *,
    scan_id: uuid.UUID,
    connection_id: uuid.UUID,
    finished_at: datetime,
    asset_ids: dict[str, uuid.UUID],
) -> list[ScoreRecord]:
    """The store's score and each table's that has an asset row (`asset_ids` by label)."""
    common: dict[str, Any] = {"scan_id": scan_id, "connection_id": connection_id, "at": finished_at}
    out = [_record(report.get("score") or {}, asset_id=None, **common)]
    for asset in report.get("assets", []):
        ref = asset.get("ref") or {}
        asset_id = asset_ids.get(label_of(ref.get("namespace", ""), ref.get("name", "")))
        if asset_id is not None:
            out.append(_record(asset.get("score") or {}, asset_id=asset_id, **common))
    return out


async def anchor(
    db: AsyncSession, scan_id: uuid.UUID, *, connection_id: uuid.UUID, asset_id: uuid.UUID | None
) -> ScoreRecord | None:
    """The score of `scan_id` at this level, where a history cut at that scan ends."""
    level = ScoreRecord.asset_id.is_(None) if asset_id is None else ScoreRecord.asset_id == asset_id
    return await db.scalar(
        select(ScoreRecord).where(
            ScoreRecord.scan_id == scan_id, ScoreRecord.connection_id == connection_id, level
        )
    )


async def history(
    db: AsyncSession,
    *,
    connection_id: uuid.UUID,
    asset_id: uuid.UUID | None,
    limit: int,
    until: ScoreRecord | None = None,
) -> list[tuple[ScoreRecord, str]]:
    """The last `limit` scores of the store (`asset_id` None) or one table, oldest first, with
    each scan's trigger; with `until`, the ones up to and including that score."""
    stmt = select(ScoreRecord, Scan.trigger).join(Scan, Scan.id == ScoreRecord.scan_id)
    if asset_id is None:
        stmt = stmt.where(ScoreRecord.connection_id == connection_id, ScoreRecord.asset_id.is_(None))
    else:
        stmt = stmt.where(ScoreRecord.asset_id == asset_id)
    if until is not None:
        stmt = stmt.where(
            tuple_(ScoreRecord.measured_at, ScoreRecord.scan_id) <= tuple_(until.measured_at, until.scan_id)
        )
    rows = await db.execute(
        stmt.order_by(ScoreRecord.measured_at.desc(), ScoreRecord.scan_id.desc()).limit(limit)
    )
    return [(record, trigger) for record, trigger in reversed(rows.all())]

"""Measure history per column (spec 024): what each successful scan measured, and reading
it back."""

from __future__ import annotations

import math
import uuid
from datetime import datetime
from typing import Any

from sahifa_core.models import label_of
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import ColumnMeasure, Scan

MEASURES_DEFAULT = 30
MEASURES_MAX = 100
# Rows per INSERT: a scan of a large store writes tens of thousands.
INSERT_CHUNK = 1000
# Profile fields stored as they are, when they are numbers.
PLAIN = ("mean", "stddev", "min", "max", "mean_length")


def _number(value: Any) -> float | None:
    """`value` as a finite float; None for anything else (text, booleans, NaN, infinity)."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _share(part: Any, whole: Any) -> float | None:
    """`part / whole`, or None when either is missing or the whole is not positive."""
    numerator, denominator = _number(part), _number(whole)
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def measures_of(profile: dict[str, Any]) -> dict[str, float]:
    """The measures of one column profile, by name; a measure the profile lacks is absent.

    `null_share` and `blank_share` are shares of the rows read, `distinct_share` of the rows
    with a value. Minimum and maximum are kept for numbers only (they are text for dates)."""
    rows, nulls = profile.get("rows"), profile.get("nulls")
    with_value = (rows or 0) - (nulls or 0)
    found: dict[str, float | None] = {
        "null_share": _share(nulls, rows),
        "distinct_share": _share(profile.get("distinct"), with_value),
        "blank_share": _share(profile.get("blanks"), rows),
    }
    for name in PLAIN:
        found[name] = _number(profile.get(name))
    for name, value in (profile.get("quantiles") or {}).items():
        found[str(name)] = _number(value)
    return {name: value for name, value in found.items() if value is not None}


def measure_rows(
    report: dict[str, Any],
    *,
    scan_id: uuid.UUID,
    connection_id: uuid.UUID,
    finished_at: datetime,
    asset_ids: dict[str, uuid.UUID],
) -> list[dict[str, Any]]:
    """One row per column of every table of the report that has an asset row (`asset_ids` by
    label), ready for a bulk insert."""
    out: list[dict[str, Any]] = []
    for asset in report.get("assets", []):
        ref = asset.get("ref") or {}
        asset_id = asset_ids.get(label_of(ref.get("namespace", ""), ref.get("name", "")))
        if asset_id is None:
            continue
        population = asset.get("population")
        for column in asset.get("columns", []):
            profile = column.get("profile") or {}
            name = profile.get("name")
            if not name:
                continue
            out.append(
                {
                    "id": uuid.uuid4(),
                    "scan_id": scan_id,
                    "connection_id": connection_id,
                    "asset_id": asset_id,
                    "column_name": name,
                    "measured_at": finished_at,
                    "rows": int(profile.get("rows") or 0),
                    "population": population if isinstance(population, int) else None,
                    "sampled": bool(asset.get("sampled")),
                    "measures": measures_of(profile),
                }
            )
    return out


async def record_measures(db: AsyncSession, rows: list[dict[str, Any]]) -> int:
    """Insert `rows` in chunks; the workspace is filled by trigger. Returns how many."""
    for start in range(0, len(rows), INSERT_CHUNK):
        await db.execute(insert(ColumnMeasure), rows[start : start + INSERT_CHUNK])
    return len(rows)


async def measure_history(
    db: AsyncSession, *, asset_id: uuid.UUID, column: str, limit: int
) -> list[tuple[ColumnMeasure, str]]:
    """The last `limit` measures of one column of a table, oldest first, with each scan's
    trigger."""
    rows = await db.execute(
        select(ColumnMeasure, Scan.trigger)
        .join(Scan, Scan.id == ColumnMeasure.scan_id)
        .where(ColumnMeasure.asset_id == asset_id, ColumnMeasure.column_name == column)
        .order_by(ColumnMeasure.measured_at.desc(), ColumnMeasure.scan_id.desc())
        .limit(limit)
    )
    return [(record, trigger) for record, trigger in reversed(rows.all())]

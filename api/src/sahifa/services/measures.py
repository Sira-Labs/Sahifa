"""Measure history per column (spec 024): what each successful scan measured, and reading
it back."""

from __future__ import annotations

import itertools
import math
import uuid
from datetime import datetime
from typing import Any

from sahifa_core.anomaly import Threshold, readings_needed, threshold
from sahifa_core.models import label_of
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db.models import ColumnMeasure, Scan

MEASURES_DEFAULT = 30
MEASURES_MAX = 100
# Rows per INSERT: a scan of a large store writes tens of thousands.
INSERT_CHUNK = 1000
# The scans a threshold is built from, newest last: enough for a false-alarm rate of 1 %.
THRESHOLD_HISTORY = 120
# Scans of a daily schedule are this far apart, give or take; such a history has a weekly cycle.
DAY_S = 86_400
DAILY_TOLERANCE_S = 3 * 3600
WEEK = 7
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


def daily_run(times: list[datetime]) -> int:
    """How many of the newest scans form an unbroken daily series: each a day after the one
    before, give or take three hours."""
    run = 1 if times else 0
    for earlier, later in itertools.pairwise(reversed(times)):
        # Reversed, so `earlier` is the later scan of the pair.
        if abs((earlier - later).total_seconds() - DAY_S) > DAILY_TOLERANCE_S:
            break
        run += 1
    return run


def weekly_run(times: list[datetime]) -> int | None:
    """The length of the newest unbroken daily series when it is long enough to show a weekly
    cycle (two weeks and a day), else None.

    The cycle is read by position, seven readings to a week, so it only holds where no day is
    missing and none has two scans: a gap or an extra scan ends the series, and what came
    before it is not read with the cycle."""
    run = daily_run(times)
    return run if run >= 2 * WEEK + 1 else None


def period_of(times: list[datetime]) -> int | None:
    """7 when the whole history is one unbroken daily series long enough for a weekly cycle,
    else None."""
    return WEEK if times and weekly_run(times) == len(times) else None


def is_share(measure: str) -> bool:
    return measure.endswith("_share")


def clamp(found: Threshold, measure: str) -> Threshold:
    """A share cannot leave 0 to 1, so its interval does not either."""
    if not is_share(measure):
        return found
    return Threshold(
        expected=min(1.0, max(0.0, found.expected)),
        low=max(0.0, found.low),
        high=min(1.0, found.high),
        scores=found.scores,
    )


def measure_thresholds(
    points: list[ColumnMeasure], *, rate: float
) -> tuple[int | None, dict[str, dict[str, Any]]]:
    """For each measure of a column's history (oldest first): the newest reading against the
    interval built from the scans before it, and the interval for the next scan. Returns the
    cycle the history was read with and, per measure, `value`, `newest`, `next`, `scans` and
    `scans_needed`; an interval is None while the measure's history is too short for `rate`.
    `scans_needed` is what the next scan's interval needs; judging the newest reading takes
    one more, because it is judged by the scans before it.

    A scan without the measure (an empty table) is left out of that measure's history."""
    # With a daily series at the end of the history, read that series with a weekly cycle and
    # leave the scans before it out: positions before a missed day would be a day off.
    run = weekly_run([p.measured_at for p in points])
    period = WEEK if run is not None else None
    cycled = points[-run:] if run is not None else points
    names: dict[str, None] = {}
    for point in points:
        names.update(dict.fromkeys(point.measures))
    out: dict[str, dict[str, Any]] = {}
    for name in names:
        # The cycle is by position, so it only holds for a measure every scan of the series has.
        whole = period is not None and all(name in p.measures for p in cycled)
        read, cycle = (cycled, period) if whole else (points, None)
        values = [float(p.measures[name]) for p in read if name in p.measures]
        has_newest = name in points[-1].measures
        before = threshold(values[:-1], rate, cycle) if has_newest else None
        upcoming = threshold(values, rate, cycle)
        out[name] = {
            "value": values[-1] if has_newest else None,
            "newest": None if before is None else _interval(clamp(before, name), values[-1]),
            "next": None if upcoming is None else _interval(clamp(upcoming, name)),
            "scans": len(values),
            "scans_needed": readings_needed(rate, cycle),
        }
    return period, out


def _interval(found: Threshold, value: float | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "expected": found.expected,
        "low": found.low,
        "high": found.high,
        "scores": found.scores,
    }
    if value is not None:
        body["unusual"] = found.outside(value)
    return body

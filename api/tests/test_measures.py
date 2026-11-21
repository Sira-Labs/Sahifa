"""Measure history per column (spec 024): what a scan stores and how it reads back."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from httpx import AsyncClient
from sahifa_core.synth import write_shop
from sqlalchemy.engine import Engine

from sahifa.db.migrate import build_config, downgrade, upgrade
from sahifa.db.models import ColumnMeasure
from sahifa.services.measures import (
    measure_rows,
    measure_thresholds,
    measures_of,
    period_of,
    weekly_run,
)

from .conftest import DB_URL, needs_db, owner_engine
from .test_checks import asset_id, connect, make_asset, make_connection, scan, sql
from .test_history import make_scan

T0 = datetime(2026, 9, 1, 2, 0, tzinfo=UTC)


@pytest.fixture
def owner() -> Iterator[Engine]:
    assert DB_URL
    upgrade(DB_URL)
    engine = owner_engine()
    yield engine
    engine.dispose()


# --- What is measured ----------------------------------------------------------------------


def test_measures_of_a_numeric_column() -> None:
    profile = {
        "name": "amount",
        "rows": 200,
        "nulls": 10,
        "distinct": 95,
        "blanks": None,
        "mean": 12.5,
        "stddev": 3.0,
        "min": 1.0,
        "max": 40,
        "quantiles": {"p01": 1.5, "p25": 9.0, "p50": 12.0, "p75": 15.0, "p99": 39.0},
        "mean_length": None,
    }
    assert measures_of(profile) == {
        "null_share": 0.05,
        "distinct_share": 0.5,
        "mean": 12.5,
        "stddev": 3.0,
        "min": 1.0,
        "max": 40.0,
        "p01": 1.5,
        "p25": 9.0,
        "p50": 12.0,
        "p75": 15.0,
        "p99": 39.0,
    }


def test_measures_of_a_text_and_a_time_column() -> None:
    text_profile = {"rows": 50, "nulls": 0, "distinct": 5, "blanks": 5, "mean_length": 7.2}
    assert measures_of(text_profile) == {
        "null_share": 0.0,
        "distinct_share": 0.1,
        "blank_share": 0.1,
        "mean_length": 7.2,
    }
    # Minimum and maximum of a timestamp are text in the profile: not stored (spec, Decisions).
    time_profile = {"rows": 4, "nulls": 1, "distinct": 3, "min": "2025-10-15T06:10:42", "max": "2026-11-14"}
    assert measures_of(time_profile) == {"null_share": 0.25, "distinct_share": 1.0}


@pytest.mark.parametrize(
    "profile",
    [
        {},
        {"rows": 0, "nulls": 0, "distinct": 0},
        # Every value null: no share of distinct values among none.
        {"rows": 3, "nulls": 3, "distinct": 0, "mean": None},
    ],
)
def test_zero_denominators_leave_the_share_out(profile: dict[str, Any]) -> None:
    measured = measures_of(profile)
    assert "distinct_share" not in measured
    assert measured == ({"null_share": 1.0} if profile.get("rows") else {})


def test_only_finite_numbers_are_stored() -> None:
    profile = {
        "rows": 10,
        "nulls": 0,
        "mean": float("nan"),
        "stddev": float("inf"),
        "max": True,
        "quantiles": {"p50": float("-inf"), "p75": 2},
    }
    assert measures_of(profile) == {"null_share": 0.0, "p75": 2.0}


def test_rows_only_for_tables_with_an_asset_row() -> None:
    aid = uuid.uuid4()
    report = {
        "assets": [
            {
                "ref": {"namespace": "public", "name": "orders"},
                "population": 1000,
                "sampled": True,
                "columns": [
                    {"profile": {"name": "id", "rows": 100, "nulls": 0, "distinct": 100}},
                    {"profile": {"rows": 100}},
                    {},
                ],
            },
            {"ref": {"namespace": "public", "name": "not_stored"}, "columns": [{"profile": {"name": "x"}}]},
            {"ref": {"namespace": "public", "name": "failed"}, "error": "boom"},
        ]
    }
    scan_id, connection_id = uuid.uuid4(), uuid.uuid4()
    rows = measure_rows(
        report,
        scan_id=scan_id,
        connection_id=connection_id,
        finished_at=T0,
        asset_ids={"public.orders": aid},
    )
    assert len(rows) == 1
    [row] = rows
    assert (row["asset_id"], row["column_name"], row["rows"], row["population"], row["sampled"]) == (
        aid,
        "id",
        100,
        1000,
        True,
    )
    assert row["measures"] == {"null_share": 0.0, "distinct_share": 1.0}
    assert (row["scan_id"], row["connection_id"], row["measured_at"]) == (scan_id, connection_id, T0)


# --- Stored by a scan, read through the API --------------------------------------------------


async def read(client: AsyncClient, asset: str, column: str, **params: Any) -> dict[str, Any]:
    r = await client.get(f"/api/assets/{asset}/measures", params={"column": column, **params})
    assert r.status_code == 200, r.text
    out: dict[str, Any] = r.json()
    return out


@needs_db
async def test_scan_writes_measures(
    client: AsyncClient, owner: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_shop(tmp_path / "shop", rows=300)
    cid = await connect(client, monkeypatch, tmp_path / "shop")
    reports = [await scan(client, cid) for _ in range(3)]
    ids = [r["scan_id"] for r in reports]

    # One row per column of every table; the share of nulls wherever the profile read rows
    # (the shop's `returns` is empty).
    for report in reports:
        profiles = [c["profile"] for a in report["assets"] for c in a["columns"]]
        with_rows = sum(1 for p in profiles if p["rows"] > 0)
        stored = sql(
            owner,
            "SELECT count(*), count(*) FILTER (WHERE measures ? 'null_share'),"
            " count(*) FILTER (WHERE measures = '{}'::jsonb) FROM column_measures WHERE scan_id = :s",
            s=report["scan_id"],
        )
        assert stored == [(len(profiles), with_rows, len(profiles) - with_rows)]
        assert 0 < with_rows < len(profiles)

    aid = await asset_id(client, cid, "orders")
    history = await read(client, aid, "amount")
    assert (history["asset_id"], history["column"]) == (aid, "amount")
    points = history["points"]
    assert [p["scan_id"] for p in points] == ids
    assert {p["trigger"] for p in points} == {"manual"}
    assert [p["finished_at"] for p in points] == sorted(p["finished_at"] for p in points)

    # The numbers are the report's profile.
    [orders] = [a for a in reports[-1]["assets"] if a["ref"]["name"] == "orders"]
    [amount] = [c["profile"] for c in orders["columns"] if c["profile"]["name"] == "amount"]
    newest = points[-1]
    assert (newest["rows"], newest["population"], newest["sampled"]) == (
        amount["rows"],
        orders["population"],
        False,
    )
    measured = newest["measures"]
    assert measured["mean"] == amount["mean"] and measured["max"] == amount["max"]
    assert measured["null_share"] == amount["nulls"] / amount["rows"]
    assert {"p01", "p25", "p50", "p75", "p99", "stddev", "min", "distinct_share"} <= set(measured)
    assert "blank_share" not in measured

    # A text column has its own measures; a timestamp only the shares.
    status = (await read(client, aid, "status"))["points"][-1]["measures"]
    assert {"null_share", "distinct_share", "blank_share", "mean_length"} == set(status)
    assert set((await read(client, aid, "ordered_at"))["points"][-1]["measures"]) == {
        "null_share",
        "distinct_share",
    }

    assert [p["scan_id"] for p in (await read(client, aid, "amount", limit=2))["points"]] == ids[1:]


@needs_db
async def test_unknown_columns_and_tables(client: AsyncClient, owner: Engine) -> None:
    cid = make_connection(owner)
    aid = make_asset(owner, cid, "orders")
    sql(
        owner,
        "INSERT INTO columns (asset_id, name, position, physical_type, logical_type, role)"
        " VALUES (:a, 'new', 0, 'INTEGER', 'integer', 'measure')",
        a=aid,
    )
    # A column that exists has an empty history; one that never did is not found.
    assert (await read(client, aid, "new"))["points"] == []
    r = await client.get(f"/api/assets/{aid}/measures", params={"column": "nope"})
    assert r.status_code == 404 and r.json()["detail"] == "column_not_found"

    # A column that is gone from the table keeps its history.
    sid = make_scan(owner, cid, at=T0)
    older = make_scan(owner, cid, at=T0 - timedelta(days=1))
    for scan_id, at, share in ((sid, T0, 0.5), (older, T0 - timedelta(days=1), 0.25)):
        sql(
            owner,
            "INSERT INTO column_measures (id, scan_id, connection_id, asset_id, column_name, measured_at,"
            " rows, population, sampled, measures) VALUES (gen_random_uuid(), :s, :c, :a, 'dropped', :at,"
            " 8, 80, true, CAST(:m AS jsonb))",
            s=scan_id,
            c=cid,
            a=aid,
            at=at,
            m=f'{{"null_share": {share}}}',
        )
    gone = (await read(client, aid, "dropped"))["points"]
    assert [(p["scan_id"], p["measures"]) for p in gone] == [
        (older, {"null_share": 0.25}),
        (sid, {"null_share": 0.5}),
    ]
    assert (gone[0]["rows"], gone[0]["population"], gone[0]["sampled"]) == (8, 80, True)

    assert (
        await client.get(f"/api/assets/{uuid.uuid4()}/measures", params={"column": "x"})
    ).status_code == 404
    assert (await client.get(f"/api/assets/{aid}/measures")).status_code == 422
    for limit in (0, 101, "x"):
        r = await client.get(f"/api/assets/{aid}/measures", params={"column": "new", "limit": limit})
        assert r.status_code == 422

    # The rows go with their scan.
    sql(owner, "DELETE FROM scans WHERE id = :s", s=older)
    assert [p["scan_id"] for p in (await read(client, aid, "dropped"))["points"]] == [sid]


@needs_db
async def test_failed_scan_writes_none(
    client: AsyncClient, owner: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = await connect(client, monkeypatch, tmp_path / "missing")
    r = await client.post("/api/scans", json={"connection_id": cid, "sample_rows": 0})
    assert r.status_code == 202, r.text
    sid = r.json()["id"]
    for _ in range(600):
        if (await client.get(f"/api/scans/{sid}")).json()["status"] == "failed":
            break
        await asyncio.sleep(0.05)
    assert (await client.get(f"/api/scans/{sid}")).json()["status"] == "failed"
    assert sql(owner, "SELECT count(*) FROM column_measures WHERE scan_id = :s", s=sid) == [(0,)]


@needs_db
def test_migration_0012_round_trips(owner: Engine) -> None:
    assert DB_URL
    downgrade(DB_URL, "0011")
    try:
        assert sql(owner, "SELECT to_regclass('column_measures')") == [(None,)]
    finally:
        upgrade(DB_URL)
    assert sql(owner, "SELECT relforcerowsecurity FROM pg_class WHERE relname = 'column_measures'") == [
        (True,)
    ]
    assert sql(owner, "SELECT count(*) FROM pg_trigger WHERE tgname = 'trg_column_measures_workspace'") == [
        (1,)
    ]
    command.check(build_config(DB_URL))


# --- Anomaly thresholds (spec 025) -------------------------------------------------------------


def reading(day: float, **measures: float) -> ColumnMeasure:
    return ColumnMeasure(measured_at=T0 + timedelta(days=day), rows=100, measures=measures)


def test_a_weekly_cycle_needs_an_unbroken_daily_series() -> None:
    daily = [T0 + timedelta(days=d, minutes=d % 5) for d in range(20)]
    assert period_of(daily) == 7 and weekly_run(daily) == 20
    assert period_of(daily[:14]) is None  # under two weeks and a day
    assert period_of([T0 + timedelta(hours=6 * d) for d in range(30)]) is None
    assert period_of([T0 + timedelta(days=7 * d) for d in range(30)]) is None
    assert period_of([]) is None and weekly_run([]) is None
    # Alternating 20 and 28 hours has a median gap of a day but is not a daily series.
    hours = [0]
    for i in range(42):
        hours.append(hours[-1] + (20 if i % 2 == 0 else 28))
    assert period_of([T0 + timedelta(hours=h) for h in hours]) is None
    # A missed day ends the series: only the scans after it are read with the cycle.
    missed = [T0 + timedelta(days=d) for d in [*range(10), *range(11, 31)]]
    assert weekly_run(missed) == 20 and period_of(missed) is None
    assert weekly_run([T0 + timedelta(days=d) for d in [*range(41), 42]]) is None


def test_thresholds_judge_the_newest_reading_and_give_the_next_interval() -> None:
    # 30 scans at irregular times: a mean around 50, a null share of 0 that jumps at the end.
    means = [50 + (i * 7 % 5) - 2 for i in range(30)]
    points = [reading(i * 1.7, mean=m, null_share=0.0) for i, m in enumerate(means)]
    points[-1].measures["null_share"] = 0.4
    period, found = measure_thresholds(points, rate=0.05)
    assert period is None
    assert set(found) == {"mean", "null_share"}

    mean = found["mean"]
    assert (mean["value"], mean["scans"], mean["scans_needed"]) == (means[-1], 30, 22)
    assert mean["newest"]["unusual"] is False
    assert mean["newest"]["low"] <= means[-1] <= mean["newest"]["high"]
    assert mean["next"]["low"] < mean["next"]["expected"] < mean["next"]["high"]
    assert "unusual" not in mean["next"] and mean["next"]["scores"] == 27

    nulls = found["null_share"]
    assert nulls["value"] == 0.4 and nulls["newest"]["unusual"] is True
    # A share's interval stays within 0 to 1.
    assert nulls["newest"]["low"] == 0.0 and 0.0 <= nulls["newest"]["high"] < 0.4
    assert nulls["next"]["low"] >= 0.0 and nulls["next"]["high"] <= 1.0


def test_thresholds_wait_for_enough_history_and_skip_scans_without_the_measure() -> None:
    points = [reading(i * 1.3, mean=float(i % 3)) for i in range(10)]
    _, found = measure_thresholds(points, rate=0.05)
    assert found["mean"] == {"value": 0.0, "newest": None, "next": None, "scans": 10, "scans_needed": 22}
    # At a rate of one in two, three warm-up scans and one error are enough.
    _, quick = measure_thresholds(points, rate=0.5)
    assert quick["mean"]["scans_needed"] == 4 and quick["mean"]["next"] is not None

    # The newest scan read an empty table: the measure has no value to judge, but an interval
    # for the next scan from the scans that had it.
    points = [reading(i * 1.3, mean=10.0 + i % 2) for i in range(30)] + [reading(40)]
    _, found = measure_thresholds(points, rate=0.05)
    assert found["mean"]["value"] is None and found["mean"]["newest"] is None
    assert found["mean"]["scans"] == 30 and found["mean"]["next"] is not None


def test_a_daily_history_is_read_with_its_weekly_cycle() -> None:
    # Six weeks of daily scans: 500 rows on weekdays, 380 on the two weekend days.
    points = [reading(d, mean=380.0 if d % 7 in (5, 6) else 500.0) for d in range(42)]
    period, found = measure_thresholds(points, rate=0.05)
    assert period == 7
    weekend = found["mean"]
    assert weekend["value"] == 380.0 and weekend["newest"]["unusual"] is False
    assert weekend["newest"]["expected"] == 380.0
    # The next scan is a weekday again.
    assert weekend["next"]["expected"] == 500.0 and weekend["scans_needed"] == 14 + 19
    # The same weekend value on a weekday is unusual.
    points.append(reading(42, mean=380.0))
    _, found = measure_thresholds(points, rate=0.05)
    assert found["mean"]["newest"]["unusual"] is True


def test_a_missed_day_does_not_shift_the_weekly_cycle() -> None:
    """Days 0 to 40, then day 42 (a weekday, 500 rows) with day 41 missing. Read by position
    with a cycle of seven, day 42 would be compared with the weekend days and called unusual."""

    def rows(day: int) -> float:
        return 380.0 if day % 7 in (5, 6) else 500.0

    points = [reading(d, mean=rows(d)) for d in [*range(41), 42]]
    period, found = measure_thresholds(points, rate=0.05)
    assert period is None
    assert found["mean"]["value"] == 500.0 and found["mean"]["newest"]["unusual"] is False

    # Three weeks after the gap the daily series is long enough again, and only it is read
    # with the cycle: 22 scans from day 42 on.
    points += [reading(d, mean=rows(d)) for d in range(43, 64)]
    period, found = measure_thresholds(points, rate=0.05)
    assert period == 7
    assert (found["mean"]["scans"], found["mean"]["scans_needed"]) == (22, 14 + 19)
    assert found["mean"]["next"] is None  # the series after the gap is still too short


@needs_db
async def test_thresholds_through_the_api(client: AsyncClient, owner: Engine) -> None:
    cid = make_connection(owner)
    aid = make_asset(owner, cid, "orders")
    sql(
        owner,
        "INSERT INTO columns (asset_id, name, position, physical_type, logical_type, role)"
        " VALUES (:a, 'new', 0, 'INTEGER', 'integer', 'measure')",
        a=aid,
    )
    for i in range(30):
        at = T0 + timedelta(hours=31 * i)
        sid = make_scan(owner, cid, at=at)
        value = 900.0 if i == 29 else 100.0 + i % 4
        sql(
            owner,
            "INSERT INTO column_measures (id, scan_id, connection_id, asset_id, column_name, measured_at,"
            " rows, measures) VALUES (gen_random_uuid(), :s, :c, :a, 'amount', :at, 50, CAST(:m AS jsonb))",
            s=sid,
            c=cid,
            a=aid,
            at=at,
            m=f'{{"mean": {value}, "null_share": 0.0}}',
        )
    path = f"/api/assets/{aid}/measures/thresholds"
    r = await client.get(path, params={"column": "amount"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["asset_id"], body["column"], body["rate"], body["period"]) == (aid, "amount", 0.05, None)
    mean = body["measures"]["mean"]
    assert mean["value"] == 900.0 and mean["newest"]["unusual"] is True
    assert mean["newest"]["high"] < 900.0 and mean["scans"] == 30 and mean["scans_needed"] == 22
    assert body["measures"]["null_share"]["newest"]["unusual"] is False

    # A stricter rate needs more history than there is.
    strict = (await client.get(path, params={"column": "amount", "rate": 0.01})).json()
    assert strict["rate"] == 0.01 and strict["measures"]["mean"]["newest"] is None
    assert strict["measures"]["mean"]["scans_needed"] == 102

    # A column without history, an unknown one, an unknown table, and bad parameters.
    empty = await client.get(path, params={"column": "new"})
    assert empty.status_code == 200 and empty.json()["measures"] == {}
    missing = await client.get(path, params={"column": "nope"})
    assert missing.status_code == 404 and missing.json()["detail"] == "column_not_found"
    other = await client.get(f"/api/assets/{uuid.uuid4()}/measures/thresholds", params={"column": "amount"})
    assert other.status_code == 404
    assert (await client.get(path)).status_code == 422
    for rate in (0, 0.001, 0.6, "x"):
        assert (await client.get(path, params={"column": "amount", "rate": rate})).status_code == 422

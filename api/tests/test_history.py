"""Score history (spec 011): scores written with each successful scan, the store and table
history routes, and migration 0007's backfill."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from asgi_lifespan import LifespanManager
from httpx import AsyncClient
from sahifa_core.synth import write_shop
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from sahifa.db.migrate import upgrade
from sahifa.main import create_app

from .conftest import DB_URL, needs_db
from .fake_idp import FakeIdp
from .test_auth_flow import auth_settings, browser
from .test_checks import asset_id, connect, make_asset, make_connection, scan, sql

pytestmark = needs_db

T0 = datetime(2026, 9, 1, 2, 0, tzinfo=UTC)


@pytest.fixture
def owner() -> Iterator[Engine]:
    assert DB_URL
    upgrade(DB_URL)
    engine = create_engine(DB_URL, isolation_level="AUTOCOMMIT")
    yield engine
    engine.dispose()


def dims(value: float, checks: int) -> dict[str, Any]:
    return {"validity": {"value": value, "low": value - 1, "high": value, "checks": checks}}


def make_scan(owner: Engine, cid: str, *, at: datetime, status: str = "succeeded", report: Any = None) -> str:
    sid = str(uuid.uuid4())
    sql(
        owner,
        "INSERT INTO scans (id, connection_id, status, sample_rows, finished_at, report)"
        " VALUES (:id, :c, :s, 0, :at, CAST(:r AS jsonb))",
        id=sid,
        c=cid,
        s=status,
        at=at,
        r=None if report is None else json.dumps(report),
    )
    return sid


def make_score(
    owner: Engine, sid: str, cid: str, *, at: datetime, overall: float | None, aid: str | None = None
) -> None:
    sql(
        owner,
        "INSERT INTO scores"
        " (id, scan_id, connection_id, asset_id, measured_at, overall, low, high, checks, dimensions)"
        " VALUES (gen_random_uuid(), :s, :c, :a, :at, :o, :lo, :hi, 3, CAST(:d AS jsonb))",
        s=sid,
        c=cid,
        a=aid,
        at=at,
        o=overall,
        lo=None if overall is None else overall - 1,
        hi=overall,
        d=json.dumps({} if overall is None else dims(overall, 3)),
    )


async def points(client: AsyncClient, path: str, **params: Any) -> list[dict[str, Any]]:
    r = await client.get(path, params=params)
    assert r.status_code == 200, r.text
    out: list[dict[str, Any]] = r.json()["points"]
    return out


async def test_successful_scans_write_scores_and_build_the_history(
    client: AsyncClient, owner: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_shop(tmp_path / "shop", rows=300)
    cid = await connect(client, monkeypatch, tmp_path / "shop")
    reports = [await scan(client, cid) for _ in range(3)]
    ids = [r["scan_id"] for r in reports]

    # One store row and one per table, with the report's values.
    for report in reports:
        rows = sql(
            owner,
            "SELECT asset_id IS NULL, overall, low, high, checks, dimensions FROM scores WHERE scan_id = :s",
            s=report["scan_id"],
        )
        assert len(rows) == 1 + len(report["assets"])
        [store] = [r for r in rows if r[0]]
        score = report["score"]
        assert store[1:4] == (score["overall"], score["low"], score["high"])
        assert store[4] == sum(d["checks"] for d in score["dimensions"].values()) > 0
        assert store[5] == score["dimensions"]

    history = await points(client, f"/api/connections/{cid}/history")
    assert [p["scan_id"] for p in history] == ids
    assert {p["trigger"] for p in history} == {"manual"}
    assert history[-1]["overall"] == reports[-1]["score"]["overall"]
    assert [p["finished_at"] for p in history] == sorted(p["finished_at"] for p in history)
    assert [p["scan_id"] for p in await points(client, f"/api/connections/{cid}/history", limit=2)] == ids[1:]
    cut = await points(client, f"/api/connections/{cid}/history", scan_id=ids[1])
    assert [p["scan_id"] for p in cut] == ids[:2]

    aid = await asset_id(client, cid, "invoices")
    table = await points(client, f"/api/assets/{aid}/history")
    assert [p["scan_id"] for p in table] == ids
    [invoices] = [a for a in reports[0]["assets"] if a["ref"]["name"] == "invoices"]
    assert (table[0]["overall"], table[0]["low"], table[0]["high"]) == (
        invoices["score"]["overall"],
        invoices["score"]["low"],
        invoices["score"]["high"],
    )
    assert [p["scan_id"] for p in await points(client, f"/api/assets/{aid}/history", scan_id=ids[0])] == ids[
        :1
    ]


async def test_a_failed_scan_writes_no_scores(
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
    assert sql(owner, "SELECT count(*) FROM scores WHERE scan_id = :s", s=sid) == [(0,)]
    assert await points(client, f"/api/connections/{cid}/history") == []


async def test_order_gaps_and_cuts(client: AsyncClient, owner: Engine) -> None:
    cid = make_connection(owner)
    aid = make_asset(owner, cid, "orders")
    # Two scans finished at the same moment are ordered by scan id; a null score is a point.
    tied = sorted(str(uuid.uuid4()) for _ in range(2))
    scans: list[str] = []
    for i, overall in enumerate((90.0, None, 80.5)):
        sid = make_scan(owner, cid, at=T0 + timedelta(days=i))
        make_score(owner, sid, cid, at=T0 + timedelta(days=i), overall=overall)
        make_score(owner, sid, cid, at=T0 + timedelta(days=i), overall=overall, aid=aid)
        scans.append(sid)
    for sid in tied:
        sql(
            owner,
            "INSERT INTO scans (id, connection_id, status, sample_rows, finished_at)"
            " VALUES (:id, :c, 'succeeded', 0, :at)",
            id=sid,
            c=cid,
            at=T0 + timedelta(days=5),
        )
        make_score(owner, sid, cid, at=T0 + timedelta(days=5), overall=70.0)
    history = await points(client, f"/api/connections/{cid}/history")
    assert [p["scan_id"] for p in history] == [*scans, *tied]
    assert [p["overall"] for p in history] == [90.0, None, 80.5, 70.0, 70.0]
    assert history[1]["low"] is None and history[1]["dimensions"] == {}
    assert history[0]["checks"] == 3 and history[0]["dimensions"] == dims(90.0, 3)
    cut = await points(client, f"/api/connections/{cid}/history", scan_id=tied[0], limit=2)
    assert [p["scan_id"] for p in cut] == [scans[2], tied[0]]
    # The table's history is its own rows only.
    assert [p["scan_id"] for p in await points(client, f"/api/assets/{aid}/history")] == scans


async def test_history_errors(client: AsyncClient, owner: Engine) -> None:
    cid = make_connection(owner)
    other = make_connection(owner)
    aid = make_asset(owner, cid, "orders")
    mine = make_scan(owner, cid, at=T0)
    make_score(owner, mine, cid, at=T0, overall=50.0)
    theirs = make_scan(owner, other, at=T0)
    make_score(owner, theirs, other, at=T0, overall=50.0)
    failed = make_scan(owner, cid, at=T0, status="failed")

    assert (await client.get(f"/api/connections/{uuid.uuid4()}/history")).status_code == 404
    assert (await client.get(f"/api/assets/{uuid.uuid4()}/history")).status_code == 404
    for path, sid in (
        (f"/api/connections/{cid}/history", theirs),
        (f"/api/connections/{cid}/history", failed),
        (f"/api/connections/{cid}/history", str(uuid.uuid4())),
        # A store score is not this table's.
        (f"/api/assets/{aid}/history", mine),
    ):
        r = await client.get(path, params={"scan_id": sid})
        assert r.status_code == 404 and r.json()["detail"] == "scan_not_in_history", (path, r.text)
    for limit in (0, 101, "x"):
        assert (
            await client.get(f"/api/connections/{cid}/history", params={"limit": limit})
        ).status_code == 422
    assert (await client.get(f"/api/connections/{cid}/history", params={"scan_id": "x"})).status_code == 422
    assert (await client.get("/api/connections/x/history")).status_code == 422


async def test_history_needs_sign_in(owner: Engine, tmp_path: Path) -> None:
    idp = FakeIdp()
    app = create_app(auth_settings(tmp_path), oidc=idp.client())
    cid = make_connection(owner)
    aid = make_asset(owner, cid, "orders")
    async with LifespanManager(app), browser(app) as c:
        assert (await c.get(f"/api/connections/{cid}/history")).status_code == 401
        assert (await c.get(f"/api/assets/{aid}/history")).status_code == 401


def report_of(overall: float, table: float) -> dict[str, Any]:
    return {
        "score": {
            "overall": overall,
            "low": overall - 2,
            "high": overall + 1,
            "dimensions": dims(overall, 4),
        },
        "assets": [
            {
                "ref": {"namespace": "", "name": "orders", "kind": "table"},
                "score": {"overall": table, "low": None, "high": None, "dimensions": dims(table, 2)},
            },
            # No asset row: skipped by the backfill.
            {
                "ref": {"namespace": "", "name": "gone", "kind": "table"},
                "score": {"overall": 1.0, "dimensions": {}},
            },
        ],
    }


def test_migration_0007_backfills_and_round_trips(owner: Engine) -> None:
    from alembic import command

    from sahifa.db.migrate import build_config, downgrade

    assert DB_URL
    cid = make_connection(owner)
    aid = make_asset(owner, cid, "orders")
    downgrade(DB_URL, "0006")
    try:
        assert sql(owner, "SELECT to_regclass('scores')") == [(None,)]
        sid = make_scan(owner, cid, at=T0, report=report_of(77.5, 60.0))
        make_scan(owner, cid, at=T0, status="failed", report=report_of(1.0, 1.0))
    finally:
        upgrade(DB_URL)
    rows = sql(
        owner,
        "SELECT scan_id::text, asset_id::text, measured_at, overall, low, high, checks FROM scores"
        " WHERE connection_id = :c ORDER BY asset_id NULLS FIRST",
        c=cid,
    )
    assert rows == [(sid, None, T0, 77.5, 75.5, 78.5, 4), (sid, aid, T0, 60.0, None, None, 2)]
    command.check(build_config(DB_URL))

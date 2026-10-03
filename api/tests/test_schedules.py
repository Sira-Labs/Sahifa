"""Scheduled scans per connection (spec 010): next runs, validation, routes and the due job."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sahifa_core.synth import write_shop
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from sahifa import jobs, main
from sahifa.db import Database
from sahifa.db.migrate import upgrade
from sahifa.main import create_app
from sahifa.services.scans import ScanRunner
from sahifa.services.schedules import (
    ScheduleError,
    fire_times,
    next_run,
    normalize_cron,
    shortest_interval,
    upcoming,
    validate,
)
from sahifa.settings import Settings

from .conftest import CSRF, DB_URL, needs_db
from .fake_idp import FakeIdp
from .test_auth_flow import ADMIN, Env, auth_settings, browser, sign_in

ZURICH = ZoneInfo("Europe/Zurich")
NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


# --- Next runs and validation (no database) ----------------------------------------------


def test_nightly_in_zurich_across_the_end_of_summer_time() -> None:
    # Summer time ends on Sunday 25 October 2026 at 03:00 (02:00 again): 02:00 is 00:00 UTC in
    # summer time, 01:00 UTC in winter time.
    assert fire_times("0 2 * * *", ZURICH, utc(2026, 10, 23, 12, 0), 3) == [
        utc(2026, 10, 24, 0, 0),
        utc(2026, 10, 25, 0, 0),
        utc(2026, 10, 26, 1, 0),
    ]
    # The repeated hour fires once, at its first occurrence.
    assert fire_times("0 * * * *", ZURICH, utc(2026, 10, 24, 23, 30), 3) == [
        utc(2026, 10, 25, 0, 0),
        utc(2026, 10, 25, 2, 0),
        utc(2026, 10, 25, 3, 0),
    ]
    assert all(t.astimezone(ZURICH).hour == 2 for t in fire_times("0 2 * * *", ZURICH, utc(2026, 10, 20), 10))


def test_a_time_skipped_by_summer_time_fires_after_the_jump() -> None:
    # 29 March 2026: 02:00 becomes 03:00; 02:30 does not exist and runs at 03:30 summer time.
    runs = fire_times("30 2 * * *", ZURICH, utc(2026, 3, 28, 12, 0), 2)
    assert runs == [utc(2026, 3, 29, 1, 30), utc(2026, 3, 30, 0, 30)]
    assert runs[0].astimezone(ZURICH).strftime("%H:%M %Z") == "03:30 CEST"
    # Hourly keeps one-hour gaps through the jump.
    hourly = fire_times("0 * * * *", ZURICH, utc(2026, 3, 28, 23, 30), 4)
    assert [b - a for a, b in pairwise(hourly)] == [timedelta(hours=1)] * 3


def test_next_run_is_strictly_after_and_upcoming_starts_at_the_stored_run() -> None:
    assert next_run("0 2 * * *", "UTC", utc(2026, 10, 3, 2, 0)) == utc(2026, 10, 4, 2, 0)
    assert next_run("0 6 * * 1", "Europe/Zurich", NOW) == utc(2026, 10, 5, 4, 0)
    assert upcoming("0 */6 * * *", "UTC", utc(2026, 10, 3, 6, 0)) == [
        utc(2026, 10, 3, 6, 0),
        utc(2026, 10, 3, 12, 0),
        utc(2026, 10, 3, 18, 0),
    ]
    assert upcoming("0 2 * * *", "UTC", None) == []


def test_shortest_interval_and_the_minimum() -> None:
    assert shortest_interval("0 */6 * * *", ZURICH, NOW) == timedelta(hours=6)
    # Nightly runs 25 hours apart when summer time ends and 23 hours apart when it starts.
    assert shortest_interval("0 2 * * *", ZURICH, utc(2026, 10, 20)) == timedelta(hours=24)
    assert shortest_interval("0 2 * * *", ZURICH, utc(2026, 3, 20)) == timedelta(hours=23)
    assert shortest_interval("0 9,10 * * 1-5", ZURICH, NOW) == timedelta(hours=1)
    assert validate("0 * * * *", "UTC", min_interval_minutes=60, now=NOW) == "0 * * * *"
    with pytest.raises(ScheduleError) as e:
        validate("*/30 * * * *", "UTC", min_interval_minutes=60, now=NOW)
    assert e.value.body() == {
        "detail": "too_frequent",
        "field": "cron",
        "message": "This schedule runs every 30 minutes at its closest; the minimum is 60 minutes.",
        "min_interval_minutes": 60,
        "interval_minutes": 30,
    }
    with pytest.raises(ScheduleError, match="every 60 minutes"):
        validate("0 * * * *", "UTC", min_interval_minutes=61, now=NOW)


def test_cron_validation() -> None:
    assert normalize_cron("  0  2 * *   * ") == "0 2 * * *"
    assert normalize_cron("0 6 * * MON") == "0 6 * * MON"
    assert normalize_cron("0 6 1-7 MAR,APR THU") == "0 6 1-7 MAR,APR THU"
    for bad in ("* * * *", "0 2 * * * *", "@daily", "61 * * * *", "0 25 * * *", "R * * * *", "H 2 * * *", ""):
        with pytest.raises(ScheduleError) as e:
            normalize_cron(bad)
        assert (e.value.code, e.value.field) == ("invalid_cron", "cron"), bad
    with pytest.raises(ScheduleError, match="never fires"):
        validate("0 0 30 2 *", "UTC", min_interval_minutes=60, now=NOW)


def test_time_zone_validation() -> None:
    assert validate("0 2 * * *", "Europe/Zurich", min_interval_minutes=60, now=NOW) == "0 2 * * *"
    for bad in ("Mars/Olympus", "europe/zurich", "../../etc/passwd", "/etc/localtime", ""):
        with pytest.raises(ScheduleError) as e:
            validate("0 2 * * *", bad, min_interval_minutes=60, now=NOW)
        assert (e.value.code, e.value.field) == ("unknown_timezone", "timezone"), bad


# --- Routes and the due-schedule job (database) ------------------------------------------


def sql(engine: Engine, statement: str, **params: Any) -> Any:
    with engine.connect() as conn:
        result = conn.execute(text(statement), params)
        return result.all() if result.returns_rows else None


@pytest.fixture
def owner() -> Iterator[Engine]:
    """A direct connection; schedules of earlier runs are dropped so that a run of the due job
    with a clock in the future sees only this test's."""
    assert DB_URL
    upgrade(DB_URL)
    engine = create_engine(DB_URL, isolation_level="AUTOCOMMIT")
    sql(engine, "DELETE FROM scan_schedules")
    yield engine
    sql(engine, "DELETE FROM scan_schedules")
    engine.dispose()


@pytest.fixture
async def db() -> AsyncIterator[Database]:
    assert DB_URL
    database = Database(DB_URL)
    yield database
    await database.dispose()


def settings_for(data_dir: Path, **overrides: Any) -> Settings:
    assert DB_URL
    return Settings(database_url=DB_URL, data_dir=data_dir, commit="test", **overrides)


async def connect(client: AsyncClient, monkeypatch: pytest.MonkeyPatch, path: Path) -> str:
    """Register a DuckDB connection on the clean shop in `path`; returns its id."""
    write_shop(path, clean=True, rows=50)
    suffix = uuid.uuid4().hex[:10].upper()
    monkeypatch.setenv(f"SAHIFA_CONN_S{suffix}", str(path))
    r = await client.post(
        "/api/connections",
        json={"name": f"s-{suffix.lower()}", "kind": "duckdb", "secret_ref": f"SAHIFA_CONN_S{suffix}"},
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def put(client: AsyncClient, cid: str, **body: Any) -> dict[str, Any]:
    r = await client.put(f"/api/connections/{cid}/schedule", json={"cron": "0 2 * * *", **body})
    assert r.status_code == 200, r.text
    out: dict[str, Any] = r.json()
    return out


def parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


def scans_of(owner: Engine, cid: str) -> list[tuple[str, str, str]]:
    rows = sql(
        owner,
        "SELECT id::text, status, trigger FROM scans WHERE connection_id = :c ORDER BY created_at",
        c=cid,
    )
    return [tuple(r) for r in rows]


def schedule_row(owner: Engine, cid: str) -> dict[str, Any]:
    rows = sql(
        owner,
        "SELECT next_run_at, last_run_at, last_scan_id::text, last_outcome, version FROM scan_schedules"
        " WHERE connection_id = :c",
        c=cid,
    )
    assert rows, "no schedule"
    return dict(
        zip(("next_run_at", "last_run_at", "last_scan_id", "last_outcome", "version"), rows[0], strict=True)
    )


async def finished(client: AsyncClient, sid: str) -> dict[str, Any]:
    for _ in range(600):
        scan: dict[str, Any] = (await client.get(f"/api/scans/{sid}")).json()
        if scan["status"] in ("succeeded", "failed"):
            return scan
        await asyncio.sleep(0.05)
    raise AssertionError(f"scan {sid} did not finish: {scan}")


@needs_db
async def test_create_replace_delete_and_stale_version(
    client: AsyncClient, owner: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = await connect(client, monkeypatch, tmp_path / "shop")
    assert (await client.get(f"/api/connections/{cid}/schedule")).json()["detail"] == "no_schedule"

    before = datetime.now(UTC)
    created = await put(client, cid, timezone="Europe/Zurich")
    assert created["version"] == 1 and created["enabled"] and created["updated_by"] == "dev"
    assert created["cron"] == "0 2 * * *" and created["timezone"] == "Europe/Zurich"
    assert (
        created["sample_rows"] is None and created["last_run_at"] is None and created["last_outcome"] is None
    )
    runs = [parse(t) for t in created["next_runs"]]
    assert len(runs) == 3 and runs[0] == parse(created["next_run_at"]) and before < runs[0]
    assert runs == fire_times("0 2 * * *", ZURICH, before, 3)
    assert all(t.astimezone(ZURICH).strftime("%H:%M") == "02:00" for t in runs)
    assert (await client.get(f"/api/connections/{cid}/schedule")).json() == created

    listed = (await client.get("/api/connections")).json()["items"]
    summary = next(c for c in listed if c["id"] == cid)["schedule"]
    assert summary == {
        "cron": "0 2 * * *",
        "timezone": "Europe/Zurich",
        "enabled": True,
        "next_run_at": created["next_run_at"],
    }
    assert (await client.get(f"/api/connections/{cid}")).json()["schedule"] == summary

    # A second create (no version) and an old version are stale.
    r = await client.put(f"/api/connections/{cid}/schedule", json={"cron": "0 3 * * *"})
    assert r.status_code == 409 and r.json() == {
        "detail": "stale_version",
        "version": 1,
        "message": "Someone changed this schedule; reload it and try again.",
    }
    disabled = await put(client, cid, cron="0 */6 * * *", enabled=False, sample_rows=500, version=1)
    assert disabled["version"] == 2 and not disabled["enabled"] and disabled["sample_rows"] == 500
    assert disabled["next_run_at"] is None and disabled["next_runs"] == []
    r = await client.put(f"/api/connections/{cid}/schedule", json={"cron": "0 3 * * *", "version": 1})
    assert r.status_code == 409 and r.json()["version"] == 2

    enabled = await put(client, cid, cron="0 */6 * * *", enabled=True, version=2)
    assert enabled["version"] == 3 and enabled["next_run_at"] is not None and len(enabled["next_runs"]) == 3
    assert [parse(b) - parse(a) for a, b in pairwise(enabled["next_runs"])] == [timedelta(hours=6)] * 2

    assert (await client.delete(f"/api/connections/{cid}/schedule")).status_code == 204
    r = await client.get(f"/api/connections/{cid}/schedule")
    assert r.status_code == 404 and r.json()["detail"] == "no_schedule"
    assert (await client.delete(f"/api/connections/{cid}/schedule")).status_code == 404
    assert (
        next(c for c in (await client.get("/api/connections")).json()["items"] if c["id"] == cid)["schedule"]
        is None
    )
    # Gone, a version is stale; without one the schedule is created again.
    r = await client.put(f"/api/connections/{cid}/schedule", json={"cron": "0 2 * * *", "version": 3})
    assert r.status_code == 409 and r.json()["version"] is None
    assert (await put(client, cid))["version"] == 1

    unknown = uuid.uuid4()
    assert (await client.get(f"/api/connections/{unknown}/schedule")).status_code == 404
    assert (
        await client.put(f"/api/connections/{unknown}/schedule", json={"cron": "0 2 * * *"})
    ).status_code == 404
    assert (await client.delete(f"/api/connections/{unknown}/schedule")).status_code == 404

    # Deleting the connection deletes its schedule.
    sql(owner, "DELETE FROM connections WHERE id = :c", c=cid)
    assert sql(owner, "SELECT count(*) FROM scan_schedules WHERE connection_id = :c", c=cid) == [(0,)]


@needs_db
async def test_invalid_schedules_are_refused(
    client: AsyncClient, owner: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = await connect(client, monkeypatch, tmp_path / "shop")
    url = f"/api/connections/{cid}/schedule"

    async def refused(body: dict[str, Any]) -> dict[str, Any]:
        r = await client.put(url, json=body)
        assert r.status_code == 422, r.text
        out: dict[str, Any] = r.json()
        return out

    bad_cron = await refused({"cron": "0 2 * *"})
    assert (
        bad_cron["detail"] == "invalid_cron"
        and bad_cron["field"] == "cron"
        and "five fields" in bad_cron["message"]
    )
    hostile = await refused({"cron": "0 2 * * *'; DROP TABLE scans; --"})
    assert hostile["detail"] == "invalid_cron"
    zone = await refused({"cron": "0 2 * * *", "timezone": "Europe/Atlantis"})
    assert zone == {
        "detail": "unknown_timezone",
        "field": "timezone",
        "message": "Europe/Atlantis is not a known time zone; use an IANA name such as Europe/Zurich.",
    }
    frequent = await refused({"cron": "*/15 * * * *"})
    assert frequent["detail"] == "too_frequent" and frequent["min_interval_minutes"] == 60
    assert frequent["interval_minutes"] == 15
    assert (await refused({"cron": ""}))["detail"][0]["loc"] == ["body", "cron"]
    assert (await refused({"cron": "0 2 * * *", "sample_rows": -1}))["detail"][0]["loc"] == [
        "body",
        "sample_rows",
    ]
    assert sql(owner, "SELECT count(*) FROM scan_schedules WHERE connection_id = :c", c=cid) == [(0,)]

    files = write_shop(tmp_path / "upload", clean=True, rows=20)
    payload = [("files", (p.name, p.read_bytes(), "text/csv")) for p in files]
    upload = (await client.post("/api/scans/upload", files=payload, data={"sample_rows": "0"})).json()
    assert upload["trigger"] == "manual"
    r = await client.put(f"/api/connections/{upload['connection_id']}/schedule", json={"cron": "0 2 * * *"})
    assert r.status_code == 422 and r.json()["detail"] == "upload_connection" and r.json()["field"] is None
    await finished(client, upload["id"])


@needs_db
async def test_minimum_interval_follows_the_setting(
    owner: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = create_app(settings_for(tmp_path, schedule_min_interval_minutes=15))
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t", headers=CSRF) as c,
    ):
        cid = await connect(c, monkeypatch, tmp_path / "shop")
        assert (await put(c, cid, cron="*/15 * * * *", enabled=False))["version"] == 1
        r = await c.put(f"/api/connections/{cid}/schedule", json={"cron": "*/5 * * * *", "version": 1})
        assert r.status_code == 422 and r.json()["min_interval_minutes"] == 15


@needs_db
async def test_due_schedule_starts_one_scheduled_scan(
    client: AsyncClient, owner: Engine, db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = await connect(client, monkeypatch, tmp_path / "shop")
    created = await put(client, cid, sample_rows=0)
    due = parse(created["next_run_at"])
    settings = settings_for(tmp_path)
    runner = ScanRunner(db.sessions, settings)

    # Not due yet: nothing happens.
    assert (
        await jobs.run_due_schedules(db.sessions, settings, due - timedelta(seconds=1), runner=runner) == []
    )
    now = due + timedelta(minutes=1)
    runs = [
        r
        for r in await jobs.run_due_schedules(db.sessions, settings, now, runner=runner)
        if r.connection_id == uuid.UUID(cid)
    ]
    assert [r.outcome for r in runs] == ["queued"]
    [(sid, _, trigger)] = scans_of(owner, cid)
    assert trigger == "schedule" and str(runs[0].scan_id) == sid
    scan = await finished(client, sid)
    assert scan["status"] == "succeeded", scan["error"]
    assert scan["trigger"] == "schedule" and scan["sample_rows"] == 0 and scan["assets_count"]
    listed = (await client.get("/api/scans", params={"limit": 100})).json()["items"]
    assert next(s for s in listed if s["id"] == sid)["trigger"] == "schedule"
    # The scheduled scan persisted its checks like a manual one (spec 007).
    assert sql(owner, "SELECT count(*) FROM checks WHERE last_scan_id = :s", s=sid)[0][0] > 0

    row = schedule_row(owner, cid)
    assert row["last_outcome"] == "queued" and row["last_scan_id"] == sid and row["last_run_at"] == now
    assert row["next_run_at"] == due + timedelta(days=1) and row["version"] == 1
    shown = (await client.get(f"/api/connections/{cid}/schedule")).json()
    assert shown["last_scan_id"] == sid and shown["last_outcome"] == "queued" and shown["version"] == 1
    assert parse(shown["next_runs"][0]) == due + timedelta(days=1)

    # A manual scan is marked manual.
    r = await client.post("/api/scans", json={"connection_id": cid, "sample_rows": 0})
    assert r.status_code == 202 and r.json()["trigger"] == "manual"
    await finished(client, r.json()["id"])


@needs_db
async def test_a_running_scan_skips_the_run(
    client: AsyncClient, owner: Engine, db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = await connect(client, monkeypatch, tmp_path / "shop")
    due = parse((await put(client, cid))["next_run_at"])
    running = str(uuid.uuid4())
    sql(
        owner,
        "INSERT INTO scans (id, connection_id, status, sample_rows, started_at)"
        " VALUES (:s, :c, 'running', 0, now())",
        s=running,
        c=cid,
    )
    settings = settings_for(tmp_path)
    try:
        now = due + timedelta(minutes=5)
        runs = await jobs.run_due_schedules(
            db.sessions, settings, now, runner=ScanRunner(db.sessions, settings)
        )
        assert [(r.outcome, r.scan_id) for r in runs if r.connection_id == uuid.UUID(cid)] == [
            ("skipped_running", None)
        ]
        assert scans_of(owner, cid) == [(running, "running", "manual")]
        row = schedule_row(owner, cid)
        assert row["last_outcome"] == "skipped_running" and row["last_scan_id"] is None
        assert row["last_run_at"] == now and row["next_run_at"] == due + timedelta(days=1)
    finally:
        sql(owner, "UPDATE scans SET status = 'failed', error = 'test' WHERE id = :s", s=running)


@needs_db
async def test_an_outage_collapses_to_one_run(
    client: AsyncClient, owner: Engine, db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = await connect(client, monkeypatch, tmp_path / "shop")
    due = parse((await put(client, cid))["next_run_at"])
    settings = settings_for(tmp_path)
    runner = ScanRunner(db.sessions, settings)
    # The worker was down for three nights; it comes back at 09:00.
    now = due + timedelta(days=3, hours=7)
    first = await jobs.run_due_schedules(db.sessions, settings, now, runner=runner)
    again = await jobs.run_due_schedules(db.sessions, settings, now + timedelta(minutes=1), runner=runner)
    assert [r.outcome for r in first if r.connection_id == uuid.UUID(cid)] == ["queued"]
    assert [r for r in again if r.connection_id == uuid.UUID(cid)] == []
    [(sid, _, _)] = scans_of(owner, cid)
    assert schedule_row(owner, cid)["next_run_at"] == due + timedelta(days=4)
    assert (await finished(client, sid))["status"] == "succeeded"


@needs_db
async def test_a_schedule_that_no_longer_resolves_is_disabled(
    client: AsyncClient, owner: Engine, db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = await connect(client, monkeypatch, tmp_path / "bad")
    good = await connect(client, monkeypatch, tmp_path / "good")
    due = parse((await put(client, good))["next_run_at"])
    await put(client, bad)
    # A zone that a tzdata update dropped; it sorts first, ahead of the good schedule.
    sql(
        owner,
        "UPDATE scan_schedules SET timezone = 'Mars/Olympus_Mons', next_run_at = :t WHERE connection_id = :c",
        t=due - timedelta(hours=1),
        c=bad,
    )
    settings = settings_for(tmp_path)
    now = due + timedelta(minutes=5)
    runs = await jobs.run_due_schedules(db.sessions, settings, now, runner=ScanRunner(db.sessions, settings))
    outcomes = {str(r.connection_id): (r.outcome, r.next_run_at) for r in runs}
    assert outcomes[bad] == ("invalid_schedule", None)
    assert outcomes[good] == ("queued", due + timedelta(days=1))
    assert scans_of(owner, bad) == []
    [(sid, _, trigger)] = scans_of(owner, good)
    assert trigger == "schedule"
    [(enabled, next_at, outcome)] = sql(
        owner, "SELECT enabled, next_run_at, last_outcome FROM scan_schedules WHERE connection_id = :c", c=bad
    )
    assert (enabled, next_at, outcome) == (False, None, "invalid_schedule")
    assert (await client.get(f"/api/connections/{bad}/schedule")).json()["next_runs"] == []
    assert (await finished(client, sid))["status"] == "succeeded"


@needs_db
async def test_concurrent_runs_start_one_scan(
    client: AsyncClient, owner: Engine, db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = await connect(client, monkeypatch, tmp_path / "shop")
    due = parse((await put(client, cid))["next_run_at"])
    settings = settings_for(tmp_path)
    runner = ScanRunner(db.sessions, settings)
    now = due + timedelta(minutes=1)

    # A row locked by another run is passed by (SKIP LOCKED), not waited for.
    async with db.sessions() as other:
        await other.execute(
            text("SELECT id FROM scan_schedules WHERE connection_id = :c FOR UPDATE"), {"c": cid}
        )
        assert (
            await asyncio.wait_for(jobs.run_due_schedules(db.sessions, settings, now, runner=runner), 10)
            == []
        )
        await other.rollback()

    a, b = await asyncio.gather(
        jobs.run_due_schedules(db.sessions, settings, now, runner=runner),
        jobs.run_due_schedules(db.sessions, settings, now, runner=runner),
    )
    mine = [r for r in a + b if r.connection_id == uuid.UUID(cid)]
    assert [r.outcome for r in mine] == ["queued"]
    [(sid, _, _)] = scans_of(owner, cid)
    assert (await finished(client, sid))["status"] == "succeeded"


@needs_db
async def test_queue_mode_defers_the_scheduled_scan(
    client: AsyncClient, owner: Engine, db: Database, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = await connect(client, monkeypatch, tmp_path / "shop")
    due = parse((await put(client, cid))["next_run_at"])
    settings = settings_for(tmp_path, scan_execution="queue")
    sql(owner, "DELETE FROM procrastinate_jobs WHERE status = 'todo'")
    async with jobs.opened(settings, "api"):
        runs = await jobs.run_due_schedules(db.sessions, settings, due + timedelta(minutes=1))
    assert [r.outcome for r in runs if r.connection_id == uuid.UUID(cid)] == ["queued"]
    [(sid, status, trigger)] = scans_of(owner, cid)
    assert (status, trigger) == ("queued", "schedule")
    assert sql(
        owner,
        "SELECT j.queueing_lock FROM scans s JOIN procrastinate_jobs j ON j.id = s.job_id WHERE s.id = :s",
        s=sid,
    ) == [(f"scan:{sid}",)]
    await jobs.work(settings, db.sessions, queues=(jobs.SCANS,), wait=False)
    assert (await finished(client, sid))["status"] == "succeeded"

    # A failure to defer leaves the scan failed and the schedule says so.
    async def broken(_: uuid.UUID) -> int:
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(jobs, "_defer_scan", broken)
    async with jobs.opened(settings, "api"):
        runs = await jobs.run_due_schedules(db.sessions, settings, due + timedelta(days=1, minutes=1))
    [failed] = [r for r in runs if r.connection_id == uuid.UUID(cid)]
    assert failed.outcome == "failed_to_queue"
    scan = (await client.get(f"/api/scans/{failed.scan_id}")).json()
    assert scan["status"] == "failed" and scan["error"] == "could not queue the scan: queue unavailable"
    row = schedule_row(owner, cid)
    assert row["last_outcome"] == "failed_to_queue" and row["last_scan_id"] == str(failed.scan_id)


def test_the_worker_runs_due_schedules_every_minute() -> None:
    periodic = jobs.app.periodic_registry.periodic_tasks[("run_due_schedules", "")]
    assert periodic.cron == "* * * * *"
    task = jobs.app.tasks["run_due_schedules"]
    assert task.queue == jobs.MAINTENANCE and task.queueing_lock == "run_due_schedules"


@needs_db
async def test_inline_mode_runs_due_schedules_in_the_background(
    owner: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main, "SCHEDULES_EVERY_S", 0.05)
    app = create_app(settings_for(tmp_path))
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t", headers=CSRF) as c,
    ):
        cid = await connect(c, monkeypatch, tmp_path / "shop")
        await put(c, cid)
        sql(
            owner,
            "UPDATE scan_schedules SET next_run_at = now() - interval '1 minute' WHERE connection_id = :c",
            c=cid,
        )
        for _ in range(200):
            if scans_of(owner, cid):
                break
            await asyncio.sleep(0.05)
        [(sid, _, trigger)] = scans_of(owner, cid)
        assert trigger == "schedule"
        assert (await finished(c, sid))["status"] == "succeeded"
        assert schedule_row(owner, cid)["next_run_at"] > datetime.now(UTC)


@needs_db
async def test_schedules_need_sign_in_and_csrf(owner: Engine, tmp_path: Path) -> None:
    idp = FakeIdp()
    app = create_app(auth_settings(tmp_path), oidc=idp.client())
    env = Env(idp=idp, app=app, make=None, owner=owner)
    cid = str(uuid.uuid4())
    sql(owner, "INSERT INTO connections (id, name, kind) VALUES (:id, :n, 'duckdb')", id=cid, n=f"s-{cid}")
    url = f"/api/connections/{cid}/schedule"
    async with LifespanManager(app), browser(app) as c:
        assert (await c.get(url)).status_code == 401
        assert (await c.put(url, json={"cron": "0 2 * * *"})).status_code == 401
        assert (await c.delete(url)).status_code == 401
        await sign_in(env, c)
        async with browser(app, csrf=False) as bare:
            bare.cookies = c.cookies
            forged = await bare.put(url, json={"cron": "0 2 * * *"})
            assert forged.status_code == 403 and forged.json() == {"detail": "csrf"}
            assert (await bare.delete(url)).status_code == 403
        saved = await c.put(url, json={"cron": "0 2 * * *"})
        assert saved.status_code == 200, saved.text
        assert saved.json()["updated_by"] == ADMIN
        assert (await c.delete(url)).status_code == 204
    sql(owner, "DELETE FROM connections WHERE id = :c", c=cid)


@needs_db
def test_migration_0006_round_trip(owner: Engine) -> None:
    from alembic import command

    from sahifa.db.migrate import build_config, downgrade

    assert DB_URL
    downgrade(DB_URL, "0005")
    try:
        assert sql(owner, "SELECT to_regclass('scan_schedules')") == [(None,)]
        assert (
            sql(
                owner,
                "SELECT 1 FROM information_schema.columns"
                " WHERE table_name = 'scans' AND column_name = 'trigger'",
            )
            == []
        )
    finally:
        upgrade(DB_URL)
    assert sql(owner, "SELECT count(*) FROM scans WHERE trigger <> 'manual'") == [(0,)]
    command.check(build_config(DB_URL))

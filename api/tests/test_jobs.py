"""The job queue, the worker, the reaper and the upload clean-up (spec 008)."""

from __future__ import annotations

import asyncio
import importlib.metadata
import os
import re
import shutil
import subprocess
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from alembic import command
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from procrastinate.schema import SchemaManager
from sahifa_core.synth import write_shop
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from sahifa import jobs, main
from sahifa import worker as worker_main
from sahifa.db import Database
from sahifa.db.migrate import MIGRATIONS_DIR, build_config, downgrade, upgrade
from sahifa.main import create_app
from sahifa.services.scans import execute_scan
from sahifa.services.uploads import clean_uploads, delete_folder
from sahifa.settings import Settings

from .conftest import CSRF, DB_URL, needs_db

ROOT = Path(__file__).resolve().parents[2]
WAIT_LIVE = ROOT / ".github" / "scripts" / "wait-live.sh"
DAY = 24 * 3600


def queue_settings(data_dir: Path, **overrides: Any) -> Settings:
    assert DB_URL
    return Settings(
        database_url=DB_URL, data_dir=data_dir, commit="test", scan_execution="queue", **overrides
    )


def sql(engine: Engine, statement: str, **params: Any) -> Any:
    with engine.connect() as conn:
        result = conn.execute(text(statement), params)
        return result.all() if result.returns_rows else None


@pytest.fixture
def owner() -> Iterator[Engine]:
    """A direct connection for setup and for reading the tables; waiting jobs of earlier runs
    are dropped so that each test's worker sees only its own."""
    assert DB_URL
    upgrade(DB_URL)
    engine = create_engine(DB_URL, isolation_level="AUTOCOMMIT")
    sql(engine, "DELETE FROM procrastinate_jobs WHERE status = 'todo'")
    yield engine
    engine.dispose()


@pytest.fixture
async def db() -> AsyncIterator[Database]:
    assert DB_URL
    database = Database(DB_URL)
    yield database
    await database.dispose()


@pytest.fixture
async def queue_client(tmp_path: Path, owner: Engine) -> AsyncIterator[AsyncClient]:
    app = create_app(queue_settings(tmp_path))
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t", headers=CSRF) as c,
    ):
        yield c


async def upload(client: AsyncClient, files: list[Path]) -> dict[str, Any]:
    payload = [("files", (p.name, p.read_bytes(), "text/csv")) for p in files]
    r = await client.post("/api/scans/upload", files=payload, data={"sample_rows": "0"})
    assert r.status_code == 202, r.text
    out: dict[str, Any] = r.json()
    return out


async def finished(client: AsyncClient, sid: str) -> dict[str, Any]:
    for _ in range(300):
        scan: dict[str, Any] = (await client.get(f"/api/scans/{sid}")).json()
        if scan["status"] in ("succeeded", "failed"):
            return scan
        await asyncio.sleep(0.1)
    raise AssertionError(f"scan {sid} did not finish: {scan}")


def job_of(owner: Engine, sid: str) -> tuple[int, str]:
    rows = sql(
        owner,
        "SELECT j.id, j.status::text FROM scans s JOIN procrastinate_jobs j ON j.id = s.job_id"
        " WHERE s.id = :s",
        s=sid,
    )
    assert rows, f"scan {sid} has no job"
    return int(rows[0][0]), str(rows[0][1])


def outcome(report: dict[str, Any]) -> list[tuple[str, int, int]]:
    return sorted((f["check_id"], f["evaluated"], f["failed"]) for f in report["findings"])


@needs_db
async def test_queue_mode_runs_in_the_worker_like_inline(
    queue_client: AsyncClient, client: AsyncClient, db: Database, owner: Engine, tmp_path: Path
) -> None:
    files = write_shop(tmp_path / "shop", rows=1000)
    queued = await upload(queue_client, files)
    assert queued["status"] == "queued"
    job_id, status = job_of(owner, queued["id"])
    assert status == "todo"
    assert sql(owner, "SELECT queueing_lock FROM procrastinate_jobs WHERE id = :j", j=job_id) == [
        (f"scan:{queued['id']}",)
    ]

    await jobs.work(queue_settings(tmp_path), db.sessions, queues=(jobs.SCANS,), wait=False)
    done = await finished(queue_client, queued["id"])
    assert done["status"] == "succeeded", done["error"]
    assert job_of(owner, queued["id"]) == (job_id, "succeeded")

    inline = await finished(client, (await upload(client, files))["id"])
    assert inline["status"] == "succeeded", inline["error"]
    a = (await queue_client.get(f"/api/scans/{done['id']}/report")).json()
    b = (await client.get(f"/api/scans/{inline['id']}/report")).json()
    assert a["score"] == b["score"] and outcome(a) == outcome(b) and a["findings"]
    assert done["findings"] == inline["findings"]


@needs_db
async def test_job_is_idempotent(
    queue_client: AsyncClient, db: Database, owner: Engine, tmp_path: Path
) -> None:
    files = write_shop(tmp_path / "shop", clean=True, rows=50)
    sid = (await upload(queue_client, files))["id"]
    settings = queue_settings(tmp_path)
    await jobs.work(settings, db.sessions, queues=(jobs.SCANS,), wait=False)
    before = sql(owner, "SELECT status, started_at, finished_at, report FROM scans WHERE id = :s", s=sid)
    assert before[0][0] == "succeeded"
    findings = sql(owner, "SELECT count(*) FROM finding_occurrences WHERE scan_id = :s", s=sid)

    # A second job for the same scan, and a direct call, change nothing.
    second = await jobs._defer_scan(uuid.UUID(sid))
    await jobs.work(settings, db.sessions, queues=(jobs.SCANS,), wait=False)
    await execute_scan(db.sessions, settings, uuid.UUID(sid))
    assert (
        sql(owner, "SELECT status, started_at, finished_at, report FROM scans WHERE id = :s", s=sid) == before
    )
    assert sql(owner, "SELECT status::text FROM procrastinate_jobs WHERE id = :j", j=second) == [
        ("succeeded",)
    ]
    assert sql(owner, "SELECT count(*) FROM finding_occurrences WHERE scan_id = :s", s=sid) == findings


@needs_db
async def test_queueing_lock_keeps_one_waiting_job(queue_client: AsyncClient, tmp_path: Path) -> None:
    from procrastinate.exceptions import AlreadyEnqueued

    files = write_shop(tmp_path / "shop", clean=True, rows=50)
    sid = (await upload(queue_client, files))["id"]
    with pytest.raises(AlreadyEnqueued):
        await jobs._defer_scan(uuid.UUID(sid))


@needs_db
async def test_failure_to_defer_fails_the_scan(
    queue_client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def broken(_: uuid.UUID) -> int:
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(jobs, "_defer_scan", broken)
    scan = await upload(queue_client, write_shop(tmp_path / "shop", clean=True, rows=50))
    assert scan["status"] == "failed"
    assert scan["error"] == "could not queue the scan: queue unavailable"
    assert (await queue_client.get(f"/api/scans/{scan['id']}")).json()["status"] == "failed"


@needs_db
async def test_reaper_interrupts_scans_of_stalled_workers(
    queue_client: AsyncClient, db: Database, owner: Engine, tmp_path: Path
) -> None:
    files = write_shop(tmp_path / "shop", clean=True, rows=50)
    stalled, alive = (await upload(queue_client, files))["id"], (await upload(queue_client, files))["id"]
    # Two workers took the jobs; one died an hour ago, the other is alive.
    for sid, age in ((stalled, "1 hour"), (alive, "0 seconds")):
        worker = sql(
            owner,
            "INSERT INTO procrastinate_workers (last_heartbeat)"
            f" VALUES (now() - interval '{age}') RETURNING id",
        )[0][0]
        job_id, _ = job_of(owner, sid)
        sql(
            owner,
            "UPDATE procrastinate_jobs SET status = 'doing', worker_id = :w WHERE id = :j",
            w=worker,
            j=job_id,
        )
        sql(owner, "UPDATE scans SET status = 'running', started_at = now() WHERE id = :s", s=sid)
    try:
        interrupted, _ = await jobs.reap(db.sessions, queue_settings(tmp_path, reaper_stale_minutes=1))
        assert interrupted >= 1
        scan = (await queue_client.get(f"/api/scans/{stalled}")).json()
        assert scan["status"] == "failed" and scan["error"] == "interrupted: the worker stopped"
        assert job_of(owner, stalled)[1] == "failed"
        assert (await queue_client.get(f"/api/scans/{alive}")).json()["status"] == "running"
        assert job_of(owner, alive)[1] == "doing"
    finally:
        sql(owner, "UPDATE procrastinate_jobs SET status = 'failed' WHERE status = 'doing'")
        sql(
            owner,
            "UPDATE scans SET status = 'failed', error = 'test' WHERE id = :s AND status = 'running'",
            s=alive,
        )
        sql(owner, "DELETE FROM procrastinate_workers WHERE last_heartbeat > now() - interval '1 minute'")


@needs_db
async def test_reaper_requeues_a_queued_scan_without_a_job(
    queue_client: AsyncClient, db: Database, owner: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_shop(tmp_path / "shop", clean=True, rows=50)
    suffix = uuid.uuid4().hex[:10].upper()
    monkeypatch.setenv(f"SAHIFA_CONN_J{suffix}", str(tmp_path / "shop"))
    r = await queue_client.post(
        "/api/connections",
        json={"name": f"j-{suffix.lower()}", "kind": "duckdb", "secret_ref": f"SAHIFA_CONN_J{suffix}"},
    )
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    old, recent = str(uuid.uuid4()), str(uuid.uuid4())
    for sid, age in ((old, "1 hour"), (recent, "0 seconds")):
        sql(
            owner,
            "INSERT INTO scans (id, connection_id, status, sample_rows, created_at)"
            f" VALUES (:s, :c, 'queued', 0, now() - interval '{age}')",
            s=sid,
            c=cid,
        )
    try:
        _, requeued = await jobs.reap(db.sessions, queue_settings(tmp_path, reaper_stale_minutes=1))
        assert requeued >= 1
        assert job_of(owner, old)[1] == "todo"
        assert sql(owner, "SELECT job_id FROM scans WHERE id = :s", s=recent) == [(None,)]
        await jobs.work(queue_settings(tmp_path), db.sessions, queues=(jobs.SCANS,), wait=False)
        scan = (await queue_client.get(f"/api/scans/{old}")).json()
        assert scan["status"] == "succeeded", scan["error"]
    finally:
        sql(owner, "UPDATE scans SET status = 'failed', error = 'test' WHERE id = :s", s=recent)


def make_upload(owner: Engine, root: Path, status: str, age_s: float) -> Path:
    """An upload folder with a connection and one scan in `status`, finished `age_s` ago."""
    batch = uuid.uuid4().hex
    folder = root / batch
    folder.mkdir(parents=True)
    (folder / "a.csv").write_text("id\n1\n")
    cid = sql(
        owner,
        "INSERT INTO connections (id, name, kind, config) VALUES (gen_random_uuid(), :n, 'upload', '{}')"
        " RETURNING id",
        n=f"upload-{batch}",
    )[0][0]
    finished_at = None if status in ("queued", "running") else f"now() - interval '{int(age_s)} seconds'"
    sql(
        owner,
        "INSERT INTO scans (id, connection_id, status, sample_rows, created_at, finished_at)"
        f" VALUES (gen_random_uuid(), :c, :st, 0, now() - interval '{int(age_s)} seconds',"
        f" {finished_at or 'NULL'})",
        c=cid,
        st=status,
    )
    return folder


def age(path: Path, seconds: float) -> None:
    then = time.time() - seconds
    os.utime(path, (then, then), follow_symlinks=False)


@needs_db
async def test_clean_uploads(owner: Engine, db: Database, tmp_path: Path) -> None:
    settings = queue_settings(tmp_path / "data", upload_ttl_days=1)
    root = settings.uploads_dir
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("keep me")
    age(outside, 2 * DAY)

    old_done = make_upload(owner, root, "succeeded", 2 * DAY)
    (old_done / "link.csv").symlink_to(outside / "secret.txt")
    old_failed = make_upload(owner, root, "failed", 2 * DAY)
    recent_done = make_upload(owner, root, "succeeded", 3600)
    running = make_upload(owner, root, "running", 2 * DAY)
    queued = make_upload(owner, root, "queued", 2 * DAY)
    orphan_old, orphan_new = root / uuid.uuid4().hex, root / uuid.uuid4().hex
    for orphan in (orphan_old, orphan_new):
        orphan.mkdir()
        (orphan / "b.csv").write_text("x\n")
    age(orphan_old, 2 * DAY)
    link = root / uuid.uuid4().hex
    link.symlink_to(outside, target_is_directory=True)
    age(link, 2 * DAY)
    try:
        cleaned = await clean_uploads(db.sessions, settings)
        assert cleaned.folders == 3 and cleaned.bytes == 2 * len("id\n1\n") + len("x\n")
        assert not old_done.exists() and not old_failed.exists() and not orphan_old.exists()
        assert recent_done.exists() and running.exists() and queued.exists() and orphan_new.exists()
        # The symlinked folder is refused, and the link inside a deleted folder was removed as a link.
        assert link.is_symlink() and (outside / "secret.txt").read_text() == "keep me"

        # Paths outside the uploads folder are refused.
        assert delete_folder(root, root / ".." / ".." / "outside") is None
        assert delete_folder(root, Path("../../outside")) is None
        assert delete_folder(root, link) is None
        assert (outside / "secret.txt").exists()
    finally:
        sql(
            owner,
            "UPDATE scans SET status = 'failed', error = 'test' WHERE status IN ('queued', 'running')"
            " AND connection_id IN (SELECT id FROM connections WHERE name IN (:a, :b))",
            a=f"upload-{running.name}",
            b=f"upload-{queued.name}",
        )


@needs_db
async def test_inline_mode_cleans_uploads_in_the_background(
    owner: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main, "CLEAN_FIRST_S", 0)
    assert DB_URL
    orphan = tmp_path / "uploads" / uuid.uuid4().hex
    orphan.mkdir(parents=True)
    age(orphan, 8 * DAY)
    app = create_app(Settings(database_url=DB_URL, data_dir=tmp_path, commit="test"))
    async with LifespanManager(app):
        for _ in range(100):
            if not orphan.exists():
                break
            await asyncio.sleep(0.05)
    assert not orphan.exists()


def run_filter(body: str) -> str:
    """The workers that wait-live.sh's jq filter reads from a /healthz body."""
    out = subprocess.run(
        ["jq", "-r", wait_live_filter()],
        input=body,
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def wait_live_filter() -> str:
    match = re.search(r"jq -r '(\[\(\.workers.*?)' 2>", WAIT_LIVE.read_text())
    assert match, "wait-live.sh no longer has the workers filter"
    return match.group(1)


@needs_db
async def test_healthz_lists_workers_by_commit(client: AsyncClient) -> None:
    assert DB_URL
    commit = uuid.uuid4().hex
    conninfo = jobs.conninfo(DB_URL)
    with (
        psycopg.connect(conninfo, application_name=f"sahifa-worker/{commit}"),
        psycopg.connect(conninfo, application_name=f"sahifa-worker/{commit}"),
    ):
        r = await client.get("/healthz")
        body = r.json()
        assert body["status"] == "ok" and body["database"] == "ok"
        assert {"commit": commit, "connections": 2} in body["workers"]
    if shutil.which("jq") is None:
        pytest.skip("jq is not installed")
    assert commit in run_filter(r.text).split(",")


def test_wait_live_filter_reads_every_form() -> None:
    if shutil.which("jq") is None:
        pytest.skip("jq is not installed")
    body = '{"workers": [{"commit": "aaa", "connections": 3}, "sahifa-worker/bbb", "ccc"]}'
    assert run_filter(body) == "aaa,bbb,ccc"


def test_worker_refuses_inline_mode(capsys: pytest.CaptureFixture[str]) -> None:
    assert worker_main.main(Settings(scan_execution="inline", role="worker")) == 2
    assert "SAHIFA_SCAN_EXECUTION" in capsys.readouterr().err


@needs_db
def test_worker_waits_for_the_schema_then_exits(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    assert DB_URL
    upgrade(DB_URL)
    monkeypatch.setattr(worker_main, "head_revision", lambda: "9999")
    assert worker_main.main(queue_settings(tmp_path, role="worker"), schema_wait_s=0) == 3


def test_worker_refuses_unsafe_prod_settings() -> None:
    settings = Settings(env="prod", scan_execution="queue", role="worker", access_gate="basic-auth-at-proxy")
    assert worker_main.main(settings) == 1


def test_conninfo_and_application_name() -> None:
    assert jobs.conninfo("postgresql+psycopg://u:p%40x@h:5432/d?sslmode=require") == (
        "postgresql://u:p%40x@h:5432/d?sslmode=require"
    )
    assert jobs.conninfo("postgres://u:p@h/d") == "postgresql://u:p@h/d"
    assert jobs.application_name("worker", "abc") == "sahifa-worker/abc"
    assert len(jobs.application_name("worker", "x" * 100)) == 63


def test_procrastinate_schema_is_pinned() -> None:
    """Migration 0004 carries Procrastinate 3.10.0's schema. A newer Procrastinate needs a new
    migration with its migration scripts (never an edit of 0004); then update this test."""
    assert importlib.metadata.version("procrastinate") == "3.10.0"
    vendored = (MIGRATIONS_DIR / "versions" / "0004_procrastinate_3_10_0.sql").read_text(encoding="utf-8")
    assert vendored.endswith(SchemaManager.get_schema())


@needs_db
def test_migration_0004_round_trip(owner: Engine) -> None:
    assert DB_URL

    def procrastinate_objects() -> int:
        return int(
            sql(
                owner,
                "SELECT (SELECT count(*) FROM pg_class WHERE relname LIKE 'procrastinate%')"
                " + (SELECT count(*) FROM pg_proc WHERE proname LIKE 'procrastinate%')"
                " + (SELECT count(*) FROM pg_type WHERE typname LIKE 'procrastinate%')",
            )[0][0]
        )

    command.check(build_config(DB_URL))
    downgrade(DB_URL, "0003")
    try:
        assert procrastinate_objects() == 0
        assert (
            sql(
                owner,
                "SELECT 1 FROM information_schema.columns"
                " WHERE table_name = 'scans' AND column_name = 'job_id'",
            )
            == []
        )
    finally:
        upgrade(DB_URL)
    assert procrastinate_objects() > 0
    command.check(build_config(DB_URL))

"""The job queue (spec 008, ADR-0009): one Procrastinate app on the API's database.

| Task | Queue | When |
|---|---|---|
| `run_scan(scan_id)` | `scans` | deferred by the API in queue mode, and by the reaper |
| `reap()` | `maintenance` | every 5 minutes |
| `clean_uploads()` | `maintenance` | hourly |
| `run_due_schedules()` | `maintenance` | every minute (spec 010) |

The app is defined at import, so the tasks can be declared on it; `opened()` gives it a
connection pool for one process, with the connections named `sahifa-<role>/<commit>` so that
`/healthz` can list the workers. The jobs get the settings and the session factory through the
worker's context (`Runtime`).

Every scan starts through `start_scan`, in either mode: `POST /api/scans`, uploads and due
schedules. In inline mode the API runs `run_due_schedules` itself every minute (`sahifa.main`).
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfoNotFoundError

from croniter import CroniterError
from procrastinate import App, JobContext, PsycopgConnector
from procrastinate.exceptions import AlreadyEnqueued
from procrastinate.jobs import Status
from psycopg_pool import AsyncConnectionPool
from sqlalchemy import Text, cast, column, exists, or_, select, table, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .db.models import Connection, Scan, ScanSchedule
from .logging import get_logger
from .services.scans import ScanRunner, execute_scan
from .services.schedules import next_run
from .services.uploads import clean_uploads as clean_upload_folders
from .settings import Settings

log = get_logger("sahifa.jobs")

SCANS = "scans"
MAINTENANCE = "maintenance"
QUEUES = (SCANS, MAINTENANCE)
RUN_SCAN = "run_scan"
INTERRUPTED = "interrupted: the worker stopped"
RUNTIME = "sahifa"
# Due schedules handled per run of `run_due_schedules`; the rest wait for the next minute.
DUE_BATCH = 20
Role = Literal["api", "worker"]

# Procrastinate's jobs table, for the reaper's "queued without a live job" query; it is not a
# model (Procrastinate owns it), only a name for SQLAlchemy.
procrastinate_jobs = table("procrastinate_jobs", column("id"), column("status"))

# The connector is replaced by `opened()`; it is never used as is.
app = App(connector=PsycopgConnector())


@dataclass(frozen=True)
class Runtime:
    """What the jobs need from the process that runs them."""

    settings: Settings
    sessions: async_sessionmaker[AsyncSession]


def conninfo(database_url: str) -> str:
    """The SQLAlchemy URL as a libpq URL: `postgresql+psycopg://` becomes `postgresql://`."""
    return re.sub(r"^postgres(?:ql)?(?:\+\w+)?://", "postgresql://", database_url)


def application_name(role: Role, commit: str) -> str:
    """`sahifa-worker/<commit>` names the worker's connections; Postgres keeps 63 characters."""
    return f"sahifa-{role}/{commit}"[:63]


@asynccontextmanager
async def opened(settings: Settings, role: Role, *, max_size: int = 2) -> AsyncIterator[App]:
    """Open the app for this process. The pool opens in the background, so an unreachable
    database delays the first job or defer instead of failing the start."""
    pool = AsyncConnectionPool(
        conninfo(settings.database_url),
        kwargs={"application_name": application_name(role, settings.commit)},
        min_size=1,
        max_size=max(max_size, 1),
        open=False,
        check=AsyncConnectionPool.check_connection,
        name=f"sahifa-{role}",
    )
    await pool.open(wait=False)
    try:
        with app.replace_connector(PsycopgConnector()):
            async with app.open_async(pool=pool):
                yield app
    finally:
        await pool.close()


async def _defer_scan(scan_id: uuid.UUID) -> int:
    """Defer the scan's job; the queueing lock keeps one waiting job per scan."""
    return await run_scan.configure(queueing_lock=f"scan:{scan_id}").defer_async(scan_id=str(scan_id))


async def enqueue_scan(db: AsyncSession, scan: Scan) -> None:
    """Queue mode: defer the job of a committed `queued` scan and store its id. When deferring
    fails the scan is marked failed with the error; the reaper also catches scans left queued
    without a job."""
    try:
        scan.job_id = await _defer_scan(scan.id)
    except Exception as e:
        message = f"could not queue the scan: {str(e)[:900] or e.__class__.__name__}"
        log.error("scan.failed", scan_id=str(scan.id), error=message)
        scan.status, scan.error, scan.finished_at = "failed", message, datetime.now(UTC)
    await db.commit()
    await db.refresh(scan)


async def start_scan(
    db: AsyncSession, scan: Scan, settings: Settings, runner: ScanRunner | None, *, connection: str
) -> None:
    """Hand a committed `queued` scan to the inline runner or, in queue mode, defer its job
    (spec 008). Manual scans, uploads and due schedules (spec 010) all start here; a failure to
    defer leaves the scan failed with its error."""
    if settings.scan_execution == "queue":
        await enqueue_scan(db, scan)
        if scan.job_id is not None:
            log.info("scan.queued", scan_id=str(scan.id), connection=connection, job_id=scan.job_id)
        return
    if runner is None:
        raise RuntimeError("inline scan execution needs the API's scan runner")
    runner.submit(scan.id)
    log.info("scan.queued", scan_id=str(scan.id), connection=connection)


@dataclass
class ScheduleRun:
    """One due schedule handled by `run_due_schedules`."""

    connection_id: uuid.UUID
    outcome: str
    scan_id: uuid.UUID | None
    next_run_at: datetime | None


async def run_due_schedules(
    sessions: async_sessionmaker[AsyncSession],
    settings: Settings,
    now: datetime | None = None,
    *,
    runner: ScanRunner | None = None,
) -> list[ScheduleRun]:
    """Start the scans of the schedules due at `now` (spec 010).

    One transaction locks at most `DUE_BATCH` due schedules (`SKIP LOCKED`: a second worker or
    the API's loop passes them by), inserts their scans and records each run with its next time
    after `now`; once it commits, the scans start through `start_scan` like manual ones. A
    connection with a scan still queued or running is skipped, and a schedule whose next time
    cannot be computed is disabled. After an outage `next_run_at` jumps past `now`, so the
    missed slots run once."""
    now = now or datetime.now(UTC)
    runs: list[ScheduleRun] = []
    queued: list[tuple[ScheduleRun, Scan, str]] = []
    async with sessions() as db:
        due = await db.scalars(
            select(ScanSchedule)
            .where(ScanSchedule.enabled.is_(True), ScanSchedule.next_run_at <= now)
            .order_by(ScanSchedule.next_run_at)
            .limit(DUE_BATCH)
            .with_for_update(skip_locked=True)
        )
        for schedule in list(due):
            conn = await db.get(Connection, schedule.connection_id)
            if conn is None:  # deleted meanwhile; the cascade takes the schedule
                continue
            try:
                upcoming_run = next_run(schedule.cron, schedule.timezone, now)
            except (ZoneInfoNotFoundError, CroniterError, ValueError):
                # Validated on save, so only a tzdata or croniter change gets here: disable the
                # schedule rather than leave it due, blocking the batch every minute.
                log.exception("schedule.invalid", schedule_id=str(schedule.id), connection_id=str(conn.id))
                schedule.enabled = False
                schedule.next_run_at = None
                schedule.last_outcome = "invalid_schedule"
                schedule.last_run_at = now
                runs.append(ScheduleRun(conn.id, schedule.last_outcome, None, None))
                continue
            busy = await db.scalar(
                select(exists().where(Scan.connection_id == conn.id, Scan.status.in_(("queued", "running"))))
            )
            scan: Scan | None = None
            if not busy:
                sample = settings.sample_rows if schedule.sample_rows is None else schedule.sample_rows
                scan = Scan(
                    connection_id=conn.id,
                    sample_rows=sample,
                    options={"assets": None},
                    status="queued",
                    trigger="schedule",
                )
                db.add(scan)
                await db.flush()
                schedule.last_scan_id = scan.id
            schedule.last_outcome = "skipped_running" if scan is None else "queued"
            schedule.last_run_at = now
            schedule.next_run_at = upcoming_run
            run = ScheduleRun(conn.id, schedule.last_outcome, scan.id if scan else None, upcoming_run)
            runs.append(run)
            if scan is not None:
                queued.append((run, scan, conn.name))
        await db.commit()
        for run, scan, name in queued:
            await db.refresh(scan)
            await start_scan(db, scan, settings, runner, connection=name)
            if scan.status == "failed":
                run.outcome = "failed_to_queue"
                await db.execute(
                    update(ScanSchedule)
                    .where(ScanSchedule.last_scan_id == scan.id)
                    .values(last_outcome=run.outcome)
                )
                await db.commit()
    for run in runs:
        log.info(
            "schedule.ran",
            connection_id=str(run.connection_id),
            outcome=run.outcome,
            scan_id=str(run.scan_id) if run.scan_id else None,
            next_run=run.next_run_at.isoformat() if run.next_run_at else None,
        )
    return runs


async def interrupt_scans(
    sessions: async_sessionmaker[AsyncSession], scan_ids: list[uuid.UUID], message: str = INTERRUPTED
) -> int:
    """Mark the scans that are still queued or running failed with `message`."""
    if not scan_ids:
        return 0
    async with sessions() as db:
        result = await db.execute(
            update(Scan)
            .where(Scan.id.in_(scan_ids), Scan.status.in_(("queued", "running")))
            .values(status="failed", error=message, finished_at=datetime.now(UTC))
        )
        await db.commit()
    return int(getattr(result, "rowcount", 0) or 0)


def _scan_id(kwargs: Mapping[str, object]) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(kwargs.get("scan_id")))
    except ValueError:
        return None


async def reap(sessions: async_sessionmaker[AsyncSession], settings: Settings) -> tuple[int, int]:
    """(1) Running scan jobs whose worker sent no heartbeat for `reaper_stale_minutes`: the scan
    fails with "interrupted", the job is marked failed. (2) `queued` scans older than that with
    no live job are deferred again. Returns (interrupted, requeued)."""
    stale = timedelta(minutes=settings.reaper_stale_minutes)
    stalled = list(
        await app.job_manager.get_stalled_jobs(
            queue=SCANS, task_name=RUN_SCAN, seconds_since_heartbeat=stale.total_seconds()
        )
    )
    scan_ids = [sid for job in stalled if (sid := _scan_id(job.task_kwargs)) is not None]
    interrupted = await interrupt_scans(sessions, scan_ids)
    for job in stalled:
        if job.id is None:
            continue
        try:
            await app.job_manager.finish_job_by_id_async(job.id, status=Status.FAILED, delete_job=False)
        except Exception as e:  # finished meanwhile
            log.warning("reaper.job_not_finished", job_id=job.id, error=str(e)[:300])
    if stalled:
        log.warning("reaper.interrupted", count=interrupted, jobs=[job.id for job in stalled])

    live = exists().where(
        procrastinate_jobs.c.id == Scan.job_id, cast(procrastinate_jobs.c.status, Text).in_(("todo", "doing"))
    )
    async with sessions() as db:
        orphans = list(
            await db.scalars(
                select(Scan.id).where(
                    Scan.status == "queued",
                    Scan.created_at < datetime.now(UTC) - stale,
                    or_(Scan.job_id.is_(None), ~live),
                )
            )
        )
    requeued = 0
    for sid in orphans:
        try:
            job_id = await _defer_scan(sid)
        except AlreadyEnqueued:
            continue
        async with sessions() as db:
            await db.execute(update(Scan).where(Scan.id == sid).values(job_id=job_id))
            await db.commit()
        log.info("scan.queued", scan_id=str(sid), job_id=job_id)
        requeued += 1
    if orphans:
        log.info("reaper.requeued", count=requeued)
    return interrupted, requeued


def _runtime(context: JobContext) -> Runtime:
    runtime = context.additional_context.get(RUNTIME)
    if not isinstance(runtime, Runtime):
        raise RuntimeError("the job runs outside a Sahifa worker")
    return runtime


@app.task(name=RUN_SCAN, queue=SCANS, pass_context=True)
async def run_scan(context: JobContext, scan_id: str) -> None:
    """Run one scan exactly as the inline runner does (`execute_scan`)."""
    rt = _runtime(context)
    sid = uuid.UUID(scan_id)
    try:
        await execute_scan(rt.sessions, rt.settings, sid, worker=rt.settings.commit)
    except asyncio.CancelledError:
        # Aborted, or the worker stopped before the scan finished.
        await interrupt_scans(rt.sessions, [sid])
        log.warning("scan.failed", scan_id=scan_id, error=INTERRUPTED, worker=rt.settings.commit)
        raise


@app.periodic(cron="*/5 * * * *")
@app.task(name="reap", queue=MAINTENANCE, pass_context=True, queueing_lock="reap")
async def reap_task(context: JobContext, timestamp: int) -> None:
    rt = _runtime(context)
    await reap(rt.sessions, rt.settings)


@app.periodic(cron="17 * * * *")
@app.task(name="clean_uploads", queue=MAINTENANCE, pass_context=True, queueing_lock="clean_uploads")
async def clean_uploads_task(context: JobContext, timestamp: int) -> None:
    rt = _runtime(context)
    await clean_upload_folders(rt.sessions, rt.settings)


@app.periodic(cron="* * * * *")
@app.task(name="run_due_schedules", queue=MAINTENANCE, pass_context=True, queueing_lock="run_due_schedules")
async def run_due_schedules_task(context: JobContext, timestamp: int) -> None:
    rt = _runtime(context)
    await run_due_schedules(rt.sessions, rt.settings)


async def work(
    settings: Settings,
    sessions: async_sessionmaker[AsyncSession],
    *,
    queues: tuple[str, ...] = QUEUES,
    wait: bool = True,
) -> None:
    """Run the worker on `queues` until stopped (SIGTERM or SIGINT: Procrastinate stops taking
    jobs and waits for the running ones), or, with `wait=False`, until the queues are empty."""
    async with opened(settings, "worker", max_size=settings.max_concurrent_scans + 2):
        await app.run_worker_async(
            queues=list(queues),
            name="sahifa-worker",
            concurrency=settings.max_concurrent_scans,
            wait=wait,
            install_signal_handlers=wait,
            listen_notify=wait,
            additional_context={RUNTIME: Runtime(settings, sessions)},
            # A worker prunes the workers that are silent for longer at start; the reaper then
            # finds their jobs. Use the reaper's threshold for both.
            stalled_worker_timeout=settings.reaper_stale_minutes * 60,
        )

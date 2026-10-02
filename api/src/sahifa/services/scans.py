"""Running scans in a worker thread and persisting their reports (spec 004, ADR-0009).

Until the Procrastinate worker (spec 008) a scan runs in the API process: one thread per
scan, at most `max_concurrent_scans` at once. A restart leaves running scans behind; the
start-up step marks them failed.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import anyio
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..db.models import Connection, Finding, Scan
from ..logging import get_logger
from ..settings import Settings
from .checks import Saved, load_saved, persist_checks
from .connections import resolve

if TYPE_CHECKING:
    from sahifa_core.models import CheckSpec

log = get_logger("sahifa.scans")
INTERRUPTED = "interrupted by a restart"


class ScanRunner:
    """Owns the concurrency limit and the background tasks of running scans."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], settings: Settings) -> None:
        self.sessions = sessions
        self.settings = settings
        self.limit = asyncio.Semaphore(settings.max_concurrent_scans)
        self.tasks: set[asyncio.Task[None]] = set()

    def submit(self, scan_id: uuid.UUID) -> None:
        task = asyncio.create_task(self._run(scan_id))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def drain(self) -> None:
        for task in list(self.tasks):
            task.cancel()

    async def _run(self, scan_id: uuid.UUID) -> None:
        async with self.limit:
            async with self.sessions() as db:
                scan = await db.get(Scan, scan_id)
                if scan is None:
                    return
                conn = await db.get(Connection, scan.connection_id)
                if conn is None:
                    return
                source = resolve(conn)
                names = conn.config.get("names") if conn.kind == "upload" else None
                saved = await load_saved(db, conn.id)
                scan.status, scan.started_at = "running", datetime.now(UTC)
                await db.commit()
            log.info("scan.started", scan_id=str(scan_id), connection=conn.name)
            try:
                if source is None:
                    raise RuntimeError(
                        f"connection {conn.name} has no source: set {conn.secret_ref or 'its files'}"
                    )
                report = await anyio.to_thread.run_sync(
                    lambda: _execute(source, names, scan_id, scan.sample_rows, self.settings, saved.specs)
                )
                await self._succeed(scan_id, report, saved)
                log.info("scan.succeeded", scan_id=str(scan_id))
            except Exception as e:
                message = str(e)[:1000] or e.__class__.__name__
                log.error("scan.failed", scan_id=str(scan_id), error=message)
                async with self.sessions() as db:
                    await db.execute(
                        update(Scan)
                        .where(Scan.id == scan_id)
                        .values(status="failed", error=message, finished_at=datetime.now(UTC))
                    )
                    await db.commit()

    async def _succeed(self, scan_id: uuid.UUID, report: dict[str, Any], saved: Saved | None = None) -> None:
        """Store the report, its findings and (spec 007) its assets, columns and checks in one
        transaction."""
        async with self.sessions() as db:
            scan = await db.get(Scan, scan_id)
            if scan is None:
                return
            score = report.get("score") or {}
            scan.status = "succeeded"
            scan.finished_at = datetime.now(UTC)
            scan.report = report
            scan.report_version = report.get("report_version")
            scan.score = {k: score.get(k) for k in ("overall", "low", "high")}
            counts = {s: 0 for s in ("critical", "high", "medium", "low")}
            for f in report.get("findings", []):
                counts[f["severity"]] = counts.get(f["severity"], 0) + 1
                db.add(
                    Finding(
                        scan_id=scan_id,
                        check_type=f["check_type"],
                        asset=f["asset"],
                        column_name=f.get("column"),
                        dimension=f["dimension"],
                        severity=f["severity"],
                        evaluated=f["evaluated"],
                        failed=f["failed"],
                        ratio=f["ratio"],
                        low=f["low"],
                        high=f["high"],
                        summary=f["summary"],
                        next_step=f["next_step"],
                        evidence={
                            "check_id": f["check_id"],
                            "title": f.get("title"),
                            "examples": f.get("examples", []),
                            "sql": f.get("sql"),
                        },
                    )
                )
            scan.finding_counts = counts
            scan.assets_count = len(report.get("assets", []))
            persisted = await persist_checks(
                db,
                scan_id=scan_id,
                connection_id=scan.connection_id,
                report=report,
                versions=saved.versions if saved else {},
            )
            await db.commit()
        log.info(
            "scan.checks_persisted",
            scan_id=str(scan_id),
            inserted=persisted.inserted,
            regenerated=persisted.regenerated,
            skipped=persisted.skipped,
        )


def _execute(
    source: str | list[str],
    names: dict[str, str] | None,
    scan_id: uuid.UUID,
    sample_rows: int,
    settings: Settings,
    saved: dict[str, list[CheckSpec]] | None = None,
) -> dict[str, Any]:
    """Run the core engine synchronously (in a thread) and return the report as JSON."""
    from sahifa_core.scan import ScanOptions, run_scan

    options = ScanOptions(
        sample_rows=sample_rows,
        seed=uuid.UUID(str(scan_id)).int % 2_147_483_647,
        memory_limit=settings.duckdb_memory,
        statement_timeout_s=settings.statement_timeout_s,
    )
    report = run_scan(source, options, scan_id=str(scan_id), names=names, saved=saved)
    data: dict[str, Any] = report.model_dump(mode="json")
    return data


async def mark_interrupted(db: AsyncSession) -> int:
    result = await db.execute(
        update(Scan)
        .where(Scan.status.in_(("queued", "running")))
        .values(status="failed", error=INTERRUPTED, finished_at=datetime.now(UTC))
    )
    await db.commit()
    return int(getattr(result, "rowcount", 0) or 0)

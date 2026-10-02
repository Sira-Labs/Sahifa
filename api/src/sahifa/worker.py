"""`python -m sahifa.worker`: the Procrastinate worker (spec 008, ADR-0009).

The same image as the API with `SAHIFA_ROLE=worker`. It refuses to start (exit 2) unless
`SAHIFA_SCAN_EXECUTION=queue`, refuses unsafe production settings like the API (exit 1),
waits up to 5 minutes for the API to migrate the schema to this image's head (exit 3 after
that), then runs the `scans` and `maintenance` queues until SIGTERM.
"""

from __future__ import annotations

import asyncio
import sys
import time

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from . import __version__
from .db import Database
from .db.migrate import head_revision
from .jobs import QUEUES, application_name, work
from .logging import configure, get_logger
from .settings import Settings, get_settings, prod_problems

log = get_logger("sahifa.worker")
SCHEMA_WAIT_S = 300
SCHEMA_POLL_S = 5.0
EXIT_MODE = 2
EXIT_SCHEMA = 3


async def _revision(db: Database) -> str | None:
    try:
        async with db.sessions() as s:
            value = (await s.execute(text("SELECT version_num FROM alembic_version"))).scalar()
            return None if value is None else str(value)
    except (SQLAlchemyError, OSError) as e:
        log.warning("db.unavailable", error=str(e)[:300])
        return None


async def wait_for_schema(db: Database, timeout_s: float, poll_s: float = SCHEMA_POLL_S) -> str | None:
    """The schema revision once it is this image's head, or None after `timeout_s`."""
    head = head_revision()
    deadline = time.monotonic() + timeout_s
    while True:
        revision = await _revision(db)
        if revision == head:
            return revision
        if time.monotonic() >= deadline:
            log.error("db.schema_mismatch", database=revision, image=head)
            return None
        log.info("worker.waiting_for_schema", database=revision, image=head)
        await asyncio.sleep(poll_s)


async def _run(settings: Settings, schema_wait_s: float) -> int:
    db = Database(settings.database_url, application_name("worker", settings.commit))
    try:
        revision = await wait_for_schema(db, schema_wait_s)
        if revision is None:
            return EXIT_SCHEMA
        settings.uploads_dir.mkdir(parents=True, exist_ok=True)
        log.info(
            "worker.start",
            version=__version__,
            commit=settings.commit,
            schema=revision,
            queues=list(QUEUES),
            concurrency=settings.max_concurrent_scans,
        )
        await work(settings, db.sessions)
        log.info("worker.stop", commit=settings.commit)
        return 0
    finally:
        await db.dispose()


def main(settings: Settings | None = None, *, schema_wait_s: float = SCHEMA_WAIT_S) -> int:
    settings = settings or get_settings()
    configure(settings.log_level)
    if settings.scan_execution != "queue":
        message = (
            "refusing to start the worker: SAHIFA_SCAN_EXECUTION is "
            f"{settings.scan_execution}; set it to queue on the worker and the api"
        )
        log.error(message)
        print(message, file=sys.stderr)  # noqa: T201
        return EXIT_MODE
    problems = prod_problems(settings)
    if problems:
        log.error("refusing to start in prod: " + "; ".join(problems))
        print(f"refusing to start in prod: {problems}", file=sys.stderr)  # noqa: T201
        return 1
    return asyncio.run(_run(settings, schema_wait_s))


if __name__ == "__main__":
    sys.exit(main())

from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Engine, create_engine, text

from sahifa.db.migrate import upgrade
from sahifa.main import create_app
from sahifa.settings import Settings

DB_URL = os.environ.get("SAHIFA_TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DB_URL, reason="SAHIFA_TEST_DATABASE_URL not set")
# What the web app sends on every request; unsafe requests without it get 403 (spec 006).
CSRF = {"X-Sahifa-Request": "1"}
DEFAULT_WORKSPACE = "(SELECT id FROM workspaces WHERE is_default)"


def owner_engine() -> Engine:
    """The tests' own engine for direct SQL: autocommit, and every workspace visible under
    row-level security (spec 016), as for the API's jobs."""
    assert DB_URL
    return create_engine(
        DB_URL, isolation_level="AUTOCOMMIT", connect_args={"options": "-c sahifa.system=on"}
    )


def drop_workspaces(engine: Engine) -> None:
    """Delete every workspace but the default one, with its connections and their rows (which
    cascade), so tests that assume one workspace keep it."""
    with engine.connect() as conn:
        # Audit entries are append-only (spec 018); a workspace's own go with it, as a purge.
        conn.execute(text("SET sahifa.audit_purge = 'on'"))
        others = "SELECT id FROM workspaces WHERE NOT is_default"
        conn.execute(text(f"DELETE FROM connections WHERE workspace_id IN ({others})"))
        conn.execute(text("DELETE FROM workspaces WHERE NOT is_default"))


@pytest.fixture(scope="session", autouse=True)
def one_workspace_at_start() -> None:
    """Workspaces left by an interrupted run would make every create and upload name one."""
    if DB_URL:
        upgrade(DB_URL)
        engine = owner_engine()
        drop_workspaces(engine)
        engine.dispose()


# When no test has started or ended for this long, the run is taken to hang.
STALL_S = 120
_progress: dict[str, Any] = {"at": time.monotonic(), "test": "", "loop": None, "told": False}


def _say(config: pytest.Config, lines: list[str]) -> None:
    """Print past pytest's capture, which also holds the real stderr: a run that hangs never
    reaches the report where captured output would be shown."""
    capture = config.pluginmanager.getplugin("capturemanager")
    with capture.global_and_fixture_disabled():
        print("\n" + "\n".join(lines), file=sys.stderr, flush=True)


def _stacks(tasks: list[asyncio.Task[Any]]) -> list[str]:
    lines = []
    for task in tasks:
        lines.append(f"task {task!r}")
        for frame in task.get_stack():
            lines.append(f"    {frame.f_code.co_filename}:{frame.f_lineno} in {frame.f_code.co_name}")
    return lines


def _report_stall(config: pytest.Config) -> None:
    """Every 15 s: when the run has stalled, print the test it stalled in or after and the
    stack of every task of that test's event loop, once per stall. pytest's faulthandler only
    shows threads, and a hang inside the loop is one thread waiting in `select`."""
    while True:
        time.sleep(15)
        if _progress["told"] or time.monotonic() - _progress["at"] < STALL_S:
            continue
        _progress["told"] = True
        lines = [f"no progress for {STALL_S} s, during or after {_progress['test']}"]
        loop = _progress["loop"]
        if loop is None or loop.is_closed():
            lines.append("its event loop is closed")
        else:
            lines += _stacks(list(asyncio.all_tasks(loop)))
        _say(config, lines)


@pytest.fixture(scope="session", autouse=True)
def stall_reporter(request: pytest.FixtureRequest) -> None:
    threading.Thread(target=_report_stall, args=(request.config,), name="stall-reporter", daemon=True).start()


# How long a task a test left behind (a scan still running in the app's runner) may take to
# end once its test is over.
LEFTOVER_TASK_S = 30


@pytest.fixture(autouse=True)
async def no_task_outlives_its_test(request: pytest.FixtureRequest) -> AsyncIterator[None]:
    """Wait for tasks a test left behind, and say where they are when they do not end.

    The event loop of a test is closed after it, and closing cancels what still runs. A task
    that never ends then hangs the whole run without a word (CI, 14 Nov 2026). Here the task
    gets `LEFTOVER_TASK_S` to end; after that its stack is printed and the test fails."""
    _progress.update(
        at=time.monotonic(), test=request.node.nodeid, loop=asyncio.get_running_loop(), told=False
    )
    yield
    _progress.update(at=time.monotonic())
    me = asyncio.current_task()
    pending = [t for t in asyncio.all_tasks() if t is not me and not t.done()]
    if not pending:
        return
    _, stuck = await asyncio.wait(pending, timeout=LEFTOVER_TASK_S)
    if stuck:
        _say(
            request.config,
            [f"still running {LEFTOVER_TASK_S} s after {request.node.nodeid}:", *_stacks(list(stuck))],
        )
        pytest.fail(
            f"{len(stuck)} task(s) still running {LEFTOVER_TASK_S} s after the test; their stacks are above"
        )


@pytest.fixture
def drops_workspaces() -> Iterator[None]:
    """For tests that create workspaces: none of them outlives the test."""
    assert DB_URL
    upgrade(DB_URL)
    engine = owner_engine()
    drop_workspaces(engine)
    try:
        yield
    finally:
        drop_workspaces(engine)
        engine.dispose()


@pytest.fixture
async def client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    assert DB_URL
    upgrade(DB_URL)
    app = create_app(Settings(database_url=DB_URL, data_dir=tmp_path, commit="test"))
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t", headers=CSRF) as c,
    ):
        yield c

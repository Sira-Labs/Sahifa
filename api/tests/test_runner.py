"""The inline scan runner at shutdown: no scan outlives the API holding a database session.

A scan that was only cancelled, not awaited, kept its transaction open after the app had shut
down. In the tests the next step is a synchronous clean-up, which then waited for that
transaction's locks while the event loop that could end it stood still: the run hung (CI,
14 Nov 2026).
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from typing import Any

import pytest

from sahifa.services import scans
from sahifa.services.scans import ScanRunner
from sahifa.settings import Settings


def runner(tmp_path: Path) -> ScanRunner:
    return ScanRunner(None, Settings(data_dir=tmp_path))  # type: ignore[arg-type]


async def test_drain_waits_until_cancelled_scans_have_let_go(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = {"holding": 0, "released": 0}
    both_hold = asyncio.Event()

    async def scan(*_: Any, **__: Any) -> None:
        state["holding"] += 1
        if state["holding"] == 2:
            both_hold.set()
        try:
            await asyncio.sleep(3600)
        finally:
            # What closing a session does on cancel: one more trip through the loop.
            await asyncio.sleep(0.05)
            state["released"] += 1

    monkeypatch.setattr(scans, "execute_scan", scan)
    r = runner(tmp_path)
    for _ in range(2):
        r.submit(uuid.uuid4())
    await both_hold.wait()

    await r.drain()

    assert state["released"] == 2
    assert not r.tasks


async def test_drain_gives_up_on_a_scan_that_cannot_be_cancelled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started = asyncio.Event()
    finish = asyncio.Event()

    async def scan(*_: Any, **__: Any) -> None:
        started.set()
        # Like the engine thread: cancellation waits until the work is done.
        await asyncio.shield(finish.wait())

    async def run(self: ScanRunner, scan_id: uuid.UUID) -> None:
        try:
            await scan()
        except asyncio.CancelledError:
            await finish.wait()
            raise

    monkeypatch.setattr(ScanRunner, "_run", run)
    monkeypatch.setattr(scans, "DRAIN_TIMEOUT_S", 0.1)
    r = runner(tmp_path)
    r.submit(uuid.uuid4())
    await started.wait()

    await asyncio.wait_for(r.drain(), timeout=5)

    assert len(r.tasks) == 1
    finish.set()
    await asyncio.gather(*r.tasks, return_exceptions=True)


async def test_drain_without_scans_returns_at_once(tmp_path: Path) -> None:
    await runner(tmp_path).drain()

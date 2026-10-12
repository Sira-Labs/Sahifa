"""What a connection's login may do, through the API (spec 021); the review fixes carried from
spec 020."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from httpx import AsyncClient
from sahifa_core.synth import write_shop

from sahifa.services import uploads

from .conftest import needs_db
from .test_checks import connect, scan


@needs_db
async def test_the_connection_test_and_the_scan_report_the_access(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    shop = tmp_path / "shop"
    write_shop(shop, rows=300)
    cid = await connect(client, monkeypatch, shop)
    tested = (await client.post(f"/api/connections/{cid}/test")).json()
    assert tested["ok"] and tested["assets"] == 6
    access = tested["access"]
    assert access["verdict"] == "can_write" and f"{shop}/" in access["writable"]
    assert ":ro" in access["advice"]
    report = await scan(client, cid)
    assert report["source_access"]["verdict"] == "can_write"


@needs_db
async def test_uploads_carry_no_access_report(client: AsyncClient, tmp_path: Path) -> None:
    files = write_shop(tmp_path / "shop", rows=200)
    r = await client.post(
        "/api/scans/upload",
        files=[("files", (p.name, p.read_bytes(), "text/csv")) for p in files[:1]],
        data={"sample_rows": "0"},
    )
    sid = r.json()["id"]
    for _ in range(300):
        if (await client.get(f"/api/scans/{sid}")).json()["status"] in ("succeeded", "failed"):
            break
        await asyncio.sleep(0.05)
    assert (await client.get(f"/api/scans/{sid}/report")).json()["source_access"] is None


def test_a_folder_that_cannot_be_measured_is_still_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = tmp_path / "batch"
    folder.mkdir()
    (folder / "orders.csv").write_text("id\n1\n")

    def vanished(path: Path) -> int:
        raise FileNotFoundError(2, "No such file or directory", str(path / "orders.csv"))

    monkeypatch.setattr(uploads, "folder_size", vanished)
    assert uploads.delete_folder(tmp_path, folder) == 0
    assert not folder.exists()

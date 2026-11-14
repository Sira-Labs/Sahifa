"""The demo scan (spec 022): one request writes the demo shop and scans it."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from httpx import AsyncClient
from sqlalchemy import text

from sahifa.db import Database
from sahifa.services.uploads import clean_uploads
from sahifa.settings import Settings

from .conftest import DB_URL, needs_db, owner_engine


async def finished(client: AsyncClient, scan: dict[str, Any]) -> dict[str, Any]:
    for _ in range(600):
        scan = (await client.get(f"/api/scans/{scan['id']}")).json()
        if scan["status"] in ("succeeded", "failed"):
            break
        await asyncio.sleep(0.1)
    return scan


@needs_db
async def test_demo_scan_round_trip(client: AsyncClient, tmp_path: Path) -> None:
    r = await client.post("/api/scans/demo")
    assert r.status_code == 202, r.text
    scan = r.json()
    assert scan["demo"] is True and scan["connection_kind"] == "upload" and scan["sample_rows"] == 0
    assert len(scan["files"]) == 6 and all(name.endswith(".csv") for name in scan["files"])
    folder = tmp_path / "uploads" / scan["connection_name"].removeprefix("upload-")
    assert sorted(p.name for p in folder.iterdir()) == sorted(scan["files"])

    scan = await finished(client, scan)
    assert scan["status"] == "succeeded", scan["error"]
    assert scan["demo"] is True and scan["assets_count"] == 6 and scan["findings"]["critical"] > 0
    findings = (await client.get(f"/api/scans/{scan['id']}/findings")).json()["items"]
    # The shop is written at the moment of the request, so its date ahead is still ahead.
    assert "sah.future_dates" in {f["check_type"] for f in findings}
    assert (await client.get("/api/scans", params={"limit": 1})).json()["items"][0]["demo"] is True

    entries = (await client.get("/api/audit", params={"action": "scan.demo"})).json()["items"]
    entry = next(e for e in entries if e["object_id"] == scan["id"])
    assert entry["summary"] == "Started a scan of the demo data"
    assert entry["after"]["files"] == scan["files"] and entry["after"]["sample_rows"] == 0


@needs_db
async def test_demo_scan_takes_a_body_with_the_workspace(client: AsyncClient) -> None:
    unknown = await client.post(
        "/api/scans/demo", json={"workspace_id": "00000000-0000-0000-0000-000000000000"}
    )
    assert unknown.status_code == 404
    assert (await client.post("/api/scans/demo", json={})).status_code == 202


@needs_db
async def test_demo_folder_is_cleaned_up(client: AsyncClient, tmp_path: Path) -> None:
    assert DB_URL
    scan = await finished(client, (await client.post("/api/scans/demo")).json())
    assert scan["status"] == "succeeded", scan["error"]
    settings = Settings(database_url=DB_URL, data_dir=tmp_path, commit="test", upload_ttl_days=1)
    folder = settings.uploads_dir / scan["connection_name"].removeprefix("upload-")
    assert folder.is_dir()
    engine = owner_engine()
    with engine.connect() as conn:
        conn.execute(
            text("UPDATE scans SET finished_at = now() - interval '2 days' WHERE id = :id"),
            {"id": scan["id"]},
        )
    engine.dispose()
    db = Database(DB_URL)
    try:
        await clean_uploads(db.system, settings)
    finally:
        await db.dispose()
    assert not folder.exists()
    # The report outlives its files.
    assert (await client.get(f"/api/scans/{scan['id']}/report")).status_code == 200


@needs_db
async def test_other_scans_are_not_demo(client: AsyncClient) -> None:
    r = await client.post(
        "/api/scans/upload",
        files=[("files", ("a.csv", b"id\n1\n2\n", "text/csv"))],
        data={"sample_rows": "0"},
    )
    assert r.status_code == 202, r.text
    assert r.json()["demo"] is False

"""Health, version, uploads and the scan round trip (spec 004)."""

from __future__ import annotations

import asyncio
from pathlib import Path

from httpx import AsyncClient
from sahifa_core.synth import write_shop

from .conftest import needs_db


@needs_db
async def test_health_and_version(client: AsyncClient) -> None:
    h = (await client.get("/healthz")).json()
    assert h["status"] == "ok" and h["database"] == "ok" and h["workers"] == []
    v = (await client.get("/api/version")).json()
    assert v["commit"] == "test" and v["schema_revision"] == "0007"


@needs_db
async def test_upload_round_trip(client: AsyncClient, tmp_path: Path) -> None:
    files = write_shop(tmp_path / "shop", rows=1000)
    payload = [("files", (p.name, p.read_bytes(), "text/csv")) for p in files]
    r = await client.post("/api/scans/upload", files=payload, data={"sample_rows": "0"})
    assert r.status_code == 202, r.text
    scan = r.json()
    assert scan["connection_kind"] == "upload" and scan["files"] == [p.name for p in files]
    for _ in range(300):
        scan = (await client.get(f"/api/scans/{scan['id']}")).json()
        if scan["status"] in ("succeeded", "failed"):
            break
        await asyncio.sleep(0.1)
    assert scan["status"] == "succeeded", scan["error"]
    assert scan["score"]["overall"] is not None and scan["findings"]["critical"] > 0
    report = (await client.get(f"/api/scans/{scan['id']}/report")).json()
    assert {a["ref"]["name"] for a in report["assets"]} == {p.stem for p in files}
    findings = (await client.get(f"/api/scans/{scan['id']}/findings", params={"severity": "critical"})).json()
    assert findings["items"] and all(f["severity"] == "critical" for f in findings["items"])
    listed = (await client.get("/api/scans", params={"limit": 1})).json()
    assert len(listed["items"]) == 1


@needs_db
async def test_upload_rejects_bad_files(client: AsyncClient) -> None:
    assert (
        await client.post("/api/scans/upload", files=[("files", ("x.exe", b"MZ", "application/x"))])
    ).status_code == 415
    assert (await client.post("/api/scans/upload", data={"sample_rows": "0"})).status_code == 422


@needs_db
async def test_report_conflict_and_missing(client: AsyncClient) -> None:
    assert (await client.get("/api/scans/00000000-0000-0000-0000-000000000000")).status_code == 404

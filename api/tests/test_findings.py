"""Findings across scans: deduplication, occurrences, automatic resolution and status (spec 009)."""

from __future__ import annotations

import asyncio
import csv
import shutil
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from asgi_lifespan import LifespanManager
from httpx import AsyncClient
from sahifa_core.synth import write_shop
from sqlalchemy.engine import Engine

from sahifa.db import Database
from sahifa.db.migrate import upgrade
from sahifa.main import create_app
from sahifa.services.findings import TRANSITIONS, record_findings

from .conftest import CSRF, DB_URL, needs_db, owner_engine
from .fake_idp import FakeIdp
from .test_auth_flow import ADMIN, Env, auth_settings, browser, sign_in
from .test_checks import (
    act,
    asset_id,
    check_by_key,
    connect,
    make_asset,
    make_check,
    make_connection,
    scan,
    sql,
)

pytestmark = needs_db

STATUSES = ("open", "acknowledged", "resolved", "muted")
VAT = "sah.semantic_format:invoices:vat_id"
ORPHANS = "sah.foreign_key:orders:customer_id"


@pytest.fixture
def owner() -> Iterator[Engine]:
    """A direct connection for setup and for reading the tables."""
    assert DB_URL
    upgrade(DB_URL)
    engine = owner_engine()
    yield engine
    engine.dispose()


async def findings_of(client: AsyncClient, connection_id: str, **params: Any) -> list[dict[str, Any]]:
    """Every finding of the connection, following the cursor."""
    out: list[dict[str, Any]] = []
    cursor = None
    while True:
        query = {"connection_id": connection_id, "limit": 200, **params} | (
            {"cursor": cursor} if cursor else {}
        )
        r = await client.get("/api/findings", params=query)
        assert r.status_code == 200, r.text
        out += r.json()["items"]
        cursor = r.json()["next_cursor"]
        if not cursor:
            return out


def without_check(finding: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in finding.items() if k != "check"}


def by_key(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {f["check"]["key"]: f for f in items}


async def change(client: AsyncClient, finding: dict[str, Any], action: str, **body: Any) -> dict[str, Any]:
    r = await client.post(
        f"/api/findings/{finding['id']}/{action}", json={"version": finding["version"], **body}
    )
    assert r.status_code == 200, r.text
    out: dict[str, Any] = r.json()
    return out


def set_vat_ids(path: Path, old: str, new: str) -> int:
    """Replace every invoice VAT ID equal to `old`; returns how many changed."""
    with path.open(newline="", encoding="utf-8") as f:
        data = list(csv.reader(f))
    column = data[0].index("vat_id")
    changed = 0
    for row in data[1:]:
        if row[column] == old:
            row[column], changed = new, changed + 1
    with path.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(data)
    return changed


def occurrence_count(owner: Engine, finding_id: str) -> int:
    return int(
        sql(owner, "SELECT count(*) FROM finding_occurrences WHERE finding_id = :f", f=finding_id)[0][0]
    )


@needs_db
async def test_rescan_auto_resolve_and_reopen(
    client: AsyncClient, owner: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_shop(tmp_path / "shop", rows=1000)
    cid = await connect(client, monkeypatch, tmp_path / "shop")
    first = await scan(client, cid)
    keys = {f["check_id"] for f in first["findings"]}
    assert VAT in keys and len(keys) == len(first["findings"])
    opened = await findings_of(client, cid)
    assert set(by_key(opened)) == keys
    assert {(f["status"], f["occurrences"], f["version"]) for f in opened} == {("open", 1, 1)}
    vat = by_key(opened)[VAT]
    assert vat["latest"]["scan_id"] == first["scan_id"] and vat["latest"]["failed"] == 4
    assert vat["asset"]["label"] == "invoices" and vat["check"]["column"] == "vat_id"
    assert vat["check"]["title"] and vat["check"]["status"] == "active"

    # A rescan of unchanged data: the same findings, each with two occurrences.
    second = await scan(client, cid)
    assert {f["check_id"] for f in second["findings"]} == keys
    again = await findings_of(client, cid)
    assert {f["id"] for f in again} == {f["id"] for f in opened}
    assert {(f["status"], f["occurrences"], f["version"]) for f in again} == {("open", 2, 2)}
    assert all(occurrence_count(owner, f["id"]) == 2 for f in again)
    per_scan = (await client.get(f"/api/scans/{second['scan_id']}/findings")).json()["items"]
    assert {(f["check_id"], f["finding_id"], f["finding_status"]) for f in per_scan} == {
        (f["check"]["key"], f["id"], "open") for f in again
    }

    # The VAT IDs fixed: that finding resolves itself, the others recur.
    invoices = tmp_path / "shop" / "invoices.csv"
    original = tmp_path / "invoices.orig.csv"
    shutil.copy(invoices, original)
    assert set_vat_ids(invoices, "DE12345", "DE123456789") == 4
    third = await scan(client, cid)
    assert VAT not in {f["check_id"] for f in third["findings"]}
    open_now = by_key(await findings_of(client, cid))
    assert set(open_now) == keys - {VAT}
    assert {f["occurrences"] for f in open_now.values()} == {3}
    resolved = by_key(await findings_of(client, cid, status="resolved"))
    assert list(resolved) == [VAT]
    assert resolved[VAT]["id"] == vat["id"] and resolved[VAT]["occurrences"] == 2
    assert resolved[VAT]["version"] == 3
    row = sql(owner, "SELECT resolved_scan_id, resolved_at FROM findings WHERE id = :f", f=vat["id"])[0]
    assert str(row[0]) == third["scan_id"] and row[1] is not None
    detail = (await client.get(f"/api/findings/{vat['id']}")).json()
    assert [(e["action"], e["actor"], e["from_status"], e["to_status"]) for e in detail["events"]] == [
        ("auto_resolved", "scanner", "open", "resolved"),
        ("recurred", "scanner", "open", "open"),
        ("opened", "scanner", None, "open"),
    ]

    # Broken again: the same finding reopens.
    shutil.copy(original, invoices)
    fourth = await scan(client, cid)
    assert VAT in {f["check_id"] for f in fourth["findings"]}
    reopened = by_key(await findings_of(client, cid))[VAT]
    assert reopened["id"] == vat["id"]
    assert (reopened["status"], reopened["occurrences"], reopened["version"]) == ("open", 3, 4)
    assert sql(owner, "SELECT count(*) FROM findings WHERE check_id = :c", c=vat["check"]["id"])[0][0] == 1
    assert sql(owner, "SELECT resolved_at, resolved_scan_id FROM findings WHERE id = :f", f=vat["id"]) == [
        (None, None)
    ]
    detail = (await client.get(f"/api/findings/{vat['id']}")).json()
    assert detail["events"][0]["action"] == "reopened" and detail["events"][0]["from_status"] == "resolved"
    assert [o["scan_id"] for o in detail["occurrences_list"]] == [
        fourth["scan_id"],
        second["scan_id"],
        first["scan_id"],
    ]
    newest = detail["occurrences_list"][0]
    assert newest["failed"] == 4 and "sql" in newest and newest["next_step"] and newest["summary"]
    assert newest["examples"] and all(e["masked"] for e in newest["examples"])  # VAT IDs are personal
    assert all(e["value"] != "DE12345" for e in newest["examples"])


@needs_db
async def test_concurrent_scans_share_one_finding_per_check(
    client: AsyncClient, owner: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_shop(tmp_path / "shop", rows=300)
    cid = await connect(client, monkeypatch, tmp_path / "shop")
    reports = await asyncio.gather(scan(client, cid), scan(client, cid))
    keys = {f["check_id"] for f in reports[0]["findings"]}
    assert keys and keys == {f["check_id"] for f in reports[1]["findings"]}
    items = await findings_of(client, cid)
    assert set(by_key(items)) == keys and len(items) == len(keys)
    assert {f["occurrences"] for f in items} == {2}


def make_finding(owner: Engine, check_id: str, status: str, **values: Any) -> str:
    fid = str(uuid.uuid4())
    sql(
        owner,
        "INSERT INTO findings (id, check_id, status, severity, occurrences, first_seen_at, last_seen_at,"
        " muted_until, version) VALUES (:id, :c, :s, :sev, 1, :seen, :seen, :until, 1)",
        id=fid,
        c=check_id,
        s=status,
        sev=values.get("severity", "high"),
        seen=values.get("seen", datetime.now(UTC)),
        until=values.get("muted_until"),
    )
    return fid


@needs_db
async def test_every_transition(client: AsyncClient, owner: Engine) -> None:
    aid = make_asset(owner, make_connection(owner), "t")
    for action, (sources, target) in TRANSITIONS.items():
        for status in STATUSES:
            later = datetime.now(UTC) + timedelta(days=3)
            fid = make_finding(owner, make_check(owner, aid, "active"), status, muted_until=later)
            body: dict[str, Any] = {"version": 1, "note": f"{action} from {status}"}
            r = await client.post(f"/api/findings/{fid}/{action}", json=body)
            if status in sources:
                assert r.status_code == 200, (action, status, r.text)
                out = r.json()
                assert (out["status"], out["version"]) == (target, 2)
                assert out["muted_until"] is None  # mute without `until` mutes indefinitely
                events = sql(
                    owner,
                    "SELECT action, from_status, to_status, actor, user_id, note FROM finding_events"
                    " WHERE finding_id = :f",
                    f=fid,
                )
                assert events == [(action, status, target, "dev", None, f"{action} from {status}")]
                resolved_at = sql(owner, "SELECT resolved_at FROM findings WHERE id = :f", f=fid)[0][0]
                assert (resolved_at is not None) == (target == "resolved")
            else:
                assert r.status_code == 409, (action, status)
                assert r.json()["detail"] == "invalid_transition" and r.json()["status"] == status
                assert (
                    sql(owner, "SELECT count(*) FROM finding_events WHERE finding_id = :f", f=fid)[0][0] == 0
                )
                assert sql(owner, "SELECT version, status FROM findings WHERE id = :f", f=fid) == [
                    (1, status)
                ]


@needs_db
async def test_stale_version_and_bad_requests(client: AsyncClient, owner: Engine) -> None:
    aid = make_asset(owner, make_connection(owner), "t")
    fid = make_finding(owner, make_check(owner, aid, "active"), "open")
    stale = await client.post(f"/api/findings/{fid}/acknowledge", json={"version": 4})
    assert stale.status_code == 409 and stale.json()["detail"] == "stale_version"
    assert stale.json()["version"] == 1 and stale.json()["message"]
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    bad = [
        ("acknowledge", {}),
        ("acknowledge", {"version": 1, "note": "x" * 1001}),
        ("acknowledge", {"version": 1, "until": future}),
        ("mute", {"version": 1, "until": past}),
        ("mute", {"version": 1, "until": "tomorrow"}),
        ("archive", {"version": 1}),
    ]
    for action, body in bad:
        assert (await client.post(f"/api/findings/{fid}/{action}", json=body)).status_code == 422, (
            action,
            body,
        )
    assert sql(owner, "SELECT version FROM findings WHERE id = :f", f=fid) == [(1,)]
    unknown = uuid.uuid4()
    assert (await client.post(f"/api/findings/{unknown}/acknowledge", json={"version": 1})).status_code == 404
    assert (await client.get(f"/api/findings/{unknown}")).status_code == 404
    longest = await client.post(f"/api/findings/{fid}/acknowledge", json={"version": 1, "note": "é" * 1000})
    assert longest.status_code == 200 and longest.json()["version"] == 2
    muted = await client.post(
        f"/api/findings/{fid}/mute", json={"version": 2, "until": future, "note": "<b>x</b>"}
    )
    assert muted.status_code == 200
    assert datetime.fromisoformat(muted.json()["muted_until"]) == datetime.fromisoformat(future)
    events = (await client.get(f"/api/findings/{fid}")).json()["events"]
    assert [(e["action"], e["note"]) for e in events] == [("mute", "<b>x</b>"), ("acknowledge", "é" * 1000)]


@needs_db
async def test_mute_with_and_without_until(
    client: AsyncClient, owner: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_shop(tmp_path / "shop", rows=1000)
    cid = await connect(client, monkeypatch, tmp_path / "shop")
    await scan(client, cid)
    items = by_key(await findings_of(client, cid))
    forever = await change(client, items[ORPHANS], "mute", note="known, owned by the CRM team")
    assert forever["status"] == "muted" and forever["muted_until"] is None
    until = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    timed = await change(client, items[VAT], "mute", until=until)
    assert timed["muted_until"] is not None
    sql(owner, "UPDATE findings SET muted_until = now() - interval '1 hour' WHERE id = :f", f=timed["id"])

    await scan(client, cid)
    after = by_key(await findings_of(client, cid))
    assert (after[ORPHANS]["status"], after[ORPHANS]["occurrences"]) == ("muted", 2)
    assert after[ORPHANS]["version"] == forever["version"] + 1
    assert (after[VAT]["status"], after[VAT]["muted_until"], after[VAT]["occurrences"]) == ("open", None, 2)
    events = (await client.get(f"/api/findings/{timed['id']}")).json()["events"]
    assert [(e["action"], e["actor"], e["from_status"], e["to_status"]) for e in events[:2]] == [
        ("unmuted", "scanner", "muted", "open"),
        ("mute", "dev", "open", "muted"),
    ]
    events = (await client.get(f"/api/findings/{forever['id']}")).json()["events"]
    assert (events[0]["action"], events[0]["to_status"]) == ("recurred", "muted")
    assert events[1]["note"] == "known, owned by the CRM team"
    # Muting or acknowledging changes no score: they follow the checks (behaviour 6).
    muted_only = await findings_of(client, cid, status="muted")
    assert [f["check"]["key"] for f in muted_only] == [ORPHANS]


@needs_db
async def test_retired_and_unevaluated_checks_leave_their_findings_alone(
    client: AsyncClient, owner: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_shop(tmp_path / "shop", rows=1000)
    cid = await connect(client, monkeypatch, tmp_path / "shop")
    first = await scan(client, cid)
    before = by_key(await findings_of(client, cid))
    orders = await asset_id(client, cid, "orders")
    await act(client, await check_by_key(client, orders, ORPHANS), "retire")

    await scan(client, cid)
    after = by_key(await findings_of(client, cid))
    assert after[ORPHANS]["check"]["status"] == "retired"
    # Same status, occurrences, version and latest occurrence.
    assert without_check(after[ORPHANS]) == without_check(before[ORPHANS])
    assert after[VAT]["occurrences"] == 2

    # A scan in which orders failed: none of its checks were evaluated, so its findings stay.
    report = dict(first)
    report["findings"] = [f for f in first["findings"] if f["asset"] != "orders"]
    report["assets"] = [
        a | {"error": "timeout", "checks": []} if a["ref"]["name"] == "orders" else a for a in first["assets"]
    ]
    sid = str(uuid.uuid4())
    sql(
        owner,
        "INSERT INTO scans (id, connection_id, status, sample_rows) VALUES (:s, :c, 'succeeded', 0)",
        s=sid,
        c=cid,
    )
    ids = {
        name: uuid.UUID(str(i))
        for i, name in sql(owner, "SELECT id, name FROM assets WHERE connection_id = :c", c=cid)
    }
    assert DB_URL
    db = Database(DB_URL)
    try:
        async with db.system() as s:
            linked = await record_findings(
                s, scan_id=uuid.UUID(sid), seen_at=datetime.now(UTC), report=report, asset_ids=ids
            )
            await s.commit()
    finally:
        await db.dispose()
    assert (linked.recurred, linked.auto_resolved, linked.opened) == (len(report["findings"]), 0, 0)
    final = by_key(await findings_of(client, cid))
    for key, f in after.items():
        if f["asset"]["label"] == "orders":
            assert final[key] == f, key
        else:
            assert final[key]["occurrences"] == f["occurrences"] + 1, key


@needs_db
async def test_list_filters_defaults_and_cursor(
    client: AsyncClient, owner: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_shop(tmp_path / "shop", rows=1000)
    cid = await connect(client, monkeypatch, tmp_path / "shop")
    report = await scan(client, cid)
    other = make_connection(owner)
    other_finding = make_finding(owner, make_check(owner, make_asset(owner, other, "t"), "active"), "open")

    everything = await findings_of(client, cid)
    assert len(everything) == len(report["findings"])
    ranks = ["critical", "high", "medium", "low"]
    order = [(ranks.index(f["severity"]), f["last_seen_at"]) for f in everything]
    assert [r for r, _ in order] == sorted(r for r, _ in order)

    seen: list[str] = []
    cursor = None
    while True:
        params: dict[str, Any] = {"connection_id": cid, "limit": 5} | ({"cursor": cursor} if cursor else {})
        page = (await client.get("/api/findings", params=params)).json()
        assert len(page["items"]) <= 5
        seen += [f["id"] for f in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert seen == [f["id"] for f in everything]

    critical = await findings_of(client, cid, severity="critical")
    assert critical and {f["severity"] for f in critical} == {"critical"}
    some = (
        await client.get(
            "/api/findings", params=[("connection_id", cid), ("severity", "low"), ("severity", "medium")]
        )
    ).json()["items"]
    assert some and {f["severity"] for f in some} == {"low", "medium"}
    orders = await asset_id(client, cid, "orders")
    by_asset = (await client.get("/api/findings", params={"asset_id": orders})).json()["items"]
    assert by_asset and {f["asset"]["id"] for f in by_asset} == {orders}
    assert other_finding not in {f["id"] for f in everything}
    assert [f["id"] for f in await findings_of(client, other)] == [other_finding]

    # Defaults: open, acknowledged and muted; resolved only when asked for.
    a, b, c = everything[:3]
    await change(client, a, "acknowledge")
    await change(client, b, "mute")
    await change(client, c, "resolve")
    default = {f["id"]: f["status"] for f in await findings_of(client, cid)}
    assert c["id"] not in default and default[a["id"]] == "acknowledged" and default[b["id"]] == "muted"
    assert [f["id"] for f in await findings_of(client, cid, status="resolved")] == [c["id"]]
    both = (
        await client.get(
            "/api/findings", params=[("connection_id", cid), ("status", "resolved"), ("status", "muted")]
        )
    ).json()["items"]
    assert {f["id"] for f in both} == {b["id"], c["id"]}

    for params in (
        {"status": "closed"},
        {"severity": "urgent"},
        {"limit": 0},
        {"limit": 201},
        {"cursor": "x"},
    ):
        assert (await client.get("/api/findings", params=params)).status_code == 422, params


@needs_db
async def test_events_name_the_user_and_need_sign_in_and_csrf(owner: Engine, tmp_path: Path) -> None:
    idp = FakeIdp()
    app = create_app(auth_settings(tmp_path), oidc=idp.client())
    env = Env(idp=idp, app=app, make=None, owner=owner)
    fid = make_finding(
        owner, make_check(owner, make_asset(owner, make_connection(owner), "t"), "active"), "open"
    )
    async with LifespanManager(app), browser(app) as c:
        assert (await c.get("/api/findings")).status_code == 401
        assert (await c.get(f"/api/findings/{fid}")).status_code == 401
        assert (await c.post(f"/api/findings/{fid}/acknowledge", json={"version": 1})).status_code == 401
        await sign_in(env, c)
        async with browser(app, csrf=False) as bare:
            bare.cookies = c.cookies
            forged = await bare.post(f"/api/findings/{fid}/acknowledge", json={"version": 1})
            assert forged.status_code == 403 and forged.json() == {"detail": "csrf"}
        r = await c.post(f"/api/findings/{fid}/acknowledge", json={"version": 1, "note": "on it"})
        assert r.status_code == 200, r.text
        events = (await c.get(f"/api/findings/{fid}")).json()["events"]
        assert [(e["actor"], e["action"], e["note"]) for e in events] == [(ADMIN, "acknowledge", "on it")]
    user = sql(owner, "SELECT id FROM users WHERE email = :e", e=ADMIN)[0][0]
    assert sql(owner, "SELECT user_id, actor FROM finding_events WHERE finding_id = :f", f=fid) == [
        (user, ADMIN)
    ]
    sql(owner, "DELETE FROM users WHERE id = :u", u=user)
    assert sql(owner, "SELECT user_id, actor FROM finding_events WHERE finding_id = :f", f=fid) == [
        (None, ADMIN)
    ]


@needs_db
@pytest.mark.parametrize("mode", ["dev", "proxy"])
async def test_events_without_sign_in_name_the_mode(owner: Engine, tmp_path: Path, mode: str) -> None:
    app = create_app(auth_settings(tmp_path, auth_mode=mode))
    fid = make_finding(
        owner, make_check(owner, make_asset(owner, make_connection(owner), "t"), "active"), "open"
    )
    async with LifespanManager(app), browser(app) as c:
        assert (await c.post(f"/api/findings/{fid}/resolve", json={"version": 1})).status_code == 200
    assert sql(owner, "SELECT user_id, actor FROM finding_events WHERE finding_id = :f", f=fid) == [
        (None, mode)
    ]


@needs_db
async def test_csrf_header_is_required_in_dev_mode(client: AsyncClient, owner: Engine) -> None:
    fid = make_finding(
        owner, make_check(owner, make_asset(owner, make_connection(owner), "t"), "active"), "open"
    )
    r = await client.post(
        f"/api/findings/{fid}/acknowledge", json={"version": 1}, headers={k: "" for k in CSRF}
    )
    assert r.status_code == 403 and r.json() == {"detail": "csrf"}


@needs_db
def test_migration_0005_keeps_occurrences(owner: Engine) -> None:
    from alembic import command

    from sahifa.db.migrate import build_config, downgrade

    assert DB_URL
    sid, cid = str(uuid.uuid4()), make_connection(owner)
    sql(
        owner,
        "INSERT INTO scans (id, connection_id, status, sample_rows) VALUES (:s, :c, 'succeeded', 0)",
        s=sid,
        c=cid,
    )
    sql(
        owner,
        "INSERT INTO finding_occurrences (id, scan_id, check_type, asset, dimension, severity, evaluated,"
        " failed, ratio, low, high, summary, next_step) VALUES (gen_random_uuid(), :s, 'sah.not_null', 't',"
        " 'completeness', 'high', 10, 1, 0.9, 0.6, 0.98, 's', 'n')",
        s=sid,
    )
    count = int(sql(owner, "SELECT count(*) FROM finding_occurrences")[0][0])
    downgrade(DB_URL, "0004")
    try:
        assert int(sql(owner, "SELECT count(*) FROM findings")[0][0]) == count
        assert sql(owner, "SELECT count(*) FROM findings WHERE scan_id = :s", s=sid) == [(1,)]
        assert sql(owner, "SELECT to_regclass('finding_events'), to_regclass('finding_occurrences')") == [
            (None, None)
        ]
    finally:
        upgrade(DB_URL)
    assert int(sql(owner, "SELECT count(*) FROM finding_occurrences")[0][0]) == count
    assert sql(owner, "SELECT finding_id FROM finding_occurrences WHERE scan_id = :s", s=sid) == [(None,)]
    command.check(build_config(DB_URL))

"""Assets, columns and checks persisted by scans; lifecycle actions and their events (spec 007)."""

from __future__ import annotations

import asyncio
import csv
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
from asgi_lifespan import LifespanManager
from httpx import AsyncClient
from sahifa_core.models import label_of
from sahifa_core.synth import write_shop
from sqlalchemy import text
from sqlalchemy.engine import Engine

from sahifa.db import Database
from sahifa.db.migrate import upgrade
from sahifa.main import create_app
from sahifa.services.checks import TRANSITIONS, load_saved, persist_checks

from .conftest import CSRF, DB_URL, DEFAULT_WORKSPACE, needs_db, owner_engine
from .fake_idp import FakeIdp
from .test_auth_flow import ADMIN, Env, auth_settings, browser, sign_in

pytestmark = needs_db

STATUSES = ("proposed", "active", "locked", "retired")
HOSTILE = "x'); DROP TABLE t; --"
UNICODE = "Ünïcödé 名前 ج"


@pytest.fixture
def owner() -> Iterator[Engine]:
    """A direct connection for setup and for reading the tables."""
    assert DB_URL
    upgrade(DB_URL)
    engine = owner_engine()
    yield engine
    engine.dispose()


def sql(engine: Engine, statement: str, **params: Any) -> Any:
    with engine.connect() as conn:
        result = conn.execute(text(statement), params)
        return result.all() if result.returns_rows else None


async def connect(client: AsyncClient, monkeypatch: pytest.MonkeyPatch, path: Path) -> str:
    """Register a DuckDB connection on the files in `path`; returns its id."""
    suffix = uuid.uuid4().hex[:10].upper()
    monkeypatch.setenv(f"SAHIFA_CONN_T{suffix}", str(path))
    r = await client.post(
        "/api/connections",
        json={"name": f"t-{suffix.lower()}", "kind": "duckdb", "secret_ref": f"SAHIFA_CONN_T{suffix}"},
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def scan(client: AsyncClient, connection_id: str) -> dict[str, Any]:
    """Run a full-read scan of the connection and return its report."""
    r = await client.post("/api/scans", json={"connection_id": connection_id, "sample_rows": 0})
    assert r.status_code == 202, r.text
    sid = r.json()["id"]
    for _ in range(600):
        s = (await client.get(f"/api/scans/{sid}")).json()
        if s["status"] in ("succeeded", "failed"):
            break
        await asyncio.sleep(0.05)
    assert s["status"] == "succeeded", s["error"]
    report: dict[str, Any] = (await client.get(f"/api/scans/{sid}/report")).json()
    return report


async def asset_id(client: AsyncClient, connection_id: str, label: str) -> str:
    items = (await client.get("/api/assets", params={"connection_id": connection_id, "limit": 200})).json()[
        "items"
    ]
    return str(next(a["id"] for a in items if a["label"] == label))


async def check_by_key(client: AsyncClient, aid: str, key: str) -> dict[str, Any]:
    checks = (await client.get("/api/checks", params={"asset_id": aid})).json()
    found: dict[str, Any] = next(c for c in checks if c["key"] == key)
    return found


async def act(client: AsyncClient, check: dict[str, Any], action: str) -> dict[str, Any]:
    r = await client.post(f"/api/checks/{check['id']}/{action}", json={"version": check["version"]})
    assert r.status_code == 200, r.text
    out: dict[str, Any] = r.json()
    return out


def generated(spec: dict[str, Any]) -> tuple[Any, ...]:
    return (spec["params"], spec["columns"], spec["severity"], spec["max_fail_ratio"])


@needs_db
async def test_scans_persist_once_and_regenerate_only_changes(
    client: AsyncClient, owner: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_shop(tmp_path / "shop", rows=1000)
    cid = await connect(client, monkeypatch, tmp_path / "shop")
    first = await scan(client, cid)

    assets = (await client.get("/api/assets", params={"connection_id": cid})).json()["items"]
    assert [a["label"] for a in assets] == sorted(a["ref"]["name"] for a in first["assets"])
    orders = next(a for a in assets if a["label"] == "orders")
    detail = (await client.get(f"/api/assets/{orders['id']}")).json()
    assert [c["name"] for c in detail["columns"]][:2] == ["id", "customer_id"]
    assert detail["row_count"] == next(
        a["population"] for a in first["assets"] if a["ref"]["name"] == "orders"
    )
    assert sum(sum(a["checks"].values()) for a in assets) == len(first["checks"])
    assert orders["checks"]["proposed"] > 0 and orders["checks"]["active"] > 0

    def counts() -> tuple[int, int, int, int]:
        row = sql(
            owner,
            "SELECT (SELECT count(*) FROM assets a WHERE a.connection_id = :c),"
            " (SELECT count(*) FROM columns k JOIN assets a ON a.id = k.asset_id WHERE a.connection_id = :c),"
            " (SELECT count(*) FROM checks k JOIN assets a ON a.id = k.asset_id WHERE a.connection_id = :c),"
            " (SELECT count(*) FROM check_events e JOIN checks k ON k.id = e.check_id"
            "  JOIN assets a ON a.id = k.asset_id WHERE a.connection_id = :c AND e.action = 'created')",
            c=cid,
        )[0]
        return tuple(int(v) for v in row)  # type: ignore[return-value]

    stored = counts()
    assert stored == (
        len(first["assets"]),
        sum(len(a["columns"]) for a in first["assets"]),
        len(first["checks"]),
        len(first["checks"]),
    )
    events = sql(
        owner,
        "SELECT DISTINCT e.actor, e.user_id FROM check_events e JOIN checks k ON k.id = e.check_id"
        " JOIN assets a ON a.id = k.asset_id WHERE a.connection_id = :c",
        c=cid,
    )
    assert events == [("scanner", None)]

    second = await scan(client, cid)
    assert counts() == stored
    before = {s["id"]: generated(s) for s in first["checks"]}
    changed = sum(1 for s in second["checks"] if s["id"] in before and before[s["id"]] != generated(s))
    regenerated = sql(
        owner,
        "SELECT count(*) FROM check_events e JOIN checks k ON k.id = e.check_id JOIN assets a"
        " ON a.id = k.asset_id WHERE a.connection_id = :c AND e.action = 'regenerated'",
        c=cid,
    )[0][0]
    assert regenerated == changed
    last = sql(owner, "SELECT DISTINCT last_scan_id FROM assets WHERE connection_id = :c", c=cid)
    assert [str(r[0]) for r in last] == [second["scan_id"]]


def add_status_and_quantity(path: Path, rows: int) -> None:
    """Give the first `rows` orders a new status and a larger quantity."""
    with path.open(newline="", encoding="utf-8") as f:
        data = list(csv.reader(f))
    header = data[0]
    status, quantity = header.index("status"), header.index("quantity")
    for row in data[1 : rows + 1]:
        row[status], row[quantity] = "returned", "9"
    with path.open("w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(data)


@needs_db
async def test_locked_check_keeps_its_parameters(
    client: AsyncClient, owner: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_shop(tmp_path / "shop", rows=1000)
    cid = await connect(client, monkeypatch, tmp_path / "shop")
    await scan(client, cid)
    orders = await asset_id(client, cid, "orders")

    values = await check_by_key(client, orders, "sah.accepted_values:orders:status")
    assert values["status"] == "proposed" and values["kind"] == "baseline"
    assert values["title"] == "Unexpected category"
    old_values = values["params"]["values"]
    locked = await act(client, await act(client, values, "approve"), "lock")
    assert locked["status"] == "locked" and locked["version"] == 3
    quantity = await act(client, await check_by_key(client, orders, "sah.range:orders:quantity"), "approve")
    assert quantity["status"] == "active" and quantity["params"]["max"] == 4

    add_status_and_quantity(tmp_path / "shop" / "orders.csv", 60)
    report = await scan(client, cid)

    after = await check_by_key(client, orders, "sah.accepted_values:orders:status")
    assert after["status"] == "locked" and after["params"]["values"] == old_values and after["version"] == 3
    result = next(
        r
        for a in report["assets"]
        for r in a["checks"]
        if r["spec"]["id"] == "sah.accepted_values:orders:status"
    )
    assert result["spec"]["status"] == "locked" and result["failed"] == 60 and not result["passed"]
    assert any(f["check_id"] == "sah.accepted_values:orders:status" for f in report["findings"])

    regenerated = await check_by_key(client, orders, "sah.range:orders:quantity")
    assert regenerated["status"] == "active" and regenerated["params"]["max"] == 9
    assert regenerated["version"] == quantity["version"] + 1
    events = (await client.get(f"/api/checks/{regenerated['id']}/events")).json()
    assert [e["action"] for e in events] == ["regenerated", "approve", "created"]
    assert events[0]["actor"] == "scanner" and events[0]["params_before"]["max"] == 4
    assert events[0]["params_after"]["max"] == 9 and events[1]["actor"] == "dev"


@needs_db
async def test_retired_check_is_not_evaluated_or_recreated(
    client: AsyncClient, owner: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_shop(tmp_path / "shop", rows=1000)
    cid = await connect(client, monkeypatch, tmp_path / "shop")
    key = "sah.foreign_key:orders:customer_id"
    first = await scan(client, cid)
    assert any(f["check_id"] == key for f in first["findings"])
    orders = await asset_id(client, cid, "orders")
    retired = await act(client, await check_by_key(client, orders, key), "retire")

    report = await scan(client, cid)
    assert key not in {r["spec"]["id"] for a in report["assets"] for r in a["checks"]}
    assert key not in {f["check_id"] for f in report["findings"]}
    assert key not in {s["id"] for s in report["checks"]}
    listed = (await client.get("/api/checks", params={"asset_id": orders, "status": "retired"})).json()
    assert [(c["key"], c["version"]) for c in listed] == [(key, retired["version"])]
    rows = sql(owner, "SELECT count(*) FROM checks WHERE asset_id = :a AND key = :k", a=orders, k=key)
    assert rows[0][0] == 1


def make_connection(owner: Engine) -> str:
    cid = str(uuid.uuid4())
    sql(
        owner,
        "INSERT INTO connections (id, name, kind, workspace_id)"
        f" VALUES (:id, :n, 'duckdb', {DEFAULT_WORKSPACE})",
        id=cid,
        n=f"t-{cid}",
    )
    return cid


def make_asset(owner: Engine, cid: str, name: str, namespace: str = "") -> str:
    aid = str(uuid.uuid4())
    sql(
        owner,
        "INSERT INTO assets (id, connection_id, namespace, name, kind) VALUES (:id, :c, :ns, :n, 'table')",
        id=aid,
        c=cid,
        ns=namespace,
        n=name,
    )
    return aid


def make_check(owner: Engine, aid: str, status: str, column: str = "c", type_: str = "sah.range") -> str:
    kid = str(uuid.uuid4())
    sql(
        owner,
        "INSERT INTO checks (id, asset_id, key, type, column_name, dimension, severity, kind, origin, status,"
        " params) VALUES (:id, :a, :k, :t, :col, 'accuracy', 'high', 'baseline', 'generated', :s,"
        ' \'{"min": 1, "max": 5}\'::jsonb)',
        id=kid,
        a=aid,
        k=f"{type_}:t:{column}:{kid}",
        t=type_,
        col=column,
        s=status,
    )
    return kid


@needs_db
async def test_every_transition(client: AsyncClient, owner: Engine) -> None:
    aid = make_asset(owner, make_connection(owner), "t")
    for action, (source, target) in TRANSITIONS.items():
        for status in STATUSES:
            kid = make_check(owner, aid, status)
            r = await client.post(f"/api/checks/{kid}/{action}", json={"version": 1})
            if status == source:
                assert r.status_code == 200, (action, status, r.text)
                assert r.json()["status"] == target and r.json()["version"] == 2
                event = sql(
                    owner,
                    "SELECT action, from_status, to_status FROM check_events WHERE check_id = :k",
                    k=kid,
                )
                assert event == [(action, source, target)]
            else:
                assert r.status_code == 409, (action, status)
                assert r.json()["detail"] == "invalid_transition" and r.json()["status"] == status
                assert sql(owner, "SELECT count(*) FROM check_events WHERE check_id = :k", k=kid)[0][0] == 0
                assert sql(owner, "SELECT version FROM checks WHERE id = :k", k=kid)[0][0] == 1


@needs_db
async def test_stale_version_and_bad_requests(client: AsyncClient, owner: Engine) -> None:
    aid = make_asset(owner, make_connection(owner), "t")
    kid = make_check(owner, aid, "proposed")
    stale = await client.post(f"/api/checks/{kid}/approve", json={"version": 7})
    assert (
        stale.status_code == 409
        and stale.json()["detail"] == "stale_version"
        and stale.json()["version"] == 1
    )
    assert (await client.post(f"/api/checks/{kid}/approve", json={})).status_code == 422
    assert (await client.post(f"/api/checks/{kid}/promote", json={"version": 1})).status_code == 422
    assert (await client.post(f"/api/checks/{uuid.uuid4()}/approve", json={"version": 1})).status_code == 404
    assert (await client.get(f"/api/checks/{uuid.uuid4()}/events")).status_code == 404
    assert (await client.get("/api/checks", params={"asset_id": str(uuid.uuid4())})).status_code == 404
    assert (await client.get("/api/checks", params={"asset_id": aid, "status": "open"})).status_code == 422
    assert (await client.get(f"/api/assets/{uuid.uuid4()}")).status_code == 404
    ok = await client.post(f"/api/checks/{kid}/approve", json={"version": 1})
    assert ok.status_code == 200
    again = await client.post(f"/api/checks/{kid}/approve", json={"version": 1})
    assert again.status_code == 409 and again.json() == {
        "detail": "stale_version",
        "version": 2,
        "message": again.json()["message"],
    }


@needs_db
async def test_check_list_filters_and_order(client: AsyncClient, owner: Engine) -> None:
    aid = make_asset(owner, make_connection(owner), "t")
    make_check(owner, aid, "active", column="b")
    make_check(owner, aid, "locked", column="a", type_="sah.not_null")
    make_check(owner, aid, "retired", column="a", type_="sah.length")
    everything = (await client.get("/api/checks", params={"asset_id": aid})).json()
    assert [(c["column"], c["type"]) for c in everything] == [
        ("a", "sah.length"),
        ("a", "sah.not_null"),
        ("b", "sah.range"),
    ]
    assert [c["title"] for c in everything] == [
        "Text too short or too long",
        "Missing values",
        "Outside the observed range",
    ]
    some = (await client.get(f"/api/checks?asset_id={aid}&status=locked&status=retired")).json()
    assert sorted(c["status"] for c in some) == ["locked", "retired"]
    asset = (await client.get(f"/api/assets/{aid}")).json()
    assert asset["checks"] == {"proposed": 0, "active": 1, "locked": 1, "retired": 1}


@needs_db
async def test_asset_list_pagination(client: AsyncClient, owner: Engine) -> None:
    cid = make_connection(owner)
    # The last two would both read `a.b.c` if parts were joined plainly; labels stay distinct.
    names = [("", "b"), ("", "a"), ("s", "a"), ("", HOSTILE), ("", UNICODE), ("a.b", "c"), ("a", "b.c")]
    for ns, name in names:
        make_asset(owner, cid, name, ns)
    labels: list[str] = []
    cursor = None
    while True:
        params: dict[str, Any] = {"connection_id": cid, "limit": 2} | ({"cursor": cursor} if cursor else {})
        page = (await client.get("/api/assets", params=params)).json()
        assert len(page["items"]) <= 2
        labels += [a["label"] for a in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    expected = sorted(label_of(ns, n) for ns, n in names)
    assert sorted(labels) == expected and len(labels) == len(set(labels)) == 7
    assert (await client.get("/api/assets", params={"limit": 0})).status_code == 422
    assert (await client.get("/api/assets", params={"limit": 201})).status_code == 422
    assert (await client.get("/api/assets", params={"cursor": "not-a-cursor"})).status_code == 422


@needs_db
async def test_lock_during_a_scan_survives_persistence(
    client: AsyncClient, owner: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_shop(tmp_path / "shop", rows=1000)
    cid = await connect(client, monkeypatch, tmp_path / "shop")
    report = await scan(client, cid)
    orders = await asset_id(client, cid, "orders")
    assert DB_URL
    db = Database(DB_URL)
    try:
        async with db.system() as s:
            saved = await load_saved(s, uuid.UUID(cid))  # the scan's step 1
        # While the scan runs, a person locks one check and approves another.
        locked = await act(
            client, await check_by_key(client, orders, "sah.not_null:orders:product_id"), "lock"
        )
        approved = await act(client, await check_by_key(client, orders, "sah.range:orders:amount"), "approve")
        # The scan computed new parameters for both.
        for spec in report["checks"]:
            if spec["id"] in (locked["key"], approved["key"]):
                spec["params"] = {"min": -1, "max": 1}
        async with db.system() as s:
            out = await persist_checks(
                s,
                scan_id=uuid.UUID(report["scan_id"]),
                connection_id=uuid.UUID(cid),
                report=report,
                versions=saved.versions,
            )
            await s.commit()
    finally:
        await db.dispose()
    assert out.skipped == 2 and out.inserted == 0 and out.regenerated == 0
    for before in (locked, approved):
        after = await check_by_key(client, orders, before["key"])
        assert (after["status"], after["version"], after["params"]) == (
            before["status"],
            before["version"],
            before["params"],
        )


@needs_db
async def test_events_name_the_user_and_survive_their_deletion(owner: Engine, tmp_path: Path) -> None:
    idp = FakeIdp()
    app = create_app(auth_settings(tmp_path), oidc=idp.client())
    env = Env(idp=idp, app=app, make=None, owner=owner)
    aid = make_asset(owner, make_connection(owner), "t")
    kid = make_check(owner, aid, "proposed")
    async with LifespanManager(app), browser(app) as c:
        anonymous = await c.post(f"/api/checks/{kid}/approve", json={"version": 1})
        assert anonymous.status_code == 401
        assert (await c.get("/api/assets")).status_code == 401
        assert (await c.get("/api/checks", params={"asset_id": aid})).status_code == 401
        await sign_in(env, c)
        async with browser(app, csrf=False) as bare:
            bare.cookies = c.cookies
            forged = await bare.post(f"/api/checks/{kid}/approve", json={"version": 1})
            assert forged.status_code == 403 and forged.json() == {"detail": "csrf"}
        r = await c.post(f"/api/checks/{kid}/approve", json={"version": 1})
        assert r.status_code == 200, r.text
        events = (await c.get(f"/api/checks/{kid}/events")).json()
        assert [(e["actor"], e["action"]) for e in events] == [(ADMIN, "approve")]
    user = sql(owner, "SELECT id FROM users WHERE email = :e", e=ADMIN)[0][0]
    assert sql(owner, "SELECT user_id, actor FROM check_events WHERE check_id = :k", k=kid) == [(user, ADMIN)]
    sql(owner, "DELETE FROM users WHERE id = :u", u=user)
    assert sql(owner, "SELECT user_id, actor FROM check_events WHERE check_id = :k", k=kid) == [(None, ADMIN)]


@needs_db
@pytest.mark.parametrize("mode", ["dev", "proxy"])
async def test_events_without_sign_in_name_the_mode(owner: Engine, tmp_path: Path, mode: str) -> None:
    app = create_app(auth_settings(tmp_path, auth_mode=mode))
    aid = make_asset(owner, make_connection(owner), "t")
    kid = make_check(owner, aid, "active")
    async with LifespanManager(app), browser(app) as c:
        assert (await c.post(f"/api/checks/{kid}/lock", json={"version": 1})).status_code == 200
        events = (await c.get(f"/api/checks/{kid}/events")).json()
    assert [(e["actor"], e["action"], e["from_status"], e["to_status"]) for e in events] == [
        (mode, "lock", "active", "locked")
    ]
    assert sql(owner, "SELECT user_id FROM check_events WHERE check_id = :k", k=kid) == [(None,)]


@pytest.fixture
async def hostile_shop(tmp_path: Path) -> AsyncIterator[Path]:
    """Files and columns named with quotes, semicolons and Unicode."""
    folder = tmp_path / "hostile"
    folder.mkdir()
    for stem in ("it's; here", UNICODE):
        with (folder / f"{stem}.csv").open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["id", HOSTILE, 'quote"col', UNICODE])
            for i in range(80):
                w.writerow([i, HOSTILE if i % 2 else "ok", "a" if i % 3 else "b", f"{i % 4}"])
    yield folder


@needs_db
async def test_hostile_names_through_persistence(
    client: AsyncClient, owner: Engine, hostile_shop: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = await connect(client, monkeypatch, hostile_shop)
    first = await scan(client, cid)
    assets = (await client.get("/api/assets", params={"connection_id": cid})).json()["items"]
    assert sorted(a["label"] for a in assets) == sorted(["it's; here", UNICODE])
    for a in assets:
        detail = (await client.get(f"/api/assets/{a['id']}")).json()
        assert [c["name"] for c in detail["columns"]] == ["id", HOSTILE, 'quote"col', UNICODE]
        checks = (await client.get("/api/checks", params={"asset_id": a["id"]})).json()
        assert HOSTILE in {c["column"] for c in checks}
        hostile = next(c for c in checks if c["column"] == HOSTILE and c["status"] == "active")
        await act(client, hostile, "lock")
    stored = sql(
        owner,
        "SELECT count(*) FROM checks k JOIN assets a ON a.id = k.asset_id WHERE a.connection_id = :c",
        c=cid,
    )
    assert stored[0][0] == len(first["checks"])
    second = await scan(client, cid)
    assert {s["id"] for s in second["checks"]} == {s["id"] for s in first["checks"]}
    assert (
        sql(
            owner,
            "SELECT count(*) FROM checks k JOIN assets a ON a.id = k.asset_id WHERE a.connection_id = :c",
            c=cid,
        )
        == stored
    )
    assert sql(owner, "SELECT count(*) FROM connections WHERE id = :c", c=cid)[0][0] == 1


@needs_db
async def test_csrf_header_is_required_in_dev_mode(client: AsyncClient, owner: Engine) -> None:
    aid = make_asset(owner, make_connection(owner), "t")
    kid = make_check(owner, aid, "proposed")
    bare = {k: "" for k in CSRF}
    r = await client.post(f"/api/checks/{kid}/approve", json={"version": 1}, headers=bare)
    assert r.status_code == 403 and r.json() == {"detail": "csrf"}


@needs_db
async def test_failure_loading_saved_checks_fails_the_scan(
    client: AsyncClient, owner: Engine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A database error before the scan starts marks it failed instead of leaving it queued."""
    import sahifa.services.scans as scans_service

    async def broken(*_: Any) -> Any:
        raise RuntimeError("database went away")

    write_shop(tmp_path, clean=True, rows=50)
    cid = await connect(client, monkeypatch, tmp_path)
    monkeypatch.setattr(scans_service, "load_saved", broken)
    r = await client.post("/api/scans", json={"connection_id": cid, "sample_rows": 0})
    sid = r.json()["id"]
    for _ in range(200):
        s = (await client.get(f"/api/scans/{sid}")).json()
        if s["status"] in ("succeeded", "failed"):
            break
        await asyncio.sleep(0.05)
    assert s["status"] == "failed" and "database went away" in s["error"]

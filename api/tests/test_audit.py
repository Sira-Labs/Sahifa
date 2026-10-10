"""The audit log of people's changes (spec 018)."""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from sahifa.db import WORKSPACES, Database

from .conftest import DB_URL, needs_db
from .tenancy import add_member, default_workspace, make_tree, make_workspace, sql, user_id
from .test_auth_flow import ADMIN, Env, browser, sign_in
from .test_auth_flow import env as env  # the fixture

pytestmark = [needs_db, pytest.mark.usefixtures("drops_workspaces")]

SECRET_REF = "SAHIFA_CONN_AUDIT"
MARKER = "MARKER-7f3a"  # in the credential's value; must never reach an entry
CSV = ("orders.csv", b"id,amount\n1,10\n", "text/csv")
WSADMIN = "wsadmin@example.org"
VIEWER = "viewer@example.org"
MEMBER = "member@example.org"


async def entries(c: AsyncClient, **params: Any) -> list[dict[str, Any]]:
    r = await c.get("/api/audit", params={"limit": 200, **params})
    assert r.status_code == 200, r.text
    items: list[dict[str, Any]] = r.json()["items"]
    return items


async def only(c: AsyncClient, action: str, object_id: str) -> dict[str, Any]:
    found = await entries(c, action=action, object_id=object_id)
    assert len(found) == 1, (action, found)
    return found[0]


@pytest.fixture
async def admin(env: Env, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> AsyncIterator[AsyncClient]:
    """The org admin, signed in; a credential with a marker in its value."""
    monkeypatch.setenv(SECRET_REF, f"postgresql://reader:{MARKER}@db.invalid/shop")
    async with browser(env.app) as c:
        await sign_in(env, c, email=ADMIN)
        yield c


async def test_approving_a_check_and_muting_a_finding_are_recorded(env: Env, admin: AsyncClient) -> None:
    tree = make_tree(env.owner, default_workspace(env.owner))
    assert (await admin.post(f"/api/checks/{tree['check']}/lock", json={"version": 1})).status_code == 200
    muted = await admin.post(
        f"/api/findings/{tree['finding']}/mute", json={"version": 1, "note": "known gap"}
    )
    assert muted.status_code == 200
    lock = await only(admin, "check.lock", tree["check"])
    assert lock["actor"] == ADMIN and lock["object_type"] == "check"
    assert lock["before"] == {"status": "active", "version": 1} and lock["after"] == {
        "status": "locked",
        "version": 2,
    }
    assert lock["summary"].startswith("Locked ") and lock["workspace"]["id"] == default_workspace(env.owner)
    mute = await only(admin, "finding.mute", tree["finding"])
    assert mute["before"]["status"] == "open"
    assert mute["after"] == {"status": "muted", "muted_until": None, "note": "known gap"}


async def test_every_action_is_recorded(env: Env, admin: AsyncClient) -> None:
    default = default_workspace(env.owner)
    async with browser(env.app) as member:
        await sign_in(env, member, email=MEMBER)
    member_id = user_id(env.owner, MEMBER)
    made = await admin.post(
        "/api/connections",
        json={
            "name": f"a-{uuid.uuid4().hex[:8]}",
            "kind": "duckdb",
            "secret_ref": SECRET_REF,
            "workspace_id": default,
        },
    )
    assert made.status_code == 201, made.text
    created = await only(admin, "connection.created", made.json()["id"])
    assert created["after"]["secret_ref"] == SECRET_REF

    tree = make_tree(env.owner, default)
    c = tree["connection"]
    saved = await admin.put(
        f"/api/connections/{c}/schedule",
        json={"cron": "0 3 * * *", "timezone": "UTC", "enabled": True, "version": 1},
    )
    assert saved.status_code == 200
    change = await only(admin, "schedule.saved", tree["schedule"])
    assert change["before"] == {"cron": "0 2 * * *", "enabled": False} and change["after"] == {
        "cron": "0 3 * * *",
        "enabled": True,
    }
    assert (await admin.delete(f"/api/connections/{c}/schedule")).status_code == 204
    assert (await only(admin, "schedule.deleted", tree["schedule"]))["before"]["cron"] == "0 3 * * *"

    scan = await admin.post("/api/scans", json={"connection_id": c, "sample_rows": 0})
    assert (await only(admin, "scan.started", scan.json()["id"]))["after"]["sample_rows"] == 0
    upload = await admin.post("/api/scans/upload", files={"files": CSV}, data={"workspace_id": default})
    assert (await only(admin, "scan.uploaded", upload.json()["id"]))["after"]["files"] == ["orders.csv"]

    ws = (await admin.post("/api/workspaces", json={"name": f"Audit {uuid.uuid4().hex[:6]}"})).json()
    assert (await only(admin, "workspace.created", ws["id"]))["after"] == {"name": ws["name"]}
    await admin.patch(f"/api/workspaces/{ws['id']}", json={"name": ws["name"] + " 2"})
    assert (await only(admin, "workspace.renamed", ws["id"]))["before"] == {"name": ws["name"]}

    members = f"/api/workspaces/{ws['id']}/members/{member_id}"
    await admin.put(members, json={"role": "viewer"})
    await admin.put(members, json={"role": "viewer"})  # no change, no entry
    await admin.put(members, json={"role": "editor"})
    await admin.delete(members)
    assert (await only(admin, "membership.added", member_id))["after"] == {"role": "viewer", "email": MEMBER}
    assert (await only(admin, "membership.changed", member_id))["after"]["role"] == "editor"
    assert (await only(admin, "membership.removed", member_id))["before"]["role"] == "editor"

    fresh = make_tree(env.owner, default)
    moved = await admin.put(
        f"/api/connections/{fresh['connection']}/workspace", json={"workspace_id": ws["id"]}
    )
    assert moved.status_code == 200
    both = await entries(admin, action="connection.moved", object_id=fresh["connection"])
    assert sorted(e["workspace"]["id"] for e in both) == sorted([default, ws["id"]])


async def test_a_failed_change_records_nothing(env: Env, admin: AsyncClient) -> None:
    tree = make_tree(env.owner, default_workspace(env.owner))
    stale = await admin.post(f"/api/checks/{tree['check']}/lock", json={"version": 9})
    assert stale.status_code == 409
    assert await entries(admin, object_id=tree["check"]) == []


async def test_entries_are_append_only(env: Env) -> None:
    tree = make_tree(env.owner, default_workspace(env.owner))
    for statement in (
        "UPDATE audit_events SET summary = 'x' WHERE id = :i",
        "DELETE FROM audit_events WHERE id = :i",
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            sql(env.owner, statement, i=tree["audit"])
    assert DB_URL
    db = Database(DB_URL)
    try:
        for statement in (
            "UPDATE audit_events SET summary = 'x' WHERE id = :i",
            "DELETE FROM audit_events WHERE id = :i",
        ):
            async with db.sessions() as s:
                s.info[WORKSPACES] = (uuid.UUID(default_workspace(env.owner)),)
                with pytest.raises(DBAPIError, match=r"append-only|permission denied"):
                    await s.execute(text(statement), {"i": tree["audit"]})
    finally:
        await db.dispose()
    assert sql(env.owner, "SELECT summary FROM audit_events WHERE id = :i", i=tree["audit"]) == [
        ("Registered",)
    ]


async def test_a_deleted_user_leaves_their_entries(env: Env, admin: AsyncClient) -> None:
    tree = make_tree(env.owner, default_workspace(env.owner))
    async with browser(env.app) as c:
        await sign_in(env, c, email=MEMBER)
        add_member(env.owner, default_workspace(env.owner), MEMBER, "editor")
        assert (await c.post(f"/api/checks/{tree['check']}/lock", json={"version": 1})).status_code == 200
    sql(env.owner, "DELETE FROM users WHERE email = :e", e=MEMBER)
    entry = await only(admin, "check.lock", tree["check"])
    assert entry["actor"] == MEMBER


async def test_admins_read_their_workspaces_only(env: Env, admin: AsyncClient) -> None:
    a, b = make_workspace(env.owner), make_workspace(env.owner)
    tree_a, tree_b = make_tree(env.owner, a), make_tree(env.owner, b)
    async with AsyncExitStack() as stack:
        wsadmin = await stack.enter_async_context(browser(env.app))
        await sign_in(env, wsadmin, email=WSADMIN)
        viewer = await stack.enter_async_context(browser(env.app))
        await sign_in(env, viewer, email=VIEWER)
        add_member(env.owner, a, WSADMIN, "admin")
        add_member(env.owner, b, WSADMIN, "viewer")
        add_member(env.owner, a, VIEWER, "viewer")
        mine = {e["id"] for e in await entries(wsadmin)}
        assert tree_a["audit"] in mine and tree_b["audit"] not in mine
        assert await entries(wsadmin, workspace_id=b) == []
        denied = await viewer.get("/api/audit")
        assert denied.status_code == 403 and denied.json()["needs"] == "admin"
        everything = {e["id"] for e in await entries(admin, object_type="connection")}
        assert {tree_a["audit"], tree_b["audit"]} <= everything


async def test_filters_and_cursor(env: Env, admin: AsyncClient) -> None:
    tree = make_tree(env.owner, default_workspace(env.owner))
    await admin.post(f"/api/checks/{tree['check']}/lock", json={"version": 1})
    await admin.post(f"/api/checks/{tree['check']}/unlock", json={"version": 2})
    checks = await entries(admin, action="check.", object_id=tree["check"])
    assert [e["action"] for e in checks] == ["check.unlock", "check.lock"]
    assert await entries(admin, action="check", object_id=tree["check"]) == []
    assert len(await entries(admin, actor="OWNER@", object_id=tree["check"])) == 2
    assert await entries(admin, actor="%", object_id=tree["check"]) == []
    first = (await admin.get("/api/audit", params={"limit": 1, "object_id": tree["check"]})).json()
    second = (
        await admin.get(
            "/api/audit", params={"limit": 1, "object_id": tree["check"], "cursor": first["next_cursor"]}
        )
    ).json()
    assert [first["items"][0]["action"], second["items"][0]["action"]] == ["check.unlock", "check.lock"]
    assert second["next_cursor"] is None
    assert (await admin.get("/api/audit", params={"cursor": "nope"})).status_code == 422


async def test_no_secret_in_any_entry(env: Env, admin: AsyncClient) -> None:
    made = await admin.post(
        "/api/connections",
        json={
            "name": f"s-{uuid.uuid4().hex[:8]}",
            "kind": "postgres",
            "secret_ref": SECRET_REF,
            "workspace_id": default_workspace(env.owner),
        },
    )
    assert made.status_code == 201
    rows = sql(env.owner, "SELECT to_jsonb(a) FROM audit_events a")
    assert rows and all(MARKER not in json.dumps(r[0]) for r in rows)


def test_migration_0009_backfills_and_round_trips(env: Env) -> None:
    from alembic import command

    from sahifa.db.migrate import build_config, downgrade, upgrade

    assert DB_URL
    tree = make_tree(env.owner, default_workspace(env.owner))
    downgrade(DB_URL, "0008")
    try:
        assert sql(env.owner, "SELECT to_regclass('audit_events')") == [(None,)]
    finally:
        upgrade(DB_URL)
    backfilled = sql(
        env.owner,
        "SELECT action, actor, before ->> 'status', after ->> 'status' FROM audit_events"
        " WHERE object_id IN (:c, :f) ORDER BY action",
        c=tree["check"],
        f=tree["finding"],
    )
    assert backfilled == [
        ("check.approve", "test", None, "active"),
        ("finding.acknowledge", "test", None, "acknowledged"),
    ]
    command.check(build_config(DB_URL))

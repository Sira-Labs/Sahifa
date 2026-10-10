"""Workspaces, members, the user search, moving connections and `/me` (spec 016); deleting a
workspace (spec 020)."""

from __future__ import annotations

import uuid
from contextlib import AsyncExitStack
from pathlib import Path

import pytest
from httpx import AsyncClient

from .conftest import needs_db
from .tenancy import (
    TABLES,
    add_member,
    default_workspace,
    make_tree,
    make_workspace,
    sql,
    user_id,
    workspaces_of,
)
from .test_auth_flow import ADMIN, ALLOWED, OTHER, Env, browser, sign_in
from .test_auth_flow import env as env  # the fixture

pytestmark = [needs_db, pytest.mark.usefixtures("drops_workspaces")]


async def person(env: Env, stack: AsyncExitStack, email: str) -> AsyncClient:
    """A browser signed in as `email`."""
    c = await stack.enter_async_context(browser(env.app))
    await sign_in(env, c, email=email)
    return c


async def test_create_and_rename(env: Env) -> None:
    name = f"Finance {uuid.uuid4().hex[:6]}"
    async with AsyncExitStack() as stack:
        admin = await person(env, stack, ADMIN)
        ana = await person(env, stack, ALLOWED)
        r = await admin.post("/api/workspaces", json={"name": name})
        assert r.status_code == 201, r.text
        created = r.json()
        assert (created["name"], created["role"], created["members"], created["connections"]) == (
            name,
            "admin",
            0,
            0,
        )
        assert (await admin.post("/api/workspaces", json={"name": name.upper()})).json()[
            "detail"
        ] == "name_taken"
        assert (await admin.post("/api/workspaces", json={"name": " "})).status_code == 422
        denied = await ana.post("/api/workspaces", json={"name": f"x {name}"})
        assert denied.status_code == 403
        assert denied.json() == {"detail": "forbidden_role", "role": "editor", "needs": "org_admin"}
        wid = created["id"]
        assert (await ana.patch(f"/api/workspaces/{wid}", json={"name": "Mine"})).status_code == 404
        add_member(env.owner, wid, ALLOWED, "viewer")
        assert (await ana.patch(f"/api/workspaces/{wid}", json={"name": "Mine"})).status_code == 403
        renamed = await admin.patch(f"/api/workspaces/{wid}", json={"name": f"{name} EU"})
        assert renamed.status_code == 200 and renamed.json()["name"] == f"{name} EU"
        listed = {w["id"]: w for w in (await ana.get("/api/workspaces")).json()}
        assert listed[wid]["role"] == "viewer" and listed[default_workspace(env.owner)]["role"] == "editor"
        assert len((await admin.get("/api/workspaces")).json()) >= 2


async def test_members_add_change_remove(env: Env) -> None:
    async with AsyncExitStack() as stack:
        admin = await person(env, stack, ADMIN)
        ana = await person(env, stack, ALLOWED)
        other = await person(env, stack, OTHER)
        assert (await other.get("/api/auth/me")).status_code == 403
        wid = make_workspace(env.owner)
        ana_id, other_id = user_id(env.owner, ALLOWED), user_id(env.owner, OTHER)
        assert (
            await admin.put(f"/api/workspaces/{wid}/members/{uuid.uuid4()}", json={"role": "viewer"})
        ).status_code == 404
        assert (
            await admin.put(f"/api/workspaces/{wid}/members/{ana_id}", json={"role": "owner"})
        ).status_code == 422
        made = await admin.put(f"/api/workspaces/{wid}/members/{ana_id}", json={"role": "admin"})
        assert made.status_code == 200 and made.json()["role"] == "admin"
        # Ana, admin of the workspace, adds Other, who then gets in.
        added = await ana.put(f"/api/workspaces/{wid}/members/{other_id}", json={"role": "viewer"})
        assert added.status_code == 200
        me = (await other.get("/api/auth/me")).json()
        assert me["workspaces"] == [
            {"id": wid, "name": me["workspaces"][0]["name"], "role": "viewer", "is_default": False}
        ]
        assert (await ana.put(f"/api/workspaces/{wid}/members/{other_id}", json={"role": "editor"})).json()[
            "role"
        ] == "editor"
        members = {m["email"]: m["role"] for m in (await ana.get(f"/api/workspaces/{wid}/members")).json()}
        assert members == {ALLOWED: "admin", OTHER: "editor"}
        assert (await other.get(f"/api/workspaces/{wid}/members")).status_code == 403
        own = await ana.put(f"/api/workspaces/{wid}/members/{ana_id}", json={"role": "editor"})
        assert own.status_code == 409 and own.json()["detail"] == "own_membership"
        assert (await ana.delete(f"/api/workspaces/{wid}/members/{ana_id}")).status_code == 409
        assert (await ana.delete(f"/api/workspaces/{wid}/members/{other_id}")).status_code == 204
        assert (await ana.delete(f"/api/workspaces/{wid}/members/{other_id}")).status_code == 404
        assert (await other.get("/api/auth/me")).status_code == 403
        # The org admin may change anyone, including the last admin.
        assert (await admin.delete(f"/api/workspaces/{wid}/members/{ana_id}")).status_code == 204


async def test_user_search(env: Env) -> None:
    async with AsyncExitStack() as stack:
        admin = await person(env, stack, ADMIN)
        ana = await person(env, stack, ALLOWED)
        await person(env, stack, OTHER)
        denied = await ana.get("/api/users", params={"q": "example"})
        assert denied.status_code == 403 and denied.json()["needs"] == "admin"
        found = {u["email"] for u in (await admin.get("/api/users", params={"q": "EXAMPLE.org"})).json()}
        assert {ADMIN, ALLOWED, OTHER} <= found
        assert (await admin.get("/api/users", params={"q": "%"})).json() == []
        assert (await admin.get("/api/users", params={"q": "_"})).json() == []
        assert (await admin.get("/api/users", params={"q": ""})).status_code == 422
        add_member(env.owner, make_workspace(env.owner), ALLOWED, "admin")
        assert [u["email"] for u in (await ana.get("/api/users", params={"q": "other@"})).json()] == [OTHER]


async def test_move_connection_moves_every_row(env: Env) -> None:
    source, target = default_workspace(env.owner), make_workspace(env.owner)
    tree = make_tree(env.owner, source)
    busy = make_tree(env.owner, source, scan_status="running")
    async with AsyncExitStack() as stack:
        admin = await person(env, stack, ADMIN)
        ana = await person(env, stack, ALLOWED)
        url = f"/api/connections/{tree['connection']}/workspace"
        denied = await ana.put(url, json={"workspace_id": target})
        assert denied.status_code == 403 and denied.json()["needs"] == "org_admin"
        assert (await admin.put(url, json={"workspace_id": str(uuid.uuid4())})).status_code == 404
        moved = await admin.put(url, json={"workspace_id": target})
        assert moved.status_code == 200, moved.text
        assert moved.json()["workspace"]["id"] == target
        assert workspaces_of(env.owner, tree["connection"]) == {t: {target} for t in TABLES}
        # Ana (editor of Default only) no longer sees it.
        assert (await ana.get(f"/api/connections/{tree['connection']}")).status_code == 404
        blocked = await admin.put(
            f"/api/connections/{busy['connection']}/workspace", json={"workspace_id": target}
        )
        assert blocked.status_code == 409 and blocked.json()["detail"] == "scan_running"
        assert workspaces_of(env.owner, busy["connection"]) == {t: {source} for t in TABLES}


async def test_me_lists_workspaces_and_the_organisation(env: Env) -> None:
    app = await env.make(org_name="Acme Data")
    async with browser(app) as admin, browser(app) as ana:
        await sign_in(env, admin, email=ADMIN)
        await sign_in(env, ana, email=ALLOWED)
        me = (await admin.get("/api/auth/me")).json()
        assert me["org_admin"] is True and me["admin"] is True and me["organisation"] == "Acme Data"
        assert {w["role"] for w in me["workspaces"]} == {"admin"}
        assert any(w["is_default"] for w in me["workspaces"])
        mine = (await ana.get("/api/auth/me")).json()
        assert mine["org_admin"] is False
        assert [(w["id"], w["role"]) for w in mine["workspaces"]] == [
            (default_workspace(env.owner), "editor")
        ]
    assert sql(env.owner, "SELECT name FROM organisations") == [("Acme Data",)]


async def test_allowed_email_becomes_editor_of_default_once(env: Env) -> None:
    async with browser(env.app) as c:
        await sign_in(env, c, email=ALLOWED)
        assert (await c.get("/api/scans")).status_code == 200
        assert (await c.get("/api/scans")).status_code == 200
    rows = sql(
        env.owner,
        "SELECT w.is_default, m.role FROM memberships m JOIN workspaces w ON w.id = m.workspace_id"
        " JOIN users u ON u.id = m.user_id WHERE u.email = :e",
        e=ALLOWED,
    )
    assert rows == [(True, "editor")]


async def test_deleting_a_workspace(env: Env, tmp_path: Path) -> None:
    """Spec 020: the org admin deletes a workspace with its uploads, scans, findings, members,
    invitations and audit entries; the record stays in the default workspace."""
    wid = make_workspace(env.owner, f"Trial {uuid.uuid4().hex[:6]}")
    name = sql(env.owner, "SELECT name FROM workspaces WHERE id = :w", w=wid)[0][0]
    tree = make_tree(env.owner, wid)
    folder = tmp_path / "uploads" / "batch-1"
    folder.mkdir(parents=True)
    (folder / "orders.csv").write_text("id\n1\n")
    async with AsyncExitStack() as stack:
        admin = await person(env, stack, ADMIN)
        ana = await person(env, stack, ALLOWED)
        add_member(env.owner, wid, ALLOWED, "admin")
        target = f"/api/workspaces/{wid}"
        has = await admin.request("DELETE", target, json={"confirm": name})
        assert has.status_code == 409 and has.json()["connections"] == [f"t-{tree['connection']}"]
        sql(
            env.owner,
            "UPDATE connections SET kind = 'upload',"
            " config = jsonb_build_object('paths', jsonb_build_array(CAST(:p AS text))) WHERE id = :c",
            p=str(folder / "orders.csv"),
            c=tree["connection"],
        )
        await admin.post(f"{target}/invitations", json={"email": "new@example.org", "role": "viewer"})
        denied = await ana.request("DELETE", target, json={"confirm": name})
        assert denied.status_code == 403 and denied.json()["needs"] == "org_admin"
        wrong = await admin.request("DELETE", target, json={"confirm": name.upper()})
        assert wrong.status_code == 422 and wrong.json()["detail"] == "confirm_mismatch"
        default = await admin.request(
            "DELETE", f"/api/workspaces/{default_workspace(env.owner)}", json={"confirm": "Default"}
        )
        assert default.status_code == 409 and default.json()["detail"] == "default_workspace"
        done = await admin.request("DELETE", target, json={"confirm": name})
        assert done.status_code == 204, done.text
        assert (await ana.get(target + "/invitations")).status_code == 404
    for table in ("connections", "scans", "findings", "memberships", "invitations", "audit_events"):
        assert sql(env.owner, f"SELECT count(*) FROM {table} WHERE workspace_id = :w", w=wid) == [(0,)], table
    assert sql(env.owner, "SELECT count(*) FROM workspaces WHERE id = :w", w=wid) == [(0,)]
    assert not folder.exists()
    record = sql(
        env.owner,
        "SELECT workspace_id, before FROM audit_events WHERE action = 'workspace.deleted' AND object_id = :w",
        w=wid,
    )
    assert len(record) == 1 and str(record[0][0]) == default_workspace(env.owner)
    assert record[0][1] | {} == {
        "name": name,
        "uploads": 1,
        "scans": 1,
        "findings": 1,
        "members": 1,
        "invitations": 1,
    }

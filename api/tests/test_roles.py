"""Roles and workspace isolation on the existing routes (spec 016): viewers cannot change,
editors can; objects of other workspaces are 404 and absent from lists. The full matrix of routes and
roles is S4-2."""

from __future__ import annotations

from contextlib import AsyncExitStack
from typing import Any

import pytest
from httpx import AsyncClient

from .conftest import needs_db
from .tenancy import add_member, default_workspace, make_tree, make_workspace
from .test_auth_flow import ALLOWED, OTHER, Env
from .test_auth_flow import env as env  # the fixture
from .test_workspaces import person

FORBIDDEN = {"detail": "forbidden_role", "role": "viewer", "needs": "editor"}
CSV = ("orders.csv", b"id,amount\n1,10\n2,20\n", "text/csv")


pytestmark = [needs_db, pytest.mark.usefixtures("drops_workspaces")]


def changes(tree: dict[str, str], workspace_id: str) -> list[tuple[str, str, dict[str, Any]]]:
    """Every change the viewer may not make and the editor may: (method, url, request kwargs)."""
    c = tree["connection"]
    schedule = {"cron": "0 3 * * *", "timezone": "UTC", "enabled": False, "version": 1}
    return [
        ("POST", f"/api/checks/{tree['check']}/lock", {"json": {"version": 1}}),
        ("POST", f"/api/findings/{tree['finding']}/acknowledge", {"json": {"version": 1}}),
        ("POST", "/api/scans", {"json": {"connection_id": c, "sample_rows": 0}}),
        ("POST", "/api/scans/upload", {"files": {"files": CSV}, "data": {"workspace_id": workspace_id}}),
        ("PUT", f"/api/connections/{c}/schedule", {"json": schedule}),
        ("DELETE", f"/api/connections/{c}/schedule", {}),
    ]


async def test_viewer_cannot_change_and_editor_can(env: Env) -> None:
    wid = make_workspace(env.owner)
    tree = make_tree(env.owner, wid)
    async with AsyncExitStack() as stack:
        viewer = await person(env, stack, OTHER)
        editor = await person(env, stack, ALLOWED)
        add_member(env.owner, wid, OTHER, "viewer")
        add_member(env.owner, wid, ALLOWED, "editor")
        seen = (await viewer.get(f"/api/connections/{tree['connection']}")).json()
        assert seen["role"] == "viewer" and seen["workspace"]["id"] == wid
        for method, url, kwargs in changes(tree, wid):
            r = await viewer.request(method, url, **kwargs)
            assert (r.status_code, r.json()) == (403, FORBIDDEN), (method, url, r.text)
        # A workspace the viewer is not in does not exist for them.
        foreign = await viewer.post(
            "/api/scans/upload", files={"files": CSV}, data={"workspace_id": make_workspace(env.owner)}
        )
        assert foreign.status_code == 404
        # Without a workspace the viewer's upload has none to go to: still 403.
        bare = await viewer.post("/api/scans/upload", files={"files": CSV})
        assert (bare.status_code, bare.json()) == (403, FORBIDDEN)
        expected = [200, 200, 202, 202, 200, 204]
        for (method, url, kwargs), status in zip(changes(tree, wid), expected, strict=True):
            r = await editor.request(method, url, **kwargs)
            assert r.status_code == status, (method, url, r.text)
        # An editor of two workspaces must name the upload's.
        add_member(env.owner, make_workspace(env.owner), ALLOWED, "editor")
        unnamed = await editor.post("/api/scans/upload", files={"files": CSV})
        assert unnamed.status_code == 422 and unnamed.json()["detail"] == "workspace_required"


async def get_ids(c: AsyncClient, url: str, **params: Any) -> set[str]:
    body = (await c.get(url, params=params)).json()
    items = body["items"] if isinstance(body, dict) else body
    return {i["id"] for i in items}


async def test_other_workspaces_are_invisible(env: Env) -> None:
    mine = make_workspace(env.owner)
    own = make_tree(env.owner, mine)
    other = make_tree(env.owner, default_workspace(env.owner))
    async with AsyncExitStack() as stack:
        viewer = await person(env, stack, OTHER)
        add_member(env.owner, mine, OTHER, "viewer")
        c, a = other["connection"], other["asset"]
        for url in (
            f"/api/connections/{c}",
            f"/api/connections/{c}/schedule",
            f"/api/connections/{c}/history",
            f"/api/scans/{other['scan']}",
            f"/api/scans/{other['scan']}/findings",
            f"/api/assets/{a}",
            f"/api/assets/{a}/history",
            f"/api/checks?asset_id={a}",
            f"/api/checks/{other['check']}/events",
            f"/api/findings/{other['finding']}",
        ):
            r = await viewer.get(url)
            assert r.status_code == 404, (url, r.text)
        # Changing something elsewhere is 404 too, not 403: it does not exist for the caller.
        r = await viewer.post(f"/api/checks/{other['check']}/lock", json={"version": 1})
        assert r.status_code == 404
        assert c not in await get_ids(viewer, "/api/connections")
        assert other["scan"] not in await get_ids(viewer, "/api/scans", limit=100)
        assert a not in await get_ids(viewer, "/api/assets", limit=200)
        assert other["finding"] not in await get_ids(viewer, "/api/findings", limit=200)
        assert own["connection"] in await get_ids(viewer, "/api/connections")
        assert own["finding"] in await get_ids(viewer, "/api/findings", limit=200)
        assert (await viewer.get(f"/api/assets/{own['asset']}/history")).status_code == 200


async def test_lists_filter_by_workspace(env: Env) -> None:
    a, b = make_workspace(env.owner), make_workspace(env.owner)
    tree_a, tree_b = make_tree(env.owner, a), make_tree(env.owner, b)
    async with AsyncExitStack() as stack:
        editor = await person(env, stack, ALLOWED)
        add_member(env.owner, a, ALLOWED, "editor")
        add_member(env.owner, b, ALLOWED, "viewer")
        for url, key in (
            ("/api/connections", "connection"),
            ("/api/scans", "scan"),
            ("/api/assets", "asset"),
            ("/api/findings", "finding"),
        ):
            assert await get_ids(editor, url, workspace_id=a) == {tree_a[key]}, url
            assert await get_ids(editor, url, workspace_id=b) == {tree_b[key]}, url

"""Every route against every role (spec 017).

`OPS` is the test's own copy of spec 016's role table: for each workspace operation its minimum
role, its scope and a request that succeeds for a caller allowed to make it. `run_matrix` asks
every operation as every caller and returns each answer that differs from the expected one.
It never reads the role from the route code, so a route that loses its check shows up here.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, Request
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from sahifa import deps
from sahifa.auth import access as access_module
from sahifa.auth.access import Access
from sahifa.auth.deps import DEV_PRINCIPAL
from sahifa.db import SYSTEM

from .conftest import needs_db
from .tenancy import add_member, make_tree, make_workspace, user_id
from .test_auth_flow import ADMIN, Env, browser, sign_in
from .test_auth_flow import env as env  # the fixture

pytestmark = [needs_db, pytest.mark.usefixtures("drops_workspaces")]

RANK = {"viewer": 1, "editor": 2, "admin": 3, "org_admin": 4}
CALLERS = ("anonymous", "no_access", "outsider", "viewer", "editor", "admin", "org_admin")
EMAILS = {
    "no_access": "noaccess@example.org",
    "outsider": "outsider@example.org",
    "viewer": "viewer@example.org",
    "editor": "editor@example.org",
    "admin": "wsadmin@example.org",
    "org_admin": ADMIN,
}
TARGET = "target@example.org"  # a person who has signed in, for the member routes
SECRET_REF = "SAHIFA_CONN_MATRIX"
CSV = ("orders.csv", b"id,amount\n1,10\n2,20\n", "text/csv")

# The operations that are not in the matrix: public ones, tested by spec 006, and the session
# ones, tested below.
PUBLIC = {
    ("GET", "/healthz"),
    ("GET", "/api/version"),
    ("GET", "/api/auth/options"),
    ("GET", "/api/auth/login"),
    ("GET", "/api/auth/passkey/add"),
    ("GET", "/api/auth/callback"),
    ("POST", "/api/auth/backchannel-logout"),
    ("POST", "/api/auth/logout"),  # idempotent: ends a session if there is one (spec 006)
}
SESSION = {
    ("GET", "/api/auth/sessions"),
    ("DELETE", "/api/auth/sessions/{session_id}"),
    ("POST", "/api/auth/sessions/revoke-others"),
}


@dataclass
class World:
    """Workspace A with a tree, workspace B with a tree, and what the requests need."""

    app: FastAPI
    owner: Any
    a: str
    b: str
    tree: dict[str, str]
    target: str

    def fresh(self) -> dict[str, str]:
        """A new tree in A, for a request that changes something."""
        return make_tree(self.owner, self.a)


Call = tuple[str, dict[str, Any]]


@dataclass(frozen=True)
class Op:
    """One workspace operation: who may call it, what it is about, and how to call it."""

    method: str
    path: str
    needs: str
    scope: str  # object | list | create | global
    ok: int
    request: Callable[[World], Call]
    # For lists: the id of A's object that the answer must hold for members and not for others.
    listed: Callable[[World], str] | None = None
    # Whether the object is in a table under row-level security (the workspace routes are not).
    rls: bool = True
    before: Callable[[World], None] | None = field(default=None)


def _name() -> str:
    return f"m-{uuid.uuid4().hex[:10]}"


def _schedule() -> dict[str, Any]:
    return {"cron": "0 3 * * *", "timezone": "UTC", "enabled": False, "version": 1}


def _target_is_member(w: World) -> None:
    add_member(w.owner, w.a, TARGET, "viewer")


OPS: tuple[Op, ...] = (
    Op("GET", "/api/auth/me", "viewer", "global", 200, lambda w: ("/api/auth/me", {})),
    # Connections and schedules
    Op(
        "GET",
        "/api/connections",
        "viewer",
        "list",
        200,
        lambda w: ("/api/connections", {}),
        listed=lambda w: w.tree["connection"],
    ),
    Op(
        "POST",
        "/api/connections",
        "admin",
        "create",
        201,
        lambda w: (
            "/api/connections",
            {"json": {"name": _name(), "kind": "duckdb", "secret_ref": SECRET_REF, "workspace_id": w.a}},
        ),
    ),
    Op(
        "GET",
        "/api/connections/{connection_id}",
        "viewer",
        "object",
        200,
        lambda w: (f"/api/connections/{w.tree['connection']}", {}),
    ),
    Op(
        "POST",
        "/api/connections/{connection_id}/test",
        "viewer",
        "object",
        200,
        lambda w: (f"/api/connections/{w.tree['connection']}/test", {}),
    ),
    Op(
        "GET",
        "/api/connections/{connection_id}/schedule",
        "viewer",
        "object",
        200,
        lambda w: (f"/api/connections/{w.tree['connection']}/schedule", {}),
    ),
    Op(
        "PUT",
        "/api/connections/{connection_id}/schedule",
        "editor",
        "object",
        200,
        lambda w: (f"/api/connections/{w.fresh()['connection']}/schedule", {"json": _schedule()}),
    ),
    Op(
        "DELETE",
        "/api/connections/{connection_id}/schedule",
        "editor",
        "object",
        204,
        lambda w: (f"/api/connections/{w.fresh()['connection']}/schedule", {}),
    ),
    Op(
        "GET",
        "/api/connections/{connection_id}/history",
        "viewer",
        "object",
        200,
        lambda w: (f"/api/connections/{w.tree['connection']}/history", {}),
    ),
    Op(
        "PUT",
        "/api/connections/{connection_id}/workspace",
        "org_admin",
        "object",
        200,
        lambda w: (f"/api/connections/{w.fresh()['connection']}/workspace", {"json": {"workspace_id": w.b}}),
    ),
    # Scans
    Op(
        "GET",
        "/api/scans",
        "viewer",
        "list",
        200,
        lambda w: ("/api/scans", {"params": {"limit": 100}}),
        listed=lambda w: w.tree["scan"],
    ),
    Op(
        "POST",
        "/api/scans",
        "editor",
        "object",
        202,
        lambda w: ("/api/scans", {"json": {"connection_id": w.fresh()["connection"], "sample_rows": 0}}),
    ),
    Op(
        "POST",
        "/api/scans/upload",
        "editor",
        "create",
        202,
        lambda w: ("/api/scans/upload", {"files": {"files": CSV}, "data": {"workspace_id": w.a}}),
    ),
    Op(
        "GET", "/api/scans/{scan_id}", "viewer", "object", 200, lambda w: (f"/api/scans/{w.tree['scan']}", {})
    ),
    Op(
        "GET",
        "/api/scans/{scan_id}/report",
        "viewer",
        "object",
        200,
        lambda w: (f"/api/scans/{w.tree['scan']}/report", {}),
    ),
    Op(
        "GET",
        "/api/scans/{scan_id}/findings",
        "viewer",
        "object",
        200,
        lambda w: (f"/api/scans/{w.tree['scan']}/findings", {}),
    ),
    # Assets and checks
    Op(
        "GET",
        "/api/assets",
        "viewer",
        "list",
        200,
        lambda w: ("/api/assets", {"params": {"connection_id": w.tree["connection"]}}),
        listed=lambda w: w.tree["asset"],
    ),
    Op(
        "GET",
        "/api/assets/{asset_id}",
        "viewer",
        "object",
        200,
        lambda w: (f"/api/assets/{w.tree['asset']}", {}),
    ),
    Op(
        "GET",
        "/api/assets/{asset_id}/history",
        "viewer",
        "object",
        200,
        lambda w: (f"/api/assets/{w.tree['asset']}/history", {}),
    ),
    Op(
        "GET",
        "/api/checks",
        "viewer",
        "object",
        200,
        lambda w: ("/api/checks", {"params": {"asset_id": w.tree["asset"]}}),
    ),
    Op(
        "POST",
        "/api/checks/{check_id}/{action}",
        "editor",
        "object",
        200,
        lambda w: (f"/api/checks/{w.fresh()['check']}/lock", {"json": {"version": 1}}),
    ),
    Op(
        "GET",
        "/api/checks/{check_id}/events",
        "viewer",
        "object",
        200,
        lambda w: (f"/api/checks/{w.tree['check']}/events", {}),
    ),
    # Findings
    Op(
        "GET",
        "/api/findings",
        "viewer",
        "list",
        200,
        lambda w: ("/api/findings", {"params": {"connection_id": w.tree["connection"]}}),
        listed=lambda w: w.tree["finding"],
    ),
    Op(
        "GET",
        "/api/findings/{finding_id}",
        "viewer",
        "object",
        200,
        lambda w: (f"/api/findings/{w.tree['finding']}", {}),
    ),
    Op(
        "POST",
        "/api/findings/{finding_id}/{action}",
        "editor",
        "object",
        200,
        lambda w: (f"/api/findings/{w.fresh()['finding']}/acknowledge", {"json": {"version": 1}}),
    ),
    # Workspaces, members and people
    Op(
        "GET",
        "/api/workspaces",
        "viewer",
        "list",
        200,
        lambda w: ("/api/workspaces", {}),
        listed=lambda w: w.a,
        rls=False,
    ),
    Op(
        "POST",
        "/api/workspaces",
        "org_admin",
        "global",
        201,
        lambda w: ("/api/workspaces", {"json": {"name": _name()}}),
        rls=False,
    ),
    Op(
        "PATCH",
        "/api/workspaces/{workspace_id}",
        "admin",
        "object",
        200,
        lambda w: (f"/api/workspaces/{w.a}", {"json": {"name": _name()}}),
        rls=False,
    ),
    Op(
        "GET",
        "/api/workspaces/{workspace_id}/members",
        "admin",
        "object",
        200,
        lambda w: (f"/api/workspaces/{w.a}/members", {}),
        rls=False,
    ),
    Op(
        "PUT",
        "/api/workspaces/{workspace_id}/members/{user_id}",
        "admin",
        "object",
        200,
        lambda w: (f"/api/workspaces/{w.a}/members/{w.target}", {"json": {"role": "viewer"}}),
        rls=False,
    ),
    Op(
        "DELETE",
        "/api/workspaces/{workspace_id}/members/{user_id}",
        "admin",
        "object",
        204,
        lambda w: (f"/api/workspaces/{w.a}/members/{w.target}", {}),
        rls=False,
        before=_target_is_member,
    ),
    Op(
        "GET",
        "/api/users",
        "admin",
        "global",
        200,
        lambda w: ("/api/users", {"params": {"q": "target"}}),
        rls=False,
    ),
)


@dataclass(frozen=True)
class Difference:
    op: Op
    caller: str
    expected: str
    got: str

    def __str__(self) -> str:
        return f"{self.op.method} {self.op.path} as {self.caller}: expected {self.expected}, got {self.got}"


def expected(op: Op, caller: str) -> tuple[int, str | None, bool | None]:
    """(status, detail or None, whether A's object is listed or None) for this caller."""
    if caller == "anonymous":
        return 401, "not_authenticated", None
    if caller == "no_access":
        return 403, "no_access", None
    if caller == "org_admin":
        return op.ok, None, True if op.listed else None
    if op.needs == "org_admin":
        return 403, "forbidden_role", None
    if caller == "outsider":
        if op.scope in ("object", "create"):
            return 404, None, None
        if op.scope == "list":
            return op.ok, None, False
        return (op.ok, None, None) if RANK["editor"] >= RANK[op.needs] else (403, "forbidden_role", None)
    if RANK[caller] >= RANK[op.needs]:
        return op.ok, None, True if op.listed else None
    return 403, "forbidden_role", None


def _ids(body: Any) -> set[str]:
    items = body["items"] if isinstance(body, dict) else body
    return {str(i.get("id")) for i in items}


async def run_matrix(world: World, clients: dict[str, AsyncClient]) -> list[Difference]:
    """Ask every operation as every caller; return every answer that differs from the table."""
    differences: list[Difference] = []
    for op in OPS:
        for caller in CALLERS:
            if op.before:
                op.before(world)
            url, kwargs = op.request(world)
            status, detail, listed = expected(op, caller)
            try:
                r = await clients[caller].request(op.method, url, **kwargs)
            except Exception as e:  # a server error is a difference, not a crash
                differences.append(Difference(op, caller, str(status), f"error {type(e).__name__}"))
                continue
            got_detail = None
            if r.status_code >= 400:
                body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
                got_detail = body.get("detail") if isinstance(body, dict) else None
            if r.status_code != status or (detail and got_detail != detail):
                differences.append(
                    Difference(
                        op,
                        caller,
                        f"{status} {detail or ''}".strip(),
                        f"{r.status_code} {got_detail or ''}".strip(),
                    )
                )
                continue
            if listed is not None and op.listed:
                present = op.listed(world) in _ids(r.json())
                if present != listed:
                    differences.append(
                        Difference(
                            op,
                            caller,
                            "listed" if listed else "not listed",
                            "listed" if present else "not listed",
                        )
                    )
    return differences


@pytest.fixture
async def setup(
    env: Env, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> AsyncIterator[tuple[World, dict[str, AsyncClient]]]:
    """Workspaces A and B with their trees, and a signed-in browser per caller."""
    monkeypatch.setenv(SECRET_REF, str(tmp_path))
    async with AsyncExitStack() as stack:
        clients: dict[str, AsyncClient] = {"anonymous": await stack.enter_async_context(browser(env.app))}
        for caller, email in (*EMAILS.items(), ("target", TARGET)):
            c = await stack.enter_async_context(browser(env.app))
            await sign_in(env, c, email=email)
            clients[caller] = c
        a, b = make_workspace(env.owner), make_workspace(env.owner)
        add_member(env.owner, b, EMAILS["outsider"], "editor")
        for role in ("viewer", "editor", "admin"):
            add_member(env.owner, a, EMAILS[role], role)
        world = World(
            app=env.app,
            owner=env.owner,
            a=a,
            b=b,
            tree=make_tree(env.owner, a),
            target=user_id(env.owner, TARGET),
        )
        make_tree(env.owner, b)
        yield world, clients


async def test_matrix(setup: tuple[World, dict[str, AsyncClient]]) -> None:
    world, clients = setup
    differences = await run_matrix(world, clients)
    assert not differences, "\n".join(map(str, differences))


async def test_session_routes(setup: tuple[World, dict[str, AsyncClient]]) -> None:
    """The session routes need a session, not a membership."""
    _, clients = setup
    for caller in CALLERS:
        c = clients[caller]
        answers = [
            (await c.get("/api/auth/sessions")).status_code,
            (await c.delete(f"/api/auth/sessions/{uuid.uuid4()}")).status_code,
            (await c.post("/api/auth/sessions/revoke-others")).status_code,
        ]
        assert answers == ([401] * 3 if caller == "anonymous" else [200, 404, 204]), (caller, answers)


def operations(app: FastAPI) -> set[tuple[str, str]]:
    return {(method.upper(), path) for path, item in app.openapi()["paths"].items() for method in item}


def test_every_route_is_classified(env: Env) -> None:
    matrix = {(op.method, op.path) for op in OPS}
    assert len(matrix) == len(OPS), "an operation is in the matrix twice"
    assert not (matrix & PUBLIC) and not (matrix & SESSION) and not (PUBLIC & SESSION)
    found = operations(env.app)
    assert found - matrix - PUBLIC - SESSION == set(), "classify these operations in OPS, PUBLIC or SESSION"
    assert (matrix | PUBLIC | SESSION) - found == set(), "these classified operations no longer exist"


async def test_an_unclassified_route_fails_the_check(env: Env) -> None:
    """The check above notices a route nobody classified."""
    app = await env.make()

    async def unclassified() -> dict[str, str]:
        return {}

    app.add_api_route("/api/unclassified", unclassified, methods=["GET"])

    app.openapi_schema = None
    matrix = {(op.method, op.path) for op in OPS}
    assert operations(app) - matrix - PUBLIC - SESSION == {("GET", "/api/unclassified")}


async def test_matrix_catches_a_missing_role_check(
    setup: tuple[World, dict[str, AsyncClient]], monkeypatch: pytest.MonkeyPatch
) -> None:
    world, clients = setup

    def allow(self: Access, *args: Any, **kwargs: Any) -> None:
        return None

    def pick(self: Access, workspace_id: uuid.UUID | None, *args: Any, **kwargs: Any) -> uuid.UUID:
        return workspace_id or next(iter(self.workspaces))

    for name in ("require", "require_any", "require_org_admin"):
        monkeypatch.setattr(Access, name, allow)
    monkeypatch.setattr(Access, "pick", pick)
    caught = {(d.op.method, d.op.path) for d in await run_matrix(world, clients) if d.caller == "viewer"}
    above_viewer = {(op.method, op.path) for op in OPS if op.needs != "viewer"}
    assert above_viewer <= caught, above_viewer - caught


async def test_matrix_catches_a_missing_scope(setup: tuple[World, dict[str, AsyncClient]]) -> None:
    """Request sessions that see every workspace, as if a route forgot its scope."""
    world, clients = setup

    async def unscoped(request: Request) -> AsyncIterator[AsyncSession]:
        async with request.app.state.db.sessions() as s:
            s.info[SYSTEM] = True
            yield s

    world.app.dependency_overrides[deps.session] = unscoped
    try:
        caught = {
            (d.op.method, d.op.path) for d in await run_matrix(world, clients) if d.caller == "outsider"
        }
    finally:
        world.app.dependency_overrides.pop(deps.session, None)
    secured = {
        (op.method, op.path)
        for op in OPS
        if op.rls and op.scope in ("object", "list") and op.needs != "org_admin"
    }
    assert secured <= caught, secured - caught


async def test_matrix_catches_a_missing_sign_in(
    setup: tuple[World, dict[str, AsyncClient]], monkeypatch: pytest.MonkeyPatch
) -> None:
    world, clients = setup

    async def everyone_is_the_org_admin(request: Any) -> Any:
        return DEV_PRINCIPAL

    monkeypatch.setattr(access_module, "signed_in", everyone_is_the_org_admin)
    differences = await run_matrix(world, clients)
    for caller in ("anonymous", "no_access"):
        caught = {(d.op.method, d.op.path) for d in differences if d.caller == caller}
        assert caught == {(op.method, op.path) for op in OPS}, caller

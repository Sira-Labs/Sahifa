"""Invitations by link (spec 020)."""

from __future__ import annotations

import hashlib
import json
import uuid
from contextlib import AsyncExitStack
from typing import Any

import pytest
from httpx import AsyncClient

from .conftest import needs_db
from .tenancy import add_member, make_workspace, sql, user_id
from .test_auth_flow import ADMIN, ALLOWED, OTHER, PUBLIC, Env, browser, sign_in
from .test_auth_flow import env as env  # the fixture

pytestmark = [needs_db, pytest.mark.usefixtures("drops_workspaces")]

NEW = "new.person@example.org"


async def person(env: Env, stack: AsyncExitStack, email: str) -> AsyncClient:
    c = await stack.enter_async_context(browser(env.app))
    await sign_in(env, c, email=email)
    return c


def token_of(created: dict[str, Any]) -> str:
    link: str = created["link"]
    assert link.startswith(f"{PUBLIC}/invite#")
    return link.split("#", 1)[1]


async def invite(c: AsyncClient, workspace_id: str, email: str, role: str = "editor") -> dict[str, Any]:
    r = await c.post(f"/api/workspaces/{workspace_id}/invitations", json={"email": email, "role": role})
    assert r.status_code == 201, r.text
    created: dict[str, Any] = r.json()
    return created


async def test_invite_sign_in_and_land_in_the_workspace(env: Env) -> None:
    wid = make_workspace(env.owner, f"Finance {uuid.uuid4().hex[:6]}")
    async with AsyncExitStack() as stack:
        admin = await person(env, stack, ADMIN)
        created = await invite(admin, wid, NEW.upper(), "editor")
        assert created["email"] == NEW and created["status"] == "open" and created["role"] == "editor"
        token = token_of(created)
        newcomer = await person(env, stack, NEW)
        assert (await newcomer.get("/api/auth/me")).status_code == 403  # no workspace yet
        looked = await newcomer.post("/api/invitations/lookup", json={"token": token})
        assert looked.status_code == 200, looked.text
        assert looked.json()["workspace"]["id"] == wid and looked.json()["email"] == "n***@example.org"
        accepted = await newcomer.post("/api/invitations/accept", json={"token": token})
        assert accepted.status_code == 200, accepted.text
        assert accepted.json() == {
            "workspace": {"id": wid, "name": looked.json()["workspace"]["name"]},
            "role": "editor",
        }
        me = (await newcomer.get("/api/auth/me")).json()
        assert {w["id"]: w["role"] for w in me["workspaces"]} == {wid: "editor"}
        again = await newcomer.post("/api/invitations/accept", json={"token": token})
        assert again.status_code == 409 and again.json()["detail"] == "invitation_used"
        listed = (await admin.get(f"/api/workspaces/{wid}/invitations")).json()
        assert [i["status"] for i in listed] == ["accepted"] and "link" not in listed[0]
        actions = sql(env.owner, "SELECT action FROM audit_events WHERE workspace_id = :w ORDER BY at", w=wid)
        assert [a for (a,) in actions] == ["invitation.created", "invitation.accepted", "membership.added"]


async def test_invalid_tokens_look_the_same(env: Env) -> None:
    wid = make_workspace(env.owner)
    async with AsyncExitStack() as stack:
        admin = await person(env, stack, ADMIN)
        newcomer = await person(env, stack, NEW)
        expired = token_of(await invite(admin, wid, NEW))
        sql(
            env.owner,
            "UPDATE invitations SET expires_at = now() - interval '1 minute' WHERE email = :e",
            e=NEW,
        )
        revoked_row = await invite(admin, wid, "someone@example.org")
        assert (await admin.delete(f"/api/invitations/{revoked_row['id']}")).status_code == 204
        assert (await admin.delete(f"/api/invitations/{revoked_row['id']}")).status_code == 409
        answers = []
        for token in (expired, token_of(revoked_row), "x" * 43):
            for path in ("/api/invitations/lookup", "/api/invitations/accept"):
                r = await newcomer.post(path, json={"token": token})
                answers.append((r.status_code, r.json()["detail"]))
        assert set(answers) == {(404, "invitation_invalid")}


async def test_another_email_is_refused(env: Env) -> None:
    wid = make_workspace(env.owner)
    async with AsyncExitStack() as stack:
        admin = await person(env, stack, ADMIN)
        token = token_of(await invite(admin, wid, "bo@example.org"))
        other = await person(env, stack, OTHER)
        r = await other.post("/api/invitations/accept", json={"token": token})
        assert r.status_code == 403
        assert r.json()["detail"] == "invitation_other_email" and r.json()["email"] == "b***@example.org"
        assert sql(env.owner, "SELECT count(*) FROM memberships WHERE workspace_id = :w", w=wid) == [(0,)]


async def test_accepting_raises_a_role_and_never_lowers_one(env: Env) -> None:
    wid = make_workspace(env.owner)
    async with AsyncExitStack() as stack:
        admin = await person(env, stack, ADMIN)
        ana = await person(env, stack, ALLOWED)
        add_member(env.owner, wid, ALLOWED, "viewer")
        raised = await ana.post(
            "/api/invitations/accept", json={"token": token_of(await invite(admin, wid, ALLOWED, "editor"))}
        )
        assert raised.json()["role"] == "editor"
        add_member(env.owner, wid, ALLOWED, "admin")
        already = await admin.post(
            f"/api/workspaces/{wid}/invitations", json={"email": ALLOWED, "role": "viewer"}
        )
        assert already.status_code == 409 and already.json()["detail"] == "already_member"
        # An invitation made before the person became admin cannot lower them.
        sql(
            env.owner,
            "UPDATE memberships SET role = 'viewer' WHERE user_id = :u",
            u=user_id(env.owner, ALLOWED),
        )
        stale = token_of(await invite(admin, wid, ALLOWED, "editor"))
        add_member(env.owner, wid, ALLOWED, "admin")
        kept = await ana.post("/api/invitations/accept", json={"token": stale})
        assert kept.json()["role"] == "admin"


async def test_a_new_invitation_replaces_the_open_one(env: Env) -> None:
    wid = make_workspace(env.owner)
    async with AsyncExitStack() as stack:
        admin = await person(env, stack, ADMIN)
        first = token_of(await invite(admin, wid, NEW, "viewer"))
        second = token_of(await invite(admin, wid, NEW, "admin"))
        newcomer = await person(env, stack, NEW)
        assert (await newcomer.post("/api/invitations/accept", json={"token": first})).status_code == 404
        assert (await newcomer.post("/api/invitations/accept", json={"token": second})).json()[
            "role"
        ] == "admin"


async def test_only_admins_invite_and_see_their_workspaces(env: Env) -> None:
    mine, theirs = make_workspace(env.owner), make_workspace(env.owner)
    async with AsyncExitStack() as stack:
        admin = await person(env, stack, ADMIN)
        ana = await person(env, stack, ALLOWED)
        add_member(env.owner, mine, ALLOWED, "editor")
        r = await ana.post(f"/api/workspaces/{mine}/invitations", json={"email": NEW, "role": "viewer"})
        assert r.status_code == 403 and r.json()["needs"] == "admin"
        assert (await ana.get(f"/api/workspaces/{theirs}/invitations")).status_code == 404
        foreign = await invite(admin, theirs, NEW)
        add_member(env.owner, mine, ALLOWED, "admin")
        assert (await ana.delete(f"/api/invitations/{foreign['id']}")).status_code == 404
        bad = await ana.post(
            f"/api/workspaces/{mine}/invitations", json={"email": "not-an-address", "role": "viewer"}
        )
        assert bad.status_code == 422


async def test_no_token_is_stored_logged_or_shown_again(env: Env, capsys: pytest.CaptureFixture[str]) -> None:
    wid = make_workspace(env.owner)
    async with AsyncExitStack() as stack:
        admin = await person(env, stack, ADMIN)
        created = await invite(admin, wid, NEW)
        token = token_of(created)
        newcomer = await person(env, stack, NEW)
        await newcomer.post("/api/invitations/accept", json={"token": token})
        listed = (await admin.get(f"/api/workspaces/{wid}/invitations")).text
        audit = (await admin.get("/api/audit", params={"workspace_id": wid})).text
    stored = sql(env.owner, "SELECT token_hash FROM invitations WHERE id = :i", i=created["id"])[0][0]
    assert bytes(stored) == hashlib.sha256(token.encode()).digest()
    rows = json.dumps([list(map(str, r)) for r in sql(env.owner, "SELECT * FROM invitations")])
    entries = json.dumps([str(r) for r in sql(env.owner, "SELECT to_jsonb(a) FROM audit_events a")])
    logs = capsys.readouterr()
    for text in (rows, entries, listed, audit, logs.out, logs.err):
        assert token not in text


async def test_invitations_need_sign_in(env: Env) -> None:
    app = await env.make(auth_mode="dev")
    wid = make_workspace(env.owner)
    async with browser(app) as dev:
        r = await dev.post(f"/api/workspaces/{wid}/invitations", json={"email": NEW, "role": "viewer"})
        assert r.status_code == 409 and r.json()["detail"] == "sign_in_required"
        r = await dev.post("/api/invitations/accept", json={"token": "x" * 43})
        assert r.status_code == 409 and r.json()["detail"] == "sign_in_required"


async def test_lookup_and_accept_need_a_session(env: Env) -> None:
    async with browser(env.app) as anonymous:
        for path in ("/api/invitations/lookup", "/api/invitations/accept"):
            assert (await anonymous.post(path, json={"token": "x" * 43})).status_code == 401


def test_migration_0010_round_trips(env: Env) -> None:
    from alembic import command

    from sahifa.db.migrate import build_config, downgrade, upgrade

    from .conftest import DB_URL

    assert DB_URL
    downgrade(DB_URL, "0009")
    try:
        assert sql(env.owner, "SELECT to_regclass('invitations')") == [(None,)]
    finally:
        upgrade(DB_URL)
    assert sql(env.owner, "SELECT relforcerowsecurity FROM pg_class WHERE relname = 'invitations'") == [
        (True,)
    ]
    command.check(build_config(DB_URL))

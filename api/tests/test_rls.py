"""Row-level security on the workspace-owned tables (spec 016): through the API's own session
factories, so the role switch and the scope listener are what is tested."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError

from sahifa.db import WORKSPACES, Database
from sahifa.db.migrate import upgrade

from .conftest import DB_URL, needs_db, owner_engine
from .tenancy import TABLES, default_workspace, make_tree, make_workspace, sql, workspaces_of

pytestmark = [needs_db, pytest.mark.usefixtures("drops_workspaces")]


@pytest.fixture
def owner() -> Iterator[Engine]:
    assert DB_URL
    upgrade(DB_URL)
    engine = owner_engine()
    yield engine
    engine.dispose()


@pytest.fixture
async def db() -> AsyncIterator[Database]:
    assert DB_URL
    database = Database(DB_URL)
    yield database
    await database.dispose()


async def counts(db: Database, ids: tuple[str, str], **info: Any) -> dict[str, tuple[int, int]]:
    """Rows of workspaces A and B per table, as a session with `info` sees them."""
    out: dict[str, tuple[int, int]] = {}
    async with db.sessions() as s:
        s.info.update(info)
        for table in TABLES:
            row = (
                await s.execute(
                    text(
                        f"SELECT count(*) FILTER (WHERE workspace_id = :a),"
                        f" count(*) FILTER (WHERE workspace_id = :b) FROM {table}"
                    ),
                    {"a": ids[0], "b": ids[1]},
                )
            ).one()
            out[table] = (int(row[0]), int(row[1]))
    return out


async def test_rows_are_visible_per_workspace_and_fail_closed(owner: Engine, db: Database) -> None:
    a, b = make_workspace(owner), make_workspace(owner)
    make_tree(owner, a)
    make_tree(owner, b)
    assert await counts(db, (a, b)) == {t: (0, 0) for t in TABLES}
    async with db.sessions() as s:
        total = {t: (await s.execute(text(f"SELECT count(*) FROM {t}"))).scalar() for t in TABLES}
    assert total == {t: 0 for t in TABLES}
    assert await counts(db, (a, b), **{WORKSPACES: (a,)}) == {t: (1, 0) for t in TABLES}
    assert await counts(db, (a, b), **{WORKSPACES: (a, b)}) == {t: (1, 1) for t in TABLES}
    async with db.system() as s:
        seen = {
            t: (
                await s.execute(
                    text(f"SELECT count(*) FROM {t} WHERE workspace_id IN (:a, :b)"), {"a": a, "b": b}
                )
            ).scalar()
            for t in TABLES
        }
    assert seen == {t: 2 for t in TABLES}


async def test_scope_survives_a_commit_and_ends_with_the_session(owner: Engine, db: Database) -> None:
    a, b = make_workspace(owner), make_workspace(owner)
    make_tree(owner, a)
    make_tree(owner, b)
    async with db.sessions() as s:
        s.info[WORKSPACES] = (a,)
        assert (
            await s.execute(text("SELECT count(*) FROM connections WHERE workspace_id = :a"), {"a": a})
        ).scalar() == 1
        await s.commit()
        assert (
            await s.execute(text("SELECT count(*) FROM connections WHERE workspace_id = :a"), {"a": a})
        ).scalar() == 1
    # The pooled connection comes back without the previous transaction's scope.
    async with db.sessions() as s:
        assert (
            await s.execute(text("SELECT count(*) FROM connections WHERE workspace_id = :a"), {"a": a})
        ).scalar() == 0
        setting = (await s.execute(text("SELECT current_setting('sahifa.workspaces', true)"))).scalar()
        assert setting in ("", None)


async def test_writes_into_another_workspace_fail(owner: Engine, db: Database) -> None:
    a, b = make_workspace(owner), make_workspace(owner)
    tree_b = make_tree(owner, b)
    async with db.sessions() as s:
        s.info[WORKSPACES] = (a,)
        with pytest.raises(DBAPIError, match="row-level security"):
            await s.execute(
                text(
                    "INSERT INTO connections (id, name, kind, workspace_id)"
                    " VALUES (gen_random_uuid(), 'x', 'duckdb', :b)"
                ),
                {"b": b},
            )
    async with db.sessions() as s:
        s.info[WORKSPACES] = (a,)
        # The parent is invisible, so the trigger finds no workspace: the policy (checked before
        # NOT NULL) refuses the row.
        with pytest.raises(DBAPIError, match=r"row-level security|workspace_id"):
            await s.execute(
                text("INSERT INTO scans (id, connection_id, sample_rows) VALUES (gen_random_uuid(), :c, 0)"),
                {"c": tree_b["connection"]},
            )
    async with db.sessions() as s:
        s.info[WORKSPACES] = (a,)
        moved = await s.execute(
            text("UPDATE connections SET workspace_id = :a WHERE id = :c"),
            {"a": a, "c": tree_b["connection"]},
        )
        assert moved.rowcount == 0  # type: ignore[attr-defined]


async def test_triggers_fill_the_workspace_from_the_parent(owner: Engine) -> None:
    a = make_workspace(owner)
    tree = make_tree(owner, a)
    assert workspaces_of(owner, tree["connection"]) == {t: {a} for t in TABLES}


def test_migration_0008_puts_existing_rows_in_default_and_round_trips(owner: Engine) -> None:
    from alembic import command

    from sahifa.db.migrate import build_config, downgrade

    assert DB_URL
    cid, sid, aid = (str(uuid.uuid4()) for _ in range(3))
    downgrade(DB_URL, "0007")
    try:
        assert sql(owner, "SELECT to_regclass('workspaces'), to_regclass('memberships')") == [(None, None)]
        sql(owner, "INSERT INTO connections (id, name, kind) VALUES (:c, :n, 'duckdb')", c=cid, n=f"m-{cid}")
        sql(
            owner,
            "INSERT INTO scans (id, connection_id, sample_rows, status) VALUES (:s, :c, 0, 'succeeded')",
            s=sid,
            c=cid,
        )
        sql(
            owner,
            "INSERT INTO assets (id, connection_id, namespace, name, kind) VALUES (:a, :c, '', 't', 'table')",
            a=aid,
            c=cid,
        )
    finally:
        upgrade(DB_URL)
    default = default_workspace(owner)
    assert sql(owner, "SELECT name, is_default FROM workspaces") == [("Default", True)]
    assert sql(owner, "SELECT count(*) FROM organisations") == [(1,)]
    placed = workspaces_of(owner, cid)
    assert placed["connections"] == placed["scans"] == placed["assets"] == {default}
    command.check(build_config(DB_URL))
    downgrade(DB_URL, "0007")
    try:
        assert sql(owner, "SELECT count(*) FROM connections WHERE id = :c", c=cid) == [(1,)]
    finally:
        upgrade(DB_URL)
    assert workspaces_of(owner, cid)["assets"] == {default_workspace(owner)}


class _Bypassing:
    """A database whose login would bypass row-level security."""

    async def bypasses_rls(self) -> bool:
        return True


async def test_prod_refuses_a_login_that_bypasses_rls(tmp_path: Path) -> None:
    from sahifa.main import EXIT_RLS, check_rls
    from sahifa.settings import Settings

    with pytest.raises(SystemExit) as stopped:
        await check_rls(_Bypassing(), Settings(env="prod", data_dir=tmp_path))  # type: ignore[arg-type]
    assert stopped.value.code == EXIT_RLS
    await check_rls(_Bypassing(), Settings(env="dev", data_dir=tmp_path))  # type: ignore[arg-type]


async def test_the_test_login_is_bound_by_rls(db: Database) -> None:
    assert await db.bypasses_rls() is False


async def test_an_app_role_with_bypassrls_is_reported(owner: Engine, db: Database) -> None:
    """Switching to `sahifa_app` does not help when someone gave it BYPASSRLS."""
    can = sql(
        owner,
        "SELECT r.rolsuper AND pg_has_role(current_user, 'sahifa_app', 'MEMBER')"
        " FROM pg_roles r WHERE r.rolname = current_user AND EXISTS"
        " (SELECT 1 FROM pg_roles WHERE rolname = 'sahifa_app')",
    )
    if not (can and can[0][0]):
        pytest.skip("needs a superuser test login that can switch to sahifa_app")
    sql(owner, "ALTER ROLE sahifa_app BYPASSRLS")
    try:
        assert await db.bypasses_rls() is True
    finally:
        sql(owner, "ALTER ROLE sahifa_app NOBYPASSRLS")

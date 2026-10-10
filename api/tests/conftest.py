from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Engine, create_engine, text

from sahifa.db.migrate import upgrade
from sahifa.main import create_app
from sahifa.settings import Settings

DB_URL = os.environ.get("SAHIFA_TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DB_URL, reason="SAHIFA_TEST_DATABASE_URL not set")
# What the web app sends on every request; unsafe requests without it get 403 (spec 006).
CSRF = {"X-Sahifa-Request": "1"}
DEFAULT_WORKSPACE = "(SELECT id FROM workspaces WHERE is_default)"


def owner_engine() -> Engine:
    """The tests' own engine for direct SQL: autocommit, and every workspace visible under
    row-level security (spec 016), as for the API's jobs."""
    assert DB_URL
    return create_engine(
        DB_URL, isolation_level="AUTOCOMMIT", connect_args={"options": "-c sahifa.system=on"}
    )


def drop_workspaces(engine: Engine) -> None:
    """Delete every workspace but the default one, with its connections and their rows (which
    cascade), so tests that assume one workspace keep it."""
    with engine.connect() as conn:
        others = "SELECT id FROM workspaces WHERE NOT is_default"
        conn.execute(text(f"DELETE FROM connections WHERE workspace_id IN ({others})"))
        conn.execute(text("DELETE FROM workspaces WHERE NOT is_default"))


@pytest.fixture(scope="session", autouse=True)
def one_workspace_at_start() -> None:
    """Workspaces left by an interrupted run would make every create and upload name one."""
    if DB_URL:
        upgrade(DB_URL)
        engine = owner_engine()
        drop_workspaces(engine)
        engine.dispose()


@pytest.fixture
def drops_workspaces() -> Iterator[None]:
    """For tests that create workspaces: none of them outlives the test."""
    assert DB_URL
    upgrade(DB_URL)
    engine = owner_engine()
    drop_workspaces(engine)
    try:
        yield
    finally:
        drop_workspaces(engine)
        engine.dispose()


@pytest.fixture
async def client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    assert DB_URL
    upgrade(DB_URL)
    app = create_app(Settings(database_url=DB_URL, data_dir=tmp_path, commit="test"))
    async with (
        LifespanManager(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://t", headers=CSRF) as c,
    ):
        yield c

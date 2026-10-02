from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from sahifa.db.migrate import upgrade
from sahifa.main import create_app
from sahifa.settings import Settings

DB_URL = os.environ.get("SAHIFA_TEST_DATABASE_URL")
needs_db = pytest.mark.skipif(not DB_URL, reason="SAHIFA_TEST_DATABASE_URL not set")


@pytest.fixture
async def client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    assert DB_URL
    upgrade(DB_URL)
    app = create_app(Settings(database_url=DB_URL, data_dir=tmp_path, commit="test"))
    async with LifespanManager(app), AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c

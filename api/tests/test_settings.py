from __future__ import annotations

import pytest

from sahifa.settings import Settings, prod_problems

STRONG = "postgresql+psycopg://sahifa:3f9a1c0d8e7b6a5f4e3d2c1b@db:5432/sahifa"


def test_dev_has_no_problems() -> None:
    assert prod_problems(Settings(env="dev")) == []


def test_prod_refuses_placeholder_password() -> None:
    problems = prod_problems(
        Settings(
            env="prod",
            database_url="postgresql+psycopg://sahifa:sahifa@db/sahifa",
            access_gate="basic-auth-at-proxy",
        )
    )
    assert any("SAHIFA_DATABASE_URL" in p for p in problems)


def test_prod_needs_access_gate() -> None:
    assert any("SAHIFA_ACCESS_GATE" in p for p in prod_problems(Settings(env="prod", database_url=STRONG)))


def test_prod_refuses_placeholder_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SAHIFA_CONN_SHOP", "postgresql://reader:secret@db/shop")
    problems = prod_problems(Settings(env="prod", database_url=STRONG, access_gate="basic-auth-at-proxy"))
    assert problems == ["SAHIFA_CONN_SHOP (missing, short or placeholder password)"]


def test_prod_ok() -> None:
    assert prod_problems(Settings(env="prod", database_url=STRONG, access_gate="basic-auth-at-proxy")) == []

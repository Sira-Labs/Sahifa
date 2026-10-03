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


OIDC = {
    "public_url": "https://sahifa.example.org",
    "oidc_issuer": "https://kc.example.org/realms/sahifa",
    "oidc_client_secret": "9c1f0e7d6b5a4c3b2a1f0e9d8c7b6a5f",
    "session_secret": "4f3e2d1c0b9a8f7e6d5c4b3a2f1e0d9c8b7a6f5e",
    "admin_email": "owner@example.org",
}


def test_auth_mode_defaults() -> None:
    """dev outside prod; in prod oidc, or proxy when the basic-auth gate is declared."""
    assert Settings(env="dev").resolved_auth_mode == "dev"
    assert Settings(env="prod").resolved_auth_mode == "oidc"
    assert Settings(env="prod", access_gate="basic-auth-at-proxy").resolved_auth_mode == "proxy"
    assert (
        Settings(env="prod", auth_mode="oidc", access_gate="basic-auth-at-proxy").resolved_auth_mode == "oidc"
    )


def test_prod_oidc_ok() -> None:
    assert prod_problems(Settings(env="prod", database_url=STRONG, **OIDC)) == []
    assert prod_problems(Settings(env="prod", database_url=STRONG, auth_mode="oidc", **OIDC)) == []


def test_prod_refuses_dev_mode() -> None:
    problems = prod_problems(
        Settings(env="prod", database_url=STRONG, auth_mode="dev", access_gate="basic-auth-at-proxy")
    )
    assert problems == ["SAHIFA_AUTH_MODE (dev is not allowed in prod: use oidc, or proxy behind basic auth)"]


def test_prod_proxy_needs_the_gate() -> None:
    problems = prod_problems(Settings(env="prod", database_url=STRONG, auth_mode="proxy"))
    assert len(problems) == 1 and problems[0].startswith("SAHIFA_ACCESS_GATE")
    explicit = Settings(env="prod", database_url=STRONG, auth_mode="proxy", access_gate="basic-auth-at-proxy")
    assert prod_problems(explicit) == []


@pytest.mark.parametrize(
    ("field", "value", "named"),
    [
        ("public_url", None, "SAHIFA_PUBLIC_URL"),
        ("public_url", "http://sahifa.example.org", "SAHIFA_PUBLIC_URL"),
        ("public_url", "https://sahifa.example.org/app", "SAHIFA_PUBLIC_URL"),
        ("oidc_issuer", None, "SAHIFA_OIDC_ISSUER"),
        ("oidc_issuer", "http://kc.example.org/realms/sahifa", "SAHIFA_OIDC_ISSUER"),
        ("oidc_client_secret", None, "SAHIFA_OIDC_CLIENT_SECRET"),
        ("oidc_client_secret", "change-me-change-me-change-me", "SAHIFA_OIDC_CLIENT_SECRET"),
        ("session_secret", None, "SAHIFA_SESSION_SECRET"),
        ("session_secret", "too-short-0123456789", "SAHIFA_SESSION_SECRET"),
        ("session_secret", "placeholder-placeholder-placeholder-x", "SAHIFA_SESSION_SECRET"),
        ("admin_email", None, "SAHIFA_ADMIN_EMAIL"),
        ("admin_email", "", "SAHIFA_ADMIN_EMAIL"),
    ],
)
def test_prod_oidc_refuses_missing_or_placeholder(field: str, value: str | None, named: str) -> None:
    settings = Settings(env="prod", database_url=STRONG, auth_mode="oidc", **(OIDC | {field: value}))
    problems = prod_problems(settings)
    assert [p for p in problems if p.startswith(named)], problems
    assert len(problems) == 1


def test_prod_default_oidc_names_the_basic_auth_alternative() -> None:
    problems = prod_problems(Settings(env="prod", database_url=STRONG))
    assert any(p.startswith("SAHIFA_OIDC_ISSUER") for p in problems)
    assert any(p.startswith("SAHIFA_ACCESS_GATE") for p in problems)


def test_access_follows_admin_and_allowed_emails() -> None:
    s = Settings(admin_email="Owner@Example.org", allowed_emails=" ana@example.org, ,BO@example.org ")
    assert s.access_emails == {"owner@example.org", "ana@example.org", "bo@example.org"}
    assert s.has_access("OWNER@example.org") and s.has_access("bo@example.org")
    assert not s.has_access("eve@example.org") and not s.has_access(None) and not s.has_access("")
    assert s.is_admin("owner@example.org") and not s.is_admin("ana@example.org")
    assert not Settings().has_access("owner@example.org")


def test_durations_and_methods() -> None:
    from datetime import timedelta

    s = Settings(session_idle="30m", session_absolute="7d", sign_in_methods="passkey, google,passkey")
    assert s.session_idle == timedelta(minutes=30) and s.session_absolute == timedelta(days=7)
    assert s.enabled_sign_in_methods == ("passkey", "google")
    with pytest.raises(ValueError, match="sign_in_methods"):
        Settings(sign_in_methods="password")


def test_empty_variables_are_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """A .env file with `SAHIFA_AUTH_MODE=` and empty OIDC rows behaves as if they were absent."""
    for name in ("AUTH_MODE", "OIDC_ISSUER", "OIDC_CLIENT_SECRET", "SESSION_SECRET", "ADMIN_EMAIL"):
        monkeypatch.setenv(f"SAHIFA_{name}", "")
    s = Settings(env="prod", database_url=STRONG, access_gate="basic-auth-at-proxy")
    assert s.auth_mode is None and s.oidc_issuer is None and s.session_secret is None
    assert s.resolved_auth_mode == "proxy" and prod_problems(s) == []


def test_scan_workers_reach_the_core(monkeypatch: pytest.MonkeyPatch, tmp_path: object) -> None:
    """`SAHIFA_SCAN_WORKERS` sets the core's parallel sessions (spec 013)."""
    import uuid

    import sahifa_core.scan as core_scan

    from sahifa.services import scans

    seen = {}

    class Report:
        def model_dump(self, mode: str) -> dict[str, object]:
            return {}

    def fake_run_scan(source: object, options: core_scan.ScanOptions, **_: object) -> Report:
        seen["workers"] = options.workers
        return Report()

    monkeypatch.setattr(core_scan, "run_scan", fake_run_scan)
    monkeypatch.setenv("SAHIFA_SCAN_WORKERS", "3")
    scans._execute("postgresql://x/y", None, uuid.uuid4(), 100, Settings())
    assert seen == {"workers": 3}
    assert Settings().scan_workers == 3
    monkeypatch.delenv("SAHIFA_SCAN_WORKERS")
    assert Settings().scan_workers == 2
    with pytest.raises(ValueError):
        Settings(scan_workers=0)

"""Configuration from `SAHIFA_*` environment variables (specs 004 and 006).

No secret has a default. In `prod` the API refuses to start with placeholder passwords, with a
source connection whose password is a placeholder, and without a way to keep strangers out:
either the OIDC sign-in (spec 006, ADR-0010) or HTTP basic auth at the proxy.
"""

from __future__ import annotations

import os
import re
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_PASSWORDS = frozenset(
    {"sahifa", "changeme", "change-me", "password", "postgres", "secret", "example", "admin", "test"}
)
CONNECTION_PREFIX = "SAHIFA_CONN_"
ACCESS_GATES = ("basic-auth-at-proxy",)
SIGN_IN_METHODS = ("google", "github", "passkey")
AuthMode = Literal["oidc", "dev", "proxy"]
ScanExecution = Literal["inline", "queue"]
SESSION_SECRET_MIN = 32
CLIENT_SECRET_MIN = 16


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SAHIFA_", env_file=".env", extra="ignore")

    env: Literal["dev", "prod"] = "dev"
    role: Literal["api", "worker"] = "api"
    database_url: str = "postgresql+psycopg://sahifa:sahifa@localhost:5432/sahifa"
    migration_database_url: str | None = None
    data_dir: Path = Path("./data")
    public_url: str | None = None
    access_gate: str | None = None
    sample_rows: int = Field(default=100_000, ge=0)
    max_upload_mb: int = Field(default=200, ge=1)
    max_upload_files: int = Field(default=20, ge=1)
    # Spec 012: the whole upload request, all files together, and the free disk it must leave.
    max_upload_total_mb: int = Field(default=1024, ge=1)
    min_free_disk_mb: int = Field(default=1024, ge=0)
    # Spec 012: token buckets per session or address; `rate_scans_per_hour` per user.
    rate_limits: bool = True
    rate_scans_per_hour: int = Field(default=60, ge=1)
    # Spec 012: `/api/docs` and `/api/openapi.json`; unset means on outside prod.
    api_docs: bool | None = None
    # Spec 008: `inline` runs scans in a thread of the api, `queue` defers them to the worker.
    scan_execution: ScanExecution = "inline"
    upload_ttl_days: int = Field(default=7, ge=1)
    max_concurrent_scans: int = Field(default=2, ge=1)
    reaper_stale_minutes: int = Field(default=10, ge=1)
    # Spec 010: a schedule whose runs come closer than this is refused.
    schedule_min_interval_minutes: int = Field(default=60, ge=1)
    duckdb_memory: str = "1GB"
    # Spec 013: Postgres sessions one scan uses to scan assets at once.
    scan_workers: int = Field(default=2, ge=1, le=8)
    statement_timeout_s: int = Field(default=60, ge=1)
    log_level: str = "info"
    commit: str = "unknown"

    # Sign-in (spec 006). Unset `auth_mode` resolves to oidc in prod (proxy when the basic-auth
    # gate is declared) and dev elsewhere; see `resolved_auth_mode`.
    auth_mode: AuthMode | None = None
    oidc_issuer: str | None = None
    oidc_client_id: str = "sahifa-api"
    oidc_client_secret: SecretStr | None = None
    session_secret: SecretStr | None = None
    admin_email: str | None = None
    allowed_emails: str = ""
    sign_in_methods: str = ",".join(SIGN_IN_METHODS)
    session_idle: timedelta = timedelta(hours=12)
    session_absolute: timedelta = timedelta(days=30)

    @field_validator(
        "auth_mode", "oidc_issuer", "oidc_client_secret", "session_secret", "admin_email", mode="before"
    )
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        """An empty variable (`SAHIFA_AUTH_MODE=` in a .env file) means unset."""
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("session_idle", "session_absolute", mode="before")
    @classmethod
    def _duration(cls, value: object) -> object:
        """Accept `30s`, `15m`, `12h` and `30d` besides pydantic's own duration forms."""
        if isinstance(value, str) and (m := re.fullmatch(r"\s*(\d+)\s*([smhd])\s*", value)):
            unit = {"s": "seconds", "m": "minutes", "h": "hours", "d": "days"}[m.group(2)]
            return timedelta(**{unit: int(m.group(1))})
        return value

    @field_validator("sign_in_methods")
    @classmethod
    def _methods(cls, value: str) -> str:
        """Only known methods, at least one, without duplicates."""
        methods = [m.strip().lower() for m in value.split(",") if m.strip()]
        unknown = sorted(set(methods) - set(SIGN_IN_METHODS))
        if unknown or not methods:
            raise ValueError(f"sign_in_methods must name some of {', '.join(SIGN_IN_METHODS)}; got {value!r}")
        return ",".join(dict.fromkeys(methods))

    @property
    def resolved_auth_mode(self) -> AuthMode:
        """The auth mode in force: the setting; unset, `oidc` in prod (or `proxy` when the
        basic-auth gate is declared, so installs from before spec 006 keep starting) and `dev`
        elsewhere."""
        if self.auth_mode is not None:
            return self.auth_mode
        if self.env != "prod":
            return "dev"
        return "proxy" if self.access_gate in ACCESS_GATES else "oidc"

    @property
    def enabled_sign_in_methods(self) -> tuple[str, ...]:
        """The sign-in methods the login page offers, in the configured order."""
        return tuple(self.sign_in_methods.split(","))

    @property
    def access_emails(self) -> frozenset[str]:
        """Lower-cased addresses that get access: the admin email and the allowed emails."""
        listed = [self.admin_email or "", *self.allowed_emails.split(",")]
        return frozenset(e.strip().lower() for e in listed if e.strip())

    def is_admin(self, email: str | None) -> bool:
        """Whether `email` is the configured admin address."""
        return bool(email and self.admin_email and email.strip().lower() == self.admin_email.strip().lower())

    def has_access(self, email: str | None) -> bool:
        """Whether a signed-in `email` may use this install (spec 006, behaviour 4)."""
        return bool(email) and (email or "").strip().lower() in self.access_emails

    @property
    def migration_url(self) -> str:
        return self.migration_database_url or self.database_url

    @property
    def docs_enabled(self) -> bool:
        """Whether the API docs are served: `api_docs`, or on outside prod when unset."""
        return self.api_docs if self.api_docs is not None else self.env != "prod"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"


def connection_env() -> dict[str, str]:
    """Every `SAHIFA_CONN_<NAME>` variable, keyed by the variable name, empty ones skipped."""
    return {k: v for k, v in os.environ.items() if k.startswith(CONNECTION_PREFIX) and v.strip()}


def _placeholder_password(url: str) -> bool:
    try:
        password = urlsplit(url).password
    except ValueError:
        return True
    return not password or password.lower() in PLACEHOLDER_PASSWORDS or len(password) < 12


def _placeholder_secret(value: str | None, minimum: int) -> bool:
    """True for an empty, short or change-me style secret."""
    text = (value or "").strip()
    lowered = text.lower()
    return (
        len(text) < minimum
        or lowered in PLACEHOLDER_PASSWORDS
        or any(word in lowered for word in ("change-me", "changeme", "change_me", "placeholder"))
    )


def _oidc_problems(settings: Settings) -> list[str]:
    """Settings the OIDC sign-in needs in prod (spec 006)."""
    problems: list[str] = []
    url = urlsplit(settings.public_url or "")
    if url.scheme != "https" or not url.netloc or url.path not in ("", "/"):
        problems.append("SAHIFA_PUBLIC_URL (an https origin without a path)")
    if not (settings.oidc_issuer or "").startswith("https://"):
        problems.append("SAHIFA_OIDC_ISSUER (the realm's https URL)")
    secret = settings.oidc_client_secret.get_secret_value() if settings.oidc_client_secret else None
    if _placeholder_secret(secret, CLIENT_SECRET_MIN):
        problems.append("SAHIFA_OIDC_CLIENT_SECRET (missing, short or placeholder)")
    session = settings.session_secret.get_secret_value() if settings.session_secret else None
    if _placeholder_secret(session, SESSION_SECRET_MIN):
        problems.append(f"SAHIFA_SESSION_SECRET (missing, placeholder or under {SESSION_SECRET_MIN} chars)")
    if "@" not in (settings.admin_email or ""):
        problems.append("SAHIFA_ADMIN_EMAIL (the address that gets access)")
    return problems


def _auth_problems(settings: Settings) -> list[str]:
    """How prod keeps strangers out: the OIDC sign-in, or basic auth at the proxy (spec 006)."""
    mode = settings.resolved_auth_mode
    if mode == "dev":
        return ["SAHIFA_AUTH_MODE (dev is not allowed in prod: use oidc, or proxy behind basic auth)"]
    if mode == "proxy":
        if settings.access_gate not in ACCESS_GATES:
            return ["SAHIFA_ACCESS_GATE (proxy mode needs basic-auth-at-proxy, set once basic auth is on)"]
        return []
    problems = _oidc_problems(settings)
    if problems and settings.auth_mode is None:
        problems.append("SAHIFA_ACCESS_GATE (or, without sign-in, basic-auth-at-proxy once basic auth is on)")
    return problems


def prod_problems(settings: Settings) -> list[str]:
    """Reasons the settings are unsafe for production; empty when they are fine."""
    if settings.env != "prod":
        return []
    problems = []
    if _placeholder_password(settings.database_url):
        problems.append("SAHIFA_DATABASE_URL (missing, short or placeholder password)")
    if settings.migration_database_url and _placeholder_password(settings.migration_database_url):
        problems.append("SAHIFA_MIGRATION_DATABASE_URL (missing, short or placeholder password)")
    problems += _auth_problems(settings)
    for name, url in connection_env().items():
        if url.startswith(("postgres://", "postgresql://")) and _placeholder_password(url):
            problems.append(f"{name} (missing, short or placeholder password)")
    return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()

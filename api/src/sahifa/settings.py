"""Configuration from `SAHIFA_*` environment variables (spec 004).

No secret has a default. In `prod` the API refuses to start with placeholder passwords, without
an access gate (ADR-0010) or with a source connection whose password is a placeholder.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_PASSWORDS = frozenset(
    {"sahifa", "changeme", "change-me", "password", "postgres", "secret", "example", "admin", "test"}
)
CONNECTION_PREFIX = "SAHIFA_CONN_"
ACCESS_GATES = ("basic-auth-at-proxy",)


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
    upload_ttl_days: int = Field(default=7, ge=1)
    max_concurrent_scans: int = Field(default=2, ge=1)
    duckdb_memory: str = "1GB"
    statement_timeout_s: int = Field(default=60, ge=1)
    log_level: str = "info"
    commit: str = "unknown"

    @property
    def migration_url(self) -> str:
        return self.migration_database_url or self.database_url

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


def prod_problems(settings: Settings) -> list[str]:
    """Reasons the settings are unsafe for production; empty when they are fine."""
    if settings.env != "prod":
        return []
    problems = []
    if _placeholder_password(settings.database_url):
        problems.append("SAHIFA_DATABASE_URL (missing, short or placeholder password)")
    if settings.migration_database_url and _placeholder_password(settings.migration_database_url):
        problems.append("SAHIFA_MIGRATION_DATABASE_URL (missing, short or placeholder password)")
    if settings.access_gate not in ACCESS_GATES:
        problems.append("SAHIFA_ACCESS_GATE (set it to basic-auth-at-proxy after enabling basic auth)")
    for name, url in connection_env().items():
        if url.startswith(("postgres://", "postgresql://")) and _placeholder_password(url):
            problems.append(f"{name} (missing, short or placeholder password)")
    return problems


@lru_cache
def get_settings() -> Settings:
    return Settings()

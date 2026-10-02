"""Response and request models of the HTTP API (spec 004)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ConnectionOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    config: dict[str, Any]
    secret_ref: str | None
    available: bool
    created_at: datetime


class ConnectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._-]*$")
    kind: Literal["postgres", "duckdb"]
    secret_ref: str = Field(min_length=13, max_length=200)
    config: dict[str, Any] = Field(default_factory=dict)


class ConnectionTest(BaseModel):
    ok: bool
    assets: int
    error: str | None = None


class ScanScore(BaseModel):
    overall: float | None
    low: float | None
    high: float | None


class ScanOut(BaseModel):
    id: uuid.UUID
    connection_id: uuid.UUID
    connection_name: str
    connection_kind: str
    status: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None
    sample_rows: int
    score: ScanScore | None
    findings: dict[str, int]
    assets_count: int | None
    files: list[str] | None = None


class ScanIn(BaseModel):
    connection_id: uuid.UUID
    assets: list[str] | None = None
    sample_rows: int | None = Field(default=None, ge=0)


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None


class Items(BaseModel, Generic[T]):
    items: list[T]

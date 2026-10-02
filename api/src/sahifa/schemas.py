"""Response and request models of the HTTP API (specs 004 and 007)."""

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


class CheckCounts(BaseModel):
    proposed: int = 0
    active: int = 0
    locked: int = 0
    retired: int = 0


class ColumnOut(BaseModel):
    name: str
    position: int
    physical_type: str
    logical_type: str
    semantic_type: str | None
    role: str


class AssetOut(BaseModel):
    id: uuid.UUID
    connection_id: uuid.UUID
    namespace: str
    name: str
    label: str
    kind: str
    row_count: int | None
    last_scan_id: uuid.UUID | None
    checks: CheckCounts


class AssetDetail(AssetOut):
    columns: list[ColumnOut]


class CheckOut(BaseModel):
    id: uuid.UUID
    key: str
    type: str
    title: str
    column: str | None
    columns: list[str]
    params: dict[str, Any]
    dimension: str
    severity: str
    kind: str
    origin: str
    status: str
    max_fail_ratio: float
    version: int
    updated_at: datetime
    last_scan_id: uuid.UUID | None


class CheckActionIn(BaseModel):
    version: int = Field(ge=1)


class CheckEventOut(BaseModel):
    at: datetime
    actor: str
    action: str
    from_status: str | None
    to_status: str
    params_before: dict[str, Any] | None
    params_after: dict[str, Any] | None

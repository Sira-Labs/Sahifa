"""Response and request models of the HTTP API (specs 004, 007, 009, 010, 011 and 016)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")
ROLE_PATTERN = r"^(viewer|editor|admin)$"


class WorkspaceRef(BaseModel):
    id: uuid.UUID
    name: str


class InWorkspace(BaseModel):
    """What every workspace-owned object carries (spec 016): its workspace and the caller's
    role there, so the web app can disable what the role does not allow."""

    workspace: WorkspaceRef | None = None
    role: str | None = None


class ScheduleSummary(BaseModel):
    """A connection's schedule in the connections list (spec 010)."""

    cron: str
    timezone: str
    enabled: bool
    next_run_at: datetime | None


class ConnectionOut(InWorkspace):
    id: uuid.UUID
    name: str
    kind: str
    config: dict[str, Any]
    secret_ref: str | None
    available: bool
    created_at: datetime
    schedule: ScheduleSummary | None = None


class ScheduleIn(BaseModel):
    """`PUT /api/connections/{id}/schedule`; `version` is required once a schedule exists."""

    cron: str = Field(min_length=1, max_length=200)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    enabled: bool = True
    sample_rows: int | None = Field(default=None, ge=0)
    version: int | None = Field(default=None, ge=1)


class ScheduleOut(InWorkspace):
    cron: str
    timezone: str
    enabled: bool
    sample_rows: int | None
    next_run_at: datetime | None
    # The stored next run, then the two after it (UTC); empty while disabled.
    next_runs: list[datetime]
    last_run_at: datetime | None
    last_scan_id: uuid.UUID | None
    last_outcome: str | None
    version: int
    updated_at: datetime
    updated_by: str


class ConnectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9 ._-]*$")
    kind: Literal["postgres", "duckdb"]
    secret_ref: str = Field(min_length=13, max_length=200)
    config: dict[str, Any] = Field(default_factory=dict)
    # Spec 016: required when the caller is admin of several workspaces.
    workspace_id: uuid.UUID | None = None


class ConnectionTest(BaseModel):
    ok: bool
    assets: int
    error: str | None = None


class ScanScore(BaseModel):
    overall: float | None
    low: float | None
    high: float | None


class ScanOut(InWorkspace):
    id: uuid.UUID
    connection_id: uuid.UUID
    connection_name: str
    connection_kind: str
    status: str
    # `manual` or `schedule` (spec 010).
    trigger: str
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


class AssetOut(InWorkspace):
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


class CheckOut(InWorkspace):
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


class FindingCheck(BaseModel):
    id: uuid.UUID
    key: str
    type: str
    title: str
    status: str
    column: str | None


class FindingAsset(BaseModel):
    id: uuid.UUID
    label: str
    connection_id: uuid.UUID


class FindingLatest(BaseModel):
    """The finding's most recent occurrence."""

    scan_id: uuid.UUID
    summary: str
    failed: int
    evaluated: int
    ratio: float
    low: float
    high: float
    dimension: str


class FindingOut(InWorkspace):
    id: uuid.UUID
    status: str
    severity: str
    occurrences: int
    first_seen_at: datetime
    last_seen_at: datetime
    muted_until: datetime | None
    version: int
    check: FindingCheck
    asset: FindingAsset
    latest: FindingLatest | None


class OccurrenceOut(BaseModel):
    scan_id: uuid.UUID
    at: datetime
    failed: int
    evaluated: int
    ratio: float
    low: float
    high: float
    summary: str
    examples: list[dict[str, Any]]
    sql: str | None
    next_step: str


class FindingEventOut(BaseModel):
    at: datetime
    actor: str
    action: str
    from_status: str | None
    to_status: str
    note: str | None


class FindingDetail(FindingOut):
    occurrences_list: list[OccurrenceOut]
    events: list[FindingEventOut]


class FindingActionIn(BaseModel):
    version: int = Field(ge=1)
    # Plain text, stored as is and rendered as text; the table enforces the same limit.
    note: str | None = Field(default=None, max_length=1000)
    until: datetime | None = None


class HistoryPoint(BaseModel):
    """One successful scan's score at one level (spec 011)."""

    scan_id: uuid.UUID
    finished_at: datetime
    # `manual` or `schedule` (spec 010).
    trigger: str
    overall: float | None
    low: float | None
    high: float | None
    checks: int
    dimensions: dict[str, Any]


class History(BaseModel):
    points: list[HistoryPoint]


class WorkspaceOut(BaseModel):
    """A workspace with the caller's role and its size (spec 016)."""

    id: uuid.UUID
    name: str
    role: str
    is_default: bool
    connections: int
    members: int
    created_at: datetime


class WorkspaceIn(BaseModel):
    name: str = Field(min_length=1, max_length=100, pattern=r"^\S(.*\S)?$")


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str
    display_name: str
    role: str
    last_login_at: datetime | None


class MemberIn(BaseModel):
    role: str = Field(pattern=ROLE_PATTERN)


class UserMatch(BaseModel):
    """A person who has signed in, to add as a member."""

    id: uuid.UUID
    email: str
    display_name: str


class MoveIn(BaseModel):
    workspace_id: uuid.UUID


class AuditEntry(BaseModel):
    """One change a person made (spec 018)."""

    id: uuid.UUID
    at: datetime
    workspace: WorkspaceRef
    actor: str
    action: str
    object_type: str
    object_id: uuid.UUID
    summary: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None

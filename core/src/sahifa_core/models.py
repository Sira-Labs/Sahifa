"""Data structures shared by profiling, checks, scoring and the report.

Names follow docs/architecture/02-domain-model.md. Everything here is a Pydantic model so the
report survives a JSON round trip unchanged (spec 003) and the API can store it as jsonb.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

# 2: `ScanReport.checks` and `AssetReport.unevaluated` (spec 007); version 1 reports still load.
REPORT_VERSION = 2


class LogicalType(StrEnum):
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    TEXT = "text"
    DATE = "date"
    TIMESTAMP = "timestamp"
    JSON = "json"
    BINARY = "binary"
    OTHER = "other"

    @property
    def is_numeric(self) -> bool:
        return self in (LogicalType.INTEGER, LogicalType.DECIMAL)

    @property
    def is_temporal(self) -> bool:
        return self in (LogicalType.DATE, LogicalType.TIMESTAMP)

    @property
    def is_scalar(self) -> bool:
        return self not in (LogicalType.JSON, LogicalType.BINARY, LogicalType.OTHER)


class Role(StrEnum):
    KEY = "key"
    FOREIGN_KEY = "foreign_key"
    TIMESTAMP = "timestamp"
    MEASURE = "measure"
    DESCRIPTION = "description"
    ATTRIBUTE = "attribute"


class Dimension(StrEnum):
    COMPLETENESS = "completeness"
    VALIDITY = "validity"
    ACCURACY = "accuracy"
    CONSISTENCY = "consistency"
    UNIQUENESS = "uniqueness"
    CURRENTNESS = "currentness"


# ISO/IEC 25012 characteristic each reported dimension maps to (domain model).
ISO_25012: dict[Dimension, str] = {
    Dimension.COMPLETENESS: "completeness",
    Dimension.VALIDITY: "accuracy (syntactic), compliance",
    Dimension.ACCURACY: "accuracy (semantic)",
    Dimension.CONSISTENCY: "consistency",
    Dimension.UNIQUENESS: "consistency (no duplicate records)",
    Dimension.CURRENTNESS: "currentness",
}


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def weight(self) -> float:
        return SEVERITY_WEIGHT[self]


SEVERITY_WEIGHT: dict[Severity, float] = {
    Severity.CRITICAL: 1.0,
    Severity.HIGH: 0.6,
    Severity.MEDIUM: 0.3,
    Severity.LOW: 0.1,
}


class CheckStatus(StrEnum):
    PROPOSED = "proposed"
    ACTIVE = "active"
    LOCKED = "locked"
    RETIRED = "retired"

    @property
    def scores(self) -> bool:
        return self in (CheckStatus.ACTIVE, CheckStatus.LOCKED)


def _label_part(part: str) -> str:
    """A namespace or name as it appears in a label: quoted (`"a.b"`, quotes doubled) when it
    holds a dot or a quote, so that no two assets share a label."""
    if "." in part or '"' in part:
        return '"' + part.replace('"', '""') + '"'
    return part


def label_of(namespace: str, name: str) -> str:
    """`public.orders`, `orders` without a namespace, `"a.b".c` when a part holds a dot; lossless,
    unlike plain joining (`a.b` + `c` and `a` + `b.c` would both read `a.b.c`)."""
    return f"{_label_part(namespace)}.{_label_part(name)}" if namespace else _label_part(name)


class AssetRef(BaseModel):
    """A table, view or file set inside a source."""

    namespace: str = ""
    name: str
    kind: Literal["table", "view", "file"] = "table"

    @property
    def label(self) -> str:
        return label_of(self.namespace, self.name)

    def __hash__(self) -> int:
        return hash((self.namespace, self.name))


class ForeignKey(BaseModel):
    column: str
    parent: AssetRef
    parent_column: str


class ColumnInfo(BaseModel):
    name: str
    position: int
    physical_type: str
    logical_type: LogicalType
    declared_not_null: bool = False


class AssetInfo(BaseModel):
    """What the source declares about an asset, before anything is measured."""

    ref: AssetRef
    columns: list[ColumnInfo]
    primary_key: list[str] = Field(default_factory=list)
    unique: list[list[str]] = Field(default_factory=list)
    foreign_keys: list[ForeignKey] = Field(default_factory=list)
    row_estimate: int | None = None


class ValueCount(BaseModel):
    value: str | None
    count: int
    masked: bool = False


class ColumnProfile(BaseModel):
    name: str
    position: int
    physical_type: str
    logical_type: LogicalType
    role: Role = Role.ATTRIBUTE
    semantic_type: str | None = None
    semantic_share: float | None = None
    declared_not_null: bool = False
    # Counts on the sample.
    rows: int = 0
    nulls: int = 0
    distinct: int | None = None
    blanks: int | None = None
    # Numbers.
    min: float | str | None = None
    max: float | str | None = None
    mean: float | None = None
    stddev: float | None = None
    quantiles: dict[str, float] | None = None
    mad: float | None = None
    zeros: int | None = None
    negatives: int | None = None
    # Text.
    min_length: int | None = None
    max_length: int | None = None
    mean_length: float | None = None
    whitespace: int | None = None
    non_printing: int | None = None
    numeric_like: int | None = None
    date_like: int | None = None
    leading_zero_numbers: int | None = None
    # Time.
    future: int | None = None
    before_1900: int | None = None
    after_2200: int | None = None
    newest: str | None = None
    # Values.
    top: list[ValueCount] = Field(default_factory=list)
    top_truncated: bool = False
    patterns: list[ValueCount] = Field(default_factory=list)

    @property
    def non_null(self) -> int:
        return self.rows - self.nulls

    @property
    def null_ratio(self) -> float:
        return self.nulls / self.rows if self.rows else 0.0

    @property
    def distinct_ratio(self) -> float:
        return (self.distinct or 0) / self.non_null if self.non_null else 0.0


class AssetProfile(BaseModel):
    ref: AssetRef
    population: int = 0
    population_exact: bool = True
    sample_rows: int = 0
    sampled: bool = False
    columns: list[ColumnProfile] = Field(default_factory=list)
    primary_key: list[str] = Field(default_factory=list)
    unique: list[list[str]] = Field(default_factory=list)
    foreign_keys: list[ForeignKey] = Field(default_factory=list)
    declared_metadata: bool = False
    time_series_candidate: bool = False
    error: str | None = None

    def column(self, name: str) -> ColumnProfile | None:
        return next((c for c in self.columns if c.name == name), None)


class CheckSpec(BaseModel):
    """A generated or saved check, before evaluation."""

    id: str
    type: str
    asset: AssetRef
    column: str | None = None
    columns: list[str] = Field(default_factory=list)
    params: dict[str, Any] = Field(default_factory=dict)
    dimension: Dimension
    severity: Severity
    kind: Literal["rule", "baseline", "manual"]
    status: CheckStatus
    max_fail_ratio: float = 0.0
    origin: Literal["generated", "manual", "suggested", "declared"] = "generated"


class Interval(BaseModel):
    value: float
    low: float
    high: float


class CheckResult(BaseModel):
    spec: CheckSpec
    evaluated: int
    failed: int
    population: int
    ratio: float
    low: float
    high: float
    passed: bool
    summary: str
    next_step: str
    examples: list[ValueCount] = Field(default_factory=list)
    sql: str | None = None
    truncated: bool = False


class Finding(BaseModel):
    check_id: str
    check_type: str
    title: str
    asset: str
    column: str | None
    dimension: Dimension
    severity: Severity
    evaluated: int
    failed: int
    ratio: float
    low: float
    high: float
    summary: str
    next_step: str
    examples: list[ValueCount] = Field(default_factory=list)
    sql: str | None = None


class HealthItem(BaseModel):
    type: str
    asset: str
    column: str | None = None
    summary: str


class DimensionScore(BaseModel):
    value: float
    low: float
    high: float
    checks: int


class Score(BaseModel):
    """A score on 0–100 with its 95 % interval, overall and per dimension."""

    overall: float | None
    low: float | None
    high: float | None
    dimensions: dict[Dimension, DimensionScore] = Field(default_factory=dict)


class UnevaluatedCheck(BaseModel):
    """A saved check that could not run this scan, kept so the owner sees a stale lock (spec 007)."""

    spec: CheckSpec
    reason: Literal["column_missing", "parent_missing", "unknown_type"]


class ColumnReport(BaseModel):
    profile: ColumnProfile
    score: Score


class AssetReport(BaseModel):
    ref: AssetRef
    population: int
    population_exact: bool
    sample_rows: int
    sampled: bool
    score: Score
    columns: list[ColumnReport] = Field(default_factory=list)
    checks: list[CheckResult] = Field(default_factory=list)
    unevaluated: list[UnevaluatedCheck] = Field(default_factory=list)
    time_series_candidate: bool = False
    error: str | None = None


class SourceInfo(BaseModel):
    kind: Literal["duckdb", "postgres"]
    label: str


class ScanOptionsModel(BaseModel):
    sample_rows: int
    seed: int


class ScanStats(BaseModel):
    assets: int = 0
    assets_failed: int = 0
    columns: int = 0
    checks_active: int = 0
    checks_proposed: int = 0
    queries: int = 0
    duration_s: float = 0.0


class ScanReport(BaseModel):
    report_version: int = REPORT_VERSION
    scan_id: str
    started_at: datetime
    finished_at: datetime
    source: SourceInfo
    options: ScanOptionsModel
    score: Score
    assets: list[AssetReport] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    health: list[HealthItem] = Field(default_factory=list)
    proposed: list[CheckResult] = Field(default_factory=list)
    # Every reconciled check of the scan, as generated or saved, before evaluation (spec 007).
    checks: list[CheckSpec] = Field(default_factory=list)
    stats: ScanStats = Field(default_factory=ScanStats)
    iso_25012: dict[Dimension, str] = Field(default_factory=lambda: dict(ISO_25012))

    def finding_counts(self) -> dict[str, int]:
        counts = {s.value: 0 for s in Severity}
        for f in self.findings:
            counts[f.severity.value] += 1
        return counts

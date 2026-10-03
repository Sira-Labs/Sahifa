// Shapes of the API (spec 004). The report mirrors `ScanReport.model_dump(mode="json")` of
// core/src/sahifa_core/models.py: enums are their string values, datetimes ISO strings,
// scores on 0–100 (or null), check ratios and their intervals on 0–1 (pass share).

export type ScanStatus = "queued" | "running" | "succeeded" | "failed";
export type Severity = "critical" | "high" | "medium" | "low";
export type Dimension = "completeness" | "validity" | "accuracy" | "consistency" | "uniqueness" | "currentness";
export type LogicalType = "integer" | "decimal" | "boolean" | "text" | "date" | "timestamp" | "json" | "binary" | "other";
export type Role = "key" | "foreign_key" | "timestamp" | "measure" | "description" | "attribute";
export type CheckStatus = "proposed" | "active" | "locked" | "retired";
export type ConnectionKind = "postgres" | "duckdb" | "upload";

/** A keyset-paginated list. */
export type Page<T> = { items: T[]; next_cursor: string | null };

export type Version = { version: string; commit: string; schema_revision: string };
export type Health = { status: "ok" | "degraded"; database: "ok" | "unavailable"; version: string };

export type Connection = {
  id: string;
  name: string;
  kind: ConnectionKind;
  config: Record<string, unknown>;
  secret_ref: string | null;
  available: boolean;
  created_at: string;
};

export type ConnectionCreate = {
  name: string;
  kind: "postgres" | "duckdb";
  secret_ref: string;
  config: Record<string, unknown>;
};

/** Result of `POST /api/connections/{id}/test`. `assets` is a count or the asset names. */
export type ConnectionTest = { ok: boolean; assets: number | string[] | null; error: string | null };

export type FindingCounts = Record<Severity, number>;

export type Scan = {
  id: string;
  connection_id: string;
  connection_name: string;
  status: ScanStatus;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  sample_rows: number | null;
  score: { overall: number | null; low: number | null; high: number | null } | null;
  findings: FindingCounts | null;
  assets_count: number | null;
  // Not in spec 004; shown when the API sends them (upload scans).
  connection_kind?: ConnectionKind;
  files?: string[];
};

export type ScanCreate = { connection_id: string; assets?: string[]; sample_rows?: number };

// --- Report (core models) ---------------------------------------------------------------

export type AssetRef = { namespace: string; name: string; kind: "table" | "view" | "file" };

export type ForeignKey = { column: string; parent: AssetRef; parent_column: string };

export type ValueCount = { value: string | null; count: number; masked: boolean };

export type ColumnProfile = {
  name: string;
  position: number;
  physical_type: string;
  logical_type: LogicalType;
  role: Role;
  semantic_type: string | null;
  semantic_share: number | null;
  declared_not_null: boolean;
  rows: number;
  nulls: number;
  distinct: number | null;
  blanks: number | null;
  min: number | string | null;
  max: number | string | null;
  mean: number | null;
  stddev: number | null;
  quantiles: Record<string, number> | null;
  mad: number | null;
  zeros: number | null;
  negatives: number | null;
  min_length: number | null;
  max_length: number | null;
  mean_length: number | null;
  whitespace: number | null;
  non_printing: number | null;
  numeric_like: number | null;
  date_like: number | null;
  leading_zero_numbers: number | null;
  future: number | null;
  before_1900: number | null;
  after_2200: number | null;
  newest: string | null;
  top: ValueCount[];
  top_truncated: boolean;
  patterns: ValueCount[];
};

export type CheckSpec = {
  id: string;
  type: string;
  asset: AssetRef;
  column: string | null;
  columns: string[];
  params: Record<string, unknown>;
  dimension: Dimension;
  severity: Severity;
  kind: "rule" | "baseline" | "manual";
  status: CheckStatus;
  max_fail_ratio: number;
  origin: "generated" | "manual" | "suggested" | "declared";
};

export type CheckResult = {
  spec: CheckSpec;
  evaluated: number;
  failed: number;
  population: number;
  ratio: number;
  low: number;
  high: number;
  passed: boolean;
  summary: string;
  next_step: string;
  examples: ValueCount[];
  sql: string | null;
  truncated: boolean;
};

export type Finding = {
  /** Present on rows from `GET /api/scans/{id}/findings`. */
  id?: string;
  /** The finding across scans this occurrence belongs to (spec 009); null before migration 0005. */
  finding_id?: string | null;
  finding_status?: FindingStatus | null;
  check_id: string;
  check_type: string;
  title: string;
  asset: string;
  column: string | null;
  dimension: Dimension;
  severity: Severity;
  evaluated: number;
  failed: number;
  ratio: number;
  low: number;
  high: number;
  summary: string;
  next_step: string;
  examples: ValueCount[];
  sql: string | null;
};

export type HealthItem = { type: string; asset: string; column: string | null; summary: string };

export type DimensionScore = { value: number; low: number; high: number; checks: number };

export type Score = {
  overall: number | null;
  low: number | null;
  high: number | null;
  dimensions: Partial<Record<Dimension, DimensionScore>>;
};

export type ColumnReport = { profile: ColumnProfile; score: Score };

export type AssetReport = {
  ref: AssetRef;
  population: number;
  population_exact: boolean;
  sample_rows: number;
  sampled: boolean;
  score: Score;
  columns: ColumnReport[];
  checks: CheckResult[];
  /** Saved checks that could not run this scan (report version 2, spec 007). */
  unevaluated?: UnevaluatedCheck[];
  time_series_candidate: boolean;
  error: string | null;
};

export type UnevaluatedCheck = { spec: CheckSpec; reason: "column_missing" | "parent_missing" | "unknown_type" };

export type SourceInfo = { kind: "duckdb" | "postgres"; label: string };

export type ScanOptions = { sample_rows: number; seed: number };

export type ScanStats = {
  assets: number;
  assets_failed: number;
  columns: number;
  checks_active: number;
  checks_proposed: number;
  queries: number;
  duration_s: number;
};

export type ScanReport = {
  report_version: number;
  scan_id: string;
  started_at: string;
  finished_at: string;
  source: SourceInfo;
  options: ScanOptions;
  score: Score;
  assets: AssetReport[];
  findings: Finding[];
  health: HealthItem[];
  proposed: CheckResult[];
  /** Every reconciled check before evaluation (report version 2, spec 007). */
  checks?: CheckSpec[];
  stats: ScanStats;
  iso_25012: Partial<Record<Dimension, string>>;
};

/** Filters of `GET /api/scans/{id}/findings` and the findings page's search params. */
export type FindingFilters = { severity?: Severity; dimension?: Dimension; asset?: string };

// --- Assets and checks (spec 007) ---------------------------------------------------------

export type CheckCounts = Record<CheckStatus, number>;

/** An asset stored by the scans of a connection. */
export type Asset = {
  id: string;
  connection_id: string;
  namespace: string;
  name: string;
  label: string;
  kind: "table" | "view" | "file";
  row_count: number | null;
  last_scan_id: string | null;
  checks: CheckCounts;
};

/** A stored check with its lifecycle status; `key` is the report's `CheckSpec.id`. */
export type StoredCheck = {
  id: string;
  key: string;
  type: string;
  title: string;
  column: string | null;
  columns: string[];
  params: Record<string, unknown>;
  dimension: Dimension;
  severity: Severity;
  kind: "rule" | "baseline" | "manual";
  origin: "generated" | "manual" | "suggested" | "declared";
  status: CheckStatus;
  max_fail_ratio: number;
  version: number;
  updated_at: string;
  last_scan_id: string | null;
};

export type CheckAction = "approve" | "reject" | "lock" | "unlock" | "retire" | "restore";

// --- Findings across scans (spec 009) ------------------------------------------------------

export type FindingStatus = "open" | "acknowledged" | "resolved" | "muted";
export type FindingAction = "acknowledge" | "resolve" | "mute" | "unmute" | "reopen";

/** One finding per failing check across scans, with its latest occurrence. */
export type StoredFinding = {
  id: string;
  status: FindingStatus;
  severity: Severity;
  occurrences: number;
  first_seen_at: string;
  last_seen_at: string;
  muted_until: string | null;
  version: number;
  check: { id: string; key: string; type: string; title: string; status: CheckStatus; column: string | null };
  asset: { id: string; label: string; connection_id: string };
  latest: {
    scan_id: string;
    summary: string;
    failed: number;
    evaluated: number;
    ratio: number;
    low: number;
    high: number;
    dimension: Dimension;
  } | null;
};

/** One scan in which the finding's check failed, with its evidence. */
export type FindingOccurrence = {
  scan_id: string;
  at: string;
  failed: number;
  evaluated: number;
  ratio: number;
  low: number;
  high: number;
  summary: string;
  examples: ValueCount[];
  sql: string | null;
  next_step: string;
};

export type FindingEvent = {
  at: string;
  actor: string;
  action: "opened" | "recurred" | "auto_resolved" | "reopened" | "unmuted" | FindingAction;
  from_status: FindingStatus | null;
  to_status: FindingStatus;
  note: string | null;
};

export type StoredFindingDetail = StoredFinding & { occurrences_list: FindingOccurrence[]; events: FindingEvent[] };

/** Which statuses the findings page shows: those needing attention (open, acknowledged, muted:
 * the API's default), one status, or all of them. */
export type FindingsView = "attention" | FindingStatus | "all";

/** Search params of `/findings`. */
export type FindingsSearch = { status?: FindingsView; severity?: Severity; connection?: string };

/** Body of `POST /api/findings/{id}/{action}`. */
export type FindingChange = { note?: string; until?: string };

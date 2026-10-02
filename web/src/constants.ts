import type { Dimension, Severity } from "./types";

// Upload limits. They mirror the API defaults SAHIFA_MAX_UPLOAD_FILES and SAHIFA_MAX_UPLOAD_MB
// (spec 004); the API enforces its own configured values and answers 413/415/422 regardless.
export const ACCEPTED_EXTENSIONS = [".csv", ".tsv", ".parquet", ".json", ".jsonl", ".ndjson"] as const;
export const MAX_UPLOAD_FILES = 20;
export const MAX_UPLOAD_MB = 200;
export const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024;

/** Rows read per asset unless the person asks for everything (`0` reads every row). */
export const DEFAULT_SAMPLE_ROWS = 100_000;

/** How often a queued or running scan is fetched again. */
export const POLL_INTERVAL_MS = 2000;

/** Scans per page of the list. */
export const SCANS_PAGE_SIZE = 25;

/** Report order of the six dimensions (domain model). */
export const DIMENSIONS: readonly Dimension[] = [
  "completeness",
  "validity",
  "accuracy",
  "consistency",
  "uniqueness",
  "currentness",
];

export const SEVERITIES: readonly Severity[] = ["critical", "high", "medium", "low"];

export const SEVERITY_RANK: Record<Severity, number> = { critical: 0, high: 1, medium: 2, low: 3 };

/** Findings shown on the store report before "all findings". */
export const TOP_FINDINGS = 5;

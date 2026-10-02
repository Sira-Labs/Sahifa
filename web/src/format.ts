import { DIMENSIONS, SEVERITY_RANK } from "./constants";
import type { AssetRef, Dimension, Finding, Scan, Score } from "./types";

/** Zero-padded absolute integer part. */
function pad(n: number, width = 2): string {
  return String(Math.trunc(Math.abs(n))).padStart(width, "0");
}

/** `YYYY-MM-DD HH:MM UTC±HH:MM` in the browser's time zone. */
export function formatLocalTime(value: string | Date | null | undefined): string {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "—";
  const offset = -d.getTimezoneOffset();
  const sign = offset >= 0 ? "+" : "-";
  const date = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const time = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  return `${date} ${time} UTC${sign}${pad(offset / 60)}:${pad(offset % 60)}`;
}

/** A duration in seconds, e.g. `850 ms`, `12 s`, `3 min 5 s`, `2 h 4 min`. */
export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds) || seconds < 0) return "—";
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  const s = Math.round(seconds);
  if (s < 60) return `${s} s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m} min${s % 60 ? ` ${s % 60} s` : ""}`;
  const h = Math.floor(m / 60);
  return `${h} h${m % 60 ? ` ${m % 60} min` : ""}`;
}

/** Seconds between two timestamps, or null while one is missing. */
export function secondsBetween(start: string | null, end: string | null): number | null {
  if (!start || !end) return null;
  const ms = new Date(end).getTime() - new Date(start).getTime();
  return Number.isFinite(ms) ? ms / 1000 : null;
}

/** Grouped integer, `1,284`. */
export function formatCount(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return "—";
  return Math.round(n).toLocaleString("en-US");
}

/** Short large numbers: `2.1 M`, `41.2 k`; below 10,000 grouped in full. */
export function formatCompact(n: number): string {
  if (Math.abs(n) >= 1e9) return `${(n / 1e9).toFixed(1)} B`;
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(1)} M`;
  if (Math.abs(n) >= 1e4) return `${(n / 1e3).toFixed(1)} k`;
  return formatCount(n);
}

/** A measured number for people: integers grouped, fractions to four significant digits. */
export function formatNumber(v: number | string | null | undefined): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "string") return v;
  if (!Number.isFinite(v)) return String(v);
  if (Number.isInteger(v)) return v.toLocaleString("en-US");
  if (Math.abs(v) >= 1000) return v.toLocaleString("en-US", { maximumFractionDigits: 1 });
  return v.toLocaleString("en-US", { maximumSignificantDigits: 4 });
}

/** File size, `12.4 MB`. */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let v = bytes / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v >= 100 ? 0 : 1)} ${units[i]}`;
}

/** A score on 0–100 with one decimal. */
export function formatScore(v: number | null | undefined): string {
  return v === null || v === undefined || !Number.isFinite(v) ? "—" : v.toFixed(1);
}

// Two bounds count as equal when they agree to well below the displayed precision.
const SAME = 1e-9;

/** Whether an interval has zero width: every row was read. */
export function isFullRead(low: number, high: number): boolean {
  return Math.abs(high - low) < SAME;
}

/** The interval part of a score: `92.3–93.1`, or `full read` when it has zero width. */
export function formatIntervalRange(low: number | null | undefined, high: number | null | undefined): string {
  if (low === null || low === undefined || high === null || high === undefined) return "";
  return isFullRead(low, high) ? "full read" : `${low.toFixed(1)}–${high.toFixed(1)}`;
}

/** `92.7 · 92.3–93.1`, `92.7 · full read`, or `—` without a value. */
export function formatScoreInterval(value: number | null | undefined, low?: number | null, high?: number | null): string {
  if (value === null || value === undefined) return "—";
  const range = formatIntervalRange(low, high);
  return range ? `${formatScore(value)} · ${range}` : formatScore(value);
}

/** Spoken form for `aria-label`s: `92.7, 95 % interval 92.3 to 93.1`. */
export function describeScore(value: number | null | undefined, low?: number | null, high?: number | null): string {
  if (value === null || value === undefined) return "no score, no active checks";
  if (low === null || low === undefined || high === null || high === undefined) return formatScore(value);
  if (isFullRead(low, high)) return `${formatScore(value)}, every row read, no sampling interval`;
  return `${formatScore(value)}, 95 % interval ${low.toFixed(1)} to ${high.toFixed(1)}`;
}

/** A share on 0–1 as a percentage with sensible precision: `6.2 %`, `0.04 %`, `<0.01 %`. */
export function formatPercent(share: number): string {
  const v = share * 100;
  if (v === 0) return "0 %";
  if (v > 0 && v < 0.01) return "<0.01 %";
  if (v < 1) return `${v.toFixed(2)} %`;
  if (v > 99.9 && v < 100) return `${v.toFixed(2)} %`;
  return `${v.toFixed(1)} %`;
}

/** A check's failed share with its interval. `ratio`, `low`, `high` are the pass share and
 * its interval (domain model: p = (n − k) / n), so the failed interval is [1 − high, 1 − low]. */
export function formatFailedShare(ratio: number, low: number, high: number): string {
  const share = formatPercent(1 - ratio);
  if (isFullRead(low, high)) return `${share} · full read`;
  return `${share} · ${formatPercent(1 - high).replace(" %", "")}–${formatPercent(1 - low)}`;
}

/** A check's pass share with its interval, for check rows. */
export function formatPassShare(ratio: number, low: number, high: number): string {
  const share = formatPercent(ratio);
  if (isFullRead(low, high)) return `${share} · full read`;
  return `${share} · ${formatPercent(low).replace(" %", "")}–${formatPercent(high)}`;
}

/** `Completeness`. */
export function titleCase(s: string): string {
  return s ? s.charAt(0).toUpperCase() + s.slice(1).replace(/_/g, " ") : s;
}

/** A label part, quoted (quotes doubled) when it holds a dot or a quote, as in the core. */
function labelPart(part: string): string {
  return part.includes(".") || part.includes('"') ? `"${part.replaceAll('"', '""')}"` : part;
}

/** `public.orders`, `orders` without a namespace, `"a.b".c` when a part holds a dot (core
 * `AssetRef.label`, lossless). */
export function assetLabel(ref: AssetRef): string {
  return ref.namespace ? `${labelPart(ref.namespace)}.${labelPart(ref.name)}` : labelPart(ref.name);
}

/** `orders.customer_id`, or `orders` for an asset-level finding. */
export function assetColumn(asset: string, column: string | null | undefined): string {
  return column ? `${asset}.${column}` : asset;
}

/** The dimension with the lowest score, or null when none has a check. */
export function worstDimension(score: Score): { name: Dimension; value: number } | null {
  let worst: { name: Dimension; value: number } | null = null;
  for (const name of DIMENSIONS) {
    const d = score.dimensions[name];
    if (d && (worst === null || d.value < worst.value)) worst = { name, value: d.value };
  }
  return worst;
}

/** Findings by severity, then by failed share, the largest first. */
export function sortFindings(findings: Finding[]): Finding[] {
  return [...findings].sort((a, b) => SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity] || a.ratio - b.ratio);
}

/** Where a scan's data came from: the connection name, or `Upload: 3 files`. */
export function scanSource(scan: Scan): string {
  if (scan.files && scan.files.length > 0) return `Upload: ${scan.files.length} ${scan.files.length === 1 ? "file" : "files"}`;
  if (scan.connection_kind === "upload" || scan.connection_name.startsWith("upload")) {
    return scan.assets_count ? `Upload: ${scan.assets_count} ${scan.assets_count === 1 ? "file" : "files"}` : "Upload";
  }
  return scan.connection_name;
}

/** The sample policy in words. */
export function samplePolicy(sampleRows: number | null | undefined): string {
  if (sampleRows === 0) return "every row read";
  if (sampleRows === null || sampleRows === undefined) return "default sample";
  return `up to ${formatCount(sampleRows)} rows per table`;
}

/** A check's parameters in one short line: `values: paid, shipped · max: 4`. Long lists are cut. */
export function formatParams(params: Record<string, unknown>, maxItems = 6): string {
  const parts = Object.entries(params).map(([key, value]) => `${key.replace(/_/g, " ")}: ${paramValue(value, maxItems)}`);
  return parts.length ? parts.join(" · ") : "—";
}

function paramValue(value: unknown, maxItems: number): string {
  if (Array.isArray(value)) {
    const shown = value.slice(0, maxItems).map((v) => paramValue(v, maxItems));
    return value.length > maxItems ? `${shown.join(", ")} … (${value.length - maxItems} more)` : shown.join(", ");
  }
  if (typeof value === "number") return formatNumber(value);
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (value === null || value === undefined) return "—";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

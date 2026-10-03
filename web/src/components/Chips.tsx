import type { CheckStatus, FindingStatus, ScanStatus, Severity } from "../types";

export type Tone = "ok" | "warn" | "bad" | "info" | "muted";

/** A rounded label with a dot. The word always carries the meaning; the colour repeats it. */
export function Chip({ tone, children, title }: { tone: Tone; children: React.ReactNode; title?: string }) {
  return (
    <span className={`chip chip-${tone}`} title={title}>
      {children}
    </span>
  );
}

const SEVERITY_TONE: Record<Severity, Tone> = { critical: "bad", high: "bad", medium: "warn", low: "muted" };
const SEVERITY_LABEL: Record<Severity, string> = { critical: "Critical", high: "High", medium: "Medium", low: "Low" };

/** Severity of a check or finding: critical and high in the bad tone, medium warn, low muted. */
export function SeverityChip({ severity }: { severity: Severity }) {
  return <Chip tone={SEVERITY_TONE[severity]}>{SEVERITY_LABEL[severity]}</Chip>;
}

export type ChipStatus = ScanStatus | CheckStatus | FindingStatus | "passed" | "available" | "unavailable";

const STATUS: Record<ChipStatus, { tone: Tone; label: string }> = {
  queued: { tone: "muted", label: "Queued" },
  running: { tone: "info", label: "Running" },
  succeeded: { tone: "ok", label: "Succeeded" },
  failed: { tone: "bad", label: "Failed" },
  passed: { tone: "ok", label: "Passed" },
  proposed: { tone: "info", label: "Proposed" },
  active: { tone: "muted", label: "Active" },
  locked: { tone: "muted", label: "Locked" },
  retired: { tone: "muted", label: "Retired" },
  open: { tone: "warn", label: "Open" },
  acknowledged: { tone: "info", label: "Acknowledged" },
  resolved: { tone: "ok", label: "Resolved" },
  muted: { tone: "muted", label: "Muted" },
  available: { tone: "ok", label: "Available" },
  unavailable: { tone: "bad", label: "Unavailable" },
};

/** Status of a scan, a check result (`passed` / `failed`), a check's lifecycle, a finding's
 * status (spec 009) or a connection. */
export function StatusChip({ status }: { status: ChipStatus }) {
  const s = STATUS[status];
  return <Chip tone={s.tone}>{s.label}</Chip>;
}

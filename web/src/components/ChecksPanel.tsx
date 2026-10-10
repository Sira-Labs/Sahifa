import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useRef, useState, type KeyboardEvent } from "react";
import { ApiError, api } from "../api";
import { formatParams } from "../format";
import type { AssetReport, CheckAction, CheckStatus, StoredCheck } from "../types";
import { VIEWER_REASON, allows } from "../workspace";
import { SeverityChip, StatusChip } from "./Chips";

const TABS: { id: CheckStatus; label: string; empty: string }[] = [
  { id: "proposed", label: "Proposed", empty: "No proposed checks. New baselines appear here after a scan." },
  { id: "active", label: "Active", empty: "No active checks." },
  { id: "locked", label: "Locked", empty: "No locked checks. Lock a check to keep its parameters across scans." },
  { id: "retired", label: "Retired", empty: "No retired checks." },
];

// The lifecycle of ADR-0005: what each status allows, in the order the buttons appear.
const ACTIONS: Record<CheckStatus, { action: CheckAction; label: string }[]> = {
  proposed: [
    { action: "approve", label: "Approve" },
    { action: "reject", label: "Reject" },
  ],
  active: [
    { action: "lock", label: "Lock" },
    { action: "retire", label: "Retire" },
  ],
  locked: [{ action: "unlock", label: "Unlock" }],
  retired: [{ action: "restore", label: "Restore" }],
};

export const STALE_MESSAGE = "Someone changed this check; the list is up to date now.";

const UNEVALUATED: Record<string, string> = {
  column_missing: "Not evaluated: its column no longer exists.",
  parent_missing: "Not evaluated: the referenced table no longer exists.",
  unknown_type: "Not evaluated: this check type is unknown.",
};

/** Where a check looks: its column, its columns, or the table. */
function target(c: StoredCheck): string {
  return c.column ?? (c.columns.length ? c.columns.join(", ") : "table");
}

function isStale(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409 && (error.body as { detail?: unknown } | null)?.detail === "stale_version";
}

/** The asset's stored checks by lifecycle status, with the actions each status allows (spec 007).
 * The asset is found by the scan's connection and the report's label. */
export function ChecksPanel({ scanId, label, asset }: { scanId: string; label: string; asset: AssetReport }) {
  const client = useQueryClient();
  const baseId = useId();
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const [chosen, setChosen] = useState<CheckStatus | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const scan = useQuery({ queryKey: ["scan", scanId], queryFn: () => api.getScan(scanId) });
  const connectionId = scan.data?.connection_id;
  const stored = useQuery({
    queryKey: ["asset", connectionId, label],
    queryFn: () => api.findAsset(connectionId!, label),
    enabled: !!connectionId,
  });
  const assetId = stored.data?.id;
  const checks = useQuery({ queryKey: ["checks", assetId], queryFn: () => api.listChecks(assetId!), enabled: !!assetId });

  const change = useMutation({
    mutationFn: ({ check, action }: { check: StoredCheck; action: CheckAction }) => api.changeCheck(check, action),
    // Keep the tab in place while its checks move to another status.
    onMutate: () => {
      setChosen(tab);
      setNotice(null);
    },
    onSuccess: () => client.invalidateQueries({ queryKey: ["checks", assetId] }),
    onError: (error) => {
      if (!isStale(error)) return;
      setNotice(STALE_MESSAGE);
      void client.invalidateQueries({ queryKey: ["checks", assetId] });
    },
  });

  const counts = { proposed: 0, active: 0, locked: 0, retired: 0 } as Record<CheckStatus, number>;
  for (const c of checks.data ?? []) counts[c.status] += 1;
  const tab = chosen ?? (counts.proposed > 0 ? "proposed" : "active");
  const shown = (checks.data ?? []).filter((c) => c.status === tab);
  // All checks of an asset share its workspace; a viewer there sees the actions disabled (spec 016).
  const readOnly = (checks.data ?? []).some((c) => !allows(c.role));
  const results = new Map(asset.checks.map((r) => [r.spec.id, r]));
  const unevaluated = new Map((asset.unevaluated ?? []).map((u) => [u.spec.id, u.reason]));

  function select(id: CheckStatus) {
    setChosen(id);
    setNotice(null);
  }

  function onKey(e: KeyboardEvent, index: number) {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const next = (index + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length;
    select(TABS[next]!.id);
    tabRefs.current[next]?.focus();
  }

  const failed = scan.isError || stored.isError || checks.isError;
  const loading = !failed && (scan.isPending || (!!connectionId && stored.isPending) || (!!assetId && checks.isPending));

  return (
    <section aria-labelledby="checks-heading" className="card stack-sm">
      <h2 id="checks-heading">Checks</h2>
      <p className="muted text-sm">
        Only active and locked checks count toward scores and findings. Lock a check to keep its parameters; retire one that does
        not apply.
      </p>
      {loading && <p role="status">Loading checks…</p>}
      {failed && (
        <p role="alert" className="text-bad">
          The checks could not be loaded: {(scan.error ?? stored.error ?? checks.error)?.message}
        </p>
      )}
      {!loading && !failed && !assetId && <p className="muted">No checks are stored for this table yet. They are saved when a scan succeeds.</p>}
      {checks.data && (
        <>
          <div role="tablist" aria-label="Checks by status" className="tabs">
            {TABS.map((t, i) => (
              <button
                key={t.id}
                ref={(el) => {
                  tabRefs.current[i] = el;
                }}
                type="button"
                role="tab"
                id={`${baseId}-${t.id}-tab`}
                aria-selected={tab === t.id}
                aria-controls={`${baseId}-panel`}
                tabIndex={tab === t.id ? 0 : -1}
                className="tab"
                onClick={() => select(t.id)}
                onKeyDown={(e) => onKey(e, i)}
              >
                {t.label} <span className="tab-count num">{counts[t.id]}</span>
              </button>
            ))}
          </div>
          {notice && (
            <p role="status" className="text-warn">
              {notice}
            </p>
          )}
          {readOnly && <p className="muted text-sm">{VIEWER_REASON}</p>}
          {change.isError && !isStale(change.error) && (
            <p role="alert" className="text-bad">
              {change.error.message}
            </p>
          )}
          <div role="tabpanel" id={`${baseId}-panel`} aria-labelledby={`${baseId}-${tab}-tab`}>
            {shown.length === 0 ? (
              <p className="muted">{TABS.find((t) => t.id === tab)!.empty}</p>
            ) : (
              <ul className="check-list">
                {shown.map((c) => {
                  const result = results.get(c.key);
                  const reason = unevaluated.get(c.key);
                  return (
                    <li key={c.id} className="check-item" aria-label={`${c.title} · ${target(c)}`}>
                      <div className="check-head">
                        <strong>{c.title}</strong>
                        <code className="check-type break-anywhere">{target(c)}</code>
                        <SeverityChip severity={c.severity} />
                        {result && <StatusChip status={result.passed ? "passed" : "failed"} />}
                      </div>
                      <p className="text-sm break-anywhere">
                        <span className="muted">Parameters: </span>
                        {formatParams(c.params)}
                      </p>
                      <p className="text-sm muted">
                        {result ? result.summary : reason ? UNEVALUATED[reason] : "Not evaluated in this scan."}
                      </p>
                      <div className="row-actions">
                        {ACTIONS[c.status].map((a) => (
                          <button
                            key={a.action}
                            type="button"
                            className={`btn btn-small${a.action === "approve" ? " btn-primary" : ""}`}
                            disabled={change.isPending || readOnly}
                            title={readOnly ? VIEWER_REASON : undefined}
                            onClick={() => change.mutate({ check: c, action: a.action })}
                          >
                            {a.label}
                          </button>
                        ))}
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </>
      )}
    </section>
  );
}

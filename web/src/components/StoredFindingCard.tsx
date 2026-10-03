import { useMutation, useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useId, useState, type FormEvent } from "react";
import { ApiError, api } from "../api";
import { assetColumn, formatCount, formatFailedShare, formatLocalTime, titleCase } from "../format";
import type { FindingAction, FindingChange, FindingEvent, FindingStatus, StoredFinding } from "../types";
import { SeverityChip, StatusChip } from "./Chips";
import { Examples } from "./Examples";
import { SqlBlock } from "./SqlBlock";

export const NOTE_MAX = 1000;
export const FINDING_STALE_MESSAGE = "Someone changed this finding; the list is up to date now.";

// What each status allows, in the order the buttons appear (spec 009). "Mute…" asks for more.
const ACTIONS: Record<FindingStatus, { action: FindingAction; label: string }[]> = {
  open: [
    { action: "acknowledge", label: "Acknowledge" },
    { action: "resolve", label: "Resolve" },
    { action: "mute", label: "Mute…" },
  ],
  acknowledged: [
    { action: "resolve", label: "Resolve" },
    { action: "mute", label: "Mute…" },
  ],
  muted: [
    { action: "unmute", label: "Unmute" },
    { action: "resolve", label: "Resolve" },
  ],
  resolved: [{ action: "reopen", label: "Reopen" }],
};

const EVENT_LABEL: Record<FindingEvent["action"], string> = {
  opened: "Opened by a scan",
  recurred: "Seen again by a scan",
  auto_resolved: "Resolved by a scan: the check passed",
  reopened: "Reopened by a scan: the check failed again",
  unmuted: "Unmuted by a scan: the mute ended",
  acknowledge: "Acknowledged",
  resolve: "Resolved",
  mute: "Muted",
  unmute: "Unmuted",
  reopen: "Reopened",
};

export function isStaleFinding(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409 && (error.body as { detail?: unknown } | null)?.detail === "stale_version";
}

/** `seen 3 times, first … last …`. */
export function seenText(f: Pick<StoredFinding, "occurrences" | "first_seen_at" | "last_seen_at">): string {
  const times = f.occurrences === 1 ? "once" : `${formatCount(f.occurrences)} times`;
  return `Seen ${times}, first ${formatLocalTime(f.first_seen_at)}, last ${formatLocalTime(f.last_seen_at)}`;
}

/** The end of a chosen day in the browser's time zone, as an ISO time for `until`. */
export function endOfDay(date: string): string {
  return new Date(`${date}T23:59:59`).toISOString();
}

function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function NoteField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const id = useId();
  return (
    <div className="filter">
      <label htmlFor={id} className="field-label">
        Note (optional)
      </label>
      <textarea id={id} className="input note-input" maxLength={NOTE_MAX} rows={2} value={value} onChange={(e) => onChange(e.target.value)} />
      <span className="muted text-sm num" aria-live="polite">
        {value.length > NOTE_MAX - 100 ? `${NOTE_MAX - value.length} characters left` : ""}
      </span>
    </div>
  );
}

/** The occurrences (latest 20, with examples, SQL and next step) and the event history. */
function FindingHistory({ id }: { id: string }) {
  const detail = useQuery({ queryKey: ["finding", id], queryFn: () => api.getStoredFinding(id) });
  if (detail.isPending) return <p role="status">Loading the history…</p>;
  if (detail.isError)
    return (
      <p role="alert" className="text-bad">
        The history could not be loaded: {detail.error.message}
      </p>
    );
  const { occurrences_list: occurrences, events } = detail.data;
  return (
    <div className="stack-sm">
      <section aria-label="Occurrences" className="stack-sm">
        <h4>Occurrences</h4>
        {occurrences.length === 0 ? (
          <p className="muted">No occurrences are stored.</p>
        ) : (
          <ol className="history-list">
            {occurrences.map((o) => (
              <li key={o.scan_id} className="stack-sm">
                <p className="text-sm">
                  <Link to="/scans/$scanId" params={{ scanId: o.scan_id }}>
                    Scan of {formatLocalTime(o.at)}
                  </Link>
                  <span className="muted num">
                    {" "}
                    · {formatCount(o.failed)} of {formatCount(o.evaluated)} · {formatFailedShare(o.ratio, o.low, o.high)}
                  </span>
                </p>
                <p className="break-anywhere">{o.summary}</p>
                <Examples items={o.examples} />
                {o.sql && <SqlBlock sql={o.sql} />}
                {o.next_step && (
                  <p className="next-step">
                    <strong>Next step: </strong>
                    {o.next_step}
                  </p>
                )}
              </li>
            ))}
          </ol>
        )}
      </section>
      <section aria-label="History" className="stack-sm">
        <h4>History</h4>
        <ol className="history-list">
          {events.map((e, i) => (
            <li key={`${e.at}-${i}`}>
              <p className="text-sm">
                <strong>{EVENT_LABEL[e.action] ?? e.action}</strong>
                <span className="muted">
                  {" "}
                  · {e.actor === "scanner" ? "Sahifa" : e.actor} · {formatLocalTime(e.at)}
                  {e.from_status && e.from_status !== e.to_status ? ` · ${titleCase(e.from_status)} → ${titleCase(e.to_status)}` : ""}
                </span>
              </p>
              {/* Notes are plain text: rendered as text, never as HTML. */}
              {e.note && <p className="note break-anywhere">{e.note}</p>}
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}

/** One finding across scans (spec 009): what is wrong, where, how often and since when, its
 * status with the actions it allows, and on demand its occurrences and history. */
export function StoredFindingCard({
  finding,
  onChanged,
  onStale,
  expanded = false,
}: {
  finding: StoredFinding;
  onChanged: (updated: StoredFinding) => void;
  onStale: () => void;
  expanded?: boolean;
}) {
  const panelId = useId();
  const untilId = useId();
  const [open, setOpen] = useState(expanded);
  const [note, setNote] = useState("");
  const [noting, setNoting] = useState(false);
  const [muting, setMuting] = useState(false);
  const [until, setUntil] = useState("");

  const change = useMutation({
    mutationFn: ({ action, body }: { action: FindingAction; body: FindingChange }) => api.changeFinding(finding, action, body),
    onSuccess: (updated) => {
      setNote("");
      setNoting(false);
      setMuting(false);
      setUntil("");
      onChanged(updated);
    },
    onError: (error) => {
      if (isStaleFinding(error)) onStale();
    },
  });

  function run(action: FindingAction, extra: FindingChange = {}) {
    const body: FindingChange = { ...extra };
    if (note.trim()) body.note = note;
    change.mutate({ action, body });
  }

  function submitMute(e: FormEvent) {
    e.preventDefault();
    run("mute", until ? { until: endOfDay(until) } : {});
  }

  const summary = finding.latest?.summary ?? finding.check.title;
  const where = assetColumn(finding.asset.label, finding.check.column);
  const error = change.isError && !isStaleFinding(change.error) ? change.error.message : null;

  return (
    <article
      className="card finding-card"
      aria-label={`${titleCase(finding.severity)} finding, ${titleCase(finding.status)}: ${summary}`}
    >
      <div className="finding-head">
        <SeverityChip severity={finding.severity} />
        <StatusChip status={finding.status} />
        {finding.latest && <span className="tag">{titleCase(finding.latest.dimension)}</span>}
        <span className="muted text-sm">{finding.check.title}</span>
      </div>
      <h3 className="finding-summary">{summary}</h3>
      <dl className="facts">
        <div>
          <dt>Where</dt>
          <dd>
            <code>{where}</code>
          </dd>
        </div>
        <div>
          <dt>Seen</dt>
          <dd>{seenText(finding)}</dd>
        </div>
        {finding.latest && (
          <div>
            <dt>Latest</dt>
            <dd className="num">
              {formatCount(finding.latest.failed)} of {formatCount(finding.latest.evaluated)} ·{" "}
              <span className="nowrap">{formatFailedShare(finding.latest.ratio, finding.latest.low, finding.latest.high)}</span>
            </dd>
          </div>
        )}
        {finding.status === "muted" && (
          <div>
            <dt>Muted until</dt>
            <dd>{finding.muted_until ? formatLocalTime(finding.muted_until) : "Indefinitely"}</dd>
          </div>
        )}
      </dl>

      {muting ? (
        <form className="action-form stack-sm" aria-label="Mute this finding" onSubmit={submitMute}>
          <div className="filter">
            <label htmlFor={untilId} className="field-label">
              Mute until (optional; empty mutes until someone unmutes)
            </label>
            <input id={untilId} type="date" className="input" min={today()} value={until} onChange={(e) => setUntil(e.target.value)} />
          </div>
          <NoteField value={note} onChange={setNote} />
          <div className="row-actions">
            <button type="submit" className="btn btn-small btn-primary" disabled={change.isPending}>
              Mute
            </button>
            <button type="button" className="btn btn-small btn-quiet" onClick={() => setMuting(false)}>
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <>
          {noting && <NoteField value={note} onChange={setNote} />}
          <div className="row-actions">
            {ACTIONS[finding.status].map((a) => (
              <button
                key={a.action}
                type="button"
                className="btn btn-small"
                disabled={change.isPending}
                onClick={() => (a.action === "mute" ? setMuting(true) : run(a.action))}
              >
                {a.label}
              </button>
            ))}
            {!noting && (
              <button type="button" className="btn btn-small btn-quiet" onClick={() => setNoting(true)}>
                Add a note
              </button>
            )}
            <button type="button" className="btn btn-small btn-quiet" aria-expanded={open} aria-controls={panelId} onClick={() => setOpen(!open)}>
              {open ? "Hide history" : "Show history"}
            </button>
          </div>
        </>
      )}
      {error && (
        <p role="alert" className="text-bad">
          {error}
        </p>
      )}
      <div id={panelId} hidden={!open}>
        {open && <FindingHistory id={finding.id} />}
      </div>
    </article>
  );
}

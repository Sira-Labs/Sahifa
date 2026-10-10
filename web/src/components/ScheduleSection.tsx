import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useId, useMemo, useState, type FormEvent } from "react";
import { ApiError, api } from "../api";
import { formatLocalTime } from "../format";
import {
  CUSTOM_LABEL,
  OUTCOME_TEXT,
  SCHEDULE_PRESETS,
  browserTimeZone,
  presetOf,
  timeZoneOptions,
  type PresetId,
} from "../schedule";
import type { Schedule, ScheduleSave } from "../types";
import { VIEWER_REASON } from "../workspace";
import { ErrorPanel } from "./ErrorPanel";

export const SCHEDULE_STALE_MESSAGE = "Someone changed this schedule; it is reloaded. Check it and save again.";

type Field = "cron" | "timezone";
type Errors = Partial<Record<Field | "form", string>>;

function isStale(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409 && (error.body as { detail?: unknown } | null)?.detail === "stale_version";
}

/** The API's 422 next to its field: Sahifa's `{detail, field, message}` or FastAPI's list. */
function errorsOf(error: unknown): Errors {
  // A stale version reloads the section; the notice says so.
  if (!error || isStale(error)) return {};
  if (!(error instanceof ApiError)) return { form: error instanceof Error ? error.message : String(error) };
  const body = error.body as { field?: unknown; detail?: unknown } | null;
  if (error.status === 422 && (body?.field === "cron" || body?.field === "timezone")) return { [body.field]: error.message };
  if (error.status === 422 && Array.isArray(body?.detail)) {
    const out: Errors = {};
    for (const item of body.detail as { loc?: unknown[]; msg?: string }[]) {
      const field = item.loc?.[1];
      if (field === "cron" || field === "timezone") out[field] = item.msg ?? "invalid";
      else out.form = error.message;
    }
    return out;
  }
  return { form: error.message };
}

/** The schedule of one connection (spec 010): presets or a cron, a time zone, on or off, the
 * next runs in local time and the last run. A 409 reloads it with a notice. */
export function ScheduleSection({ connectionId, name, readOnly = false }: { connectionId: string; name: string; readOnly?: boolean }) {
  const headingId = useId();
  const client = useQueryClient();
  const key = ["schedule", connectionId];
  const schedule = useQuery({ queryKey: key, queryFn: () => api.getSchedule(connectionId) });
  const [notice, setNotice] = useState<string | null>(null);

  function changed(next: Schedule | null, message: string) {
    client.setQueryData(key, next);
    void client.invalidateQueries({ queryKey: ["connections"] });
    setNotice(message);
  }

  function stale() {
    setNotice(SCHEDULE_STALE_MESSAGE);
    void schedule.refetch();
  }

  return (
    <section aria-labelledby={headingId} className="schedule">
      <h3 id={headingId}>Schedule for {name}</h3>
      {schedule.isPending && <p role="status">Loading the schedule…</p>}
      {schedule.isError && (
        <ErrorPanel title="Could not load the schedule" error={schedule.error} onRetry={() => void schedule.refetch()} />
      )}
      {schedule.isSuccess && (
        // A new version (saved, reloaded or removed) starts the form afresh from it.
        <ScheduleForm
          key={schedule.data?.version ?? "new"}
          connectionId={connectionId}
          saved={schedule.data}
          onSaved={(s) => changed(s, "Schedule saved.")}
          onRemoved={() => changed(null, "Schedule removed.")}
          onStale={stale}
          onEdit={() => setNotice(null)}
          readOnly={readOnly}
        />
      )}
      <p role="status" aria-live="polite" className={notice === SCHEDULE_STALE_MESSAGE ? "text-warn" : "text-sm"}>
        {notice}
      </p>
    </section>
  );
}

function ScheduleForm({
  connectionId,
  saved,
  onSaved,
  onRemoved,
  onStale,
  onEdit,
  readOnly,
}: {
  connectionId: string;
  saved: Schedule | null;
  onSaved: (s: Schedule) => void;
  onRemoved: () => void;
  onStale: () => void;
  onEdit: () => void;
  /** A viewer of the connection's workspace (spec 016): every field and button disabled. */
  readOnly: boolean;
}) {
  const id = useId();
  const initialCron = saved?.cron ?? SCHEDULE_PRESETS[0]!.cron;
  const [preset, setPreset] = useState<PresetId>(presetOf(initialCron));
  const [cron, setCron] = useState(initialCron);
  const [timezone, setTimezone] = useState(saved?.timezone ?? browserTimeZone());
  const [enabled, setEnabled] = useState(saved?.enabled ?? true);
  const zones = useMemo(() => timeZoneOptions(browserTimeZone(), saved?.timezone ?? ""), [saved?.timezone]);

  const save = useMutation({
    mutationFn: (body: ScheduleSave) => api.saveSchedule(connectionId, body),
    onSuccess: onSaved,
    onError: (error) => isStale(error) && onStale(),
  });
  const remove = useMutation({
    mutationFn: () => api.deleteSchedule(connectionId),
    onSuccess: onRemoved,
    onError: (error) => error instanceof ApiError && error.status === 404 && onRemoved(),
  });
  const errors = errorsOf(save.error ?? remove.error);
  const busy = save.isPending || remove.isPending;
  const dirty = !!saved && (cron.trim() !== saved.cron || timezone !== saved.timezone || enabled !== saved.enabled);

  function edit() {
    save.reset();
    remove.reset();
    onEdit();
  }

  function choosePreset(value: PresetId) {
    setPreset(value);
    const found = SCHEDULE_PRESETS.find((p) => p.id === value);
    if (found) setCron(found.cron);
    edit();
  }

  function submit(e: FormEvent) {
    e.preventDefault();
    const body: ScheduleSave = { cron: cron.trim(), timezone, enabled, sample_rows: saved?.sample_rows ?? null };
    if (saved) body.version = saved.version;
    save.mutate(body);
  }

  const describe = (field: Field, help: string) => (errors[field] ? `${id}-${field}-error` : help);

  return (
    <form className="stack-sm" onSubmit={submit} noValidate>
      {readOnly && <p className="muted text-sm">{VIEWER_REASON}</p>}
      <fieldset className="fieldset stack-sm" disabled={readOnly}>
      <div className="schedule-fields">
        <div className="field">
          <label htmlFor={`${id}-preset`} className="field-label">
            Repeat
          </label>
          <select id={`${id}-preset`} className="input" value={preset} onChange={(e) => choosePreset(e.target.value as PresetId)}>
            {SCHEDULE_PRESETS.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
            <option value="custom">{CUSTOM_LABEL}</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor={`${id}-cron`} className="field-label">
            Cron expression
          </label>
          <input
            id={`${id}-cron`}
            className="input num"
            value={cron}
            spellCheck={false}
            autoComplete="off"
            aria-invalid={errors.cron ? true : undefined}
            aria-describedby={describe("cron", `${id}-cron-help`)}
            onChange={(e) => {
              setCron(e.target.value);
              setPreset(presetOf(e.target.value));
              edit();
            }}
          />
          {errors.cron ? (
            <p id={`${id}-cron-error`} className="field-error">
              {errors.cron}
            </p>
          ) : (
            <p id={`${id}-cron-help`} className="muted text-sm">
              Minute, hour, day of month, month, day of week.
            </p>
          )}
        </div>
        <div className="field">
          <label htmlFor={`${id}-tz`} className="field-label">
            Time zone
          </label>
          <select
            id={`${id}-tz`}
            className="input"
            value={timezone}
            aria-invalid={errors.timezone ? true : undefined}
            aria-describedby={describe("timezone", `${id}-tz-help`)}
            onChange={(e) => {
              setTimezone(e.target.value);
              edit();
            }}
          >
            {zones.map((z) => (
              <option key={z} value={z}>
                {z}
              </option>
            ))}
          </select>
          {errors.timezone ? (
            <p id={`${id}-timezone-error`} className="field-error">
              {errors.timezone}
            </p>
          ) : (
            <p id={`${id}-tz-help`} className="muted text-sm">
              The cron is read on this clock, daylight saving included.
            </p>
          )}
        </div>
        <div className="field">
          <span className="field-label">State</span>
          <label className="check">
            <input
              type="checkbox"
              role="switch"
              checked={enabled}
              onChange={(e) => {
                setEnabled(e.target.checked);
                edit();
              }}
            />
            Enabled
          </label>
        </div>
      </div>

      <div className="schedule-facts">
        <div>
          <h4 className="field-label">Next runs</h4>
          {!saved && <p className="muted text-sm">Save the schedule to see its next runs.</p>}
          {saved && saved.next_runs.length === 0 && <p className="muted text-sm">Paused: no runs until it is enabled.</p>}
          {saved && saved.next_runs.length > 0 && (
            <ol className="run-list" aria-label="Next runs">
              {saved.next_runs.map((t) => (
                <li key={t} className="num">
                  <time dateTime={t}>{formatLocalTime(t)}</time>
                </li>
              ))}
            </ol>
          )}
          {dirty && <p className="muted text-sm">For the saved schedule; save to update.</p>}
        </div>
        <div>
          <h4 className="field-label">Last run</h4>
          {saved?.last_run_at ? (
            <p className="text-sm">
              <time dateTime={saved.last_run_at} className="num">
                {formatLocalTime(saved.last_run_at)}
              </time>
              {saved.last_outcome && <> · {OUTCOME_TEXT[saved.last_outcome]}</>}
              {saved.last_scan_id && saved.last_outcome !== "skipped_running" && (
                <>
                  {" · "}
                  <Link to="/scans/$scanId" params={{ scanId: saved.last_scan_id }}>
                    View scan
                  </Link>
                </>
              )}
            </p>
          ) : (
            <p className="muted text-sm">Not run yet.</p>
          )}
        </div>
      </div>

      {errors.form && (
        <p role="alert" className="text-bad">
          {errors.form}
        </p>
      )}
      <div className="row-actions">
        <button type="submit" className="btn btn-primary btn-small" disabled={busy}>
          {save.isPending ? "Saving…" : "Save"}
        </button>
        {saved && (
          <button type="button" className="btn btn-small" disabled={busy} onClick={() => remove.mutate()}>
            {remove.isPending ? "Removing…" : "Remove schedule"}
          </button>
        )}
      </div>
      </fieldset>
    </form>
  );
}

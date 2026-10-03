// Schedules of connections (spec 010): presets, time zones and the words for a schedule.
import { formatLocalTime } from "./format";
import type { ScheduleOutcome, ScheduleSummary } from "./types";

export type PresetId = "nightly" | "every-6-hours" | "weekly" | "custom";

/** The presets of the schedule form; each fills the cron field. */
export const SCHEDULE_PRESETS: { id: Exclude<PresetId, "custom">; label: string; cron: string }[] = [
  { id: "nightly", label: "Nightly at 02:00", cron: "0 2 * * *" },
  { id: "every-6-hours", label: "Every 6 hours", cron: "0 */6 * * *" },
  { id: "weekly", label: "Weekly on Monday at 06:00", cron: "0 6 * * 1" },
];

export const CUSTOM_LABEL = "Custom (cron)";

/** The preset whose cron this is (spaces aside), or `custom`. */
export function presetOf(cron: string): PresetId {
  const normal = cron.trim().split(/\s+/).join(" ");
  return SCHEDULE_PRESETS.find((p) => p.cron === normal)?.id ?? "custom";
}

/** `Nightly at 02:00`, or the cron itself for a custom schedule. */
export function scheduleLabel(cron: string): string {
  const preset = SCHEDULE_PRESETS.find((p) => p.id === presetOf(cron));
  return preset ? preset.label : `cron ${cron}`;
}

/** One line for the connections table: `Nightly at 02:00 (Europe/Zurich) · next …`. */
export function describeSchedule(s: ScheduleSummary): string {
  const what = `${scheduleLabel(s.cron)} (${s.timezone})`;
  if (!s.enabled) return `${what} · paused`;
  return s.next_run_at ? `${what} · next ${formatLocalTime(s.next_run_at)}` : what;
}

/** What the last run did. */
export const OUTCOME_TEXT: Record<ScheduleOutcome, string> = {
  queued: "Scan started",
  skipped_running: "Skipped: the previous scan was still running",
  failed_to_queue: "Could not start the scan",
  invalid_schedule: "Disabled: the cron or time zone no longer resolves; save it again",
};

/** The browser's time zone, `UTC` when it cannot tell. */
export function browserTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

// When the browser cannot list its time zones (`Intl.supportedValuesOf` is newer than some).
const FALLBACK_ZONES = [
  "Africa/Cairo",
  "Africa/Johannesburg",
  "Africa/Lagos",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "America/New_York",
  "America/Sao_Paulo",
  "America/Toronto",
  "Asia/Dubai",
  "Asia/Kolkata",
  "Asia/Riyadh",
  "Asia/Shanghai",
  "Asia/Singapore",
  "Asia/Tokyo",
  "Australia/Sydney",
  "Europe/Berlin",
  "Europe/Istanbul",
  "Europe/London",
  "Europe/Madrid",
  "Europe/Paris",
  "Europe/Zurich",
  "Pacific/Auckland",
];

/** IANA time zones for the select: UTC first, then the browser's list (or a short one), plus
 * any of `include` (the saved and the browser's zone) the list lacks. */
export function timeZoneOptions(...include: string[]): string[] {
  let zones: string[] = [];
  try {
    const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
    zones = intl.supportedValuesOf?.("timeZone") ?? [];
  } catch {
    zones = [];
  }
  const all = new Set([...(zones.length ? zones : FALLBACK_ZONES), ...include.filter(Boolean)]);
  all.delete("UTC");
  return ["UTC", ...[...all].sort()];
}

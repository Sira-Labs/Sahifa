import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { SCHEDULE_STALE_MESSAGE } from "../components/ScheduleSection";
import { formatLocalTime } from "../format";
import { describeSchedule, presetOf, timeZoneOptions } from "../schedule";
import type { Connection, Schedule, ScheduleSave } from "../types";
import { json, makeScan, renderApp, stubFetch } from "./helpers";

const CID = "c0000000-0000-4000-8000-000000000001";
const SCHEDULE_URL = `/api/connections/${CID}/schedule`;
const SCAN_ID = "5ca70000-0000-4000-8000-0000000000aa";

const CONNECTION: Connection = {
  id: CID,
  name: "shop",
  kind: "postgres",
  config: {},
  secret_ref: "SAHIFA_CONN_SHOP",
  available: true,
  created_at: "2026-10-01T08:00:00Z",
  schedule: null,
};

function makeSchedule(overrides: Partial<Schedule> = {}): Schedule {
  return {
    cron: "0 2 * * *",
    timezone: "Europe/Zurich",
    enabled: true,
    sample_rows: null,
    next_run_at: "2026-10-04T00:00:00Z",
    next_runs: ["2026-10-04T00:00:00Z", "2026-10-05T00:00:00Z", "2026-10-06T00:00:00Z"],
    last_run_at: null,
    last_scan_id: null,
    last_outcome: null,
    version: 1,
    updated_at: "2026-10-03T09:00:00Z",
    updated_by: "dev",
    ...overrides,
  };
}

type Call = { method: string; body: ScheduleSave | null; headers: Record<string, string> };

/** A fake API with one connection and its schedule; PUT and DELETE change it as the server would
 * unless `onPut` answers instead. */
function serve(initial: Schedule | null, onPut?: (body: ScheduleSave) => Response | undefined) {
  let schedule = initial;
  const calls: Call[] = [];
  const fetch = stubFetch((url, init) => {
    if (url === "/api/connections")
      return {
        items: [
          { ...CONNECTION, schedule: schedule && { cron: schedule.cron, timezone: schedule.timezone, enabled: schedule.enabled, next_run_at: schedule.next_run_at } },
          { ...CONNECTION, id: "upload-1", name: "upload-abc", kind: "upload" },
        ],
      };
    if (url === SCHEDULE_URL) {
      const method = init?.method ?? "GET";
      const body = init?.body ? (JSON.parse(String(init.body)) as ScheduleSave) : null;
      calls.push({ method, body, headers: (init?.headers ?? {}) as Record<string, string> });
      if (method === "GET") return schedule ?? json({ detail: "no_schedule", message: "This connection has no schedule." }, 404);
      if (method === "DELETE") {
        schedule = null;
        return new Response(null, { status: 204 });
      }
      if (method === "PUT" && body) {
        const override = onPut?.(body);
        if (override) return override;
        schedule = makeSchedule({
          cron: body.cron,
          timezone: body.timezone,
          enabled: body.enabled,
          version: (schedule?.version ?? 0) + 1,
          next_run_at: body.enabled ? "2026-10-04T00:00:00Z" : null,
          next_runs: body.enabled ? makeSchedule().next_runs : [],
        });
        return schedule;
      }
    }
    throw new Error(`unexpected ${init?.method ?? "GET"} ${url}`);
  });
  return { fetch, calls, set: (s: Schedule | null) => (schedule = s) };
}

async function openSchedule() {
  renderApp("/connections");
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Schedule for shop" }));
  const section = await screen.findByRole("region", { name: "Schedule for shop" });
  return { user, section };
}

const cronInput = (section: HTMLElement) => within(section).getByRole("textbox", { name: "Cron expression" }) as HTMLInputElement;

describe("Schedule on the connections page", () => {
  it("offers a schedule for registered connections only and lists it in the table", async () => {
    serve(makeSchedule());
    renderApp("/connections");
    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row").filter((r) => !r.hidden && r.closest("tbody"));
    expect(rows).toHaveLength(1);
    expect(rows[0]!.textContent).toContain(`Nightly at 02:00 (Europe/Zurich) · next ${formatLocalTime("2026-10-04T00:00:00Z")}`);
    expect(screen.queryByRole("button", { name: "Schedule for upload-abc" })).toBeNull();
    const toggle = screen.getByRole("button", { name: "Schedule for shop" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
  });

  it("fills the cron from the presets and keeps a custom cron", async () => {
    serve(null);
    const { user, section } = await openSchedule();
    const repeat = within(section).getByRole("combobox", { name: "Repeat" }) as HTMLSelectElement;
    expect(repeat.value).toBe("nightly");
    expect(cronInput(section).value).toBe("0 2 * * *");
    await user.selectOptions(repeat, "Every 6 hours");
    expect(cronInput(section).value).toBe("0 */6 * * *");
    await user.selectOptions(repeat, "Weekly on Monday at 06:00");
    expect(cronInput(section).value).toBe("0 6 * * 1");
    await user.selectOptions(repeat, "Custom (cron)");
    expect(cronInput(section).value).toBe("0 6 * * 1");
    await user.clear(cronInput(section));
    await user.type(cronInput(section), "15 3 * * 2-6");
    expect(repeat.value).toBe("custom");
    // The browser's time zone by default (the tests run in Asia/Riyadh).
    expect((within(section).getByRole("combobox", { name: "Time zone" }) as HTMLSelectElement).value).toBe("Asia/Riyadh");
    expect(within(section).getByRole("switch", { name: "Enabled" })).toHaveProperty("checked", true);
    expect(within(section).getByText("Save the schedule to see its next runs.")).toBeTruthy();
    expect(within(section).queryByRole("button", { name: "Remove schedule" })).toBeNull();
  });

  it("saves with the CSRF header, then with the version, and shows the next runs", async () => {
    const { calls } = serve(null);
    const { user, section } = await openSchedule();
    await user.selectOptions(within(section).getByRole("combobox", { name: "Time zone" }), "Europe/Zurich");
    await user.click(within(section).getByRole("button", { name: "Save" }));

    const runs = await within(section).findByRole("list", { name: "Next runs" });
    expect(within(runs).getAllByRole("listitem").map((li) => li.textContent)).toEqual(
      makeSchedule().next_runs.map((t) => formatLocalTime(t)),
    );
    const first = calls.find((c) => c.method === "PUT")!;
    expect(first.headers["X-Sahifa-Request"]).toBe("1");
    expect(first.body).toEqual({ cron: "0 2 * * *", timezone: "Europe/Zurich", enabled: true, sample_rows: null });
    expect(within(section).getByText("Schedule saved.")).toBeTruthy();

    await user.click(within(section).getByRole("switch", { name: "Enabled" }));
    await user.click(within(section).getByRole("button", { name: "Save" }));
    await within(section).findByText("Paused: no runs until it is enabled.");
    const second = calls.filter((c) => c.method === "PUT")[1]!;
    expect(second.body).toEqual({ cron: "0 2 * * *", timezone: "Europe/Zurich", enabled: false, sample_rows: null, version: 1 });
    await waitFor(() => expect(screen.getByRole("table").textContent).toContain("Nightly at 02:00 (Europe/Zurich) · paused"));
  });

  it("shows the API's 422 message at its field", async () => {
    serve(null, (body) =>
      body.cron === "*/5 * * * *"
        ? json(
            {
              detail: "too_frequent",
              field: "cron",
              message: "This schedule runs every 5 minutes at its closest; the minimum is 60 minutes.",
              min_interval_minutes: 60,
              interval_minutes: 5,
            },
            422,
          )
        : json({ detail: "unknown_timezone", field: "timezone", message: "Asia/Riyadh is not a known time zone." }, 422),
    );
    const { user, section } = await openSchedule();
    await user.selectOptions(within(section).getByRole("combobox", { name: "Repeat" }), "Custom (cron)");
    await user.clear(cronInput(section));
    await user.type(cronInput(section), "*/5 * * * *");
    await user.click(within(section).getByRole("button", { name: "Save" }));

    const message = await within(section).findByText("This schedule runs every 5 minutes at its closest; the minimum is 60 minutes.");
    const input = cronInput(section);
    expect(input.getAttribute("aria-invalid")).toBe("true");
    expect(input.getAttribute("aria-describedby")).toBe(message.id);
    expect(within(section).queryByRole("alert")).toBeNull();

    // Editing clears it; a time-zone error appears at the time zone.
    await user.clear(input);
    await user.type(input, "0 2 * * *");
    expect(input.getAttribute("aria-invalid")).toBeNull();
    await user.click(within(section).getByRole("button", { name: "Save" }));
    const zoneMessage = await within(section).findByText("Asia/Riyadh is not a known time zone.");
    expect(within(section).getByRole("combobox", { name: "Time zone" }).getAttribute("aria-describedby")).toBe(zoneMessage.id);
  });

  it("shows the last run with its outcome and scan, and removes the schedule", async () => {
    const { calls } = serve(makeSchedule({ last_run_at: "2026-10-03T00:00:00Z", last_scan_id: SCAN_ID, last_outcome: "queued" }));
    const { user, section } = await openSchedule();
    expect(cronInput(section).value).toBe("0 2 * * *");
    expect(within(section).getByText(/Scan started/).textContent).toContain(formatLocalTime("2026-10-03T00:00:00Z"));
    expect(within(section).getByRole("link", { name: "View scan" }).getAttribute("href")).toBe(`/scans/${SCAN_ID}`);

    await user.click(within(section).getByRole("button", { name: "Remove schedule" }));
    await within(section).findByText("Schedule removed.");
    expect(calls.some((c) => c.method === "DELETE" && c.headers["X-Sahifa-Request"] === "1")).toBe(true);
    expect(within(section).queryByRole("button", { name: "Remove schedule" })).toBeNull();
    expect(within(section).getByText("Save the schedule to see its next runs.")).toBeTruthy();
    await waitFor(() => expect(screen.getByRole("table").textContent).toContain("None"));
  });

  it("reloads the section with a notice on a stale version", async () => {
    const api = serve(makeSchedule(), () => {
      api.set(makeSchedule({ cron: "0 6 * * 1", version: 2, updated_by: "ana@example.org" }));
      return json({ detail: "stale_version", version: 2, message: "Someone changed this schedule; reload it and try again." }, 409);
    });
    const { user, section } = await openSchedule();
    await user.click(within(section).getByRole("button", { name: "Save" }));
    await within(section).findByText(SCHEDULE_STALE_MESSAGE);
    await waitFor(() => expect(cronInput(section).value).toBe("0 6 * * 1"));
    expect((within(section).getByRole("combobox", { name: "Repeat" }) as HTMLSelectElement).value).toBe("weekly");
    expect(within(section).queryByRole("alert")).toBeNull();
  });

  it("reads presets and time zones", () => {
    expect(presetOf(" 0  2 * * * ")).toBe("nightly");
    expect(presetOf("0 3 * * *")).toBe("custom");
    expect(describeSchedule({ cron: "0 3 * * *", timezone: "UTC", enabled: false, next_run_at: null })).toBe("cron 0 3 * * * (UTC) · paused");
    const zones = timeZoneOptions("Etc/Unknown");
    expect(zones[0]).toBe("UTC");
    expect(zones).toContain("Europe/Zurich");
    expect(zones).toContain("Etc/Unknown");
    expect(zones.filter((z) => z === "UTC")).toHaveLength(1);
  });
});

describe("Scheduled scans in the scans list", () => {
  it("marks scheduled scans with a badge", async () => {
    stubFetch((url) => {
      if (url === "/api/scans?limit=25")
        return {
          items: [
            makeScan({ id: "00000000-0000-4000-8000-000000000001", trigger: "schedule" }),
            makeScan({ id: "00000000-0000-4000-8000-000000000002", trigger: "manual" }),
          ],
          next_cursor: null,
        };
      throw new Error(`unexpected ${url}`);
    });
    renderApp("/");
    const table = await screen.findByRole("table");
    const [scheduled, manual] = within(table).getAllByRole("row").slice(1);
    expect(within(scheduled!).getByText("scheduled")).toBeTruthy();
    expect(within(scheduled!).getAllByRole("cell")[1]!.textContent).toBe("shop scheduled");
    expect(within(manual!).queryByText("scheduled")).toBeNull();
  });
});

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { formatDelta, intervalsOverlap, lastChange, yDomain } from "../components/ScoreHistory";
import { formatLocalTime } from "../format";
import type { HistoryPoint } from "../types";
import { SCAN_ID, fetchedUrls, json, makeReport, makeScan, renderApp, stubFetch } from "./helpers";

const CID = makeScan().connection_id;
const ASSET_ID = "a0000000-0000-4000-8000-0000000000b1";
const STORE_HISTORY = `/api/connections/${CID}/history?scan_id=${SCAN_ID}`;
const ASSET_HISTORY = `/api/assets/${ASSET_ID}/history?scan_id=${SCAN_ID}`;

function point(i: number, overall: number | null, overrides: Partial<HistoryPoint> = {}): HistoryPoint {
  return {
    scan_id: `5ca70000-0000-4000-8000-00000000000${i}`,
    finished_at: `2026-10-0${i}T02:00:00Z`,
    trigger: "manual",
    overall,
    low: overall === null ? null : overall - 0.5,
    high: overall === null ? null : overall + 0.5,
    checks: 40,
    dimensions: {},
    ...overrides,
  };
}

/** Three scans ending at the viewed one; the middle one scheduled. */
const POINTS: HistoryPoint[] = [
  point(2, 88.1),
  point(3, 90.3, { trigger: "schedule" }),
  point(1, 92.7, { scan_id: SCAN_ID, finished_at: "2026-10-04T02:00:00Z" }),
];

function serve(store: unknown = { points: POINTS }, asset: unknown = { points: POINTS }) {
  return stubFetch((url) => {
    if (url === `/api/scans/${SCAN_ID}`) return makeScan();
    if (url === `/api/scans/${SCAN_ID}/report`) return makeReport();
    if (url === STORE_HISTORY) return store;
    if (url.startsWith("/api/assets?"))
      return {
        items: [{ id: ASSET_ID, connection_id: CID, namespace: "", name: "orders", label: "orders", kind: "table", row_count: 5, last_scan_id: SCAN_ID, checks: {} }],
        next_cursor: null,
      };
    if (url === ASSET_HISTORY) return asset;
    if (url.startsWith("/api/checks?")) return [];
    throw new Error(`unexpected ${url}`);
  });
}

async function storePanel() {
  renderApp(`/scans/${SCAN_ID}`);
  return screen.findByRole("region", { name: "Store score history" });
}

describe("Score history", () => {
  it("draws one linked point per scan, the viewed scan last and accented", async () => {
    serve();
    const panel = await storePanel();
    const marks = within(within(panel).getByRole("list", { name: /one link per scan/ })).getAllByRole("link");
    expect(marks).toHaveLength(3);
    expect(marks.map((m) => m.getAttribute("href"))).toEqual(POINTS.map((p) => `/scans/${p.scan_id}`));
    const current = marks.at(-1)!;
    expect(current.getAttribute("aria-current")).toBe("page");
    expect(current.className).toContain("is-current");
    expect(marks.filter((m) => m.className.includes("is-current"))).toHaveLength(1);
    expect(current.getAttribute("aria-label")).toBe(
      `This scan of ${formatLocalTime("2026-10-04T02:00:00Z")}, 92.7, 95 % interval 92.2 to 93.2, 40 checks`,
    );
    expect(marks[1]!.getAttribute("aria-label")).toContain(", scheduled");
    // The line and band are drawn; one segment for three scored points.
    expect(panel.querySelectorAll("polyline.history-line")).toHaveLength(1);
    expect(panel.querySelectorAll("polygon.history-band")).toHaveLength(1);
    expect(within(panel).getByText("Last 3 scans")).toBeTruthy();
  });

  it("states the change since the previous scan and whether it is within the interval", async () => {
    serve();
    const panel = await storePanel();
    const change = within(panel).getByTestId("history-change");
    expect(change.textContent).toContain("+2.4 since");
    expect(change.textContent).not.toContain("within the interval");

    expect(formatDelta(90.3, 92.7)).toBe("+2.4");
    expect(formatDelta(92.7, 90.3)).toBe("−2.4");
    expect(formatDelta(90.0, 90.04)).toBe("±0.0");
    expect(intervalsOverlap(point(1, 90), point(2, 90.8))).toBe(true);
    expect(intervalsOverlap(point(1, 90), point(2, 91.2))).toBe(false);
    // A scan without a score is skipped for the change and breaks the line.
    const gap = [point(1, 90), point(2, null), point(3, 90.6)];
    expect(lastChange(gap)).toMatchObject({ delta: "+0.6", within: true, since: { scan_id: gap[0]!.scan_id } });
    expect(lastChange([point(1, 90), point(2, null)])).toBeNull();
  });

  it("marks a change within the interval and leaves a gap for a scan without a score", async () => {
    serve({ points: [point(2, 91.0), point(3, null), point(1, 91.4, { scan_id: SCAN_ID })] });
    const panel = await storePanel();
    expect(within(panel).getByTestId("history-change").textContent).toContain("+0.4 since");
    expect(within(panel).getByText(/within the interval/)).toBeTruthy();
    const marks = within(panel).getAllByRole("list")[0]!.querySelectorAll("a.history-point");
    expect(marks[1]!.className).toContain("is-empty");
    expect(marks[1]!.getAttribute("aria-label")).toContain("no score");
    // Two single-point runs: no line, no band.
    expect(panel.querySelectorAll("polyline.history-line")).toHaveLength(0);
  });

  it("shows a point's numbers on focus", async () => {
    serve();
    const panel = await storePanel();
    expect(within(panel).queryByRole("tooltip")).toBeNull();
    const marks = within(panel).getAllByRole("list")[0]!.querySelectorAll("a");
    (marks[1] as HTMLAnchorElement).focus();
    const tip = await within(panel).findByRole("tooltip");
    expect(tip.textContent).toContain(formatLocalTime(POINTS[1]!.finished_at));
    expect(tip.textContent).toContain("90.3 · 89.8–90.8");
    expect(tip.textContent).toContain("40 checks · scheduled");
    expect(marks[1]!.getAttribute("aria-describedby")).toBe(tip.id);
    (marks[1] as HTMLAnchorElement).blur();
    await waitFor(() => expect(within(panel).queryByRole("tooltip")).toBeNull());
  });

  it("lists the same points as a table", async () => {
    serve();
    const panel = await storePanel();
    const user = userEvent.setup();
    await user.click(within(panel).getByText("Show as table"));
    const rows = within(within(panel).getByRole("table")).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(3);
    expect(rows[1]!.textContent).toContain("90.3");
    expect(rows[1]!.textContent).toContain("89.8–90.8");
    expect(rows[1]!.textContent).toContain("schedule");
    expect(within(rows[2]!).getByRole("link").getAttribute("href")).toBe(`/scans/${SCAN_ID}`);
  });

  it("fits the axis to the scores shown, at least 4 points tall and within 0–100", async () => {
    serve();
    const panel = await storePanel();
    // 87.6–93.2 shown: whole-number bounds around every interval.
    expect(panel.querySelector(".history-axis")!.textContent).toBe("9490.587");
    expect(yDomain(POINTS)).toEqual({ min: 87, max: 94 });
    expect(yDomain([point(1, 98.9), point(2, 99.1)])).toEqual({ min: 96, max: 100 });
    expect(yDomain([point(1, 0.2)])).toEqual({ min: 0, max: 4 });
    expect(yDomain([point(1, 50)])).toEqual({ min: 48, max: 52 });
    expect(yDomain([point(1, null)])).toEqual({ min: 0, max: 100 });
  });

  it("says history starts with this scan when there is one point", async () => {
    serve({ points: [point(1, 92.7, { scan_id: SCAN_ID })] });
    const panel = await storePanel();
    expect(within(panel).getByText(/History starts with this scan/)).toBeTruthy();
    expect(panel.querySelector("svg")).toBeNull();
    expect(within(panel).queryByTestId("history-change")).toBeNull();
  });

  it("shows nothing when the scan has no score here, and a message when the request fails", async () => {
    const fetch = serve(json({ detail: "scan_not_in_history", message: "x" }, 404));
    renderApp(`/scans/${SCAN_ID}`);
    await screen.findByLabelText(/Store score:/);
    await waitFor(() => expect(fetchedUrls(fetch)).toContain(STORE_HISTORY));
    expect(screen.queryByRole("region", { name: "Store score history" })).toBeNull();
    expect(screen.queryByText(/Could not load the score history/)).toBeNull();
  });

  it("asks for the table's history on the table report", async () => {
    const fetch = serve(undefined, { points: POINTS.slice(1) });
    renderApp(`/scans/${SCAN_ID}/assets/orders`);
    const panel = await screen.findByRole("region", { name: "Table score history" });
    expect(fetchedUrls(fetch)).toContain(ASSET_HISTORY);
    expect(within(panel).getByText("Last 2 scans")).toBeTruthy();
  });

  it("reports a failed history request without hiding the report", async () => {
    serve(json({ detail: "boom" }, 500));
    renderApp(`/scans/${SCAN_ID}`);
    expect(await screen.findByText("Could not load the score history.")).toBeTruthy();
    expect(screen.getByLabelText(/Store score:/)).toBeTruthy();
  });
});

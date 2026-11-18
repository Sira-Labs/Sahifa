import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { chartPoints } from "../components/MeasureChart";
import { describeSeries, formatMeasure, seriesOf } from "../measures";
import type { MeasurePoint } from "../types";
import { json, renderApp, stubFetch } from "./helpers";

const ASSET_ID = "a1111111-1111-4111-8111-111111111111";
const ASSET_URL = `/api/assets/${ASSET_ID}`;
const MEASURES_URL = `/api/assets/${ASSET_ID}/measures?column=amount`;

const ASSET = {
  id: ASSET_ID,
  connection_id: "c1",
  namespace: "public",
  name: "orders",
  label: "public.orders",
  kind: "table",
  row_count: 1000,
  last_scan_id: "s3",
  workspace: { id: "w1", name: "Default" },
  checks: { proposed: 0, active: 1, locked: 0, retired: 0 },
  columns: [{ name: "amount", position: 4, physical_type: "DECIMAL(10,2)", logical_type: "decimal", semantic_type: null, role: "measure" }],
};

function point(n: number, measures: Record<string, number>, extra: Partial<MeasurePoint> = {}): MeasurePoint {
  return {
    scan_id: `s${n}`,
    finished_at: `2026-11-0${n}T02:00:00Z`,
    trigger: "manual",
    rows: 1000,
    population: 1000,
    sampled: false,
    measures,
    ...extra,
  };
}

const POINTS = [
  point(1, { null_share: 0.01, mean: 40 }),
  point(2, { null_share: 0.02, mean: 42.5 }, { trigger: "schedule" }),
  point(3, { null_share: 0.25, mean: 41 }, { rows: 500, population: 20000, sampled: true }),
];

function serve(points: MeasurePoint[], measures: () => unknown = () => ({ asset_id: ASSET_ID, column: "amount", points })) {
  return stubFetch((url) => {
    if (url === ASSET_URL) return ASSET;
    if (url === MEASURES_URL) return measures();
    throw new Error(`unexpected ${url}`);
  });
}

describe("measures of a column (spec 024)", () => {
  it("builds one series per measure the points have, in the page's order", () => {
    const series = seriesOf([point(1, { mean: 2, null_share: 0 }), point(2, { mean: 3 })]);
    expect(series.map((s) => [s.key, s.values.map((v) => v.value)])).toEqual([
      ["null_share", [0]],
      ["mean", [2, 3]],
    ]);
    expect(seriesOf([point(1, {})])).toEqual([]);
  });

  it("writes shares as percentages and describes a series in words", () => {
    expect(formatMeasure(0.25, true)).toBe("25.0 %");
    expect(formatMeasure(undefined)).toBe("—");
    const [nulls] = seriesOf(POINTS);
    expect(describeSeries(nulls!)).toBe("Null share over 3 scans: first 1.0 %, newest 25.0 %, lowest 1.0 %, highest 25.0 %.");
    const [one] = seriesOf(POINTS.slice(0, 1));
    expect(describeSeries(one!)).toBe("Null share: 1.0 % in the one scan so far. A second scan makes a line.");
  });

  it("places values along the chart, a flat or single series in the middle", () => {
    const [low, high] = chartPoints([1, 3]);
    expect(low!.x).toBeLessThan(high!.x);
    expect(low!.y).toBeGreaterThan(high!.y);
    expect(new Set(chartPoints([5, 5, 5]).map((p) => p.y)).size).toBe(1);
    expect(chartPoints([7])).toEqual([{ x: 120, y: 28 }]);
  });
});

describe("Column measures page (spec 024)", () => {
  it("shows a chart per measure with its text alternative and the newest value", async () => {
    serve(POINTS);
    renderApp(`/assets/${ASSET_ID}/columns/amount`);

    expect(await screen.findByRole("heading", { level: 1, name: "amount" })).toBeTruthy();
    expect(screen.getByText("Column · public.orders")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Measures over the last 3 scans" })).toBeTruthy();
    const charts = screen.getAllByRole("img");
    expect(charts.map((c) => c.getAttribute("aria-label"))).toEqual([
      "Null share over 3 scans: first 1.0 %, newest 25.0 %, lowest 1.0 %, highest 25.0 %.",
      "Mean over 3 scans: first 40, newest 41, lowest 40, highest 42.5.",
    ]);
    const card = charts[0]!.closest("li")!;
    expect(card.textContent).toContain("Null share");
    expect(card.textContent).toContain("25.0 %");
    expect(card.textContent).toContain("1.0 % to 25.0 % over 3 scans");
    expect(charts[0]!.querySelectorAll("circle")).toHaveLength(3);
    expect(screen.getByText(/Some scans read a sample/)).toBeTruthy();
  });

  it("lists the scans newest first, each linking to its report", async () => {
    serve(POINTS);
    renderApp(`/assets/${ASSET_ID}/columns/amount`);

    const table = await screen.findByRole("table");
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Scan",
      "Rows read",
      "Rows in table",
      "Null share",
      "Mean",
    ]);
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getByRole("link").getAttribute("href"))).toEqual(["/scans/s3", "/scans/s2", "/scans/s1"]);
    const newest = within(rows[0]!).getAllByRole("cell").map((c) => c.textContent);
    expect(newest).toEqual(["500 sampled", "20,000", "25.0 %", "41"]);
    expect(rows[1]!.textContent).toContain("scheduled");
  });

  it("says so when there is one scan, and when there is none", async () => {
    serve(POINTS.slice(0, 1));
    const first = renderApp(`/assets/${ASSET_ID}/columns/amount`);
    expect(await screen.findByRole("heading", { name: "Measures over the last scan" })).toBeTruthy();
    expect(screen.getAllByRole("img")[0]!.getAttribute("aria-label")).toContain("A second scan makes a line.");
    expect(screen.getAllByText("One scan so far")).toHaveLength(2);
    first.unmount();

    serve([]);
    renderApp(`/assets/${ASSET_ID}/columns/amount`);
    expect(await screen.findByText(/Nothing has been measured on this column yet/)).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("keeps the history of a column that is gone from the table", async () => {
    stubFetch((url) => {
      if (url === ASSET_URL) return ASSET;
      if (url === `/api/assets/${ASSET_ID}/measures?column=old+name`) return { asset_id: ASSET_ID, column: "old name", points: POINTS };
      throw new Error(`unexpected ${url}`);
    });
    renderApp(`/assets/${ASSET_ID}/columns/${encodeURIComponent("old name")}`);
    expect(await screen.findByRole("heading", { level: 1, name: "old name" })).toBeTruthy();
    expect(screen.getByText("No longer in the table; this is its history.")).toBeTruthy();
  });

  it("shows the API's refusal with a retry", async () => {
    let fail = true;
    serve(POINTS, () => (fail ? json({ detail: "column_not_found", message: "This table has no column of that name, now or in its history." }, 404) : { asset_id: ASSET_ID, column: "amount", points: POINTS }));
    const user = userEvent.setup();
    renderApp(`/assets/${ASSET_ID}/columns/amount`);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Could not load the column's measures");
    expect(alert.textContent).toContain("This table has no column of that name");
    fail = false;
    await user.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("heading", { name: "Measures over the last 3 scans" })).toBeTruthy();
  });
});

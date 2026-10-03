import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { SCAN_ID, fetchedUrls, json, makeReport, makeScan, renderApp, stubFetch } from "./helpers";

const SCAN_URL = `/api/scans/${SCAN_ID}`;
const REPORT_URL = `/api/scans/${SCAN_ID}/report`;

describe("Report", () => {
  it("shows the score card with the overall interval and six dimension bars", async () => {
    stubFetch((url) => {
      if (url === SCAN_URL) return makeScan();
      if (url === REPORT_URL) return makeReport();
      if (url.includes("/history?")) return { points: [] };
      throw new Error(`unexpected ${url}`);
    });
    renderApp(`/scans/${SCAN_ID}`);

    expect(await screen.findByLabelText("Store score: 92.7, 95 % interval 92.3 to 93.1")).toBeTruthy();
    expect(screen.getByText("95 % interval 92.3–93.1")).toBeTruthy();

    const dims = screen.getByRole("list", { name: /scores per dimension/i });
    const bars = within(dims).getAllByRole("img");
    expect(bars.map((b) => b.getAttribute("aria-label"))).toEqual([
      "Completeness: 98.1, 95 % interval 97.8 to 98.4, 12 checks",
      "Validity: 90.3, 95 % interval 89.9 to 90.8, 8 checks",
      "Accuracy: 89.6, 95 % interval 88.1 to 91.0, 6 checks",
      "Consistency: 94.2, 95 % interval 93.7 to 94.6, 4 checks",
      // One table is sampled, so a zero-width store interval is rounding, not a full read.
      "Uniqueness: 99.4, 95 % interval 99.4 to 99.4, 2 checks",
      "Currentness: no score, no active checks",
    ]);
    const items = within(dims).getAllByRole("listitem");
    expect(items[0]!.textContent).toContain("98.1 · 97.8–98.4");
    expect(items[4]!.textContent).toContain("99.4 · 99.4–99.4");
    expect(items[5]!.textContent).toContain("— no active checks");
    // The axis is labelled.
    expect(dims.textContent).toContain("0255075100");

    // The interval sentence names the sample.
    expect(screen.getByText(/sampling uncertainty from reading 100,000 of up to 2\.1 M rows per table \(1 of 2 tables sampled\)/)).toBeTruthy();
  });

  it("summarises findings by severity with the five most severe", async () => {
    stubFetch((url) => {
      if (url === SCAN_URL) return makeScan();
      if (url === REPORT_URL) return makeReport();
      if (url.includes("/history?")) return { points: [] };
      throw new Error(`unexpected ${url}`);
    });
    renderApp(`/scans/${SCAN_ID}`);

    const counts = await screen.findByRole("list", { name: "Findings by severity" });
    expect(within(counts).getAllByRole("link").map((a) => a.textContent)).toEqual(["2Critical", "3High", "1Medium", "0Low"]);
    expect(within(counts).getAllByRole("link")[1]!.getAttribute("href")).toBe(`/scans/${SCAN_ID}/findings?severity=high`);

    const cards = screen.getAllByRole("article", { name: /finding:/ });
    expect(cards.map((c) => within(c).getByRole("heading").textContent)).toEqual([
      "Critical B: invalid IBANs.",
      "Critical A: 312 orphan orders.",
      "High A: future order dates.",
      "High B: duplicate order ids.",
      "High C: negative amounts.",
    ]);
    expect(screen.getByRole("link", { name: "All 6 findings" }).getAttribute("href")).toBe(`/scans/${SCAN_ID}/findings`);

    // The tables, store health and proposed checks follow.
    const tables = screen.getByRole("table", { name: /tables in this scan/i });
    const rows = within(tables).getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getByRole("rowheader").textContent)).toEqual(["orders", "customers"]);
    expect(rows[0]!.textContent).toContain("5,000 · full read");
    expect(rows[1]!.textContent).toContain("2.1 M · 100,000 read");
    // Both tables score 95.1 with equal bounds: a full read for orders, rounding for customers.
    expect(within(rows[0]!).getByLabelText("95.1, every row read, no sampling interval").textContent).toBe("95.1 · full read");
    expect(within(rows[1]!).getByLabelText("95.1, 95 % interval 95.1 to 95.1").textContent).toBe("95.1 · 95.1–95.1");
    expect(within(rows[0]!).getByRole("link", { name: "orders" }).getAttribute("href")).toBe(`/scans/${SCAN_ID}/assets/orders`);
    expect(screen.getByText("amount holds numbers stored as text.")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Proposed checks" }).parentElement!.textContent).toMatch(/2 baseline checks were proposed.*1 of them would report a problem/);
  });

  it("calls a zero-width store interval a full read only when no table was sampled", async () => {
    const report = makeReport();
    stubFetch((url) => {
      if (url === SCAN_URL) return makeScan();
      if (url === REPORT_URL) return { ...report, assets: report.assets.map((a) => ({ ...a, sampled: false })) };
      if (url.includes("/history?")) return { points: [] };
      throw new Error(`unexpected ${url}`);
    });
    renderApp(`/scans/${SCAN_ID}`);
    const dims = await screen.findByRole("list", { name: /scores per dimension/i });
    expect(within(dims).getByLabelText("Uniqueness: 99.4, every row read, no sampling interval, 2 checks")).toBeTruthy();
    expect(within(dims).getAllByRole("listitem")[4]!.textContent).toContain("99.4 · full read");
  });

  it("shows progress while the scan runs and does not ask for the report", async () => {
    const fetchFn = stubFetch((url) => {
      if (url === SCAN_URL) return makeScan({ status: "running", finished_at: null, score: null, findings: null });
      if (url.includes("/history?")) return { points: [] };
      throw new Error(`unexpected ${url}`);
    });
    renderApp(`/scans/${SCAN_ID}`);

    const status = await screen.findByText(/scanning: profiling every table/i);
    expect(status.closest("[role=status]")).toBeTruthy();
    expect(screen.getByText("Running")).toBeTruthy();
    expect(screen.getByText(/updates every 2 seconds/i)).toBeTruthy();
    expect(fetchedUrls(fetchFn)).not.toContain(REPORT_URL);
  });

  it("shows the error of a failed scan", async () => {
    const fetchFn = stubFetch((url) => {
      if (url === SCAN_URL) return makeScan({ status: "failed", error: "interrupted by a restart", score: null, findings: null });
      if (url.includes("/history?")) return { points: [] };
      throw new Error(`unexpected ${url}`);
    });
    renderApp(`/scans/${SCAN_ID}`);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("The scan failed");
    expect(alert.textContent).toContain("interrupted by a restart");
    expect(fetchedUrls(fetchFn)).not.toContain(REPORT_URL);
  });

  it("shows the API's message with a retry when the report cannot be loaded", async () => {
    let fail = true;
    stubFetch((url) => {
      if (url === SCAN_URL) return makeScan();
      if (url === REPORT_URL) return fail ? json({ detail: "report not ready" }, 409) : makeReport();
      if (url.includes("/history?")) return { points: [] };
      throw new Error(`unexpected ${url}`);
    });
    const user = userEvent.setup();
    renderApp(`/scans/${SCAN_ID}`);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("report not ready");
    fail = false;
    await user.click(within(alert).getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByLabelText(/store score: 92\.7/i)).toBeTruthy());
  });

  it("opens an asset with its table checks and expandable columns", async () => {
    stubFetch((url) => {
      if (url === REPORT_URL) return makeReport();
      if (url.includes("/history?")) return { points: [] };
      throw new Error(`unexpected ${url}`);
    });
    const user = userEvent.setup();
    renderApp(`/scans/${SCAN_ID}/assets/orders`);

    expect(await screen.findByRole("heading", { level: 1, name: "orders" })).toBeTruthy();
    const tableChecks = screen.getByRole("heading", { name: "Table-level checks" }).parentElement!;
    expect(tableChecks.textContent).toContain("sah.row_count");
    expect(tableChecks.textContent).not.toContain("sah.not_null");

    const toggle = screen.getByRole("button", { name: /customer_id/ });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    await user.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    const detail = document.getElementById(toggle.getAttribute("aria-controls")!)!;
    expect(detail.textContent).toContain("Top values");
    expect(detail.textContent).toContain("Berlin");
    expect(detail.textContent).toContain("sah.not_null");
    expect(within(detail).getByText("Failed")).toBeTruthy();
    expect(detail.textContent).toContain("passing 99.5 % · full read");
    expect(screen.getByLabelText("Table score: 95.1, every row read, no sampling interval")).toBeTruthy();
  });

  it("does not call a sampled table's zero-width score a full read", async () => {
    stubFetch((url) => {
      if (url === REPORT_URL) return makeReport();
      if (url.startsWith("/api/")) return json({ detail: "not here" }, 404);
      throw new Error(`unexpected ${url}`);
    });
    renderApp(`/scans/${SCAN_ID}/assets/customers`);
    expect(await screen.findByLabelText("Table score: 95.1, 95 % interval 95.1 to 95.1")).toBeTruthy();
    expect(screen.getByText("95 % interval 95.1–95.1")).toBeTruthy();
    expect(screen.queryByText(/every row read · no sampling interval/)).toBeNull();
  });
});

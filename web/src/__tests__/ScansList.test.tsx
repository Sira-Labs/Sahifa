import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { json, makeScan, renderApp, stubFetch } from "./helpers";

/** Scan number `n` of a list page. */
function scan(n: number, overrides = {}) {
  return makeScan({ id: `00000000-0000-4000-8000-00000000000${n}`, connection_name: `source-${n}`, ...overrides });
}

describe("ScansList", () => {
  it("shows a row per scan with source, status, score with interval and findings", async () => {
    stubFetch((url) => {
      if (url === "/api/scans?limit=25")
        return {
          items: [
            scan(1),
            scan(2, { status: "failed", score: null, findings: null, error: "boom" }),
            scan(3, { score: { overall: 99.0, low: 99.0, high: 99.0 }, findings: { critical: 0, high: 0, medium: 0, low: 0 } }),
          ],
          next_cursor: null,
        };
      throw new Error(`unexpected ${url}`);
    });
    renderApp("/");

    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(3);

    const first = rows[0]!;
    expect(within(first).getByText("source-1")).toBeTruthy();
    expect(within(first).getByText("Succeeded")).toBeTruthy();
    expect(within(first).getByLabelText("92.7, 95 % interval 92.3 to 93.1").textContent).toBe("92.7 · 92.3–93.1");
    expect(first.textContent).toContain("2 critical");
    expect(first.textContent).toContain("3 high");
    expect(first.textContent).not.toContain("low");
    expect(within(first).getByText("12 s")).toBeTruthy();
    expect(within(first).getByRole("link").getAttribute("href")).toBe(`/scans/${scan(1).id}`);

    expect(within(rows[1]!).getByText("Failed")).toBeTruthy();
    expect(rows[2]!.textContent).toContain("99.0 · full read");
    expect(rows[2]!.textContent).toContain("none");
  });

  it("invites a first scan when there are none", async () => {
    stubFetch(() => ({ items: [], next_cursor: null }));
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "No scans yet" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Start your first scan" }).getAttribute("href")).toBe("/scans/new");
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("appends the next page on load more", async () => {
    stubFetch((url) => {
      if (url === "/api/scans?limit=25") return { items: [scan(1), scan(2)], next_cursor: "c1" };
      if (url === "/api/scans?limit=25&cursor=c1") return { items: [scan(3)], next_cursor: null };
      throw new Error(`unexpected ${url}`);
    });
    const user = userEvent.setup();
    renderApp("/");

    const table = await screen.findByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    await user.click(screen.getByRole("button", { name: "Load more" }));
    await screen.findByText("source-3");
    expect(within(table).getAllByRole("row").slice(1).map((r) => within(r).getAllByRole("cell")[1]!.textContent)).toEqual([
      "source-1",
      "source-2",
      "source-3",
    ]);
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
  });

  it("shows the API's message and retries", async () => {
    let fail = true;
    stubFetch(() => (fail ? json({ detail: "database unavailable" }, 503) : { items: [scan(1)], next_cursor: null }));
    const user = userEvent.setup();
    renderApp("/");

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("database unavailable");
    fail = false;
    await user.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("source-1")).toBeTruthy();
  });
});

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { waitFor } from "@testing-library/react";
import type { Me } from "../auth";
import { DEFAULT_WORKSPACE, ME, json, makeScan, renderApp, stubFetch } from "./helpers";

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
            scan(3, { sample_rows: 0, score: { overall: 99.0, low: 99.0, high: 99.0 }, findings: { critical: 0, high: 0, medium: 0, low: 0 } }),
            // Sampled, with bounds that round to the same value: not a full read.
            scan(4, { score: { overall: 98.5, low: 98.5, high: 98.5 } }),
          ],
          next_cursor: null,
        };
      throw new Error(`unexpected ${url}`);
    });
    renderApp("/");

    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows).toHaveLength(4);

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
    expect(rows[3]!.textContent).toContain("98.5 · 98.5–98.5");
    expect(rows[3]!.textContent).not.toContain("full read");
    expect(within(rows[3]!).getByLabelText("98.5, 95 % interval 98.5 to 98.5")).toBeTruthy();
  });

  it("explains the three steps and offers the demo or the person's own data when there are no scans", async () => {
    stubFetch(() => ({ items: [], next_cursor: null }));
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "No scans yet" })).toBeTruthy();
    const steps = screen.getAllByRole("listitem").map((li) => li.textContent ?? "");
    expect(steps).toHaveLength(3);
    expect(steps[0]).toContain("Point Sahifa at data.");
    expect(steps[1]).toContain("It profiles and checks every table.");
    expect(steps[2]).toContain("Read the report.");
    expect(screen.getByRole("button", { name: "Try the demo data" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Scan your own data" }).getAttribute("href")).toBe("/scans/new");
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("starts the demo scan with one click and opens it", async () => {
    const created = makeScan({ id: "demo-scan", status: "queued", score: null, findings: null, demo: true });
    const fetchFn = stubFetch((url) => {
      if (url === "/api/scans/demo") return json(created, 202);
      if (url === "/api/scans/demo-scan") return created;
      return { items: [], next_cursor: null };
    });
    const user = userEvent.setup();
    const { router } = renderApp("/");
    await user.click(await screen.findByRole("button", { name: "Try the demo data" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/scans/demo-scan"));
    const call = fetchFn.mock.calls.find((c) => c[0] === "/api/scans/demo")!;
    expect(call[1]!.method).toBe("POST");
    // One workspace to upload to: the API picks it.
    expect(call[1]!.body).toBe("{}");
    expect(await screen.findByText("Demo data")).toBeTruthy();
  });

  it("names the workspace of the demo when the person may upload to several", async () => {
    const finance = { id: "w0000000-0000-4000-8000-000000000002", name: "Finance", role: "editor" as const, is_default: false };
    const me: Me = { ...ME, workspaces: [DEFAULT_WORKSPACE, finance] };
    const created = makeScan({ id: "demo-scan", status: "queued", score: null, findings: null, demo: true });
    const fetchFn = stubFetch(
      (url) => {
        if (url === "/api/scans/demo") return json(created, 202);
        if (url === "/api/scans/demo-scan") return created;
        return { items: [], next_cursor: null };
      },
      { me },
    );
    const user = userEvent.setup();
    renderApp("/");
    await user.click(await screen.findByRole("button", { name: "Try the demo data" }));
    await waitFor(() => expect(fetchFn.mock.calls.some((c) => c[0] === "/api/scans/demo")).toBe(true));
    const call = fetchFn.mock.calls.find((c) => c[0] === "/api/scans/demo")!;
    expect(JSON.parse(String(call[1]!.body))).toEqual({ workspace_id: DEFAULT_WORKSPACE.id });
  });

  it("does not let a viewer start the demo, and says why", async () => {
    const me: Me = { ...ME, admin: false, org_admin: false, workspaces: [{ ...DEFAULT_WORKSPACE, role: "viewer" }] };
    stubFetch(() => ({ items: [], next_cursor: null }), { me });
    renderApp("/");
    const button = (await screen.findByRole("button", { name: "Try the demo data" })) as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(true));
    expect(screen.getAllByText(/Viewers can look but not change/).length).toBeGreaterThan(0);
  });

  it("shows why the demo did not start, with what to do and a retry", async () => {
    let fail = true;
    const created = makeScan({ id: "demo-scan", status: "queued", score: null, findings: null, demo: true });
    stubFetch((url) => {
      if (url === "/api/scans/demo") return fail ? json({ detail: "disk full" }, 507) : json(created, 202);
      if (url === "/api/scans/demo-scan") return created;
      return { items: [], next_cursor: null };
    });
    const user = userEvent.setup();
    const { router } = renderApp("/");
    await user.click(await screen.findByRole("button", { name: "Try the demo data" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("The demo scan did not start");
    expect(alert.textContent).toContain("disk full");
    expect(alert.textContent).toContain("Free disk space on the server");
    fail = false;
    await user.click(within(alert).getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(router.state.location.pathname).toBe("/scans/demo-scan"));
  });

  it("says that the API is down instead of asking for the session in a loop", async () => {
    let down = true;
    const fetchFn = stubFetch(() => ({ items: [], next_cursor: null }), { me: json({ detail: "database unavailable" }, 503) });
    const original = fetchFn.getMockImplementation()!;
    fetchFn.mockImplementation(async (input, init) => {
      if (input === "/api/auth/me" && !down) return json(ME);
      return original(input, init);
    });
    const user = userEvent.setup();
    renderApp("/");
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Sahifa could not check your session");
    expect(alert.textContent).toContain("database unavailable");
    expect(alert.textContent).toContain("The API is starting or down");
    await new Promise((r) => setTimeout(r, 50));
    expect(fetchFn.mock.calls.filter((c) => c[0] === "/api/auth/me")).toHaveLength(1);
    down = false;
    await user.click(within(alert).getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("heading", { name: "No scans yet" })).toBeTruthy();
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

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { STALE_MESSAGE } from "../components/ChecksPanel";
import type { Asset, CheckStatus, StoredCheck } from "../types";
import { SCAN_ID, json, makeReport, makeScan, renderApp, stubFetch } from "./helpers";

const SCAN_URL = `/api/scans/${SCAN_ID}`;
const REPORT_URL = `/api/scans/${SCAN_ID}/report`;
const ASSET_ID = "a0000000-0000-4000-8000-000000000001";
const CHECKS_URL = `/api/checks?asset_id=${ASSET_ID}`;

const ASSET: Asset = {
  id: ASSET_ID,
  connection_id: makeScan().connection_id,
  namespace: "",
  name: "orders",
  label: "orders",
  kind: "file",
  row_count: 5000,
  last_scan_id: SCAN_ID,
  checks: { proposed: 2, active: 1, locked: 1, retired: 1 },
};

function stored(id: string, status: CheckStatus, overrides: Partial<StoredCheck> = {}): StoredCheck {
  return {
    id,
    key: `sah.range:orders:${id}`,
    type: "sah.range",
    title: "Outside the observed range",
    column: id,
    columns: [],
    params: { min: 1, max: 4 },
    dimension: "accuracy",
    severity: "high",
    kind: "baseline",
    origin: "generated",
    status,
    max_fail_ratio: 0,
    version: 1,
    updated_at: "2026-10-02T06:00:13Z",
    last_scan_id: SCAN_ID,
    ...overrides,
  };
}

function initialChecks(): StoredCheck[] {
  return [
    stored("quantity", "proposed"),
    stored("status", "proposed", {
      type: "sah.accepted_values",
      key: "sah.accepted_values:orders:status",
      title: "Unexpected category",
      params: { values: ["cancelled", "delivered", "paid", "shipped"] },
    }),
    stored("customer_id", "active", {
      key: "orders.customer_id.sah.not_null",
      type: "sah.not_null",
      title: "Missing values",
      kind: "rule",
      params: {},
    }),
    stored("amount", "locked", { version: 3 }),
    stored("city", "retired", { version: 2 }),
  ];
}

const NEXT: Record<string, CheckStatus> = {
  approve: "active",
  reject: "retired",
  lock: "locked",
  unlock: "active",
  retire: "retired",
  restore: "active",
};

/** A fake API holding the checks; POSTs change them as the server would. */
function serve(onPost?: (id: string, action: string, body: { version: number }) => Response | undefined) {
  let checks = initialChecks();
  let listCalls = 0;
  const fetch = stubFetch((url, init) => {
    if (url === SCAN_URL) return makeScan();
    if (url === REPORT_URL) return makeReport();
    if (url.startsWith("/api/assets?")) return { items: [{ ...ASSET, label: "customers", id: "other" }, ASSET], next_cursor: null };
    if (url === CHECKS_URL) {
      listCalls += 1;
      return checks;
    }
    const m = /^\/api\/checks\/([^/]+)\/([a-z]+)$/.exec(url);
    if (m && init?.method === "POST") {
      const body = JSON.parse(String(init.body)) as { version: number };
      const override = onPost?.(m[1]!, m[2]!, body);
      if (override) return override;
      checks = checks.map((c) => (c.id === m[1] ? { ...c, status: NEXT[m[2]!]!, version: c.version + 1 } : c));
      return checks.find((c) => c.id === m[1]);
    }
    throw new Error(`unexpected ${init?.method ?? "GET"} ${url}`);
  });
  return { fetch, listCalls: () => listCalls, setChecks: (c: StoredCheck[]) => (checks = c) };
}

async function openChecks() {
  renderApp(`/scans/${SCAN_ID}/assets/orders`);
  return screen.findByRole("tablist", { name: "Checks by status" });
}

describe("Checks on the asset report", () => {
  it("shows tabs with counts and starts on the proposed checks", async () => {
    const { fetch } = serve();
    const tabs = await openChecks();
    const names = within(tabs)
      .getAllByRole("tab")
      .map((t) => t.textContent);
    expect(names).toEqual(["Proposed 2", "Active 1", "Locked 1", "Retired 1"]);
    expect(within(tabs).getByRole("tab", { name: "Proposed 2" }).getAttribute("aria-selected")).toBe("true");
    const row = screen.getByRole("listitem", { name: "Unexpected category · status" });
    expect(row.textContent).toContain("values: cancelled, delivered, paid, shipped");
    expect(within(row).getByText("High")).toBeTruthy();
    expect(fetch.mock.calls.some(([url]) => String(url) === `/api/assets?connection_id=${ASSET.connection_id}&limit=200`)).toBe(true);
  });

  it("offers the actions each status allows", async () => {
    serve();
    const tabs = await openChecks();
    const user = userEvent.setup();
    const buttons = (name: string) =>
      within(screen.getByRole("listitem", { name }))
        .getAllByRole("button")
        .map((b) => b.textContent);

    expect(buttons("Outside the observed range · quantity")).toEqual(["Approve", "Reject"]);
    await user.click(within(tabs).getByRole("tab", { name: "Active 1" }));
    expect(buttons("Missing values · customer_id")).toEqual(["Lock", "Retire"]);
    // The latest result of this scan, matched by the check's key.
    expect(screen.getByRole("listitem", { name: "Missing values · customer_id" }).textContent).toContain(
      "sah.not_null: 25 of 5,000 rows fail.",
    );
    await user.click(within(tabs).getByRole("tab", { name: "Locked 1" }));
    expect(buttons("Outside the observed range · amount")).toEqual(["Unlock"]);
    await user.click(within(tabs).getByRole("tab", { name: "Retired 1" }));
    expect(buttons("Outside the observed range · city")).toEqual(["Restore"]);
    expect(screen.getByRole("listitem", { name: "Outside the observed range · city" }).textContent).toContain("Not evaluated in this scan.");
  });

  it("posts the action with the CSRF header and the version, then refreshes the list", async () => {
    const { fetch, listCalls } = serve();
    await openChecks();
    const user = userEvent.setup();
    const before = listCalls();

    const row = screen.getByRole("listitem", { name: "Unexpected category · status" });
    await user.click(within(row).getByRole("button", { name: "Approve" }));

    await waitFor(() => expect(screen.getByRole("tab", { name: "Active 2" })).toBeTruthy());
    expect(screen.getByRole("tab", { name: "Proposed 1" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.queryByRole("listitem", { name: "Unexpected category · status" })).toBeNull();
    expect(listCalls()).toBeGreaterThan(before);
    const post = fetch.mock.calls.find(([url, init]) => url === "/api/checks/status/approve" && init?.method === "POST");
    expect((post?.[1]?.headers as Record<string, string>)["X-Sahifa-Request"]).toBe("1");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ version: 1 });

    await user.click(screen.getByRole("tab", { name: "Active 2" }));
    await user.click(within(screen.getByRole("listitem", { name: "Unexpected category · status" })).getByRole("button", { name: "Lock" }));
    await waitFor(() => expect(screen.getByRole("tab", { name: "Locked 2" })).toBeTruthy());
    const lock = fetch.mock.calls.find(([url]) => url === "/api/checks/status/lock");
    expect(JSON.parse(String(lock?.[1]?.body))).toEqual({ version: 2 });
  });

  it("reloads the list and says so when someone else changed the check", async () => {
    const api = serve((id) => {
      if (id !== "quantity") return undefined;
      // Someone locked it first: the server's list moves on.
      api.setChecks(initialChecks().map((c) => (c.id === "quantity" ? { ...c, status: "active", version: 2 } : c)));
      return json({ detail: "stale_version", version: 2, message: "Someone changed this check; reload it and try again." }, 409);
    });
    await openChecks();
    const user = userEvent.setup();
    const before = api.listCalls();

    await user.click(within(screen.getByRole("listitem", { name: "Outside the observed range · quantity" })).getByRole("button", { name: "Reject" }));

    expect((await screen.findByText(STALE_MESSAGE)).getAttribute("role")).toBe("status");
    expect(api.listCalls()).toBeGreaterThan(before);
    await waitFor(() => expect(screen.getByRole("tab", { name: "Active 2" })).toBeTruthy());
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows other errors without the stale message", async () => {
    serve(() => json({ detail: "invalid_transition", status: "locked", message: "A locked check cannot be changed with approve." }, 409));
    await openChecks();
    await userEvent
      .setup()
      .click(within(screen.getByRole("listitem", { name: "Outside the observed range · quantity" })).getByRole("button", { name: "Approve" }));
    expect((await screen.findByRole("alert")).textContent).toContain("A locked check cannot be changed with approve.");
    expect(screen.queryByText(STALE_MESSAGE)).toBeNull();
  });

  it("explains when no checks are stored for the table", async () => {
    stubFetch((url) => {
      if (url === SCAN_URL) return makeScan();
      if (url === REPORT_URL) return makeReport();
      if (url.startsWith("/api/assets?")) return { items: [], next_cursor: null };
      throw new Error(`unexpected ${url}`);
    });
    renderApp(`/scans/${SCAN_ID}/assets/orders`);
    expect(await screen.findByText(/No checks are stored for this table yet/)).toBeTruthy();
    expect(screen.queryByRole("tablist", { name: "Checks by status" })).toBeNull();
  });
});

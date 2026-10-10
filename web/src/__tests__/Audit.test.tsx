import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import type { Me } from "../auth";
import { changes } from "../pages/Audit";
import type { AuditEntry } from "../types";
import { setWorkspaceFilter } from "../workspace";
import { DEFAULT_WORKSPACE, ME, renderApp, stubFetch } from "./helpers";

function entry(overrides: Partial<AuditEntry> = {}): AuditEntry {
  return {
    id: crypto.randomUUID(),
    at: "2026-10-10T08:00:00Z",
    workspace: { id: DEFAULT_WORKSPACE.id, name: "Default" },
    actor: "ana@example.org",
    action: "check.lock",
    object_type: "check",
    object_id: crypto.randomUUID(),
    summary: "Locked “Range” on orders.amount",
    before: { status: "active", version: 1 },
    after: { status: "locked", version: 2 },
    ...overrides,
  };
}

beforeEach(() => setWorkspaceFilter(null));

describe("changes", () => {
  it("shows each changed field before and after, without bookkeeping fields", () => {
    expect(changes(entry())).toEqual(["status: active → locked"]);
    expect(changes(entry({ before: null, after: { name: "Finance" } }))).toEqual(["name: Finance"]);
    expect(changes(entry({ before: { role: "viewer", email: "bo@example.org" }, after: null }))).toEqual(["role: viewer → removed"]);
    expect(
      changes(entry({ before: { workspace: { id: "w1", name: "Default" } }, after: { workspace: { id: "w2", name: "Finance" } } })),
    ).toEqual(["workspace: Default → Finance"]);
  });
});

describe("/audit (spec 018)", () => {
  it("lists entries, filters them and loads more", async () => {
    const finding = entry({ action: "finding.mute", object_type: "finding", summary: "Muted finding of “Not null” on orders.id" });
    const fetch = stubFetch((url) => {
      if (url.startsWith("/api/audit") && url.includes("cursor=c1")) return { items: [entry({ summary: "Older change" })], next_cursor: null };
      if (url.startsWith("/api/audit")) return { items: [entry(), finding], next_cursor: "c1" };
      return { items: [] };
    });
    renderApp("/audit");
    const row = (await screen.findByText("Locked “Range” on orders.amount")).closest("tr")!;
    expect(within(row).getByText("status: active → locked")).toBeTruthy();
    expect(within(row).getByText("ana@example.org")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Muted finding/ }).getAttribute("href")).toBe(`/findings/${finding.object_id}`);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Load more" }));
    expect(await screen.findByText("Older change")).toBeTruthy();
    await user.selectOptions(screen.getByRole("combobox", { name: "Kind of change" }), "Findings");
    await user.type(screen.getByRole("textbox", { name: "Person" }), "ana@");
    await user.click(screen.getByRole("button", { name: "Filter" }));
    await waitFor(() =>
      expect(fetch.mock.calls.some(([url]) => String(url) === "/api/audit?action=finding.&actor=ana%40&limit=50")).toBe(true),
    );
  });

  it("is linked only for admins", async () => {
    const editor: Me = { ...ME, admin: false, org_admin: false, workspaces: [{ ...DEFAULT_WORKSPACE, role: "editor" }] };
    stubFetch(() => ({ items: [], next_cursor: null }), { me: editor });
    renderApp("/");
    await screen.findByRole("heading", { name: "No scans yet" });
    expect(screen.queryByRole("link", { name: "Audit" })).toBeNull();
  });

  it("is linked for the org admin", async () => {
    stubFetch(() => ({ items: [], next_cursor: null }));
    renderApp("/");
    expect(await screen.findByRole("link", { name: "Audit" })).toBeTruthy();
  });
});

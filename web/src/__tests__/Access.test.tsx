import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { SourceAccess } from "../types";
import { SCAN_ID, makeReport, makeScan, renderApp, stubFetch } from "./helpers";

const SHOP = { id: "c1", name: "shop", kind: "postgres", config: {}, secret_ref: "SAHIFA_CONN_SHOP", available: true, created_at: "2026-10-01T00:00:00Z" };

function access(overrides: Partial<SourceAccess> = {}): SourceAccess {
  return {
    verdict: "read_only",
    readable: 6,
    unreadable: 0,
    writable: [],
    writable_count: 0,
    can_create_in: [],
    role_flags: [],
    advice: null,
    reason: null,
    ...overrides,
  };
}

const WRITER = access({
  verdict: "can_write",
  writable: ["public.orders", "public.invoices"],
  writable_count: 3,
  can_create_in: ["schema public"],
  advice: "Revoke INSERT, UPDATE, DELETE and TRUNCATE (and ownership) on 3 tables; Revoke CREATE on schema public. See docs/guides/read-only-login.md.",
});

describe("what the login may do (spec 021)", () => {
  async function testShop(result: SourceAccess) {
    stubFetch((url) => {
      if (url === "/api/connections/c1/test") return { ok: true, assets: 6, error: null, access: result };
      if (url.startsWith("/api/connections")) return { items: [SHOP] };
      return { items: [] };
    });
    const user = userEvent.setup();
    renderApp("/connections");
    await user.click(await screen.findByRole("button", { name: "Test shop" }));
    return user;
  }

  it("says a read-only login is read-only", async () => {
    await testShop(access());
    expect(await screen.findByText("✓ Read-only login")).toBeTruthy();
  });

  it("says what a login could write, the advice, and lists the tables on request", async () => {
    const user = await testShop(WRITER);
    expect(await screen.findByText(/This login could write: may change 3 tables or files; may create in schema public/)).toBeTruthy();
    expect(screen.getByText(/Revoke CREATE on schema public/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Show what it could change" }));
    const list = screen.getByRole("list", { name: "Writable tables or files" });
    expect(within(list).getByText("public.orders")).toBeTruthy();
    expect(within(list).getByText("and 1 more")).toBeTruthy();
  });

  it("warns above a report whose scan ran with a login that could write", async () => {
    stubFetch((url) => {
      if (url === `/api/scans/${SCAN_ID}/report`) return makeReport({ source_access: WRITER });
      if (url === `/api/scans/${SCAN_ID}`) return makeScan();
      return { items: [] };
    });
    renderApp(`/scans/${SCAN_ID}`);
    const note = await screen.findByRole("complementary", { name: "Login rights" });
    expect(within(note).getByText("The login this scan used could write to the source.")).toBeTruthy();
  });

  it("shows no warning for a read-only login or an upload", async () => {
    stubFetch((url) => {
      if (url === `/api/scans/${SCAN_ID}/report`) return makeReport({ source_access: access() });
      if (url === `/api/scans/${SCAN_ID}`) return makeScan();
      return { items: [] };
    });
    renderApp(`/scans/${SCAN_ID}`);
    expect(await screen.findByRole("heading", { name: "Store score" })).toBeTruthy();
    expect(screen.queryByRole("complementary", { name: "Login rights" })).toBeNull();
  });
});

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { Me } from "../auth";
import type { Connection, Invitation, InvitationCreated, Member, StoredFinding, Workspace } from "../types";
import { VIEWER_REASON, setWorkspaceFilter } from "../workspace";
import { DEFAULT_WORKSPACE, DEV_ME, ME, json, renderApp, stubFetch } from "./helpers";

const FINANCE = { id: "w0000000-0000-4000-8000-000000000002", name: "Finance", is_default: false };

/** Ana: editor of Default, viewer of Finance. */
const ANA: Me = {
  ...ME,
  admin: false,
  org_admin: false,
  organisation: "Acme Data",
  workspaces: [
    { ...DEFAULT_WORKSPACE, role: "editor" },
    { ...FINANCE, role: "viewer" },
  ],
};

function connection(overrides: Partial<Connection>): Connection {
  return {
    id: "c0000000-0000-4000-8000-000000000001",
    name: "shop",
    kind: "postgres",
    config: {},
    secret_ref: "SAHIFA_CONN_SHOP",
    available: true,
    created_at: "2026-10-01T08:00:00Z",
    schedule: null,
    workspace: { id: DEFAULT_WORKSPACE.id, name: "Default" },
    role: "editor",
    ...overrides,
  };
}

const LEDGER = connection({
  id: "c0000000-0000-4000-8000-000000000002",
  name: "ledger",
  workspace: { id: FINANCE.id, name: "Finance" },
  role: "viewer",
});

function finding(overrides: Partial<StoredFinding> = {}): StoredFinding {
  return {
    id: "f0000000-0000-4000-8000-000000000001",
    status: "open",
    severity: "high",
    occurrences: 1,
    first_seen_at: "2026-10-02T06:00:00Z",
    last_seen_at: "2026-10-02T06:00:00Z",
    muted_until: null,
    version: 1,
    check: { id: "k1", key: "k1", type: "sah.not_null", title: "Not null", status: "active", column: "amount" },
    asset: { id: "a1", label: "entries", connection_id: LEDGER.id },
    latest: null,
    workspace: { id: FINANCE.id, name: "Finance" },
    role: "viewer",
    ...overrides,
  };
}

beforeEach(() => setWorkspaceFilter(null));

describe("roles in the web app (spec 016)", () => {
  it("shows a viewer's actions disabled with the reason, and each item's workspace", async () => {
    stubFetch(
      (url) => {
        if (url.startsWith("/api/connections")) return { items: [connection({}), LEDGER] };
        return { items: [], next_cursor: null };
      },
      { me: ANA },
    );
    renderApp("/connections");
    const ledger = (await screen.findByRole("rowheader", { name: "ledger" })).closest("tr")!;
    expect(within(ledger).getByText("Finance")).toBeTruthy();
    const scan = within(ledger).getByRole("button", { name: "Scan" });
    expect(scan).toHaveProperty("disabled", true);
    expect(scan.getAttribute("title")).toBe(VIEWER_REASON);
    const shop = screen.getByRole("rowheader", { name: "shop" }).closest("tr")!;
    expect(within(shop).getByRole("link", { name: "Scan" })).toBeTruthy();
    expect(screen.getByText("Acme Data")).toBeTruthy();
    // No /workspaces link for someone who administers nothing.
    expect(screen.queryByRole("link", { name: "Workspaces" })).toBeNull();
  });

  it("disables a viewer's finding actions and says why", async () => {
    stubFetch(
      (url) => {
        if (url.startsWith("/api/connections")) return { items: [LEDGER] };
        if (url.startsWith("/api/findings")) return { items: [finding()], next_cursor: null };
        return { items: [] };
      },
      { me: ANA },
    );
    renderApp("/findings");
    const acknowledge = await screen.findByRole("button", { name: "Acknowledge" });
    expect(acknowledge).toHaveProperty("disabled", true);
    expect(screen.getByText(VIEWER_REASON)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Add a note" })).toBeNull();
    expect(screen.getByText("Finance · ledger")).toBeTruthy();
  });

  it("filters the lists by the workspace chosen in the header and remembers it", async () => {
    const fetch = stubFetch(() => ({ items: [], next_cursor: null }), { me: ANA });
    renderApp("/");
    const select = await screen.findByRole("combobox", { name: "Workspace" });
    await userEvent.setup().selectOptions(select, "Finance");
    await waitFor(() =>
      expect(fetch.mock.calls.some(([url]) => String(url) === `/api/scans?limit=25&workspace_id=${FINANCE.id}`)).toBe(true),
    );
    expect(window.localStorage.getItem("sahifa.workspace")).toBe(FINANCE.id);
  });

  it("asks where an upload goes when the person may upload to several workspaces", async () => {
    const both: Me = { ...ANA, workspaces: [{ ...DEFAULT_WORKSPACE, role: "editor" }, { ...FINANCE, role: "admin" }] };
    const fetch = stubFetch((url) => (url === "/api/scans/upload" ? json({ id: "s1" }, 202) : { items: [] }), { me: both });
    renderApp("/scans/new");
    const user = userEvent.setup();
    const where = await screen.findByRole("combobox", { name: "Upload to workspace" });
    expect((where as HTMLSelectElement).value).toBe(DEFAULT_WORKSPACE.id);
    await user.selectOptions(where, "Finance");
    const input = document.querySelector<HTMLInputElement>('input[type="file"]')!;
    await user.upload(input, new File(["id\n1\n"], "a.csv", { type: "text/csv" }));
    await user.click(screen.getByRole("button", { name: "Start scan" }));
    await waitFor(() => expect(fetch.mock.calls.some(([url]) => url === "/api/scans/upload")).toBe(true));
    const body = fetch.mock.calls.find(([url]) => url === "/api/scans/upload")![1]!.body as FormData;
    expect(body.get("workspace_id")).toBe(FINANCE.id);
  });

  it("disables uploads for someone who only views", async () => {
    const viewer: Me = { ...ANA, workspaces: [{ ...FINANCE, role: "viewer" }] };
    stubFetch(() => ({ items: [] }), { me: viewer });
    renderApp("/scans/new");
    const start = await screen.findByRole("button", { name: "Start scan" });
    expect(start).toHaveProperty("disabled", true);
    expect(screen.getByText(VIEWER_REASON)).toBeTruthy();
  });
});

describe("/workspaces (spec 016)", () => {
  const workspaces: Workspace[] = [
    { ...DEFAULT_WORKSPACE, connections: 1, members: 1, created_at: "2026-10-10T08:00:00Z" },
    { ...FINANCE, role: "admin", connections: 0, members: 0, created_at: "2026-10-10T09:00:00Z" },
  ];
  const members: Member[] = [
    { user_id: "u2", email: "bo@example.org", display_name: "Bo", role: "viewer", last_login_at: "2026-10-09T08:00:00Z" },
  ];
  const ORG_ADMIN: Me = { ...DEV_ME, workspaces: [DEFAULT_WORKSPACE, { ...FINANCE, role: "admin" }] };
  const invitation: Invitation = {
    id: "i1",
    workspace_id: DEFAULT_WORKSPACE.id,
    email: "cy@example.org",
    role: "editor",
    created_at: "2026-10-10T08:00:00Z",
    expires_at: "2026-10-17T08:00:00Z",
    status: "open",
    accepted_at: null,
  };
  const created: InvitationCreated = { ...invitation, id: "i2", email: "dee@example.org", link: "https://sahifa.test/invite#tok123" };

  function serve() {
    return stubFetch(
      (url, init) => {
        const method = init?.method ?? "GET";
        if (url === "/api/workspaces" && method === "GET") return workspaces;
        if (url === "/api/workspaces" && method === "POST") return json({ ...workspaces[1], id: "w3", name: "Ops" }, 201);
        if (url.endsWith("/invitations") && method === "POST") return json(created, 201);
        if (url.endsWith("/invitations")) return url.includes(DEFAULT_WORKSPACE.id) ? [invitation] : [];
        if (url.startsWith("/api/invitations/") && method === "DELETE") return new Response(null, { status: 204 });
        if (url === `/api/workspaces/${FINANCE.id}` && method === "DELETE") return new Response(null, { status: 204 });
        if (url.startsWith("/api/workspaces/") && url.endsWith("/members")) return url.includes(DEFAULT_WORKSPACE.id) ? members : [];
        if (url.includes("/members/")) return method === "DELETE" ? new Response(null, { status: 204 }) : members[0];
        if (url.startsWith("/api/workspaces/") && method === "PATCH") return workspaces[0];
        if (url.startsWith("/api/users")) return [{ id: "u3", email: "cy@example.org", display_name: "Cy" }];
        if (url.endsWith("/workspace") && method === "PUT") return connection({ workspace: { id: FINANCE.id, name: "Finance" } });
        if (url.startsWith("/api/connections")) return { items: [connection({ role: "admin" })] };
        return {};
      },
      { me: ORG_ADMIN },
    );
  }

  function sent(fetch: ReturnType<typeof stubFetch>, method: string, path: string) {
    const call = fetch.mock.calls.find(([url, init]) => url === path && init?.method === method);
    return call ? (call[1]?.body ? JSON.parse(String(call[1].body)) : null) : undefined;
  }

  it("creates and renames workspaces", async () => {
    const fetch = serve();
    renderApp("/workspaces");
    const user = userEvent.setup();
    const create = await screen.findByRole("form", { name: "Create a workspace" });
    await user.type(within(create).getByRole("textbox", { name: "Name" }), "Ops");
    await user.click(within(create).getByRole("button", { name: "Create" }));
    await waitFor(() => expect(sent(fetch, "POST", "/api/workspaces")).toEqual({ name: "Ops" }));
    const rename = screen.getByRole("form", { name: "Rename Default" });
    const name = within(rename).getByRole("textbox", { name: "Name" });
    await user.clear(name);
    await user.type(name, "Shop");
    await user.click(within(rename).getByRole("button", { name: "Rename" }));
    await waitFor(() => expect(sent(fetch, "PATCH", `/api/workspaces/${DEFAULT_WORKSPACE.id}`)).toEqual({ name: "Shop" }));
  });

  it("changes, removes and adds members", async () => {
    const fetch = serve();
    renderApp("/workspaces");
    const user = userEvent.setup();
    const role = await screen.findByRole("combobox", { name: "Role of bo@example.org" });
    await user.selectOptions(role, "editor");
    await waitFor(() => expect(sent(fetch, "PUT", `/api/workspaces/${DEFAULT_WORKSPACE.id}/members/u2`)).toEqual({ role: "editor" }));
    await user.click(screen.getByRole("button", { name: "Remove bo@example.org" }));
    await waitFor(() => expect(sent(fetch, "DELETE", `/api/workspaces/${DEFAULT_WORKSPACE.id}/members/u2`)).toBe(null));
    const [search] = screen.getAllByRole("textbox", { name: "Email or name" });
    await user.type(search!, "cy");
    const add = await screen.findByRole("button", { name: "Add" });
    await user.click(add);
    await waitFor(() => expect(sent(fetch, "PUT", `/api/workspaces/${DEFAULT_WORKSPACE.id}/members/u3`)).toEqual({ role: "viewer" }));
  });

  it("moves a connection to another workspace", async () => {
    const fetch = serve();
    renderApp("/workspaces");
    const user = userEvent.setup();
    const move = await screen.findByRole("combobox", { name: "Move to workspace…" });
    await user.selectOptions(move, "Finance");
    await user.click(screen.getByRole("button", { name: "Move" }));
    await waitFor(() =>
      expect(sent(fetch, "PUT", "/api/connections/c0000000-0000-4000-8000-000000000001/workspace")).toEqual({ workspace_id: FINANCE.id }),
    );
  });
  it("creates an invitation link, shows it once and revokes an open one (spec 020)", async () => {
    const fetch = serve();
    renderApp("/workspaces");
    const user = userEvent.setup();
    const form = await screen.findByRole("form", { name: "Invite to Default" });
    await user.type(within(form).getByRole("textbox", { name: "Email" }), "dee@example.org");
    await user.selectOptions(within(form).getByRole("combobox", { name: "as" }), "editor");
    await user.click(within(form).getByRole("button", { name: "Create link" }));
    await waitFor(() =>
      expect(sent(fetch, "POST", `/api/workspaces/${DEFAULT_WORKSPACE.id}/invitations`)).toEqual({ email: "dee@example.org", role: "editor" }),
    );
    const link = await screen.findByRole("textbox", { name: "Invitation link" });
    expect((link as HTMLInputElement).value).toBe("https://sahifa.test/invite#tok123");
    const writeText = vi.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    await user.click(screen.getByRole("button", { name: "Copy link" }));
    expect(writeText).toHaveBeenCalledWith("https://sahifa.test/invite#tok123");
    expect(await screen.findByRole("button", { name: "Copied" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Revoke the invitation of cy@example.org" }));
    await waitFor(() => expect(sent(fetch, "DELETE", "/api/invitations/i1")).toBe(null));
  });

  it("deletes a workspace only after its name is typed (spec 020)", async () => {
    const fetch = serve();
    renderApp("/workspaces");
    const user = userEvent.setup();
    const finance = (await screen.findByRole("heading", { name: "Finance" })).closest("section")!;
    expect(within(screen.getByRole("heading", { name: /Default/ }).closest("section")!).queryByRole("button", { name: /Delete workspace/ })).toBeNull();
    await user.click(within(finance).getByRole("button", { name: "Delete workspace…" }));
    const confirm = within(finance).getByRole("button", { name: "Delete" });
    expect((confirm as HTMLButtonElement).disabled).toBe(true);
    await user.type(within(finance).getByRole("textbox", { name: "Type the name to confirm" }), "Finance");
    await user.click(confirm);
    await waitFor(() => expect(sent(fetch, "DELETE", `/api/workspaces/${FINANCE.id}`)).toEqual({ confirm: "Finance" }));
  });
});

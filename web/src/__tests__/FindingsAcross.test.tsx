import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { FINDING_STALE_MESSAGE } from "../components/StoredFindingCard";
import type { FindingStatus, StoredFinding, StoredFindingDetail } from "../types";
import { SCAN_ID, fetchedUrls, json, makeFinding, makeReport, renderApp, stubFetch } from "./helpers";

const CONN = "c0000000-0000-4000-8000-000000000001";
const OTHER = "c0000000-0000-4000-8000-000000000002";

function stored(id: string, status: FindingStatus, overrides: Partial<StoredFinding> = {}): StoredFinding {
  return {
    id,
    status,
    severity: "critical",
    occurrences: 3,
    first_seen_at: "2026-10-01T06:00:13Z",
    last_seen_at: "2026-10-03T06:00:13Z",
    muted_until: null,
    version: 1,
    check: { id: `k-${id}`, key: `sah.foreign_key:orders:${id}`, type: "sah.foreign_key", title: "Orphan references", status: "active", column: id },
    asset: { id: "a1", label: "orders", connection_id: CONN },
    latest: {
      scan_id: SCAN_ID,
      summary: `Summary of ${id}.`,
      failed: 25,
      evaluated: 1000,
      ratio: 0.975,
      low: 0.975,
      high: 0.975,
      dimension: "consistency",
    },
    ...overrides,
  };
}

function initial(): StoredFinding[] {
  return [
    stored("customer_id", "open"),
    stored("email", "acknowledged", { severity: "high", occurrences: 1 }),
    stored("iban", "muted", { severity: "high", muted_until: "2026-12-31T20:59:59Z" }),
    stored("vat_id", "resolved", { severity: "medium" }),
  ];
}

const NEXT: Record<string, FindingStatus> = {
  acknowledge: "acknowledged",
  resolve: "resolved",
  mute: "muted",
  unmute: "open",
  reopen: "open",
};

function detail(f: StoredFinding): StoredFindingDetail {
  return {
    ...f,
    occurrences_list: [
      {
        scan_id: SCAN_ID,
        at: "2026-10-03T06:00:13Z",
        failed: 25,
        evaluated: 1000,
        ratio: 0.975,
        low: 0.975,
        high: 0.975,
        summary: "25 of 1,000 orders refer to a missing customer.",
        examples: [{ value: "a***@example.org", count: 2, masked: true }],
        sql: 'SELECT o.customer_id FROM "orders" AS o',
        next_step: "Load customers before orders.",
      },
    ],
    events: [
      { at: "2026-10-03T07:00:00Z", actor: "ana@example.org", action: "acknowledge", from_status: "open", to_status: "acknowledged", note: "<b>on it</b>" },
      { at: "2026-10-01T06:00:13Z", actor: "scanner", action: "opened", from_status: null, to_status: "open", note: null },
    ],
  };
}

type Post = { id: string; action: string; body: Record<string, unknown>; headers: Record<string, string> };

/** A fake API: the list (two per page, filtered by status as the server would), the detail,
 * the connections and the actions. */
function serve(onPost?: (post: Post) => Response | undefined) {
  let findings = initial();
  const posts: Post[] = [];
  let listCalls = 0;
  const fetch = stubFetch((url, init) => {
    if (url === "/api/connections")
      return {
        items: [
          { id: CONN, name: "shop", kind: "duckdb", config: {}, secret_ref: "SAHIFA_CONN_SHOP", available: true, created_at: "2026-10-01T00:00:00Z" },
          { id: OTHER, name: "crm", kind: "postgres", config: {}, secret_ref: "SAHIFA_CONN_CRM", available: true, created_at: "2026-10-01T00:00:00Z" },
        ],
      };
    if (url.startsWith("/api/findings?")) {
      listCalls += 1;
      const q = new URL(url, "http://x").searchParams;
      const statuses = q.getAll("status").length ? q.getAll("status") : ["open", "acknowledged", "muted"];
      const matching = findings.filter(
        (f) =>
          statuses.includes(f.status) &&
          (!q.get("severity") || f.severity === q.get("severity")) &&
          (!q.get("connection_id") || f.asset.connection_id === q.get("connection_id")),
      );
      const start = q.get("cursor") ? Number(q.get("cursor")) : 0;
      const next = start + 2 < matching.length ? String(start + 2) : null;
      return { items: matching.slice(start, start + 2), next_cursor: next };
    }
    const action = /^\/api\/findings\/([^/]+)\/([a-z]+)$/.exec(url);
    if (action && init?.method === "POST") {
      const post = {
        id: action[1]!,
        action: action[2]!,
        body: JSON.parse(String(init.body)) as Record<string, unknown>,
        headers: init.headers as Record<string, string>,
      };
      posts.push(post);
      const override = onPost?.(post);
      if (override) return override;
      findings = findings.map((f) =>
        f.id === post.id
          ? { ...f, status: NEXT[post.action]!, version: f.version + 1, muted_until: (post.body.until as string | undefined) ?? null }
          : f,
      );
      return findings.find((f) => f.id === post.id);
    }
    const one = /^\/api\/findings\/([^/?]+)$/.exec(url);
    if (one) {
      const f = findings.find((x) => x.id === one[1]);
      return f ? detail(f) : json({ detail: "finding not found" }, 404);
    }
    throw new Error(`unexpected ${init?.method ?? "GET"} ${url}`);
  });
  return { fetch, posts, listCalls: () => listCalls, set: (f: StoredFinding[]) => (findings = f) };
}

function card(name: RegExp | string) {
  return screen.getByRole("article", { name: typeof name === "string" ? new RegExp(name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")) : name });
}

function buttons(name: string): string[] {
  return within(card(name))
    .getAllByRole("button")
    .map((b) => b.textContent ?? "");
}

describe("Findings across scans", () => {
  it("lists findings needing attention by default, filters and loads more", async () => {
    const { fetch } = serve();
    const user = userEvent.setup();
    const { router } = renderApp("/findings");

    await screen.findByText("2+ findings, most severe first.");
    expect(fetchedUrls(fetch)).toContain("/api/findings?limit=50");
    expect((screen.getByLabelText("Status") as HTMLSelectElement).value).toBe("attention");
    expect(screen.getByRole("link", { name: "Findings" }).getAttribute("aria-current")).toBe("page");
    const first = card("Critical finding, Open: Summary of customer_id.");
    expect(within(first).getByText("Orphan references")).toBeTruthy();
    expect(within(first).getByText("orders.customer_id")).toBeTruthy();
    expect(first.textContent).toContain("Seen 3 times, first 2026-10-01 09:00 UTC+03:00, last 2026-10-03 09:00 UTC+03:00");
    expect(first.textContent).toContain("25 of 1,000 · 2.5 % · full read");
    expect(card("High finding, Acknowledged").textContent).toContain("Seen once");

    await user.click(screen.getByRole("button", { name: "Load more" }));
    const muted = await screen.findByRole("article", { name: /High finding, Muted/ });
    expect(muted.textContent).toContain("Muted until2026-12-31 23:59 UTC+03:00");
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
    expect(screen.queryByRole("article", { name: /Resolved/ })).toBeNull();
    expect(fetchedUrls(fetch)).toContain("/api/findings?limit=50&cursor=2");

    await user.selectOptions(screen.getByLabelText("Status"), "resolved");
    await waitFor(() => expect(router.state.location.search).toEqual({ status: "resolved" }));
    expect(await screen.findByRole("article", { name: /Medium finding, Resolved/ })).toBeTruthy();
    expect(fetchedUrls(fetch)).toContain("/api/findings?status=resolved&limit=50");

    await user.selectOptions(screen.getByLabelText("Status"), "all");
    await user.selectOptions(screen.getByLabelText("Severity"), "high");
    await screen.findByText("2 findings, most severe first.");
    expect(fetchedUrls(fetch)).toContain(
      "/api/findings?status=open&status=acknowledged&status=resolved&status=muted&severity=high&limit=50",
    );

    await user.selectOptions(screen.getByLabelText("Connection"), "crm");
    expect(await screen.findByText("No findings match these filters.")).toBeTruthy();
    expect(router.state.location.search).toEqual({ status: "all", severity: "high", connection: OTHER });

    await user.click(screen.getByRole("button", { name: "Reset filters" }));
    // Back to the first view, with the page loaded earlier.
    await screen.findByText("3 findings, most severe first.");
    expect(router.state.location.search).toEqual({});
  });

  it("offers the actions each status allows", async () => {
    serve();
    renderApp("/findings?status=all");
    await screen.findByText("2+ findings, most severe first.");
    await userEvent.setup().click(screen.getByRole("button", { name: "Load more" }));
    await screen.findByRole("article", { name: /Resolved/ });
    const actions = (name: string) => buttons(name).filter((b) => !["Add a note", "Show history"].includes(b));
    expect(actions("Open: Summary of customer_id.")).toEqual(["Acknowledge", "Resolve", "Mute…"]);
    expect(actions("Acknowledged: Summary of email.")).toEqual(["Resolve", "Mute…"]);
    expect(actions("Muted: Summary of iban.")).toEqual(["Unmute", "Resolve"]);
    expect(actions("Resolved: Summary of vat_id.")).toEqual(["Reopen"]);
  });

  it("sends each action with the CSRF header, the version and an optional note, and updates the card", async () => {
    const { posts } = serve();
    const user = userEvent.setup();
    renderApp("/findings");
    await screen.findByText("2+ findings, most severe first.");

    await user.click(within(card("Open: Summary of customer_id.")).getByRole("button", { name: "Acknowledge" }));
    const updated = await screen.findByRole("article", { name: /Critical finding, Acknowledged: Summary of customer_id/ });
    expect(within(updated).getByText("Acknowledged")).toBeTruthy();
    expect(posts[0]).toMatchObject({ id: "customer_id", action: "acknowledge", body: { version: 1 } });
    expect(posts[0]!.headers["X-Sahifa-Request"]).toBe("1");

    await user.click(within(updated).getByRole("button", { name: "Add a note" }));
    await user.type(within(updated).getByLabelText("Note (optional)"), "Fixed in the loader.");
    await user.click(within(updated).getByRole("button", { name: "Resolve" }));
    await screen.findByRole("article", { name: /Critical finding, Resolved: Summary of customer_id/ });
    expect(posts[1]).toMatchObject({ action: "resolve", body: { version: 2, note: "Fixed in the loader." } });
    // The card stays in place until the next reload, now offering Reopen.
    expect(buttons("Resolved: Summary of customer_id.")).toContain("Reopen");
  });

  it("mutes with an optional end date and a note", async () => {
    const { posts } = serve();
    const user = userEvent.setup();
    renderApp("/findings");
    await screen.findByText("2+ findings, most severe first.");

    const open = card("Open: Summary of customer_id.");
    await user.click(within(open).getByRole("button", { name: "Mute…" }));
    const form = within(open).getByRole("form", { name: "Mute this finding" });
    await user.type(within(form).getByLabelText(/Mute until/), "2099-12-31");
    await user.type(within(form).getByLabelText("Note (optional)"), "Known; the CRM team owns it.");
    await user.click(within(form).getByRole("button", { name: "Mute" }));

    const muted = await screen.findByRole("article", { name: /Critical finding, Muted: Summary of customer_id/ });
    expect(posts[0]).toMatchObject({
      action: "mute",
      body: { version: 1, until: new Date("2099-12-31T23:59:59").toISOString(), note: "Known; the CRM team owns it." },
    });
    expect(posts[0]!.body.until).toBe("2099-12-31T20:59:59.000Z");
    expect(muted.textContent).toContain("Muted until2099-12-31 23:59 UTC+03:00");

    // Without a date: muted until someone unmutes.
    const email = card("Acknowledged: Summary of email.");
    await user.click(within(email).getByRole("button", { name: "Mute…" }));
    await user.click(within(within(email).getByRole("form", { name: "Mute this finding" })).getByRole("button", { name: "Mute" }));
    const indefinitely = await screen.findByRole("article", { name: /High finding, Muted: Summary of email/ });
    expect(posts[1]).toMatchObject({ action: "mute", body: { version: 1 } });
    expect(posts[1]!.body).not.toHaveProperty("until");
    expect(indefinitely.textContent).toContain("Muted untilIndefinitely");
  });

  it("reloads the list with a notice on stale_version", async () => {
    const api = serve((post) => {
      api.set(initial().map((f) => (f.id === post.id ? { ...f, status: "acknowledged", version: 2 } : f)));
      return json({ detail: "stale_version", version: 2, message: "Someone changed this finding; reload it and try again." }, 409);
    });
    const user = userEvent.setup();
    renderApp("/findings");
    await screen.findByText("2+ findings, most severe first.");
    const before = api.listCalls();

    await user.click(within(card("Open: Summary of customer_id.")).getByRole("button", { name: "Resolve" }));

    expect((await screen.findByText(FINDING_STALE_MESSAGE)).getAttribute("role")).toBe("status");
    await screen.findByRole("article", { name: /Critical finding, Acknowledged: Summary of customer_id/ });
    expect(api.listCalls()).toBeGreaterThan(before);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows other errors on the card", async () => {
    serve(() => json({ detail: "invalid_transition", status: "resolved", message: "A resolved finding cannot be changed with resolve." }, 409));
    renderApp("/findings");
    await screen.findByText("2+ findings, most severe first.");
    await userEvent.setup().click(within(card("Open: Summary of customer_id.")).getByRole("button", { name: "Resolve" }));
    expect((await screen.findByRole("alert")).textContent).toContain("A resolved finding cannot be changed with resolve.");
    expect(screen.queryByText(FINDING_STALE_MESSAGE)).toBeNull();
  });

  it("shows the occurrences and the history on demand", async () => {
    const { fetch } = serve();
    const user = userEvent.setup();
    renderApp("/findings");
    await screen.findByText("2+ findings, most severe first.");
    const open = card("Open: Summary of customer_id.");
    const toggle = within(open).getByRole("button", { name: "Show history" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");

    await user.click(toggle);
    const occurrences = await within(open).findByRole("region", { name: "Occurrences" });
    expect(fetchedUrls(fetch)).toContain("/api/findings/customer_id");
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(occurrences.textContent).toContain("25 of 1,000 orders refer to a missing customer.");
    expect(within(occurrences).getByText("a***@example.org")).toBeTruthy();
    expect(within(occurrences).getByText("(masked)")).toBeTruthy();
    expect(occurrences.querySelector("pre")!.textContent).toContain('FROM "orders"');
    expect(occurrences.textContent).toContain("Next step: Load customers before orders.");
    expect(within(occurrences).getByRole("link", { name: /Scan of 2026-10-03/ }).getAttribute("href")).toBe(`/scans/${SCAN_ID}`);

    const history = within(open).getByRole("region", { name: "History" });
    const items = within(history).getAllByRole("listitem");
    expect(items[0]!.textContent).toContain("Acknowledged · ana@example.org");
    expect(items[0]!.textContent).toContain("Open → Acknowledged");
    // Notes are text: the markup shows as typed and makes no element.
    expect(within(items[0]!).getByText("<b>on it</b>")).toBeTruthy();
    expect(items[0]!.querySelector("b")).toBeNull();
    expect(items[1]!.textContent).toContain("Opened by a scan · Sahifa");
  });

  it("opens one finding at its own address", async () => {
    serve();
    renderApp("/findings/email");
    expect(await screen.findByRole("article", { name: /High finding, Acknowledged: Summary of email/ })).toBeTruthy();
    expect(await screen.findByRole("region", { name: "History" })).toBeTruthy();
    const crumbs = screen.getByRole("navigation", { name: "Breadcrumb" });
    expect(within(crumbs).getByRole("link", { name: "Findings" }).getAttribute("href")).toBe("/findings");
  });
});

describe("Scan findings with their status across scans", () => {
  it("shows each finding's status chip and links to it", async () => {
    stubFetch((url) => {
      if (url === `/api/scans/${SCAN_ID}/report`) return makeReport();
      if (url.startsWith(`/api/scans/${SCAN_ID}/findings`))
        return {
          items: [
            makeFinding({ id: "o1", summary: "Linked finding.", finding_id: "f-1", finding_status: "acknowledged" }),
            makeFinding({ id: "o2", summary: "Old finding.", severity: "low", finding_id: null, finding_status: null }),
          ],
        };
      throw new Error(`unexpected ${url}`);
    });
    renderApp(`/scans/${SCAN_ID}/findings`);
    const linked = await screen.findByRole("article", { name: /Linked finding/ });
    expect(within(linked).getByText("Acknowledged")).toBeTruthy();
    expect(within(linked).getByRole("link", { name: /Status and history of this finding/ }).getAttribute("href")).toBe("/findings/f-1");
    const old = screen.getByRole("article", { name: /Old finding/ });
    expect(within(old).queryByRole("link", { name: /Status and history/ })).toBeNull();
    expect(within(old).queryByText("Acknowledged")).toBeNull();
  });
});

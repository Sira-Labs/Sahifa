import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { EXAMPLES_SKIPPED } from "../components/Examples";
import { SCAN_ID, makeFinding, makeReport, renderApp, stubFetch } from "./helpers";

const BASE = `/api/scans/${SCAN_ID}/findings`;

function stub() {
  const findings = makeReport().findings;
  return stubFetch((url) => {
    if (url === `/api/scans/${SCAN_ID}/report`) return makeReport();
    if (url.startsWith(BASE)) {
      const q = new URL(url, "http://x").searchParams;
      return {
        items: findings.filter(
          (f) =>
            (!q.get("severity") || f.severity === q.get("severity")) &&
            (!q.get("dimension") || f.dimension === q.get("dimension")) &&
            (!q.get("asset") || f.asset === q.get("asset")),
        ),
      };
    }
    throw new Error(`unexpected ${url}`);
  });
}

describe("Findings", () => {
  it("says why a finding has no examples when the scan skipped them (spec 013)", async () => {
    const skipped = makeFinding({ summary: "Skipped: many failures.", examples: [], examples_skipped: true });
    stubFetch((url) => {
      if (url === `/api/scans/${SCAN_ID}/report`) return makeReport({ findings: [skipped] });
      if (url.startsWith(BASE)) return { items: [{ ...skipped, examples: undefined, evidence: { examples: [], examples_skipped: true } }] };
      throw new Error(`unexpected ${url}`);
    });
    renderApp(`/scans/${SCAN_ID}/findings`);
    expect(await screen.findByText(EXAMPLES_SKIPPED)).toBeTruthy();
  });

  it("lists findings by severity then failed share, with check, place, counts, examples, SQL and next step", async () => {
    stub();
    renderApp(`/scans/${SCAN_ID}/findings`);

    await screen.findByText("6 findings, most severe first.");
    const cards = screen.getAllByRole("article", { name: /finding:/ });
    expect(cards.map((c) => within(c).getByRole("heading").textContent)).toEqual([
      "Critical B: invalid IBANs.",
      "Critical A: 312 orphan orders.",
      "High A: future order dates.",
      "High B: duplicate order ids.",
      "High C: negative amounts.",
      "Medium: casing variants of city names.",
    ]);
    const card = cards[1]!;
    expect(within(card).getByText("Critical")).toBeTruthy();
    expect(within(card).getByText("orders.customer_id.foreign_key")).toBeTruthy();
    expect(within(card).getByRole("link", { name: "orders.customer_id" }).getAttribute("href")).toBe(`/scans/${SCAN_ID}/assets/orders`);
    expect(card.textContent).toContain("312 of 5,000 · 6.2 % · 5.6–6.9 %");
    expect(within(card).getByText("a***@example.org")).toBeTruthy();
    expect(within(card).getByText("(masked)")).toBeTruthy();
    expect(card.textContent).toContain("Next step: Find where orders are loaded before their customers.");
    expect(card.querySelector("pre")!.textContent).toContain('LEFT JOIN "customers"');
  });

  it("applies filters from the search params and updates them from the selects", async () => {
    const fetchFn = stub();
    const user = userEvent.setup();
    const { router } = renderApp(`/scans/${SCAN_ID}/findings?severity=high&dimension=bogus`);

    await screen.findByText("3 findings match these filters, most severe first.");
    expect(fetchFn.mock.calls.map((c) => c[0])).toContain(`${BASE}?severity=high`);
    expect((screen.getByLabelText("Severity") as HTMLSelectElement).value).toBe("high");
    expect((screen.getByLabelText("Dimension") as HTMLSelectElement).value).toBe("");

    await user.selectOptions(screen.getByLabelText("Table"), "customers");
    await waitFor(() => expect(router.state.location.search).toEqual({ severity: "high", asset: "customers" }));
    expect(await screen.findByText("No findings match these filters.")).toBeTruthy();
    expect(fetchFn.mock.calls.map((c) => c[0])).toContain(`${BASE}?severity=high&asset=customers`);

    await user.selectOptions(screen.getByLabelText("Severity"), "");
    await screen.findByText("1 finding matches these filters, most severe first.");
    expect(router.state.location.search).toEqual({ asset: "customers" });

    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    await screen.findByText("6 findings, most severe first.");
    expect(router.state.location.search).toEqual({});
  });

  it("copies the SQL", async () => {
    stub();
    const writeText = vi.fn(async () => undefined);
    const user = userEvent.setup();
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    renderApp(`/scans/${SCAN_ID}/findings?severity=critical&asset=orders`);

    const card = await screen.findByRole("article", { name: /finding:/ });
    await user.click(within(card).getByText("SQL"));
    await user.click(within(card).getByRole("button", { name: "Copy SQL" }));
    expect(writeText).toHaveBeenCalledWith(makeFinding().sql);
    expect(await within(card).findByText("Copied")).toBeTruthy();
  });
});

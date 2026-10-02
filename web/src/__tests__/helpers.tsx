import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory } from "@tanstack/react-router";
import { render } from "@testing-library/react";
import { vi } from "vitest";
import type { Me } from "../auth";
import { makeRouter } from "../router";
import type { AssetReport, CheckResult, ColumnReport, Finding, Scan, ScanReport } from "../types";

export type Route = (url: string, init?: RequestInit) => unknown | Promise<unknown>;

/** JSON response helper. */
export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

/** The principal of a server without sign-in (dev mode): what most tests run as. */
export const DEV_ME: Me = {
  mode: "dev",
  user: { id: null, email: null, display_name: "Developer" },
  sign_in_method: "dev",
  admin: true,
};

/** A signed-in administrator (oidc mode, Google). */
export const ME: Me = {
  mode: "oidc",
  user: { id: "u1", email: "ana@example.org", display_name: "Ana" },
  sign_in_method: "google",
  admin: true,
};

/** Stub `fetch` with a router function; a returned Response is passed through, anything else is
 * JSON. `/api/version` always answers; `/api/auth/me` answers `me` (dev mode unless given). */
export function stubFetch(route: Route, { me = DEV_ME }: { me?: Me | Response } = {}) {
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.pathname + input.search : input.url;
    if (url === "/api/version") return json({ version: "0.1.0", commit: "abc", schema_revision: "0002" });
    if (url === "/api/auth/me") return me instanceof Response ? me.clone() : json(me);
    const out = await route(url, init);
    return out instanceof Response ? out : json(out);
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

/** The URLs fetched so far, without the version and session calls. */
export function fetchedUrls(fn: ReturnType<typeof stubFetch>): string[] {
  return fn.mock.calls.map((c) => String(c[0])).filter((u) => u !== "/api/version" && u !== "/api/auth/me");
}

/** Render the app at `path` with a fresh query client and memory history. */
export function renderApp(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const router = makeRouter(createMemoryHistory({ initialEntries: [path] }));
  const view = render(
    <QueryClientProvider client={client}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { ...view, router, client };
}

export const SCAN_ID = "5ca70000-0000-4000-8000-000000000001";

/** A scan with sensible defaults: a finished upload of the faulty shop. */
export function makeScan(overrides: Partial<Scan> = {}): Scan {
  return {
    id: SCAN_ID,
    connection_id: "c0000000-0000-4000-8000-000000000001",
    connection_name: "shop",
    status: "succeeded",
    created_at: "2026-10-02T06:00:00Z",
    started_at: "2026-10-02T06:00:01Z",
    finished_at: "2026-10-02T06:00:13Z",
    error: null,
    sample_rows: 100000,
    score: { overall: 92.7, low: 92.3, high: 93.1 },
    findings: { critical: 2, high: 3, medium: 1, low: 0 },
    assets_count: 2,
    ...overrides,
  };
}

/** A finding with sensible defaults. */
export function makeFinding(overrides: Partial<Finding> = {}): Finding {
  return {
    id: crypto.randomUUID(),
    check_id: "orders.customer_id.foreign_key",
    check_type: "sah.foreign_key",
    title: "Foreign key",
    asset: "orders",
    column: "customer_id",
    dimension: "consistency",
    severity: "critical",
    evaluated: 5000,
    failed: 312,
    ratio: 0.9376,
    low: 0.931,
    high: 0.9437,
    summary: "312 orders refer to a customer that does not exist.",
    next_step: "Find where orders are loaded before their customers.",
    examples: [
      { value: "c-9001", count: 4, masked: false },
      { value: "a***@example.org", count: 2, masked: true },
    ],
    sql: 'SELECT o.customer_id, count(*)\nFROM "orders" AS o\nLEFT JOIN "customers" AS c ON o.customer_id = c.id\nWHERE c.id IS NULL\nGROUP BY 1',
    ...overrides,
  };
}

function check(overrides: Partial<CheckResult> & { type: string; column: string | null; passed: boolean }): CheckResult {
  const { type, column, passed, ...rest } = overrides;
  return {
    spec: {
      id: `orders.${column ?? "table"}.${type}`,
      type,
      asset: { namespace: "", name: "orders", kind: "file" },
      column,
      columns: column ? [column] : [],
      params: {},
      dimension: "completeness",
      severity: "high",
      kind: "rule",
      status: "active",
      max_fail_ratio: 0,
      origin: "generated",
    },
    evaluated: 5000,
    failed: passed ? 0 : 25,
    population: 5000,
    ratio: passed ? 1 : 0.995,
    low: passed ? 1 : 0.995,
    high: passed ? 1 : 0.995,
    passed,
    summary: passed ? `${type} passes.` : `${type}: 25 of 5,000 rows fail.`,
    next_step: passed ? "" : "Fix the loader.",
    examples: [],
    sql: passed ? null : "SELECT 1",
    truncated: false,
    ...rest,
  };
}

function column(name: string, overrides: Partial<ColumnReport["profile"]> = {}, value: number | null = 99.5): ColumnReport {
  return {
    profile: {
      name,
      position: 0,
      physical_type: "VARCHAR",
      logical_type: "text",
      role: "attribute",
      semantic_type: null,
      semantic_share: null,
      declared_not_null: false,
      rows: 5000,
      nulls: 50,
      distinct: 4800,
      blanks: 0,
      min: null,
      max: null,
      mean: null,
      stddev: null,
      quantiles: null,
      mad: null,
      zeros: null,
      negatives: null,
      min_length: 3,
      max_length: 40,
      mean_length: 12.5,
      whitespace: 0,
      non_printing: 0,
      numeric_like: null,
      date_like: null,
      leading_zero_numbers: null,
      future: null,
      before_1900: null,
      after_2200: null,
      newest: null,
      top: [{ value: "Berlin", count: 1200, masked: false }],
      top_truncated: false,
      patterns: [{ value: "Aa", count: 4900, masked: false }],
      ...overrides,
    },
    score: {
      overall: value,
      low: value === null ? null : value - 0.2,
      high: value === null ? null : value + 0.2,
      dimensions: value === null ? {} : { completeness: { value, low: value - 0.2, high: value + 0.2, checks: 1 } },
    },
  };
}

/** An asset of the report. */
export function makeAsset(name: string, overrides: Partial<AssetReport> = {}): AssetReport {
  return {
    ref: { namespace: "", name, kind: "file" },
    population: 5000,
    population_exact: true,
    sample_rows: 5000,
    sampled: false,
    score: {
      overall: 95.1,
      low: 95.1,
      high: 95.1,
      dimensions: { completeness: { value: 98.0, low: 98.0, high: 98.0, checks: 3 }, consistency: { value: 92.2, low: 92.2, high: 92.2, checks: 1 } },
    },
    columns: [column("customer_id", { role: "foreign_key", semantic_type: null }), column("city", {}, null)],
    checks: [
      check({ type: "sah.row_count", column: null, passed: true }),
      check({ type: "sah.not_null", column: "customer_id", passed: false }),
    ],
    time_series_candidate: false,
    error: null,
    ...overrides,
  };
}

/** A report: two tables, one sampled; six findings; one health item; two proposed checks. */
export function makeReport(overrides: Partial<ScanReport> = {}): ScanReport {
  const findings: Finding[] = [
    makeFinding({ severity: "medium", summary: "Medium: casing variants of city names.", ratio: 0.99 }),
    makeFinding({ severity: "critical", summary: "Critical A: 312 orphan orders.", ratio: 0.9376 }),
    makeFinding({ severity: "high", summary: "High B: duplicate order ids.", ratio: 0.999 }),
    makeFinding({ severity: "critical", summary: "Critical B: invalid IBANs.", ratio: 0.8, asset: "customers", column: "iban" }),
    makeFinding({ severity: "high", summary: "High A: future order dates.", ratio: 0.95 }),
    makeFinding({ severity: "high", summary: "High C: negative amounts.", ratio: 0.9995 }),
  ];
  return {
    report_version: 1,
    scan_id: SCAN_ID,
    started_at: "2026-10-02T06:00:01Z",
    finished_at: "2026-10-02T06:00:13Z",
    source: { kind: "duckdb", label: "shop" },
    options: { sample_rows: 100000, seed: 7 },
    score: {
      overall: 92.7,
      low: 92.3,
      high: 93.1,
      dimensions: {
        completeness: { value: 98.1, low: 97.8, high: 98.4, checks: 12 },
        validity: { value: 90.3, low: 89.9, high: 90.8, checks: 8 },
        accuracy: { value: 89.6, low: 88.1, high: 91.0, checks: 6 },
        consistency: { value: 94.2, low: 93.7, high: 94.6, checks: 4 },
        uniqueness: { value: 99.4, low: 99.4, high: 99.4, checks: 2 },
      },
    },
    assets: [
      makeAsset("orders"),
      makeAsset("customers", { population: 2_100_000, sample_rows: 100_000, sampled: true }),
    ],
    findings,
    health: [{ type: "store.numbers_as_text", asset: "orders", column: "amount", summary: "amount holds numbers stored as text." }],
    proposed: [
      check({ type: "sah.range", column: "amount", passed: false }),
      check({ type: "sah.length", column: "city", passed: true }),
    ],
    stats: { assets: 2, assets_failed: 0, columns: 4, checks_active: 32, checks_proposed: 2, queries: 9, duration_s: 12.4 },
    iso_25012: {},
    ...overrides,
  };
}

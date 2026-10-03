import { DIMENSIONS, SEVERITIES } from "./constants";
import type { Dimension, FindingFilters, FindingsSearch, FindingsView, Severity } from "./types";

// TanStack Router merges the raw search params with what validateSearch returns, so the
// validators name every key they own and set unknown values to undefined explicitly.

export type NewScanTab = "upload" | "connection";
export type NewScanSearch = { tab?: NewScanTab; connection?: string };

/** Search params of `/scans/new`. */
export function parseNewScanSearch(search: Record<string, unknown>): NewScanSearch {
  return {
    tab: search.tab === "upload" || search.tab === "connection" ? search.tab : undefined,
    connection: typeof search.connection === "string" && search.connection ? search.connection : undefined,
  };
}

/** Search params of the findings page; anything unknown is dropped rather than sent to the API. */
export function parseFindingFilters(search: Record<string, unknown>): FindingFilters {
  return {
    severity: typeof search.severity === "string" && SEVERITIES.includes(search.severity as Severity) ? (search.severity as Severity) : undefined,
    dimension:
      typeof search.dimension === "string" && DIMENSIONS.includes(search.dimension as Dimension) ? (search.dimension as Dimension) : undefined,
    asset: typeof search.asset === "string" && search.asset ? search.asset : undefined,
  };
}

const FINDINGS_VIEWS: readonly FindingsView[] = ["attention", "open", "acknowledged", "muted", "resolved", "all"];

/** Search params of `/findings` (spec 009); the default view (needing attention) is left out. */
export function parseFindingsSearch(search: Record<string, unknown>): FindingsSearch {
  const status = typeof search.status === "string" && FINDINGS_VIEWS.includes(search.status as FindingsView) ? (search.status as FindingsView) : undefined;
  return {
    status: status === "attention" ? undefined : status,
    severity: typeof search.severity === "string" && SEVERITIES.includes(search.severity as Severity) ? (search.severity as Severity) : undefined,
    connection: typeof search.connection === "string" && search.connection ? search.connection : undefined,
  };
}

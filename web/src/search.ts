import { DIMENSIONS, SEVERITIES } from "./constants";
import type { Dimension, FindingFilters, Severity } from "./types";

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

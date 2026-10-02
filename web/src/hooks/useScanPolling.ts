import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { POLL_INTERVAL_MS } from "../constants";
import type { ScanStatus } from "../types";

export const TERMINAL_STATUSES: ReadonlySet<ScanStatus> = new Set(["succeeded", "failed"]);

/** Whether a scan has finished, successfully or not. */
export function isTerminal(status: ScanStatus | undefined): boolean {
  return status !== undefined && TERMINAL_STATUSES.has(status);
}

/** The scan, fetched again every `intervalMs` while it is queued or running, then left alone.
 * An error stops the polling too; the page's Retry starts it again. */
export function useScanPolling(scanId: string, intervalMs: number = POLL_INTERVAL_MS) {
  return useQuery({
    queryKey: ["scan", scanId],
    queryFn: () => api.getScan(scanId),
    refetchInterval: (q) => {
      if (q.state.status === "error") return false;
      return isTerminal(q.state.data?.status) ? false : intervalMs;
    },
    refetchIntervalInBackground: false,
  });
}

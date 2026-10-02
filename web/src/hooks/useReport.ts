import { useQuery } from "@tanstack/react-query";
import { api } from "../api";

/** The finished report of a scan. It never changes once written, so it is not refetched. */
export function useReport(scanId: string, enabled = true) {
  return useQuery({
    queryKey: ["report", scanId],
    queryFn: () => api.getReport(scanId),
    enabled,
    staleTime: Infinity,
  });
}

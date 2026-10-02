import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { useScanPolling } from "../hooks/useScanPolling";
import { json, makeScan, stubFetch } from "./helpers";

/** Query client provider for the hook under test. */
function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const pause = (ms: number) => new Promise((r) => setTimeout(r, ms));

describe("useScanPolling", () => {
  it("polls while queued or running and stops when the scan succeeded", async () => {
    const statuses = ["queued", "running", "running", "succeeded"] as const;
    let calls = 0;
    const fetchFn = stubFetch(() => makeScan({ status: statuses[Math.min(calls++, statuses.length - 1)] }));

    const { result } = renderHook(() => useScanPolling("scan-1", 20), { wrapper });

    await waitFor(() => expect(result.current.data?.status).toBe("succeeded"));
    expect(fetchFn).toHaveBeenCalledTimes(4);
    expect(fetchFn.mock.calls[0]![0]).toBe("/api/scans/scan-1");
    await pause(120);
    expect(fetchFn).toHaveBeenCalledTimes(4);
  });

  it("stops on failed too", async () => {
    const fetchFn = stubFetch(() => makeScan({ status: "failed", error: "cannot parse CSV" }));
    const { result } = renderHook(() => useScanPolling("scan-2", 20), { wrapper });
    await waitFor(() => expect(result.current.data?.status).toBe("failed"));
    await pause(100);
    expect(fetchFn).toHaveBeenCalledTimes(1);
  });

  it("stops on an API error until retried", async () => {
    const fetchFn = stubFetch(() => json({ detail: "scan not found" }, 404));
    const { result } = renderHook(() => useScanPolling("scan-3", 20), { wrapper });
    await waitFor(() => expect(result.current.error?.message).toBe("scan not found"));
    await pause(100);
    expect(fetchFn).toHaveBeenCalledTimes(1);
  });
});

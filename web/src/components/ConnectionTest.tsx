import { useMutation } from "@tanstack/react-query";
import { api } from "../api";
import type { ConnectionTest as Result } from "../types";
import { StatusChip } from "./Chips";

/** "3 assets" from a test answer that carries a count or the names. */
function assetCount(result: Result): string {
  const n = Array.isArray(result.assets) ? result.assets.length : result.assets;
  return n === null || n === undefined ? "reachable" : `sees ${n} ${n === 1 ? "asset" : "assets"}`;
}

/** A Test button for one connection and what the test found. */
export function ConnectionTest({ connectionId, name }: { connectionId: string; name: string }) {
  const test = useMutation({ mutationFn: () => api.testConnection(connectionId) });
  return (
    <div className="conn-test">
      <button type="button" className="btn btn-small" onClick={() => test.mutate()} disabled={test.isPending} aria-label={`Test ${name}`}>
        {test.isPending ? "Testing…" : "Test"}
      </button>
      <span role="status" aria-live="polite" className="text-sm">
        {test.data &&
          (test.data.ok ? (
            <>
              <StatusChip status="available" /> <span className="num">{assetCount(test.data)}</span>
            </>
          ) : (
            <>
              <StatusChip status="unavailable" /> {test.data.error ?? "the test failed"}
            </>
          ))}
        {test.isError && <span className="text-bad">{test.error.message}</span>}
      </span>
    </div>
  );
}

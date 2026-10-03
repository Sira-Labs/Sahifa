import { useInfiniteQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { api } from "../api";
import { StatusChip } from "../components/Chips";
import { ErrorPanel } from "../components/ErrorPanel";
import { ScoreText } from "../components/ScoreText";
import { POLL_INTERVAL_MS, SCANS_PAGE_SIZE, SEVERITIES } from "../constants";
import { formatDuration, formatLocalTime, scanSource, secondsBetween } from "../format";
import { isTerminal } from "../hooks/useScanPolling";
import type { Scan } from "../types";

/** Open findings by severity, words included: "2 critical · 5 high". */
function FindingCounts({ scan }: { scan: Scan }) {
  if (scan.status !== "succeeded" || !scan.findings) return <span className="muted">—</span>;
  const parts = SEVERITIES.filter((s) => (scan.findings?.[s] ?? 0) > 0);
  if (parts.length === 0) return <span className="muted">none</span>;
  return (
    <span className="counts">
      {parts.map((s) => (
        <span key={s} className={`count count-${s}`}>
          <span className="num">{scan.findings?.[s]}</span> {s}
        </span>
      ))}
    </span>
  );
}

/** `/`: scans, newest first, with "Load more"; running scans refresh every 2 s. */
export function ScansList() {
  const scans = useInfiniteQuery({
    queryKey: ["scans"],
    queryFn: ({ pageParam }) => api.listScans(pageParam, SCANS_PAGE_SIZE),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    refetchInterval: (q) =>
      q.state.data?.pages.some((p) => p.items.some((s) => !isTerminal(s.status))) ? POLL_INTERVAL_MS : false,
  });
  const items = scans.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <section aria-labelledby="scans-heading" className="stack">
      <div className="page-head">
        <div>
          <p className="eyebrow">Data quality</p>
          <h1 id="scans-heading">Scans</h1>
        </div>
        <Link to="/scans/new" className="btn btn-primary">
          New scan
        </Link>
      </div>

      {scans.isPending && <p role="status">Loading scans…</p>}
      {scans.isError && <ErrorPanel title="Could not load the scans" error={scans.error} onRetry={() => void scans.refetch()} />}

      {scans.isSuccess && items.length === 0 && (
        <div className="card empty">
          <h2>No scans yet</h2>
          <p className="muted">
            Drop a few CSV, Parquet or JSON exports on the page, or pick a registered connection, and Sahifa profiles every
            table, writes the checks and scores each dimension with its interval.
          </p>
          <Link to="/scans/new" className="btn btn-primary">
            Start your first scan
          </Link>
        </div>
      )}

      {items.length > 0 && (
        <div className="table-card">
          <table className="rtable">
            <caption className="sr-only">Scans, newest first</caption>
            <thead>
              <tr>
                <th scope="col">When</th>
                <th scope="col">Source</th>
                <th scope="col">Status</th>
                <th scope="col">Score</th>
                <th scope="col">Findings</th>
                <th scope="col">Duration</th>
              </tr>
            </thead>
            <tbody>
              {items.map((scan) => (
                <tr key={scan.id}>
                  <td data-label="When" className="num">
                    <Link to="/scans/$scanId" params={{ scanId: scan.id }}>
                      {formatLocalTime(scan.created_at)}
                    </Link>
                  </td>
                  <td data-label="Source">
                    {scanSource(scan)}
                    {scan.trigger === "schedule" && (
                      <>
                        {" "}
                        <span className="tag" title="Started by the connection's schedule">
                          scheduled
                        </span>
                      </>
                    )}
                  </td>
                  <td data-label="Status">
                    <StatusChip status={scan.status} />
                  </td>
                  <td data-label="Score">
                    {scan.score ? <ScoreText
                        value={scan.score.overall}
                        low={scan.score.low}
                        high={scan.score.high}
                        read={scan.sample_rows === 0 ? "full" : undefined}
                      /> : <span className="muted">—</span>}
                  </td>
                  <td data-label="Findings">
                    <FindingCounts scan={scan} />
                  </td>
                  <td data-label="Duration" className="num">
                    {formatDuration(secondsBetween(scan.started_at, scan.finished_at))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {scans.hasNextPage && (
        <div>
          <button type="button" className="btn" onClick={() => void scans.fetchNextPage()} disabled={scans.isFetchingNextPage}>
            {scans.isFetchingNextPage ? "Loading…" : "Load more"}
          </button>
        </div>
      )}
    </section>
  );
}

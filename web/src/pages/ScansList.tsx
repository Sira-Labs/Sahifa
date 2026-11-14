import { useInfiniteQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "@tanstack/react-router";
import { api } from "../api";
import { StatusChip } from "../components/Chips";
import { DemoScanButton } from "../components/DemoScanButton";
import { ErrorPanel } from "../components/ErrorPanel";
import { ScoreText } from "../components/ScoreText";
import { POLL_INTERVAL_MS, SCANS_PAGE_SIZE, SEVERITIES } from "../constants";
import { formatDuration, formatLocalTime, scanSource, secondsBetween } from "../format";
import { isTerminal } from "../hooks/useScanPolling";
import type { Scan } from "../types";
import { VIEWER_REASON, editableWorkspaces, useMe, useShowsWorkspaces, useWorkspaceFilter } from "../workspace";

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

/** The start page of a fresh install (spec 022): what Sahifa does in three steps, and two ways
 * in, the demo shop or the person's own data. */
function FirstRun() {
  const navigate = useNavigate();
  const me = useMe();
  const readOnly = !!me.data && editableWorkspaces(me.data).length === 0;
  return (
    <div className="card empty">
      <h2>No scans yet</h2>
      <ol className="steps">
        <li>
          <span className="font-semibold">Point Sahifa at data.</span> Drop a few CSV, Parquet or JSON exports on the page, or pick a
          registered connection. Sahifa only reads.
        </li>
        <li>
          <span className="font-semibold">It profiles and checks every table.</span> Sahifa works out each column&rsquo;s type and
          meaning and writes the checks itself.
        </li>
        <li>
          <span className="font-semibold">Read the report.</span> A score per quality dimension with its interval, and every finding
          with examples, the SQL behind it and a next step.
        </li>
      </ol>
      <div className="actions">
        <DemoScanButton
          label="Try the demo data"
          className="btn btn-primary"
          onCreated={(scan) => void navigate({ to: "/scans/$scanId", params: { scanId: scan.id } })}
        />
        <Link to="/scans/new" className="btn">
          Scan your own data
        </Link>
      </div>
      <p className="muted text-sm">
        {readOnly
          ? VIEWER_REASON
          : "The demo is a made-up web shop with faults put in on purpose. Its report is ready in under a minute."}
      </p>
    </div>
  );
}

/** `/`: scans, newest first, with "Load more"; running scans refresh every 2 s. */
export function ScansList() {
  const workspace = useWorkspaceFilter();
  const showWorkspace = useShowsWorkspaces();
  const scans = useInfiniteQuery({
    queryKey: ["scans", workspace ?? null],
    queryFn: ({ pageParam }) => api.listScans(pageParam, SCANS_PAGE_SIZE, workspace),
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

      {scans.isSuccess && items.length === 0 && <FirstRun />}

      {items.length > 0 && (
        <div className="table-card">
          <table className="rtable">
            <caption className="sr-only">Scans, newest first</caption>
            <thead>
              <tr>
                <th scope="col">When</th>
                <th scope="col">Source</th>
                {showWorkspace && <th scope="col">Workspace</th>}
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
                  {showWorkspace && <td data-label="Workspace">{scan.workspace?.name ?? "—"}</td>}
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

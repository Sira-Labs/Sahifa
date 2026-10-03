import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useId, useState } from "react";
import { api } from "../api";
import { describeScore, formatIntervalRange, formatLocalTime, formatScore, formatScoreInterval } from "../format";
import type { HistoryPoint } from "../types";

/** The change from `before` to `after`, signed with one decimal: `+2.4`, `−1.3`, `±0.0`. */
export function formatDelta(before: number, after: number): string {
  const d = Math.round((after - before) * 10) / 10;
  if (d === 0) return "±0.0";
  return d > 0 ? `+${d.toFixed(1)}` : `−${Math.abs(d).toFixed(1)}`;
}

/** Whether two scores' 95 % intervals share any value, so the change may be sampling noise. */
export function intervalsOverlap(a: HistoryPoint, b: HistoryPoint): boolean {
  if (a.low === null || a.high === null || b.low === null || b.high === null) return false;
  return a.low <= b.high && b.low <= a.high;
}

/** A date short enough for a headline, in the browser's locale: `1 Oct` or `Oct 1`. */
function shortDate(value: string): string {
  return new Date(value).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** The change of the last point against the nearest earlier point that has a score. */
export function lastChange(points: HistoryPoint[]): { delta: string; since: HistoryPoint; within: boolean } | null {
  const last = points.at(-1);
  if (!last || last.overall === null) return null;
  const since = points
    .slice(0, -1)
    .reverse()
    .find((p) => p.overall !== null);
  if (!since || since.overall === null) return null;
  return { delta: formatDelta(since.overall, last.overall), since, within: intervalsOverlap(since, last) };
}

/** The smallest height of the y-axis, in score points, so sampling noise stays small. */
const MIN_SPAN = 4;

/** The y-axis: whole-number bounds around every score and interval shown, at least `MIN_SPAN`
 * tall, within 0–100. Scores that sit at 98–99 would be a flat line on a fixed 0–100 axis. */
export function yDomain(points: HistoryPoint[]): { min: number; max: number } {
  const values = points.flatMap((p) => [p.low ?? p.overall, p.high ?? p.overall]).filter((v): v is number => v !== null);
  if (values.length === 0) return { min: 0, max: 100 };
  let min = Math.floor(Math.min(...values));
  let max = Math.ceil(Math.max(...values));
  if (max - min < MIN_SPAN) {
    const grow = MIN_SPAN - (max - min);
    min -= Math.floor(grow / 2);
    max += Math.ceil(grow / 2);
  }
  if (min < 0) [min, max] = [0, Math.min(100, max - min)];
  if (max > 100) [min, max] = [Math.max(0, min - (max - 100)), 100];
  return { min, max };
}

type Domain = { min: number; max: number };

/** A score's height on the plot: 0 at the top bound, 100 at the bottom one. */
function yOf(v: number, d: Domain): number {
  return ((d.max - v) / (d.max - d.min)) * 100;
}

/** An axis bound, without a needless decimal. */
function tick(v: number): string {
  return Number.isInteger(v) ? String(v) : v.toFixed(1);
}

/** Runs of consecutive scored points; a scan without a score breaks the line. */
function runs(points: HistoryPoint[]): { x: number; p: HistoryPoint }[][] {
  const step = points.length > 1 ? 100 / (points.length - 1) : 0;
  const out: { x: number; p: HistoryPoint }[][] = [[]];
  points.forEach((p, i) => {
    if (p.overall === null) out.push([]);
    else out.at(-1)!.push({ x: i * step, p });
  });
  return out.filter((r) => r.length > 0);
}

/** A point's x and y on the 0–100 plot, as percentages of its box. */
function place(p: HistoryPoint, i: number, count: number, d: Domain): { left: number; top: number } {
  const left = count > 1 ? (i / (count - 1)) * 100 : 50;
  return { left, top: p.overall === null ? 100 : yOf(p.overall, d) };
}

function describePoint(p: HistoryPoint, current: boolean): string {
  const parts = [
    `${current ? "This scan" : "Scan"} of ${formatLocalTime(p.finished_at)}`,
    describeScore(p.overall, p.low, p.high),
    `${p.checks} ${p.checks === 1 ? "check" : "checks"}`,
  ];
  if (p.trigger === "schedule") parts.push("scheduled");
  return parts.join(", ");
}

type Props = {
  /** Heading, e.g. "Store score history". */
  title: string;
  /** Oldest first; the last point is the scan being viewed. */
  points: HistoryPoint[];
};

/** The score over the last scans (spec 011): a line on a fitted axis with the 95 % band, the
 * viewed scan accented, the change since the previous scored scan, each point a link to its
 * scan with its numbers on hover or focus, and the same points as a table. */
export function ScoreHistory({ title, points }: Props) {
  const titleId = useId();
  const tipId = useId();
  const [active, setActive] = useState<number | null>(null);
  const change = lastChange(points);
  const segments = runs(points);
  const domain = yDomain(points);
  const mid = (domain.min + domain.max) / 2;
  const shown = active === null ? undefined : points[active];
  const at = shown && active !== null ? place(shown, active, points.length, domain) : null;

  return (
    <section className="card history" aria-labelledby={titleId}>
      <div className="history-head">
        <h2 id={titleId} className="eyebrow">
          {title}
        </h2>
        {points.length > 1 && (
          <p className="history-summary">
            <span>
              Last {points.length} {points.length === 1 ? "scan" : "scans"}
            </span>
            {change && (
              <span className="num" data-testid="history-change">
                <b>{change.delta}</b> since {shortDate(change.since.finished_at)}
                {change.within && <span className="history-note"> · within the interval</span>}
              </span>
            )}
          </p>
        )}
      </div>

      {points.length < 2 ? (
        <p className="caption">History starts with this scan; the next scans add to it.</p>
      ) : (
        <>
          <div className="history-plot">
            <span className="history-axis num" aria-hidden="true">
              <span style={{ top: "0%" }}>{tick(domain.max)}</span>
              <span style={{ top: "50%" }}>{tick(mid)}</span>
              <span style={{ top: "100%" }}>{tick(domain.min)}</span>
            </span>
            <div className="history-area" onMouseLeave={() => setActive(null)}>
              <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true" focusable="false">
                {[0, 50, 100].map((y) => (
                  <line key={y} className="history-grid" x1="0" x2="100" y1={y} y2={y} vectorEffect="non-scaling-stroke" />
                ))}
                {segments.map((seg) => {
                  const key = seg[0]?.p.scan_id;
                  const banded = seg.every(({ p }) => p.low !== null && p.high !== null);
                  const upper = seg.map(({ x, p }) => `${x},${yOf(p.high ?? p.overall!, domain)}`);
                  const lower = seg.map(({ x, p }) => `${x},${yOf(p.low ?? p.overall!, domain)}`).reverse();
                  return (
                    <g key={key}>
                      {banded && seg.length > 1 && <polygon className="history-band" points={[...upper, ...lower].join(" ")} />}
                      {seg.length > 1 && (
                        <polyline
                          className="history-line"
                          points={seg.map(({ x, p }) => `${x},${yOf(p.overall!, domain)}`).join(" ")}
                          vectorEffect="non-scaling-stroke"
                        />
                      )}
                    </g>
                  );
                })}
              </svg>
              <ol className="history-points" aria-label={`${title}, one link per scan`}>
                {points.map((p, i) => {
                  const current = i === points.length - 1;
                  const { left, top } = place(p, i, points.length, domain);
                  return (
                    <li key={p.scan_id} style={{ left: `${left}%`, top: `${top}%` }}>
                      <Link
                        to="/scans/$scanId"
                        params={{ scanId: p.scan_id }}
                        className={`history-point${current ? " is-current" : ""}${p.overall === null ? " is-empty" : ""}`}
                        aria-label={describePoint(p, current)}
                        aria-current={current ? "page" : undefined}
                        aria-describedby={active === i ? tipId : undefined}
                        onMouseEnter={() => setActive(i)}
                        onFocus={() => setActive(i)}
                        onBlur={() => setActive(null)}
                      />
                    </li>
                  );
                })}
              </ol>
              {shown && at && (
                <div
                  id={tipId}
                  role="tooltip"
                  className={`history-tip${at.left < 20 ? " is-start" : at.left > 80 ? " is-end" : ""}${at.top < 45 ? " is-below" : ""}`}
                  style={{ left: `${at.left}%`, top: `${at.top}%` }}
                >
                  <span className="history-tip-date">{formatLocalTime(shown.finished_at)}</span>
                  <b className="num">{formatScoreInterval(shown.overall, shown.low, shown.high)}</b>
                  <span>
                    {shown.checks} {shown.checks === 1 ? "check" : "checks"}
                    {shown.trigger === "schedule" && " · scheduled"}
                  </span>
                </div>
              )}
            </div>
          </div>
          <details className="history-table">
            <summary>Show as table</summary>
            <table className="rtable">
              <thead>
                <tr>
                  <th scope="col">Scan</th>
                  <th scope="col" className="num">
                    Score
                  </th>
                  <th scope="col" className="num">
                    95 % interval
                  </th>
                  <th scope="col" className="num">
                    Checks
                  </th>
                  <th scope="col">Started by</th>
                </tr>
              </thead>
              <tbody>
                {points.map((p) => (
                  <tr key={p.scan_id}>
                    <td data-label="Scan">
                      <Link to="/scans/$scanId" params={{ scanId: p.scan_id }}>
                        {formatLocalTime(p.finished_at)}
                      </Link>
                    </td>
                    <td data-label="Score" className="num">
                      {formatScore(p.overall)}
                    </td>
                    <td data-label="95 % interval" className="num">
                      {formatIntervalRange(p.low, p.high) || "—"}
                    </td>
                    <td data-label="Checks" className="num">
                      {p.checks}
                    </td>
                    <td data-label="Started by">{p.trigger === "schedule" ? "schedule" : "a person"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </>
      )}
    </section>
  );
}

/** Loading and error states around the panel; a scan with no score here shows nothing. */
function HistoryState({
  title,
  points,
  isPending,
  isError,
}: {
  title: string;
  points: HistoryPoint[] | null | undefined;
  isPending: boolean;
  isError: boolean;
}) {
  if (isError) {
    return (
      <p role="alert" className="card caption">
        Could not load the score history.
      </p>
    );
  }
  if (isPending) return <p role="status">Loading the score history…</p>;
  if (!points || points.length === 0) return null;
  return <ScoreHistory title={title} points={points} />;
}

/** The store's history, ending at this scan. */
export function StoreHistory({ connectionId, scanId }: { connectionId: string; scanId: string }) {
  const history = useQuery({
    queryKey: ["history", "store", connectionId, scanId],
    queryFn: () => api.storeHistory(connectionId, scanId),
  });
  return <HistoryState title="Store score history" points={history.data} isPending={history.isPending} isError={history.isError} />;
}

/** A table's history, ending at this scan; the asset is found as the checks panel finds it. */
export function AssetHistory({ scanId, label }: { scanId: string; label: string }) {
  const scan = useQuery({ queryKey: ["scan", scanId], queryFn: () => api.getScan(scanId) });
  const connectionId = scan.data?.connection_id;
  const stored = useQuery({
    queryKey: ["asset", connectionId, label],
    queryFn: () => api.findAsset(connectionId!, label),
    enabled: !!connectionId,
  });
  const assetId = stored.data?.id;
  const history = useQuery({
    queryKey: ["history", "asset", assetId, scanId],
    queryFn: () => api.assetHistory(assetId!, scanId),
    enabled: !!assetId,
  });
  // No stored asset (a table the scan could not persist): nothing to show.
  if (stored.data === null) return null;
  return (
    <HistoryState
      title="Table score history"
      points={history.data}
      isPending={scan.isPending || stored.isPending || history.isPending}
      isError={scan.isError || stored.isError || history.isError}
    />
  );
}

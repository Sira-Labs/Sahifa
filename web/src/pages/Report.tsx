import { Link, getRouteApi } from "@tanstack/react-router";
import { SeverityChip, StatusChip } from "../components/Chips";
import { ErrorPanel } from "../components/ErrorPanel";
import { FindingCard } from "../components/FindingCard";
import { ScoreCard } from "../components/ScoreCard";
import { StoreHistory } from "../components/ScoreHistory";
import { ScoreText } from "../components/ScoreText";
import { SEVERITIES, TOP_FINDINGS } from "../constants";
import {
  assetColumn,
  assetLabel,
  formatCompact,
  formatCount,
  formatDuration,
  formatLocalTime,
  formatPassShare,
  samplePolicy,
  scanSource,
  sortFindings,
  titleCase,
  worstDimension,
  type ReadKind,
} from "../format";
import { useReport } from "../hooks/useReport";
import { useScanPolling } from "../hooks/useScanPolling";
import type { AssetReport, Scan, ScanReport } from "../types";

const routeApi = getRouteApi("/_app/scans/$scanId");

/** How the store was read: in full only when no table was sampled. */
export function storeRead(report: ScanReport): ReadKind {
  return report.assets.some((a) => a.sampled) ? "sampled" : "full";
}

/** The sentence under the score card: what the interval covers. */
export function intervalCaption(report: ScanReport): string {
  const sampled = report.assets.filter((a) => a.sampled);
  if (sampled.length === 0) {
    return "Every row of every table was read, so the intervals have zero width. They cover sampling uncertainty only, not problems no check looks for.";
  }
  const largest = Math.max(...sampled.map((a) => a.population));
  const rows = Math.max(...sampled.map((a) => a.sample_rows));
  const tables = report.assets.length;
  return (
    `The 95 % intervals cover sampling uncertainty from reading ${formatCount(rows)} of up to ${formatCompact(largest)} rows per table ` +
    `(${sampled.length} of ${tables} ${tables === 1 ? "table" : "tables"} sampled). They do not cover problems no check looks for.`
  );
}

/** Rows of an asset in words: "2.1 M rows · 100,000 read" or "5,000 rows · full read". */
function assetRows(a: AssetReport): string {
  const population = `${a.population_exact ? "" : "≈ "}${formatCompact(a.population)}`;
  return a.sampled ? `${population} · ${formatCount(a.sample_rows)} read` : `${population} · full read`;
}

function ReportHeader({ scan, report }: { scan?: Scan; report?: ScanReport }) {
  const source = report ? report.source.label : scan ? scanSource(scan) : "";
  return (
    <div className="page-head">
      <div className="min-w-0">
        <p className="eyebrow">Store report{report ? ` · ${report.source.kind}` : ""}</p>
        <h1 className="break-anywhere">{source || "Scan"}</h1>
        {report ? (
          <p className="meta-line">
            <span className="num">{formatLocalTime(report.started_at)}</span>
            <span>{samplePolicy(report.options.sample_rows)}</span>
            <span className="num">took {formatDuration(report.stats.duration_s)}</span>
            <span className="num">
              {formatCount(report.stats.assets)} {report.stats.assets === 1 ? "table" : "tables"} · {formatCount(report.stats.columns)} columns ·{" "}
              {formatCount(report.stats.checks_active)} active checks
            </span>
          </p>
        ) : (
          scan && (
            <p className="meta-line">
              <span className="num">{formatLocalTime(scan.created_at)}</span>
              <span>{samplePolicy(scan.sample_rows)}</span>
            </p>
          )
        )}
      </div>
      {scan && <StatusChip status={scan.status} />}
    </div>
  );
}

function Running({ scan }: { scan: Scan }) {
  return (
    <div role="status" className="card running">
      <p className="font-semibold">{scan.status === "queued" ? "Waiting for a free scan slot…" : "Scanning: profiling every table and running the checks…"}</p>
      <div className="progress" aria-hidden="true">
        <span />
      </div>
      <p className="muted text-sm">This page updates every 2 seconds. You can leave and come back; the scan keeps running.</p>
    </div>
  );
}

function Failed({ scan }: { scan: Scan }) {
  return (
    <div role="alert" className="card error-panel">
      <p className="font-semibold">The scan failed</p>
      <p className="break-anywhere">{scan.error ?? "The API gave no reason."}</p>
      <p className="muted text-sm">
        Fix the source and <Link to="/scans/new">start a new scan</Link>.
      </p>
    </div>
  );
}

function FindingsSummary({ report, scanId }: { report: ScanReport; scanId: string }) {
  const counts = Object.fromEntries(SEVERITIES.map((s) => [s, report.findings.filter((f) => f.severity === s).length]));
  const top = sortFindings(report.findings).slice(0, TOP_FINDINGS);
  return (
    <section aria-labelledby="findings-heading" className="stack">
      <div className="section-head">
        <h2 id="findings-heading">Findings</h2>
        {report.findings.length > 0 && (
          <Link to="/scans/$scanId/findings" params={{ scanId }} search={{}} className="btn btn-small">
            All {formatCount(report.findings.length)} findings
          </Link>
        )}
      </div>
      <ul className="severity-counts" aria-label="Findings by severity">
        {SEVERITIES.map((s) => (
          <li key={s}>
            <Link to="/scans/$scanId/findings" params={{ scanId }} search={{ severity: s }} className="severity-count">
              <span className="num big">{counts[s]}</span>
              <SeverityChip severity={s} />
            </Link>
          </li>
        ))}
      </ul>
      {top.length === 0 ? (
        <p className="muted">No findings: every active check passed.</p>
      ) : (
        <>
          <h3 className="eyebrow">The {top.length} most severe</h3>
          <div className="stack">
            {top.map((f, i) => (
              <FindingCard key={f.id ?? `${f.check_id}-${i}`} finding={f} scanId={scanId} />
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function AssetsTable({ report, scanId }: { report: ScanReport; scanId: string }) {
  return (
    <section aria-labelledby="assets-heading" className="stack">
      <h2 id="assets-heading">Tables</h2>
      <div className="table-card">
        <table className="rtable">
          <caption className="sr-only">Tables in this scan with their scores</caption>
          <thead>
            <tr>
              <th scope="col">Name</th>
              <th scope="col">Rows</th>
              <th scope="col">Score</th>
              <th scope="col">Worst dimension</th>
              <th scope="col">Findings</th>
            </tr>
          </thead>
          <tbody>
            {report.assets.map((a) => {
              const label = assetLabel(a.ref);
              const worst = worstDimension(a.score);
              const findings = report.findings.filter((f) => f.asset === label).length;
              return (
                <tr key={label}>
                  <th scope="row" data-label="Name">
                    <Link to="/scans/$scanId/assets/$asset" params={{ scanId, asset: label }} className="code-link">
                      {label}
                    </Link>
                    {a.error && <span className="text-bad text-sm block">{a.error}</span>}
                  </th>
                  <td data-label="Rows" className="num">
                    {assetRows(a)}
                  </td>
                  <td data-label="Score">
                    <ScoreText value={a.score.overall} low={a.score.low} high={a.score.high} read={a.sampled ? "sampled" : "full"} />
                  </td>
                  <td data-label="Worst dimension">
                    {worst ? (
                      <>
                        {titleCase(worst.name)} <span className="num muted">{worst.value.toFixed(1)}</span>
                      </>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td data-label="Findings" className="num">
                    {findings > 0 ? (
                      <Link to="/scans/$scanId/findings" params={{ scanId }} search={{ asset: label }}>
                        {findings}
                      </Link>
                    ) : (
                      "0"
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function StoreHealth({ report }: { report: ScanReport }) {
  return (
    <section aria-labelledby="health-heading" className="card stack-sm">
      <h2 id="health-heading">Store health</h2>
      <p className="muted text-sm">Reported beside the scores; these do not change them.</p>
      {report.health.length === 0 ? (
        <p>Nothing to report.</p>
      ) : (
        <ul className="health-list">
          {report.health.map((h, i) => (
            <li key={i}>
              <code className="tag">{h.type}</code> <code className="break-anywhere">{assetColumn(h.asset, h.column)}</code>
              <p>{h.summary}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Proposed({ report }: { report: ScanReport }) {
  const n = report.proposed.length;
  const failing = report.proposed.filter((c) => !c.passed);
  return (
    <section aria-labelledby="proposed-heading" className="card stack-sm">
      <h2 id="proposed-heading">Proposed checks</h2>
      <p>
        <span className="num font-semibold">{formatCount(n)}</span> baseline {n === 1 ? "check was" : "checks were"} proposed from the
        profile.{" "}
        {n > 0 && (
          <>
            Active, <span className="num">{formatCount(failing.length)}</span> of them would report a problem today. They do not
            count toward the score until you activate them.
          </>
        )}
      </p>
      {n > 0 && (
        <details>
          <summary>What they would report</summary>
          <ul className="health-list">
            {report.proposed.map((c) => (
              <li key={c.spec.id}>
                <StatusChip status={c.passed ? "passed" : "failed"} /> <code className="tag">{c.spec.type}</code>{" "}
                <code className="break-anywhere">{assetColumn(assetLabel(c.spec.asset), c.spec.column)}</code>
                <p>{c.summary}</p>
                <p className="num muted text-sm">passing {formatPassShare(c.ratio, c.low, c.high)}</p>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

/** `/scans/$scanId`: progress while the scan runs, the error if it failed, the store report
 * when it succeeded. */
export function Report() {
  const { scanId } = routeApi.useParams();
  const scan = useScanPolling(scanId);
  const succeeded = scan.data?.status === "succeeded";
  const report = useReport(scanId, succeeded);

  if (scan.isPending) return <p role="status">Loading the scan…</p>;
  if (scan.isError) return <ErrorPanel title="Could not load the scan" error={scan.error} onRetry={() => void scan.refetch()} />;

  const s = scan.data;
  return (
    <article className="stack-lg">
      <ReportHeader scan={s} report={report.data} />
      {(s.status === "queued" || s.status === "running") && <Running scan={s} />}
      {s.status === "failed" && <Failed scan={s} />}
      {succeeded && report.isPending && <p role="status">Loading the report…</p>}
      {succeeded && report.isError && (
        <ErrorPanel title="Could not load the report" error={report.error} onRetry={() => void report.refetch()} />
      )}
      {report.data && (
        <>
          <ScoreCard
            title="Store score"
            score={report.data.score}
            caption={intervalCaption(report.data)}
            meta={<span>{samplePolicy(report.data.options.sample_rows)}</span>}
            read={storeRead(report.data)}
          />
          <StoreHistory connectionId={s.connection_id} scanId={scanId} />
          <FindingsSummary report={report.data} scanId={scanId} />
          <AssetsTable report={report.data} scanId={scanId} />
          <div className="grid-2">
            <StoreHealth report={report.data} />
            <Proposed report={report.data} />
          </div>
        </>
      )}
    </article>
  );
}

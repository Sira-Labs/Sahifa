import { Link, getRouteApi } from "@tanstack/react-router";
import { CheckList } from "../components/CheckList";
import { ChecksPanel } from "../components/ChecksPanel";
import { ColumnRow } from "../components/ColumnRow";
import { ErrorPanel } from "../components/ErrorPanel";
import { ScoreCard } from "../components/ScoreCard";
import { AssetHistory } from "../components/ScoreHistory";
import { assetLabel, formatCompact, formatCount } from "../format";
import { useReport } from "../hooks/useReport";
import type { AssetReport as Asset } from "../types";

const routeApi = getRouteApi("/_app/scans/$scanId/assets/$asset");

/** What the asset's interval covers. */
function caption(a: Asset): string {
  if (!a.sampled) return "Every row was read, so the intervals have zero width. They cover sampling uncertainty only.";
  return `The 95 % intervals cover sampling uncertainty from reading ${formatCount(a.sample_rows)} of ${formatCompact(a.population)} rows.`;
}

/** `/scans/$scanId/assets/$asset`: asset-level checks, the columns with their profile and
 * checks, then the stored checks with their lifecycle actions (spec 007). `asset` is the asset
 * label (`namespace.name`). */
export function AssetReport() {
  const { scanId, asset } = routeApi.useParams();
  const report = useReport(scanId);

  if (report.isPending) return <p role="status">Loading the report…</p>;
  if (report.isError) return <ErrorPanel title="Could not load the report" error={report.error} onRetry={() => void report.refetch()} />;

  const a = report.data.assets.find((x) => assetLabel(x.ref) === asset);
  if (!a) {
    return (
      <div role="alert" className="card error-panel">
        <p className="font-semibold">No table named “{asset}” in this scan</p>
        <Link to="/scans/$scanId" params={{ scanId }}>
          Back to the store report
        </Link>
      </div>
    );
  }

  const assetChecks = a.checks.filter((c) => !c.spec.column);
  const findings = report.data.findings.filter((f) => f.asset === asset).length;

  return (
    <article className="stack-lg">
      <nav aria-label="Breadcrumb" className="crumbs">
        <Link to="/scans/$scanId" params={{ scanId }}>
          Store report
        </Link>
        <span aria-hidden="true"> / </span>
        <span aria-current="page" className="break-anywhere">
          {asset}
        </span>
      </nav>
      <div className="page-head">
        <div className="min-w-0">
          <p className="eyebrow">Table report · {a.ref.kind}</p>
          <h1 className="break-anywhere">{asset}</h1>
          <p className="meta-line num">
            <span>
              {a.population_exact ? "" : "≈ "}
              {formatCount(a.population)} rows
            </span>
            <span>{a.sampled ? `${formatCount(a.sample_rows)} read` : "full read"}</span>
            <span>{formatCount(a.columns.length)} columns</span>
          </p>
        </div>
        {findings > 0 && (
          <Link to="/scans/$scanId/findings" params={{ scanId }} search={{ asset }} className="btn btn-small">
            {findings} {findings === 1 ? "finding" : "findings"}
          </Link>
        )}
      </div>
      {a.error && (
        <p role="alert" className="card error-panel">
          {a.error}
        </p>
      )}
      <ScoreCard title="Table score" score={a.score} caption={caption(a)} read={a.sampled ? "sampled" : "full"} />
      <AssetHistory scanId={scanId} label={asset} />

      <section aria-labelledby="asset-checks-heading" className="card stack-sm">
        <h2 id="asset-checks-heading">Table-level checks</h2>
        <CheckList checks={assetChecks} empty="No table-level checks." />
      </section>

      <section aria-labelledby="columns-heading" className="stack">
        <h2 id="columns-heading">Columns</h2>
        <div className="table-card">
          <table className="rtable columns-table">
            <caption className="sr-only">Columns of {asset}; expand a row for its profile and checks</caption>
            <thead>
              <tr>
                <th scope="col">Column</th>
                <th scope="col">Type</th>
                <th scope="col">Role</th>
                <th scope="col">Semantic type</th>
                <th scope="col">Nulls</th>
                <th scope="col">Distinct</th>
                <th scope="col">Score</th>
                <th scope="col">Worst dimension</th>
              </tr>
            </thead>
            <tbody>
              {a.columns.map((c) => (
                <ColumnRow
                  key={c.profile.name}
                  column={c}
                  checks={a.checks.filter((k) => k.spec.column === c.profile.name)}
                  read={a.sampled ? "sampled" : "full"}
                />
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <ChecksPanel scanId={scanId} label={asset} asset={a} />
    </article>
  );
}

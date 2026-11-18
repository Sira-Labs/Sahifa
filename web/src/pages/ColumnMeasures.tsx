import { useQuery } from "@tanstack/react-query";
import { Link, getRouteApi } from "@tanstack/react-router";
import { api } from "../api";
import { ErrorPanel } from "../components/ErrorPanel";
import { MeasureChart } from "../components/MeasureChart";
import { formatCount, formatLocalTime, titleCase } from "../format";
import { formatMeasure, seriesOf } from "../measures";

const routeApi = getRouteApi("/_app/assets/$assetId/columns/$column");

/** `/assets/$assetId/columns/$column`: what the last scans measured on one column (spec 024):
 * a small chart per measure, then every scan with its numbers. */
export function ColumnMeasures() {
  const { assetId, column } = routeApi.useParams();
  const asset = useQuery({ queryKey: ["asset-detail", assetId], queryFn: () => api.getAsset(assetId) });
  const history = useQuery({ queryKey: ["measures", assetId, column], queryFn: () => api.columnMeasures(assetId, column) });

  if (asset.isError) return <ErrorPanel title="Could not load the table" error={asset.error} onRetry={() => void asset.refetch()} />;
  if (history.isError) {
    return <ErrorPanel title="Could not load the column's measures" error={history.error} onRetry={() => void history.refetch()} />;
  }
  if (asset.isPending || history.isPending) return <p role="status">Loading the column's measures…</p>;

  const points = history.data.points;
  const series = seriesOf(points);
  const stored = asset.data.columns.find((c) => c.name === column);
  const newestFirst = [...points].reverse();
  const sampled = points.some((p) => p.sampled);

  return (
    <article className="stack-lg">
      <div className="page-head">
        <div className="min-w-0">
          <p className="eyebrow">Column · {asset.data.label}</p>
          <h1 className="break-anywhere">
            <code>{column}</code>
          </h1>
          <p className="meta-line num">
            {stored ? (
              <>
                <span>{stored.logical_type}</span>
                <span>{titleCase(stored.role)}</span>
                {stored.semantic_type && <span>{stored.semantic_type}</span>}
              </>
            ) : (
              <span>No longer in the table; this is its history.</span>
            )}
            <span>
              {formatCount(points.length)} {points.length === 1 ? "scan" : "scans"}
            </span>
          </p>
        </div>
      </div>

      {points.length === 0 ? (
        <p className="card">Nothing has been measured on this column yet. The next successful scan of its table starts the history.</p>
      ) : (
        <>
          <section aria-labelledby="measures-heading" className="stack">
            <h2 id="measures-heading">Measures over the last {points.length === 1 ? "scan" : `${points.length} scans`}</h2>
            {sampled && <p className="muted text-sm">Some scans read a sample of the table: their measures are estimates.</p>}
            {series.length === 0 ? (
              <p className="card">The table had no rows in these scans, so there is nothing to chart.</p>
            ) : (
              <ul className="measure-grid">
                {series.map((s) => (
                  <MeasureChart key={s.key} series={s} />
                ))}
              </ul>
            )}
          </section>

          <section aria-labelledby="scans-heading" className="stack">
            <h2 id="scans-heading">Per scan</h2>
            <div className="table-card">
              <table className="rtable">
                <caption className="sr-only">The measures of {column} per scan, newest first</caption>
                <thead>
                  <tr>
                    <th scope="col">Scan</th>
                    <th scope="col">Rows read</th>
                    <th scope="col">Rows in table</th>
                    {series.map((s) => (
                      <th scope="col" key={s.key}>
                        {s.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {newestFirst.map((p) => (
                    <tr key={p.scan_id}>
                      <th scope="row" data-label="Scan">
                        <Link to="/scans/$scanId" params={{ scanId: p.scan_id }}>
                          {formatLocalTime(p.finished_at)}
                        </Link>
                        {p.trigger === "schedule" && <span className="muted text-sm"> · scheduled</span>}
                      </th>
                      <td data-label="Rows read" className="num">
                        {formatCount(p.rows)}
                        {p.sampled && <span className="muted text-sm"> sampled</span>}
                      </td>
                      <td data-label="Rows in table" className="num">
                        {p.population === null ? "—" : formatCount(p.population)}
                      </td>
                      {series.map((s) => (
                        <td data-label={s.label} className="num" key={s.key}>
                          {formatMeasure(p.measures[s.key], s.share)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </article>
  );
}

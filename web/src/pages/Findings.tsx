import { useQuery } from "@tanstack/react-query";
import { Link, getRouteApi, useNavigate } from "@tanstack/react-router";
import { useId } from "react";
import { api } from "../api";
import { ErrorPanel } from "../components/ErrorPanel";
import { FindingCard } from "../components/FindingCard";
import { DIMENSIONS, SEVERITIES } from "../constants";
import { assetLabel, sortFindings, titleCase } from "../format";
import { useReport } from "../hooks/useReport";
import { parseFindingFilters } from "../search";
import type { FindingFilters } from "../types";

const routeApi = getRouteApi("/scans/$scanId/findings");

function Select({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string | undefined;
  options: { value: string; label: string }[];
  onChange: (v: string | undefined) => void;
}) {
  const id = useId();
  return (
    <div className="filter">
      <label htmlFor={id} className="field-label">
        {label}
      </label>
      <select id={id} className="input" value={value ?? ""} onChange={(e) => onChange(e.target.value || undefined)}>
        <option value="">All</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

/** `/scans/$scanId/findings`: findings ordered by severity then failed share, filtered by
 * severity, dimension and asset through the search params. */
export function Findings() {
  const { scanId } = routeApi.useParams();
  // Only the known keys: the router passes unknown search params through.
  const filters: FindingFilters = parseFindingFilters(routeApi.useSearch());
  const navigate = useNavigate();
  const findings = useQuery({
    queryKey: ["findings", scanId, filters.severity ?? null, filters.dimension ?? null, filters.asset ?? null],
    queryFn: () => api.listFindings(scanId, filters),
  });
  // Asset choices come from the report; it is usually cached from the store report already.
  const report = useReport(scanId);
  const assets = report.data
    ? report.data.assets.map((a) => assetLabel(a.ref))
    : [...new Set([...(findings.data?.items.map((f) => f.asset) ?? []), ...(filters.asset ? [filters.asset] : [])])];

  const set = (patch: FindingFilters) =>
    void navigate({ to: "/scans/$scanId/findings", params: { scanId }, search: { ...filters, ...patch }, replace: true });
  const active = Boolean(filters.severity || filters.dimension || filters.asset);
  const items = findings.data ? sortFindings(findings.data.items) : [];

  return (
    <article className="stack-lg">
      <nav aria-label="Breadcrumb" className="crumbs">
        <Link to="/scans/$scanId" params={{ scanId }}>
          Store report
        </Link>
        <span aria-hidden="true"> / </span>
        <span aria-current="page">Findings</span>
      </nav>
      <div className="page-head">
        <div>
          <p className="eyebrow">{report.data ? report.data.source.label : "Scan"}</p>
          <h1>Findings</h1>
        </div>
      </div>

      <form className="card filters" aria-label="Filter findings" onSubmit={(e) => e.preventDefault()}>
        <Select
          label="Severity"
          value={filters.severity}
          options={SEVERITIES.map((s) => ({ value: s, label: titleCase(s) }))}
          onChange={(v) => set({ severity: v as FindingFilters["severity"] })}
        />
        <Select
          label="Dimension"
          value={filters.dimension}
          options={DIMENSIONS.map((d) => ({ value: d, label: titleCase(d) }))}
          onChange={(v) => set({ dimension: v as FindingFilters["dimension"] })}
        />
        <Select label="Table" value={filters.asset} options={assets.map((a) => ({ value: a, label: a }))} onChange={(v) => set({ asset: v })} />
        {active && (
          <button type="button" className="btn btn-small btn-quiet" onClick={() => set({ severity: undefined, dimension: undefined, asset: undefined })}>
            Clear filters
          </button>
        )}
      </form>

      {findings.isPending && <p role="status">Loading findings…</p>}
      {findings.isError && <ErrorPanel title="Could not load the findings" error={findings.error} onRetry={() => void findings.refetch()} />}
      {findings.isSuccess && (
        <>
          <p role="status" className="muted">
            {items.length === 0
              ? active
                ? "No findings match these filters."
                : "No findings: every active check passed."
              : `${items.length} ${items.length === 1 ? "finding" : "findings"}${active ? (items.length === 1 ? " matches these filters" : " match these filters") : ""}, most severe first.`}
          </p>
          <div className="stack">
            {items.map((f, i) => (
              <FindingCard key={f.id ?? `${f.check_id}-${i}`} finding={f} scanId={scanId} />
            ))}
          </div>
        </>
      )}
    </article>
  );
}

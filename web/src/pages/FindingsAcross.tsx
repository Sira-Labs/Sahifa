import { useInfiniteQuery, useQuery, useQueryClient, type InfiniteData } from "@tanstack/react-query";
import { Link, getRouteApi, useNavigate } from "@tanstack/react-router";
import { useId, useState } from "react";
import { api } from "../api";
import { ErrorPanel } from "../components/ErrorPanel";
import { FINDING_STALE_MESSAGE, StoredFindingCard } from "../components/StoredFindingCard";
import { SEVERITIES } from "../constants";
import { titleCase } from "../format";
import { parseFindingsSearch } from "../search";
import type { FindingsSearch, FindingsView, Page, StoredFinding } from "../types";

const listRoute = getRouteApi("/_app/findings");
const detailRoute = getRouteApi("/_app/findings/$findingId");

const PAGE_SIZE = 50;

const VIEWS: { value: FindingsView; label: string }[] = [
  { value: "attention", label: "Needs attention" },
  { value: "open", label: "Open" },
  { value: "acknowledged", label: "Acknowledged" },
  { value: "muted", label: "Muted" },
  { value: "resolved", label: "Resolved" },
  { value: "all", label: "All" },
];

function Select({
  label,
  value,
  options,
  onChange,
  all,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (v: string) => void;
  all?: string;
}) {
  const id = useId();
  return (
    <div className="filter">
      <label htmlFor={id} className="field-label">
        {label}
      </label>
      <select id={id} className="input" value={value} onChange={(e) => onChange(e.target.value)}>
        {all !== undefined && <option value="">{all}</option>}
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

/** Replace one finding in every cached page of the list, so the card updates in place. */
function replaceIn(data: InfiniteData<Page<StoredFinding>> | undefined, updated: StoredFinding) {
  if (!data) return data;
  return { ...data, pages: data.pages.map((p) => ({ ...p, items: p.items.map((f) => (f.id === updated.id ? updated : f)) })) };
}

/** `/findings`: one finding per failing check across all scans (spec 009), by default those
 * needing attention, most severe and most recent first, with "Load more". */
export function FindingsAcross() {
  const search: FindingsSearch = parseFindingsSearch(listRoute.useSearch());
  const navigate = useNavigate();
  const client = useQueryClient();
  const [notice, setNotice] = useState<string | null>(null);
  const connections = useQuery({ queryKey: ["connections"], queryFn: api.listConnections });
  const key = ["stored-findings", search.status ?? "attention", search.severity ?? null, search.connection ?? null];
  const findings = useInfiniteQuery({
    queryKey: key,
    queryFn: ({ pageParam }) => api.listStoredFindings(search, pageParam, PAGE_SIZE),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });

  const set = (patch: FindingsSearch) => {
    setNotice(null);
    void navigate({ to: "/findings", search: { ...search, ...patch }, replace: true });
  };
  const filtered = Boolean(search.status || search.severity || search.connection);
  const items = findings.data?.pages.flatMap((p) => p.items) ?? [];
  const names = new Map((connections.data?.items ?? []).map((c) => [c.id, c.name]));

  function changed(updated: StoredFinding) {
    setNotice(null);
    client.setQueryData<InfiniteData<Page<StoredFinding>>>(key, (data) => replaceIn(data, updated));
    // Other cached views (another status filter) still hold the old version; drop them so they
    // refetch instead of offering an action that would fail with stale_version.
    client.removeQueries({ queryKey: ["stored-findings"], type: "inactive" });
    void client.invalidateQueries({ queryKey: ["finding", updated.id] });
  }

  function stale() {
    setNotice(FINDING_STALE_MESSAGE);
    void client.invalidateQueries({ queryKey: ["stored-findings"] });
  }

  return (
    <article className="stack-lg">
      <div className="page-head">
        <div>
          <p className="eyebrow">Across scans</p>
          <h1>Findings</h1>
        </div>
      </div>
      <p className="muted lede">
        One finding per failing check. A scan that finds the problem again adds an occurrence; a check that passes again resolves it.
      </p>

      <form className="card filters" aria-label="Filter findings" onSubmit={(e) => e.preventDefault()}>
        <Select
          label="Status"
          value={search.status ?? "attention"}
          options={VIEWS}
          onChange={(v) => set({ status: v === "attention" ? undefined : (v as FindingsView) })}
        />
        <Select
          label="Severity"
          value={search.severity ?? ""}
          all="All"
          options={SEVERITIES.map((s) => ({ value: s, label: titleCase(s) }))}
          onChange={(v) => set({ severity: (v || undefined) as FindingsSearch["severity"] })}
        />
        <Select
          label="Connection"
          value={search.connection ?? ""}
          all="All"
          options={(connections.data?.items ?? []).map((c) => ({ value: c.id, label: c.name }))}
          onChange={(v) => set({ connection: v || undefined })}
        />
        {filtered && (
          <button type="button" className="btn btn-small btn-quiet" onClick={() => set({ status: undefined, severity: undefined, connection: undefined })}>
            Reset filters
          </button>
        )}
      </form>

      {notice && (
        <p role="status" className="text-warn">
          {notice}
        </p>
      )}
      {findings.isPending && <p role="status">Loading findings…</p>}
      {findings.isError && <ErrorPanel title="Could not load the findings" error={findings.error} onRetry={() => void findings.refetch()} />}
      {findings.isSuccess && (
        <>
          <p role="status" className="muted">
            {items.length === 0
              ? filtered
                ? "No findings match these filters."
                : "No findings need attention."
              : `${items.length}${findings.hasNextPage ? "+" : ""} ${items.length === 1 ? "finding" : "findings"}, most severe first.`}
          </p>
          <div className="stack">
            {items.map((f) => (
              <div key={f.id} className="stack-sm">
                {!search.connection && names.get(f.asset.connection_id) && (
                  <p className="eyebrow">{names.get(f.asset.connection_id)}</p>
                )}
                <StoredFindingCard finding={f} onChanged={changed} onStale={stale} />
              </div>
            ))}
          </div>
          {findings.hasNextPage && (
            <button type="button" className="btn" disabled={findings.isFetchingNextPage} onClick={() => void findings.fetchNextPage()}>
              {findings.isFetchingNextPage ? "Loading…" : "Load more"}
            </button>
          )}
        </>
      )}
    </article>
  );
}

/** `/findings/$findingId`: one finding with its occurrences and history open; the scan
 * findings page links here. */
export function FindingPage() {
  const { findingId } = detailRoute.useParams();
  const client = useQueryClient();
  const [notice, setNotice] = useState<string | null>(null);
  const finding = useQuery({ queryKey: ["finding", findingId], queryFn: () => api.getStoredFinding(findingId) });

  function changed() {
    setNotice(null);
    void client.invalidateQueries({ queryKey: ["finding", findingId] });
    void client.invalidateQueries({ queryKey: ["stored-findings"] });
  }

  function stale() {
    setNotice(FINDING_STALE_MESSAGE.replace("the list is", "this page is"));
    void client.invalidateQueries({ queryKey: ["finding", findingId] });
  }

  return (
    <article className="stack-lg">
      <nav aria-label="Breadcrumb" className="crumbs">
        <Link to="/findings">Findings</Link>
        <span aria-hidden="true"> / </span>
        <span aria-current="page">Finding</span>
      </nav>
      {notice && (
        <p role="status" className="text-warn">
          {notice}
        </p>
      )}
      {finding.isPending && <p role="status">Loading the finding…</p>}
      {finding.isError && <ErrorPanel title="Could not load the finding" error={finding.error} onRetry={() => void finding.refetch()} />}
      {finding.data && <StoredFindingCard finding={finding.data} onChanged={changed} onStale={stale} expanded />}
    </article>
  );
}

import { useInfiniteQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useId, useState } from "react";
import { api } from "../api";
import { ErrorPanel } from "../components/ErrorPanel";
import { formatLocalTime } from "../format";
import type { AuditEntry, AuditFilters } from "../types";
import { useShowsWorkspaces, useWorkspaceFilter } from "../workspace";

const KINDS: { value: string; label: string }[] = [
  { value: "check.", label: "Checks" },
  { value: "finding.", label: "Findings" },
  { value: "schedule.", label: "Schedules" },
  { value: "scan.", label: "Scans" },
  { value: "connection.", label: "Connections" },
  { value: "workspace.", label: "Workspaces" },
  { value: "membership.", label: "Members" },
];

/** A value as the change column shows it. */
function show(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") {
    const named = value as { name?: unknown };
    return typeof named.name === "string" ? named.name : JSON.stringify(value);
  }
  return String(value);
}

/** Each changed field as `field: before → after`; only what is after for a creation. */
export function changes(entry: Pick<AuditEntry, "before" | "after">): string[] {
  const keys = [...new Set([...Object.keys(entry.before ?? {}), ...Object.keys(entry.after ?? {})])];
  return keys
    .filter((k) => k !== "email" && k !== "version")
    .map((k) => {
      const was = entry.before?.[k];
      const now = entry.after?.[k];
      if (!entry.before) return `${k}: ${show(now)}`;
      if (!entry.after) return `${k}: ${show(was)} → removed`;
      return `${k}: ${show(was)} → ${show(now)}`;
    });
}

/** Where an entry leads, when its object has a page of its own. */
function ObjectLink({ entry }: { entry: AuditEntry }) {
  if (entry.object_type === "finding") {
    return (
      <Link to="/findings/$findingId" params={{ findingId: entry.object_id }}>
        {entry.summary}
      </Link>
    );
  }
  if (entry.object_type === "scan") {
    return (
      <Link to="/scans/$scanId" params={{ scanId: entry.object_id }}>
        {entry.summary}
      </Link>
    );
  }
  return <>{entry.summary}</>;
}

/** `/audit` (spec 018): who changed what, when, and how, in the workspaces the person
 * administers; newest first, with "Load more". */
export function Audit() {
  const kindId = useId();
  const actorId = useId();
  const workspace = useWorkspaceFilter();
  const showWorkspace = useShowsWorkspaces();
  const [filters, setFilters] = useState<AuditFilters>({});
  const [person, setPerson] = useState("");
  const entries = useInfiniteQuery({
    queryKey: ["audit", workspace ?? null, filters.action ?? null, filters.actor ?? null],
    queryFn: ({ pageParam }) => api.listAudit(filters, pageParam, workspace),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const items = entries.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <section aria-labelledby="audit-heading" className="stack">
      <div className="page-head">
        <div>
          <p className="eyebrow">Administration</p>
          <h1 id="audit-heading">Audit log</h1>
        </div>
      </div>
      <p className="muted lede">
        Every change a person made in the workspaces you administer: checks, findings, schedules, scans, connections and
        members. Entries cannot be changed or deleted.
      </p>

      <form
        className="card filters"
        aria-label="Filter the audit log"
        onSubmit={(e) => {
          e.preventDefault();
          setFilters((f) => ({ ...f, actor: person.trim() || undefined }));
        }}
      >
        <div className="filter">
          <label htmlFor={kindId} className="field-label">
            Kind of change
          </label>
          <select
            id={kindId}
            className="input"
            value={filters.action ?? ""}
            onChange={(e) => setFilters((f) => ({ ...f, action: e.target.value || undefined }))}
          >
            <option value="">All</option>
            {KINDS.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </select>
        </div>
        <div className="filter">
          <label htmlFor={actorId} className="field-label">
            Person
          </label>
          <input id={actorId} className="input" value={person} placeholder="Email" onChange={(e) => setPerson(e.target.value)} />
        </div>
        <button type="submit" className="btn btn-small">
          Filter
        </button>
      </form>

      {entries.isPending && <p role="status">Loading the audit log…</p>}
      {entries.isError && <ErrorPanel title="Could not load the audit log" error={entries.error} onRetry={() => void entries.refetch()} />}
      {entries.isSuccess && items.length === 0 && <p className="muted">No changes match.</p>}
      {items.length > 0 && (
        <div className="table-card">
          <table className="rtable">
            <caption className="sr-only">Changes, newest first</caption>
            <thead>
              <tr>
                <th scope="col">When</th>
                <th scope="col">Who</th>
                {showWorkspace && <th scope="col">Workspace</th>}
                <th scope="col">What</th>
                <th scope="col">Change</th>
              </tr>
            </thead>
            <tbody>
              {items.map((e) => (
                <tr key={e.id}>
                  <td data-label="When" className="num">
                    {formatLocalTime(e.at)}
                  </td>
                  <td data-label="Who" className="break-anywhere">
                    {e.actor}
                  </td>
                  {showWorkspace && <td data-label="Workspace">{e.workspace.name}</td>}
                  <td data-label="What">
                    <ObjectLink entry={e} />
                  </td>
                  <td data-label="Change" className="text-sm">
                    {changes(e).map((line) => (
                      <div key={line} className="break-anywhere">
                        {line}
                      </div>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {entries.hasNextPage && (
        <div>
          <button type="button" className="btn" disabled={entries.isFetchingNextPage} onClick={() => void entries.fetchNextPage()}>
            {entries.isFetchingNextPage ? "Loading…" : "Load more"}
          </button>
        </div>
      )}
    </section>
  );
}

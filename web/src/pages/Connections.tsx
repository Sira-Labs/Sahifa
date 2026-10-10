import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useId, useState } from "react";
import { api } from "../api";
import { StatusChip } from "../components/Chips";
import { ConnectionTest } from "../components/ConnectionTest";
import { ErrorPanel } from "../components/ErrorPanel";
import { ScheduleSection } from "../components/ScheduleSection";
import { formatLocalTime } from "../format";
import { describeSchedule } from "../schedule";
import type { Connection } from "../types";
import { VIEWER_REASON, allows, useShowsWorkspaces, useWorkspaceFilter } from "../workspace";

/** One connection, with its schedule (spec 010) in a row that opens below it. A viewer of its
 * workspace (spec 016) sees Scan and the schedule's fields disabled, with the reason. */
function ConnectionRow({ c, showWorkspace, columns }: { c: Connection; showWorkspace: boolean; columns: number }) {
  const [open, setOpen] = useState(false);
  const detailId = useId();
  const readOnly = !allows(c.role);
  return (
    <>
      <tr className={open ? "is-open" : undefined}>
        <th scope="row" data-label="Name">
          {c.name}
        </th>
        {showWorkspace && <td data-label="Workspace">{c.workspace?.name ?? "—"}</td>}
        <td data-label="Kind">{c.kind}</td>
        <td data-label="Credential">{c.secret_ref ? <code className="break-anywhere">{c.secret_ref}</code> : "—"}</td>
        <td data-label="Status">
          <StatusChip status={c.available ? "available" : "unavailable"} />
        </td>
        <td data-label="Schedule" className="text-sm">
          {c.schedule ? describeSchedule(c.schedule) : <span className="muted">None</span>}
        </td>
        <td data-label="Registered" className="num">
          {formatLocalTime(c.created_at)}
        </td>
        <td data-label="Actions">
          <div className="row-actions">
            <ConnectionTest connectionId={c.id} name={c.name} />
            {readOnly ? (
              <button type="button" className="btn btn-small" disabled title={VIEWER_REASON}>
                Scan
              </button>
            ) : (
              <Link to="/scans/new" search={{ tab: "connection", connection: c.id }} className="btn btn-small">
                Scan
              </Link>
            )}
            <button
              type="button"
              className="btn btn-small"
              aria-expanded={open}
              aria-controls={detailId}
              aria-label={`Schedule for ${c.name}`}
              onClick={() => setOpen((o) => !o)}
            >
              Schedule
            </button>
          </div>
        </td>
      </tr>
      <tr id={detailId} className="detail-row" hidden={!open}>
        <td colSpan={columns}>{open && <ScheduleSection connectionId={c.id} name={c.name} readOnly={readOnly} />}</td>
      </tr>
    </>
  );
}

/** `/connections`: the registered connections with Test, Scan and Schedule each. */
export function Connections() {
  const workspace = useWorkspaceFilter();
  const showWorkspace = useShowsWorkspaces();
  const connections = useQuery({ queryKey: ["connections", workspace ?? null], queryFn: () => api.listConnections(workspace) });
  const items = (connections.data?.items ?? []).filter((c) => c.kind !== "upload");
  const columns = showWorkspace ? 8 : 7;

  return (
    <section aria-labelledby="connections-heading" className="stack">
      <div className="page-head">
        <div>
          <p className="eyebrow">Sources</p>
          <h1 id="connections-heading">Connections</h1>
        </div>
      </div>
      <p className="muted lede">
        Sahifa registers a connection for every <code>SAHIFA_CONN_&lt;NAME&gt;</code> variable of the API. Credentials stay in the
        environment; Sahifa only reads, in read-only sessions with timeouts. A schedule scans a connection on its own.
      </p>

      {connections.isPending && <p role="status">Loading connections…</p>}
      {connections.isError && (
        <ErrorPanel title="Could not load the connections" error={connections.error} onRetry={() => void connections.refetch()} />
      )}
      {connections.isSuccess && items.length === 0 && (
        <div className="card">
          <p className="font-semibold">No connections yet</p>
          <p className="muted">
            Set <code>SAHIFA_CONN_SHOP=postgresql://reader@db/shop</code> on the API and restart it, or{" "}
            <Link to="/scans/new">upload files</Link> instead.
          </p>
        </div>
      )}
      {items.length > 0 && (
        <div className="table-card">
          <table className="rtable">
            <caption className="sr-only">Registered connections</caption>
            <thead>
              <tr>
                <th scope="col">Name</th>
                {showWorkspace && <th scope="col">Workspace</th>}
                <th scope="col">Kind</th>
                <th scope="col">Credential</th>
                <th scope="col">Status</th>
                <th scope="col">Schedule</th>
                <th scope="col">Registered</th>
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <ConnectionRow key={c.id} c={c} showWorkspace={showWorkspace} columns={columns} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

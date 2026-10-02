import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { api } from "../api";
import { StatusChip } from "../components/Chips";
import { ConnectionTest } from "../components/ConnectionTest";
import { ErrorPanel } from "../components/ErrorPanel";
import { formatLocalTime } from "../format";

/** `/connections`: the registered connections with a Test button each. */
export function Connections() {
  const connections = useQuery({ queryKey: ["connections"], queryFn: api.listConnections });
  const items = (connections.data?.items ?? []).filter((c) => c.kind !== "upload");

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
        environment; Sahifa only reads, in read-only sessions with timeouts.
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
                <th scope="col">Kind</th>
                <th scope="col">Credential</th>
                <th scope="col">Status</th>
                <th scope="col">Registered</th>
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr key={c.id}>
                  <th scope="row" data-label="Name">
                    {c.name}
                  </th>
                  <td data-label="Kind">{c.kind}</td>
                  <td data-label="Credential">{c.secret_ref ? <code className="break-anywhere">{c.secret_ref}</code> : "—"}</td>
                  <td data-label="Status">
                    <StatusChip status={c.available ? "available" : "unavailable"} />
                  </td>
                  <td data-label="Registered" className="num">
                    {formatLocalTime(c.created_at)}
                  </td>
                  <td data-label="Actions">
                    <div className="row-actions">
                      <ConnectionTest connectionId={c.id} name={c.name} />
                      <Link to="/scans/new" search={{ tab: "connection", connection: c.id }} className="btn btn-small">
                        Scan
                      </Link>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

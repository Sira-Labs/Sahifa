import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState, type FormEvent } from "react";
import { api } from "../api";
import { ErrorPanel } from "../components/ErrorPanel";
import { formatLocalTime } from "../format";
import type { Connection, Member, Workspace, WorkspaceRole } from "../types";
import { useMe } from "../workspace";

const ROLES: { value: WorkspaceRole; label: string }[] = [
  { value: "viewer", label: "Viewer" },
  { value: "editor", label: "Editor" },
  { value: "admin", label: "Admin" },
];

/** Whatever changes a workspace or its members invalidates: the lists, and `/me` (the header's
 * workspaces and the caller's roles). */
function useRefresh() {
  const client = useQueryClient();
  return () => {
    void client.invalidateQueries({ queryKey: ["workspaces"] });
    void client.invalidateQueries({ queryKey: ["me"] });
    void client.invalidateQueries({ queryKey: ["connections"] });
  };
}

function CreateWorkspace() {
  const id = useId();
  const refresh = useRefresh();
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: () => api.createWorkspace(name.trim()),
    onSuccess: () => {
      setName("");
      refresh();
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    if (name.trim()) create.mutate();
  }

  return (
    <form className="card stack-sm" aria-label="Create a workspace" onSubmit={submit}>
      <h2>Create a workspace</h2>
      <div className="inline-form">
        <label htmlFor={id} className="field-label">
          Name
        </label>
        <input id={id} className="input" maxLength={100} value={name} onChange={(e) => setName(e.target.value)} />
        <button type="submit" className="btn btn-primary btn-small" disabled={create.isPending || !name.trim()}>
          Create
        </button>
      </div>
      {create.isError && (
        <p role="alert" className="text-bad">
          {create.error.message}
        </p>
      )}
    </form>
  );
}

function Rename({ workspace }: { workspace: Workspace }) {
  const id = useId();
  const refresh = useRefresh();
  const [name, setName] = useState(workspace.name);
  const rename = useMutation({ mutationFn: () => api.renameWorkspace(workspace.id, name.trim()), onSuccess: refresh });
  const changed = name.trim() !== "" && name.trim() !== workspace.name;

  function submit(e: FormEvent) {
    e.preventDefault();
    if (changed) rename.mutate();
  }

  return (
    <form className="inline-form" aria-label={`Rename ${workspace.name}`} onSubmit={submit}>
      <label htmlFor={id} className="field-label">
        Name
      </label>
      <input id={id} className="input" maxLength={100} value={name} onChange={(e) => setName(e.target.value)} />
      <button type="submit" className="btn btn-small" disabled={rename.isPending || !changed}>
        Rename
      </button>
      {rename.isError && (
        <p role="alert" className="text-bad">
          {rename.error.message}
        </p>
      )}
    </form>
  );
}

function MemberRow({ workspace, member, self }: { workspace: Workspace; member: Member; self: boolean }) {
  const client = useQueryClient();
  const refresh = useRefresh();
  const roleId = useId();
  const key = ["members", workspace.id];
  const done = () => {
    void client.invalidateQueries({ queryKey: key });
    refresh();
  };
  const change = useMutation({ mutationFn: (role: WorkspaceRole) => api.putMember(workspace.id, member.user_id, role), onSuccess: done });
  const remove = useMutation({ mutationFn: () => api.removeMember(workspace.id, member.user_id), onSuccess: done });
  const error = change.error ?? remove.error;

  return (
    <tr>
      <th scope="row" data-label="Person">
        <span className="font-semibold">{member.display_name || member.email}</span>
        <br />
        <span className="muted text-sm break-anywhere">{member.email}</span>
      </th>
      <td data-label="Role">
        <label htmlFor={roleId} className="sr-only">
          Role of {member.email}
        </label>
        <select
          id={roleId}
          className="input input-small"
          value={member.role}
          disabled={change.isPending}
          onChange={(e) => change.mutate(e.target.value as WorkspaceRole)}
        >
          {ROLES.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </select>
      </td>
      <td data-label="Last sign-in" className="num">
        {member.last_login_at ? formatLocalTime(member.last_login_at) : "—"}
      </td>
      <td data-label="Actions">
        <button
          type="button"
          className="btn btn-small btn-quiet"
          disabled={remove.isPending}
          aria-label={`Remove ${member.email}`}
          onClick={() => remove.mutate()}
        >
          {self ? "Leave" : "Remove"}
        </button>
        {error && (
          <p role="alert" className="text-bad text-sm">
            {error.message}
          </p>
        )}
      </td>
    </tr>
  );
}

function AddMember({ workspace, members }: { workspace: Workspace; members: Member[] }) {
  const client = useQueryClient();
  const refresh = useRefresh();
  const searchId = useId();
  const roleId = useId();
  const [q, setQ] = useState("");
  const [role, setRole] = useState<WorkspaceRole>("viewer");
  const term = q.trim();
  const matches = useQuery({ queryKey: ["users", term], queryFn: () => api.searchUsers(term), enabled: term.length >= 2 });
  const add = useMutation({
    mutationFn: (userId: string) => api.putMember(workspace.id, userId, role),
    onSuccess: () => {
      setQ("");
      void client.invalidateQueries({ queryKey: ["members", workspace.id] });
      refresh();
    },
  });
  const known = new Set(members.map((m) => m.user_id));
  const found = (matches.data ?? []).filter((u) => !known.has(u.id));

  return (
    <div className="stack-sm">
      <h4>Add a person who has signed in</h4>
      <div className="inline-form">
        <label htmlFor={searchId} className="field-label">
          Email or name
        </label>
        <input id={searchId} className="input" value={q} onChange={(e) => setQ(e.target.value)} autoComplete="off" />
        <label htmlFor={roleId} className="field-label">
          as
        </label>
        <select id={roleId} className="input input-small" value={role} onChange={(e) => setRole(e.target.value as WorkspaceRole)}>
          {ROLES.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label}
            </option>
          ))}
        </select>
      </div>
      {term.length >= 2 && matches.isSuccess && found.length === 0 && (
        <p className="muted text-sm">Nobody else matches. People appear here after they have signed in once.</p>
      )}
      {found.length > 0 && (
        <ul className="plain-list" aria-label="Matching people">
          {found.map((u) => (
            <li key={u.id} className="row-actions">
              <span>
                {u.display_name || u.email} <span className="muted text-sm">{u.email}</span>
              </span>
              <button type="button" className="btn btn-small" disabled={add.isPending} onClick={() => add.mutate(u.id)}>
                Add
              </button>
            </li>
          ))}
        </ul>
      )}
      {(matches.isError || add.isError) && (
        <p role="alert" className="text-bad">
          {(matches.error ?? add.error)?.message}
        </p>
      )}
    </div>
  );
}

function Members({ workspace, selfId }: { workspace: Workspace; selfId: string | null }) {
  const members = useQuery({ queryKey: ["members", workspace.id], queryFn: () => api.listMembers(workspace.id) });
  if (members.isPending) return <p role="status">Loading members…</p>;
  if (members.isError) return <ErrorPanel title="Could not load the members" error={members.error} onRetry={() => void members.refetch()} />;
  return (
    <div className="stack-sm">
      <h3>Members</h3>
      {members.data.length === 0 ? (
        <p className="muted">No members yet.</p>
      ) : (
        <div className="table-card">
          <table className="rtable">
            <caption className="sr-only">Members of {workspace.name}</caption>
            <thead>
              <tr>
                <th scope="col">Person</th>
                <th scope="col">Role</th>
                <th scope="col">Last sign-in</th>
                <th scope="col">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {members.data.map((m) => (
                <MemberRow key={m.user_id} workspace={workspace} member={m} self={m.user_id === selfId} />
              ))}
            </tbody>
          </table>
        </div>
      )}
      <AddMember workspace={workspace} members={members.data} />
    </div>
  );
}

function MoveConnection({ connection, workspaces }: { connection: Connection; workspaces: Workspace[] }) {
  const id = useId();
  const refresh = useRefresh();
  const client = useQueryClient();
  const others = workspaces.filter((w) => w.id !== connection.workspace?.id);
  const [target, setTarget] = useState("");
  const move = useMutation({
    mutationFn: () => api.moveConnection(connection.id, target),
    onSuccess: () => {
      setTarget("");
      refresh();
      void client.invalidateQueries({ queryKey: ["scans"] });
      void client.invalidateQueries({ queryKey: ["stored-findings"] });
    },
  });
  if (others.length === 0) return null;
  return (
    <li className="stack-xs">
      <div className="inline-form">
        <span className="font-semibold">{connection.name}</span>
        <label htmlFor={id} className="field-label">
          Move to workspace…
        </label>
        <select id={id} className="input input-small" value={target} onChange={(e) => setTarget(e.target.value)}>
          <option value="">Choose</option>
          {others.map((w) => (
            <option key={w.id} value={w.id}>
              {w.name}
            </option>
          ))}
        </select>
        <button type="button" className="btn btn-small" disabled={!target || move.isPending} onClick={() => move.mutate()}>
          Move
        </button>
      </div>
      {move.isError && (
        <p role="alert" className="text-bad text-sm">
          {move.error.message}
        </p>
      )}
    </li>
  );
}

function WorkspaceCard({
  workspace,
  workspaces,
  connections,
  orgAdmin,
  selfId,
}: {
  workspace: Workspace;
  workspaces: Workspace[];
  connections: Connection[];
  orgAdmin: boolean;
  selfId: string | null;
}) {
  const headingId = useId();
  const own = connections.filter((c) => c.workspace?.id === workspace.id);
  const admin = workspace.role === "admin";
  return (
    <section aria-labelledby={headingId} className="card stack">
      <div className="page-head">
        <div>
          <h2 id={headingId}>
            {workspace.name} {workspace.is_default && <span className="tag">default</span>}
          </h2>
          <p className="muted text-sm">
            {workspace.connections} {workspace.connections === 1 ? "connection" : "connections"} · {workspace.members}{" "}
            {workspace.members === 1 ? "member" : "members"} · your role: {workspace.role}
          </p>
        </div>
      </div>
      {admin && <Rename workspace={workspace} />}
      {admin && <Members workspace={workspace} selfId={selfId} />}
      {orgAdmin && own.length > 0 && (
        <div className="stack-sm">
          <h3>Connections</h3>
          <ul className="plain-list stack-sm">
            {own.map((c) => (
              <MoveConnection key={c.id} connection={c} workspaces={workspaces} />
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

/** `/workspaces` (spec 016): the workspaces the person administers, with rename and members;
 * the org admin also creates workspaces and moves connections between them. */
export function Workspaces() {
  const me = useMe();
  const workspaces = useQuery({ queryKey: ["workspaces"], queryFn: api.listWorkspaces });
  const orgAdmin = me.data?.org_admin ?? false;
  const connections = useQuery({
    queryKey: ["connections", "all"],
    queryFn: () => api.listConnections(),
    enabled: orgAdmin,
  });
  const shown = (workspaces.data ?? []).filter((w) => orgAdmin || w.role === "admin");

  return (
    <section aria-labelledby="workspaces-heading" className="stack">
      <div className="page-head">
        <div>
          <p className="eyebrow">{me.data?.organisation ?? "Organisation"}</p>
          <h1 id="workspaces-heading">Workspaces</h1>
        </div>
      </div>
      <p className="muted lede">
        A workspace groups connections and the people who work on them. Viewers see its scans, checks and findings; editors also
        scan and change checks, findings and schedules; admins manage its members.
      </p>
      {orgAdmin && <CreateWorkspace />}
      {workspaces.isPending && <p role="status">Loading workspaces…</p>}
      {workspaces.isError && (
        <ErrorPanel title="Could not load the workspaces" error={workspaces.error} onRetry={() => void workspaces.refetch()} />
      )}
      {workspaces.isSuccess && shown.length === 0 && <p className="muted">You administer no workspace.</p>}
      {shown.map((w) => (
        <WorkspaceCard
          key={w.id}
          workspace={w}
          workspaces={workspaces.data ?? []}
          connections={(connections.data?.items ?? []).filter((c) => c.kind !== "upload")}
          orgAdmin={orgAdmin}
          selfId={me.data?.user.id ?? null}
        />
      ))}
    </section>
  );
}

# Spec 016 — Workspaces, memberships and roles with row-level security

Sprint 4, story S4-1. Depends on: spec 006 (sign-in, `Principal`), spec 007 (checks), spec 009
(findings), spec 010 (schedules), spec 011 (scores), ADR-0003 (Postgres metadata store), ADR-0010
(org → workspace → connection RBAC with row-level security). Packages: `api/` (models,
migration 0008, auth, routers, services), `web/`, `docs/`.

Status: approved 2026-10-10 by the owner, with member management in this spec (S4-3 keeps
invitations and deleting workspaces); done.

## Goal

An install serves a team, not one person. People belong to workspaces with a role, and every
connection belongs to a workspace. A person sees only the connections of their workspaces, with
the scans, checks, findings, schedules and scores that belong to them. They can only change
what their role allows.

The rule is enforced twice:

1. **In the API.** Every route resolves the caller's role for the object's workspace.
2. **In Postgres.** Row-level security hides other workspaces' rows from every query, so a
   query that forgets its filter still returns nothing it should not.

## User story

As the administrator of a Sahifa install, I can put the finance team's databases in a "Finance"
workspace and give the controllers a viewer role. They then see the findings on their data and
nothing else, and cannot lock or retire a check by mistake.

## Interface

### Concepts

| Term | Meaning |
|---|---|
| Organisation | The install. There is exactly one in R2: created by the migration, named by `SAHIFA_ORG_NAME` (default `Sahifa`). Several organisations per install are R3. |
| Workspace | A group of connections and the people who work on them. The name is unique in the organisation. |
| Membership | (workspace, user, role). A person can be in several workspaces with different roles. |
| Org admin | The person whose email is `SAHIFA_ADMIN_EMAIL`, as today, and the single principal in `proxy` and `dev` mode. An org admin can see and change everything. |

### Roles

| Action | viewer | editor | admin | org admin |
|---|---|---|---|---|
| See the workspace's connections, scans, reports, checks, findings, schedules, history | ✓ | ✓ | ✓ | ✓ (all workspaces) |
| Start a scan, upload files | | ✓ | ✓ | ✓ |
| Change a check (approve, reject, lock, unlock, retire, restore) | | ✓ | ✓ | ✓ |
| Change a finding (acknowledge, resolve, mute, reopen) | | ✓ | ✓ | ✓ |
| Create, change or delete a schedule | | ✓ | ✓ | ✓ |
| Rename the workspace; add, change or remove members | | | ✓ | ✓ |
| Create a workspace; move a connection to another workspace | | | | ✓ |

**Error codes:**
- An object in a workspace the caller is not a member of: `404`, as if it did not exist.
- An action the caller's role does not allow: `403` with `{"detail": "forbidden_role", "role": "viewer", "needs": "editor"}`.
- A signed-in person with no membership: `403 no_access`, as today.

### Database (migration 0008)

- **New tables:**
  - `organisations(id, name, created_at)`;
  - `workspaces(id, organisation_id → organisations, name, is_default, created_at)`, with `UNIQUE (organisation_id, lower(name))` and at most one default per organisation;
  - `memberships(workspace_id → workspaces ON DELETE CASCADE, user_id → users ON DELETE CASCADE, role CHECK IN ('viewer','editor','admin'), created_at, created_by → users ON DELETE SET NULL)`, with primary key `(workspace_id, user_id)` and an index on `user_id`.
- **`workspace_id` on every workspace-owned table.** The column is `NOT NULL`, references `workspaces`, and is indexed where lists filter on it. The tables are `connections`, `scans`, `scan_schedules`, `assets`, `columns`, `checks`, `check_events`, `findings`, `finding_events`, `finding_occurrences` and `scores`.
  - **Filled by the database.** On every table except `connections`, a `BEFORE INSERT` trigger copies `workspace_id` from the parent row (connection, asset, check, finding or scan). A new insert path cannot leave it empty or get it wrong.
  - **Moving a connection** updates its rows in all of these tables in one transaction.
- **Row-level security.** `ENABLE` and `FORCE ROW LEVEL SECURITY` apply on those 11 tables, so the policies bind the table owner the API connects as. Each table has one policy for `USING` and `WITH CHECK`:
  ```sql
  sahifa_visible(workspace_id)  -- current_setting('sahifa.system', true) = 'on'
                                -- OR workspace_id = ANY(string_to_array(
                                --      current_setting('sahifa.workspaces', true), ',')::uuid[])
  ```
  - **Fail closed.** With neither setting, a query sees no rows.
- **Migrating existing data.** The migration creates the organisation and a workspace `Default`, and fills `workspace_id` on every existing row with `Default`, before row-level security is switched on.
- **The role `sahifa_app`.** A superuser bypasses row-level security even with `FORCE`, and the Postgres image makes `POSTGRES_USER` a superuser. The migration therefore creates a role `sahifa_app` without login (when the migrating login may create roles), grants it the tables and lets the login join it. Every API transaction switches to it with `SET LOCAL ROLE`. A login that bypasses row-level security and cannot switch makes the API refuse to start in prod (exit 4).

### Settings

| Name | Default | Meaning |
|---|---|---|
| `SAHIFA_ORG_NAME` | `Sahifa` | The organisation's name, shown in the header |
| `SAHIFA_ALLOWED_EMAILS` | (unchanged) | Until invitations (S4-3): an allowed email that has no membership becomes an **editor of `Default`** at its first request after sign-in |

### API

**Existing routes:**
- Lists return only rows the caller can see. The lists of connections, scans, assets and findings take `workspace_id` to show one workspace.
- `connections`, `scans`, `assets`, `checks`, `findings` and `schedules` responses gain `workspace: {id, name}` and `role` (the caller's role there).
- The upload route of `POST /api/scans` takes `workspace_id`. It is required only when the caller is an editor in more than one workspace (422 `workspace_required`); otherwise the only such workspace is used.
- `POST /api/connections` takes `workspace_id` in the same way and needs the admin role there.

**`GET /api/auth/me`** gains `org_admin` and `workspaces: [{id, name, role}]`.

**New routes:**

| Route | Who | Request | Response |
|---|---|---|---|
| `GET /api/workspaces` | any member | — | `[{id, name, role, connections, members}]`; org admin: all workspaces |
| `POST /api/workspaces` | org admin | `{name}` | 201 workspace; 409 `name_taken` |
| `PATCH /api/workspaces/{id}` | workspace admin | `{name}` | 200; 409 `name_taken` |
| `GET /api/workspaces/{id}/members` | workspace admin | — | `[{user_id, email, display_name, role, last_login_at}]` |
| `PUT /api/workspaces/{id}/members/{user_id}` | workspace admin | `{role}` | 200 membership (added or changed); 404 for a user who never signed in |
| `DELETE /api/workspaces/{id}/members/{user_id}` | workspace admin | — | 204 |
| `GET /api/users?q=` | workspace admin | — | people who have signed in, matched on email or name (at most 20), to add as members |
| `PUT /api/connections/{id}/workspace` | org admin | `{workspace_id}` | 200; moves the connection with its scans, assets, checks, findings, schedule and scores |

**Rules for members:**
- A workspace admin cannot demote or remove themselves (409 `own_membership`), so a workspace never locks out its last admin. An org admin can.
- Org admins are not stored as members; their access comes from the setting.

### Web

- **Header.**
  - The organisation name.
  - A workspace filter ("All workspaces" or one), when the person has more than one workspace. The choice is stored per browser.
- **Lists.** Connections, scans and findings show each item's workspace name.
- **What viewers see.** Actions their role does not allow (scan, upload, check and finding actions, schedule editing) are disabled, with the reason: "Viewers can look but not change. Ask a workspace admin for the editor role." The API refuses them anyway.
- **New page `/workspaces`**, for workspace admins and org admins:
  - the list of workspaces;
  - create a workspace (org admin);
  - rename a workspace;
  - members, with a role select, remove, and "Add a person who has signed in" (search);
  - per connection, "Move to workspace…" (org admin).

## Behaviour

1. **Per request.**
   - The API resolves the principal (spec 006) and loads their memberships, or all workspaces for an org admin.
   - It opens the database transaction with `SET LOCAL sahifa.workspaces = '<ids>'`.
   - Jobs set `SET LOCAL sahifa.system = 'on'`: the worker, the scheduler, the reaper, the upload clean-up, and connection registration at start-up.
2. **Object routes.**
   - The API loads the object under row-level security, so an object in another workspace gives 404.
   - It then compares the caller's role in that workspace with the action's minimum role. Below it: 403 `forbidden_role`.
3. **Access.**
   - A signed-in person has access if they are an org admin or have at least one membership.
   - An email in `SAHIFA_ALLOWED_EMAILS` with no membership gets the editor role in `Default` at its first request after sign-in (`/api/auth/me`).
   - Anyone else: 403 `no_access`, with a message that now says "Ask a workspace admin to add you".
4. **Connections from the environment.**
   - A `SAHIFA_CONN_*` connection that does not exist yet is registered in `Default`.
   - An existing one keeps its workspace, even after it was moved.
   - Uploads are created in the workspace chosen at upload.
5. **Moving a connection.**
   - One transaction updates `workspace_id` on the connection and on all its rows.
   - A running scan of the connection blocks the move: 409 `scan_running`.
6. **Deleting.** Workspaces are not deleted in this spec. An empty workspace stays; deleting it is S4-3.
7. **Logging.**
   - `rbac.denied` with user, workspace, action, role and needed role, for each 403.
   - `workspace.created`, `workspace.renamed`, `membership.changed`, `connection.moved`.

## Acceptance criteria

- [x] **Viewer cannot change:** a viewer gets 403 `forbidden_role` on every check and finding action, on starting a scan, on uploading and on editing a schedule. An editor gets 2xx on the same requests.
- [x] **Other workspaces are invisible:**
  - their connections, scans, assets, checks, findings, schedules and history return 404 by id;
  - they are absent from every list;
  - also on the findings page and in score history.
- [x] **Row-level security fails closed:**
  - a raw `SELECT` on each of the 11 tables, without `sahifa.workspaces` and `sahifa.system`, returns no rows;
  - with one workspace set, it returns only that workspace's rows;
  - an `INSERT` with another workspace's id fails.
- [x] **Migration 0008:**
  - upgrades a database with existing scans, so that everything is in `Default`;
  - is reversible with `downgrade`;
  - `alembic check` is clean.
- [x] **Jobs keep working:**
  - scheduled scans, queue-mode scans, the reaper and the upload clean-up still run;
  - their rows carry the right `workspace_id`.
- [x] **Allowed emails:** an allowed email signs in and becomes an editor of `Default`. An unknown email gets 403 `no_access`.
- [x] **Moving a connection** moves all its rows. A running scan blocks it.
- [x] **Web:**
  - viewers see disabled actions with the reason;
  - the workspace filter and the `/workspaces` page work for admins.
- [x] `make lint` and `make test` pass.

## Test cases

- **API, `tests/test_rls.py`** (database):
  - for each table: no setting → 0 rows; workspace A → only A's rows; `system` → all rows;
  - an insert with B's id under A → error;
  - the triggers fill `workspace_id` from the parent.
- **API, `tests/test_workspaces.py`:**
  - workspaces CRUD and its errors (`name_taken`, 403 for a non-admin);
  - members: add, change, remove, and refusal of self-demotion;
  - users search;
  - moving a connection, with a running scan → 409;
  - `/api/auth/me` lists workspaces;
  - allowed-email bootstrap.
- **API, `tests/test_roles.py`:**
  - the viewer/editor cases of the first criterion;
  - cross-workspace 404 on one route per router. The full route × role matrix is S4-2.
- **API, existing tests** run as an org admin, the `dev` principal, and keep passing.
- **Migration test:** upgrade from 0007 with data, check `Default`, downgrade, upgrade again.
- **Web:** viewer actions disabled with the reason; the workspace filter; `/workspaces` (create, rename, members, move).

## Implementation notes

- **`is_default` on workspaces.** The default workspace is found by a flag, not by its name, so
  renaming `Default` keeps new environment connections and allowed emails landing there.
- **`sahifa_app` and `SET LOCAL ROLE`.** Added to the database section above with the reason: on
  staging the login is a superuser, which row-level security does not bind. Both paths are
  tested: the role switch, and `FORCE` on a non-superuser owner when the role is missing or
  cannot be joined (the migration then warns instead of failing).
- **The scope is transaction-local.** Each transaction begins with `set_config(…, true)` from
  the session's scope, so a commit in the middle of a request keeps it and a pooled connection
  never carries it into the next request.
- **An invisible parent is refused by the policy.** Postgres checks the policy before `NOT
  NULL`, so an insert under a parent in another workspace fails with a row-level security error.
- **Creating a connection needs the admin role** in its workspace, and takes `workspace_id` like
  the upload; the spec did not say. Testing a connection stays open to viewers: it only reads.
- **The org admin must name a workspace too** once there are several, for connections and
  uploads. `Default` is the broadest workspace, so nothing lands there by accident.
- **Allowed emails come back.** While an address is in `SAHIFA_ALLOWED_EMAILS`, removing it from
  every workspace makes it an editor of `Default` again at its next request. Remove it from the
  setting too; S4-3 retires the setting.
- **Web.** Lists name each item's workspace only for someone who sees more than one. The
  workspace filter is a per-browser choice in the header, not part of the URL.

## Out of scope

- Invitations by email for people who have not signed in yet, retiring `SAHIFA_ALLOWED_EMAILS`, and deleting workspaces: S4-3.
- The route × role matrix test across every route: S4-2.
- The audit log of these changes and its page: S4-4. Membership changes and moves are logged as events in this spec.
- Several organisations per install, per-connection roles, and API tokens: R3.

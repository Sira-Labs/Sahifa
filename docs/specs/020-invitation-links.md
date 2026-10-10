# Spec 020 — Invitations by link, deleting workspaces

Sprint 4b, story S4b-1 (replaces S4-3). Depends on: spec 006 (sign-in), spec 016 (workspaces,
memberships, row-level security), spec 017 (role matrix), spec 018 (audit log). Packages:
`api/` (model, migration 0010, service, router), `web/`, `docs/`.

Status: draft, waiting for the owner's approval.

## Goal

An admin brings a test user in without touching the server. The admin creates an invitation for
an email address and a role, copies the link and sends it any way they like. The invited person
opens the link, signs in, and lands in the right workspace with the right role. This replaces
`SAHIFA_ALLOWED_EMAILS`. An org admin can also delete a workspace that is no longer needed.

There is no SMTP account yet, so Sahifa sends no email in this spec. A later spec can add an
email sender behind the same invitations.

## User story

As a workspace admin, I invite a colleague by copying a link. They click it, sign in with
Google, GitHub or a passkey, and see our workspace, with nobody editing a server setting.

## Interface

### Database (migration 0010)

**Table `invitations`:**

| Column | Type | Meaning |
|---|---|---|
| `id` | uuid | |
| `workspace_id` | uuid → workspaces, `ON DELETE CASCADE` | where the person lands |
| `email` | text, lower case | who may accept it |
| `role` | varchar(20) | `viewer`, `editor` or `admin` |
| `token_hash` | bytea, unique | SHA-256 of the token; the token itself is never stored |
| `created_by` | uuid → users, `ON DELETE SET NULL` | |
| `created_at`, `expires_at` | timestamptz | `expires_at` = created + `SAHIFA_INVITATION_TTL_DAYS` (default 7) |
| `accepted_at`, `accepted_by` | timestamptz, uuid → users, nullable | set once |
| `revoked_at` | timestamptz, nullable | |

- The table is under row-level security like the other workspace-owned tables (spec 016).
- At most one open invitation (not accepted, revoked or expired) per workspace and email: a
  partial unique index.

### Settings

| Variable | Default | Meaning |
|---|---|---|
| `SAHIFA_INVITATION_TTL_DAYS` | 7 | how long a link works (1–90) |
| `SAHIFA_ALLOWED_EMAILS` | (deprecated) | still honoured in this release, with a warning in the log at start; removed in the next release |

### API

| Route | Who | What |
|---|---|---|
| `POST /api/workspaces/{id}/invitations` `{email, role}` | admin of the workspace, org admin | creates an invitation and returns it **with the link**, once |
| `GET /api/workspaces/{id}/invitations` | admin of the workspace, org admin | open and recent invitations, without links |
| `DELETE /api/invitations/{id}` | admin of its workspace, org admin | revokes an open invitation |
| `GET /api/invitations/lookup?token=…` | anyone signed in | the workspace name, the role and the masked email, so the page can say what the link does |
| `POST /api/invitations/accept` `{token}` | anyone signed in, with or without a workspace | accepts: creates or raises the membership |
| `DELETE /api/workspaces/{id}` `{confirm: "<name>"}` | org admin | deletes a workspace (Behaviour 6) |

- **The link** is `<SAHIFA_PUBLIC_URL>/invite#<token>`, with the token after `#`. Browsers do not
  send the part after `#` to the server, and it does not reach proxy logs or the `Referer`
  header. The page reads the token and posts it.
- The token is 32 random bytes (`new_token()`, spec 006).
- **Errors** on lookup and accept:
  - an unknown, revoked or expired token: 404 `invitation_invalid`. The answer is the same for
    all three, so a token cannot be probed.
  - accepted already: 409 `invitation_used`.
  - signed in with another address: 403 `invitation_other_email`, with the masked invited
    address (`b***@example.org`).
- **Rate limit.** Lookup and accept count against the `auth` bucket of spec 012 (20 per minute
  per client).
- **Role matrix (spec 017).** The three invitation routes and workspace deletion join `OPS` with
  minimum role `admin` (deletion: org admin). Lookup and accept join the `SESSION` set.

### Web

- **On `/workspaces`, for admins:** an "Invite" form (email, role) in each workspace.
  - After creating, it shows the link once, with a "Copy link" button and the expiry date.
  - A list of open invitations with "Revoke".
- **The page `/invite`:**
  - It reads the token from the address and asks the API what it is for: "Ana invited you to
    *Finance* as editor".
  - Not signed in: a sign-in button that comes back to `/invite` with the token kept.
  - Signed in: an "Accept" button. After accepting, the workspace opens.
  - Errors in plain words: expired or revoked, already used, or the wrong address (sign out and
    sign in with the invited address).
  - The page works for a signed-in person without any workspace. The "No access yet" page links
    to it when the person has a link.
- **Deleting a workspace** (org admin, on `/workspaces`): a "Delete" button that asks the person
  to type the workspace's name, and lists what will be deleted.

## Behaviour

1. **Creating.** An admin of the workspace (or the org admin) creates the invitation. Creating
   one for an address that already has an open invitation replaces the old one: the old link
   stops working. Inviting someone who is already a member at the same or a higher role answers
   409 `already_member`.
2. **Keeping the token secret.**
   - The link is shown once, in the answer to the creating request.
   - The database stores only the SHA-256 of the token.
   - The audit log and the structured logs record the invitation id, the email and the role,
     never the token or the link.
3. **Accepting.**
   - The signed-in email must equal the invited email, ignoring case. Sign-in providers vouch
     for the address (spec 006).
   - Accepting creates the membership with the invited role. If the person is already a member
     with a lower role, it raises the role; it never lowers one.
   - The invitation is marked accepted in the same transaction. A second accept answers 409.
4. **The deprecated allowed-emails list.** It keeps working as in spec 016 for this release, so
   staging keeps its users. When it is set, the API logs once at start that it is deprecated and
   that invitations replace it. The next release removes it.
5. **Audit (spec 018).** New actions, all in the invitation's workspace:
   - `invitation.created` and `invitation.revoked`, with email and role;
   - `invitation.accepted`, with the member, together with `membership.added` or
     `membership.changed`;
   - `workspace.deleted` (Behaviour 6).
6. **Deleting a workspace.**
   - Only the org admin may delete a workspace, and never the default workspace.
   - The confirmation must repeat the workspace's name.
   - A workspace that still holds database connections from `SAHIFA_CONN_*` cannot be deleted
     (409 `workspace_has_connections`, with their names). Move them first: on the next start
     they would otherwise come back in the default workspace.
   - Everything else in it is deleted in one transaction:
     - uploads, scans, findings, checks, schedules and score history;
     - memberships and invitations;
     - its audit entries, using the purge setting of spec 018.
   - The uploaded files of its upload connections are removed from the data directory after
     the commit.
   - The deletion is recorded as `workspace.deleted` in the default workspace, with the name
     and the counts, so the record outlives the workspace.

## Acceptance criteria

- [ ] An admin creates an invitation and copies the link; the invited person opens it, signs
      in, accepts and lands in the workspace with the invited role (the sprint plan's "done when").
- [ ] Only the SHA-256 of the token is stored. No token or link appears in the audit log, the
      structured logs or a later `GET`.
- [ ] Expired, revoked, unknown and used tokens are refused with the codes above. Unknown,
      revoked and expired look the same.
- [ ] Accepting with another email is refused. Accepting never lowers an existing role.
- [ ] Invitations are admin-only; the role matrix covers the new routes, and RLS keeps another
      workspace's invitations invisible.
- [ ] The org admin deletes a non-default workspace without connections. Its rows and its
      uploaded files are gone, and `workspace.deleted` stays in the default workspace.
- [ ] `SAHIFA_ALLOWED_EMAILS` still works and logs its deprecation.
- [ ] Migration 0010 is reversible and `alembic check` is clean.
- [ ] `make lint` and `make test` pass.

## Test cases

- **API, `tests/test_invitations.py`:**
  - create, look up, accept: membership and role, accepted once, 409 on a second accept;
  - expiry (a past `expires_at`), revoke, unknown token: the same 404;
  - another email: 403 with the masked address;
  - an existing viewer accepting an editor invitation is raised; an admin accepting a viewer
    invitation stays admin;
  - a new invitation for the same address replaces the old one;
  - nothing secret recorded: the token does not appear in `audit_events`, in the API answers
    after creation, or in the captured log lines;
  - an editor creating an invitation: 403; another workspace's invitation: 404.
- **API, `tests/test_workspaces.py`:** deleting:
  - the default workspace: refused;
  - a workspace with a registered connection: 409;
  - the wrong confirmation name: refused;
  - a workspace with an upload scan, findings and an invitation: everything gone, the files
    removed, and the audit entry in the default workspace.
- **API, `tests/test_matrix.py`:** the new routes in `OPS` and `SESSION`.
- **Migration:** upgrade from 0009, downgrade, upgrade again.
- **Web:**
  - the invite form shows the link once and copies it;
  - `/invite` signed out shows the sign-in button and keeps the token;
  - signed in, it accepts and opens the workspace;
  - the error texts;
  - the delete dialog needs the name.

## Out of scope

- Sending invitation emails. That comes with an SMTP account, behind the same invitations.
- Removing `SAHIFA_ALLOWED_EMAILS`: the next release.
- Self-sign-up, and a workspace of one's own for every new person. Test users come by
  invitation.
- Transferring ownership of a deleted workspace's data elsewhere: deleting means deleting.

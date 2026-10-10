# Spec 017 — Role matrix: every route against every role

Sprint 4, story S4-2. Depends on: spec 006 (sign-in, `Principal`), spec 016 (workspaces, roles,
row-level security). Packages: `api/` (tests only, unless the matrix finds a defect), `docs/`.

Status: draft, waiting for the owner's approval.

## Goal

Spec 016 tests roles on one route per router. When this spec is done, one test asks every API
operation, as every kind of caller, and compares the answer with the role table of spec 016. It
also fails:
- when a route stops checking the role;
- when a route reads past its workspace;
- when someone adds a route without deciding who may call it.

## User story

As the administrator of a Sahifa install, I can rely on a viewer never changing anything and a
person never seeing another workspace's data, whichever route is used, including routes added
later.

## Interface

### Callers

Each runs against workspace **A**, which holds one connection with a tree of rows (scan,
schedule, asset, columns, check, check event, finding, finding event, occurrence, score). A second
workspace **B** holds a tree of its own.

| Caller | Who |
|---|---|
| `anonymous` | no session |
| `no_access` | signed in, no membership, not the org admin |
| `outsider` | editor of B only |
| `viewer` | viewer of A |
| `editor` | editor of A |
| `admin` | admin of A |
| `org_admin` | `SAHIFA_ADMIN_EMAIL` |

### Route classes

Every operation in the app's OpenAPI document is in exactly one class:

| Class | Operations | Expected |
|---|---|---|
| **public** | `/healthz`, `/api/version`, `/api/auth/options`, `/api/auth/login`, `/api/auth/passkey/add`, `/api/auth/callback`, `/api/auth/backchannel-logout` | not part of the matrix; their own tests cover them (spec 006) |
| **session** | `/api/auth/sessions` (list, revoke, revoke others), `/api/auth/logout` | `anonymous` 401; every signed-in caller, `no_access` included, gets through |
| **workspace** | the other 32 operations, `/api/auth/me` included | the matrix below |

For each workspace operation, the matrix in `api/tests/test_matrix.py` records:
- the minimum role: `viewer`, `editor`, `admin` or `org_admin`;
- the scope:
  - **object**: it names an object of A;
  - **list**: it lists across workspaces;
  - **create**: it creates something in A, named by `workspace_id`;
  - **global**: it is not about one workspace;
- the request: method, path, body or files;
- the success status.

### Expected answers

| Caller | object | list | create | global |
|---|---|---|---|---|
| `anonymous` | 401 | 401 | 401 | 401 |
| `no_access` | 403 `no_access` | 403 `no_access` | 403 `no_access` | 403 `no_access` |
| `outsider` | 404 | the success status, without A's rows | 404 | 403 `forbidden_role` below the minimum role, else success |
| below the minimum role | 403 `forbidden_role` with `role` and `needs` | (lists need only `viewer`) | 403 `forbidden_role` | 403 `forbidden_role` |
| at or above it | the success status | the success status, with A's rows | the success status | the success status |

An operation whose minimum role is `org_admin` (creating a workspace, moving a connection)
refuses everyone else with 403 `forbidden_role` before it looks anything up, the outsider
included. It names no object to them, so the 403 reveals nothing.

The table is the test's own copy of spec 016's role table. It is never derived from the route
code, so a check that goes missing from a route shows up as a difference.

## Behaviour

1. **Setup.**
   - Fresh A and B with their trees.
   - Members and sessions for the callers.
   - A fresh object for every request that changes something, so a version or a transition
     already used never answers 409 instead of the status under test.
2. **Matrix.**
   - Every (operation, caller) pair is requested once.
   - The test collects every difference from the expected answer and fails listing all of them,
     not only the first.
3. **Lists.** For a list operation the test also checks the content: A's object is in the
   answer for the members of A and the org admin, and absent for the outsider.
4. **Every route is classified.**
   - A second test reads the app's OpenAPI document and fails for any operation that is in no
     class, or in more than one.
   - So a new route needs a line in the matrix before CI passes.
5. **The matrix catches what it should.** Meta-tests break the API on purpose and assert that
   the matrix reports differences:
   - with the role check switched off (`Access.require` and `Access.pick` let everything
     through), every operation whose minimum role is above `viewer`;
   - with request sessions scoped to every workspace (as if a route forgot its scope), every
     object operation for the outsider;
   - with sign-in switched off (every request as the org admin), every operation for
     `anonymous` and `no_access`.
6. **A defect the matrix finds** is fixed in this spec, with a line in the implementation
   notes.

## Acceptance criteria

- [ ] `test_matrix` covers all 32 workspace operations for the 7 callers, plus the session
      operations, and is green.
- [ ] `test_every_route_is_classified` fails for an unclassified operation. A deliberately
      added test route shows this.
- [ ] The three meta-tests show the matrix fails when the role check, the workspace scope or
      the sign-in is removed.
- [ ] The matrix runs in under 60 seconds in CI.
- [ ] `make lint` and `make test` pass.

## Test cases

- **API, `tests/test_matrix.py`:**
  - `test_matrix`;
  - `test_session_routes`;
  - `test_every_route_is_classified`;
  - `test_matrix_catches_a_missing_role_check`;
  - `test_matrix_catches_a_missing_scope`;
  - `test_matrix_catches_a_missing_sign_in`.
- **Fixtures** reuse `tests/tenancy.py` (trees, members) and the fake identity provider of the
  sign-in tests, to sign in as each caller.

## Out of scope

- The same matrix for the web app. The web disables actions as a convenience, and the API is
  the enforcement this spec tests.
- The audit log of changes: S4-4.
- Invitations and deleting workspaces: S4-3.
- API tokens and per-connection roles: R3.

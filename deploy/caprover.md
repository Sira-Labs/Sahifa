# Deploying on CapRover

CapRover already provides the reverse proxy, TLS and container scheduling, so the compose
bundle is not used there (its Caddy would fight CapRover's nginx for ports 80/443). Instead,
three CapRover apps run the published images; CapRover's nginx terminates TLS and asks for the
basic-auth password, and the web app's Caddy proxies `/api` to the API app over the internal
network. The API reads the sources it assesses with a read-only login.

```
Internet ──▶ CapRover nginx (TLS; basic auth in the interim) ──▶ sahifa-web (Caddy :80) ──/api──▶ sahifa-api (:8000) ──▶ sahifa-db
```

## Quick start: one-click template

`deploy/caprover/one-click/sahifa.yml` creates the three apps in one step, the way Suffa's
templates do. In CapRover: **Apps → One-Click Apps/Databases → `>> TEMPLATE <<`**, paste the
file, enter the app name, fill in the variables, Deploy.

| App name you enter | Creates | Server |
|---|---|---|
| `sahifa-stg` | `sahifa-stg-db`, `sahifa-stg-api`, `sahifa-stg-web` | staging (current server) |
| `sahifa` | `sahifa-db`, `sahifa-api`, `sahifa-web` | production |

The template generates the database password, gives the api a volume for uploads at
`/data`, hides the api from the internet ("Do not expose as web-app"), points the web app's
Caddy at the api, and sets `SAHIFA_ACCESS_GATE=basic-auth-at-proxy` with `SAHIFA_AUTH_MODE=proxy`
(its Keycloak variables are optional and empty, see section 4a). After deploying, do the
template's closing steps: connect the domain with HTTPS, **turn on Password protect on the web
app**, check `/healthz`, enable app tokens. Switching to sign-in later is section 4a. The GitHub `staging` environment then needs
`CAPROVER_APP_API=sahifa-stg-api` and `CAPROVER_APP_WEB=sahifa-stg-web` (these names differ
from the hand-made `-stg` suffix of sections 1–4: the template puts the suffix before the role).

The template is optional: sections 1–4 set up the same apps by hand.

The worker (queue mode, section 3) has its own template, `deploy/caprover/one-click/sahifa-worker.yml`:
paste it the same way with the **same** app name (`sahifa-stg`); it creates `sahifa-stg-worker`
on the api's upload volume `sahifa-stg-data` and asks for the api's values (database password,
auth settings). Then set `SAHIFA_SCAN_EXECUTION=queue` on `sahifa-stg-api`, and set
`CAPROVER_APP_WORKER=sahifa-stg-worker` with the worker's app token on the GitHub environment.

## Checklist for the owner (first deploy)

Sahifa has no install yet, so the first deploy is a clean setup of staging on the current
server. Production follows later (section 5, "Production, later").

1. **DNS:** an `A` record `sahifa-stg.siralabs.org` → the staging server (the current
   CapRover server).
2. **Apps** on the staging server: either the one-click template above with the app name
   `sahifa-stg`, or by hand as in sections 1, 2 and 4 with the `-stg` names and the
   staging column of the table below: `sahifa-db-stg` (Has Persistent Data), `sahifa-api-stg`
   (Has Persistent Data), `sahifa-web-stg` with the domain `sahifa-stg.siralabs.org`,
   Enable HTTPS and Force HTTPS.
3. **Sign-in** through the Keycloak realm `sahifa` (section 4a). Until it is set up:
   **basic auth** on `sahifa-web-stg` (HTTP Settings → *Password protect*), then
   `SAHIFA_ACCESS_GATE=basic-auth-at-proxy` and `SAHIFA_AUTH_MODE=proxy` on `sahifa-api-stg`
   (section 4a, "Interim"). Without one of the two the api refuses to start.
4. **App tokens:** Deployment tab → **Enable App Token** on `sahifa-api-stg` and
   `sahifa-web-stg`; copy both.
5. **GitHub environment `staging`** with the variables and secrets of section 5, "GitHub
   settings": `CAPROVER_SERVER`, `CAPROVER_WEB_URL`, `CAPROVER_APP_API=sahifa-api-stg`,
   `CAPROVER_APP_WEB=sahifa-web-stg`, `CAPROVER_APP_WORKER=sahifa-worker-stg`, the secrets
   `CAPROVER_APP_TOKEN_API`, `CAPROVER_APP_TOKEN_WEB` and `CAPROVER_WEB_BASIC_AUTH`.
6. **First push to `main`.** `release.yml` builds, scans and publishes the images and deploys
   them to the two `-stg` apps.
7. **Verify:** `GET https://sahifa-stg.siralabs.org/api/version` (after the basic-auth prompt)
   shows the commit of that push, and the release run's last step says
   `web and api run <commit>`.
8. **Queue mode (spec 008), when you are ready:** create `sahifa-worker-stg` with the api's
   variables plus `SAHIFA_ROLE=worker` and `SAHIFA_SCAN_EXECUTION=queue`, the api's persistent
   directory label `sahifa-stg-data` on `/data`, and its app token as
   `CAPROVER_APP_TOKEN_WORKER` on the `staging` environment; then set
   `SAHIFA_SCAN_EXECUTION=queue` on `sahifa-api-stg` and check that `/healthz` lists the
   worker (section 3). Until then scans run inside the api, which is fine for staging.

Optional, any time after: connect a test database to assess (section 6).

## Staging and production (ADR-0012)

Two independent CapRover servers at Hetzner, shared with the other Sīra Labs products:

| Server | Apps | Domain | Data |
|---|---|---|---|
| **Staging and tools** (the current server) | `sahifa-db-stg`, `sahifa-api-stg`, `sahifa-web-stg`, optionally `sahifa-worker-stg` | `sahifa-stg.siralabs.org` | test data only |
| **Production** (server in Germany) | `sahifa-db`, `sahifa-api`, `sahifa-web`, optionally `sahifa-worker` | `sahifa.siralabs.org` | real people's data, and only there |

Sections 1–4 below describe one server's apps with the production names. On staging every app
name gets the `-stg` suffix, and so does every internal address and label that names an app:

| Setting | Production | Staging |
|---|---|---|
| `SAHIFA_DATABASE_URL` (and `SAHIFA_MIGRATION_DATABASE_URL`) host | `srv-captain--sahifa-db` | `srv-captain--sahifa-db-stg` |
| `SAHIFA_API_UPSTREAM` (web app) | `srv-captain--sahifa-api:8000` | `srv-captain--sahifa-api-stg:8000` |
| `SAHIFA_PUBLIC_URL` (api app) | `https://sahifa.siralabs.org` | `https://sahifa-stg.siralabs.org` |
| Persistent directory label of the db | `sahifa-pgdata` | `sahifa-stg-pgdata` |
| Persistent directory label of the api (and the worker, the same label) | `sahifa-data` | `sahifa-stg-data` |
| `CAPROVER_APP_API`, `_WEB`, `_WORKER` on the GitHub environment | unset (defaults `sahifa-api`, `sahifa-web`, `sahifa-worker`) | `sahifa-api-stg`, `sahifa-web-stg`, `sahifa-worker-stg` |

A staging app that keeps an unsuffixed address talks to nothing, or, once production apps
share a server with it, to the wrong ones. CapRover cannot rename an app: its name is also its
internal address, so choose the name when creating it.

Rules:

- Personal data of real people lives only on production. Staging connects only to test
  databases and takes only test uploads; nothing is copied across.
- Staging and production have separate secrets: database passwords, basic-auth passwords,
  source logins and CapRover app tokens.
- `main` deploys to staging automatically; production runs the image digest staging runs,
  after the owner approves it (section 5).
- Production Postgres is backed up continuously (section 8); restore drills go into a
  throwaway database on the production server, never into staging.

## 1. Database app: `sahifa-db`

- Create a plain app named `sahifa-db` with **Has Persistent Data** ticked (not a One-Click
  App: the plain app keeps the image and its version under our control).
- Deployment tab → *Deploy via ImageName*: `postgres:17`
- App Configs:
  - Environment variables: `POSTGRES_USER=sahifa`, `POSTGRES_PASSWORD=<generated>`,
    `POSTGRES_DB=sahifa`. Generate the password with `openssl rand -hex 24`: hex is safe
    inside the database URL, while base64 may contain `/` or `+`.
  - Persistent directory: path in app `/var/lib/postgresql/data`, label `sahifa-pgdata`
  - Do not map a host port; the API reaches it as `srv-captain--sahifa-db:5432`.
- Check before the first real data: App Configs must show the persistent directory above.
  Without it the data lives in the container and a restart (any Save & Update) starts an
  empty database. CapRover cannot add persistent data to an existing app: delete and
  recreate it with the box ticked.
- `POSTGRES_USER`, `POSTGRES_PASSWORD` and `POSTGRES_DB` only apply when the data directory
  is created. Changing them later changes nothing in the database (the owner keeps its
  password), so leave them as they were; to change a password, `ALTER ROLE` in `psql`.
- `postgres:17` stays on major version 17; a major upgrade needs `pg_upgrade` or a dump and
  restore, never just a new tag.

## 2. API app: `sahifa-api`

- Create app `sahifa-api` with **Has Persistent Data** ticked (for uploads).
- App Configs:
  - Environment variables:

    | Name | Value |
    |---|---|
    | `SAHIFA_ENV` | `prod` |
    | `SAHIFA_DATABASE_URL` | `postgresql+psycopg://sahifa:<password>@srv-captain--sahifa-db:5432/sahifa` |
    | `SAHIFA_MIGRATION_DATABASE_URL` | optional; an owner login for the migration step only. Defaults to `SAHIFA_DATABASE_URL` |
    | `SAHIFA_DATA_DIR` | `/data` (the image default; uploads go to `/data/uploads`) |
    | `SAHIFA_PUBLIC_URL` | the web app's address: `https://sahifa-stg.siralabs.org` on staging, `https://sahifa.siralabs.org` on production |
    | `SAHIFA_CONN_<NAME>` | one per database to assess (section 6) |

    Sign-in (section 4a, spec 006), either the Keycloak rows:

    | Name | Value |
    |---|---|
    | `SAHIFA_AUTH_MODE` | `oidc` |
    | `SAHIFA_OIDC_ISSUER` | `https://miftachun.apps.data-and-ai-dude.ch/realms/sahifa` |
    | `SAHIFA_OIDC_CLIENT_ID` | `sahifa-api` (the default) |
    | `SAHIFA_OIDC_CLIENT_SECRET` | the `sahifa-api` client's secret from Keycloak (Clients → `sahifa-api` → Credentials) |
    | `SAHIFA_SESSION_SECRET` | `openssl rand -hex 32`; changing it signs everyone out |
    | `SAHIFA_ADMIN_EMAIL` | the administrator's address; always has access |
    | `SAHIFA_ALLOWED_EMAILS` | deprecated (removed in the next release): further addresses, each an editor of `Default` at its first sign-in; invite people by link on `/workspaces` instead |
    | `SAHIFA_INVITATION_TTL_DAYS` | optional, default `7`: how long an invitation link works |
    | `SAHIFA_ORG_NAME` | optional, default `Sahifa`: the organisation's name in the header |
    | `SAHIFA_SIGN_IN_METHODS` | optional, default `google,github,passkey` |
    | `SAHIFA_SESSION_IDLE` / `SAHIFA_SESSION_ABSOLUTE` | optional, defaults `12h` / `30d` |

    or, in the interim, the basic-auth rows (section 4a, "Interim"):

    | Name | Value |
    |---|---|
    | `SAHIFA_AUTH_MODE` | `proxy` |
    | `SAHIFA_ACCESS_GATE` | `basic-auth-at-proxy`, **only after** basic auth is on for the web app |

    Optional, with their defaults:

    | Name | Default | Meaning |
    |---|---|---|
    | `SAHIFA_SAMPLE_ROWS` | `100000` | rows per table or file the profile and checks see; `0` reads everything |
    | `SAHIFA_MAX_UPLOAD_MB` | `200` | per file |
    | `SAHIFA_MAX_UPLOAD_TOTAL_MB` | `1024` | per upload request, all files together; raise nginx's limit to match (below) |
    | `SAHIFA_MAX_UPLOAD_FILES` | `20` | per upload |
    | `SAHIFA_MIN_FREE_DISK_MB` | `1024` | an upload that would leave less free disk is refused (507) |
    | `SAHIFA_RATE_LIMITS` | `on` | per session or address: sign-in 20/min, writes 120/min, reads 1,200/min (spec 012) |
    | `SAHIFA_RATE_SCANS_PER_HOUR` | `60` | scans one user may start per hour |
    | `SAHIFA_UPLOAD_TTL_DAYS` | `7` | uploaded files are deleted this long after their scan finished (hourly clean-up) |
    | `SAHIFA_SCAN_EXECUTION` | `inline` | `inline`: the api runs scans; `queue`: the worker does (section 3, same value on both apps) |
    | `SAHIFA_MAX_CONCURRENT_SCANS` | `2` | scans run at once, by the api or, in queue mode, by the worker (ADR-0009) |
    | `SAHIFA_SCHEDULE_MIN_INTERVAL_MINUTES` | `60` | a connection's schedule may not run more often (spec 010); due schedules start every minute, by the api or, in queue mode, by the worker |
    | `SAHIFA_SCAN_WORKERS` | `2` | Postgres sessions one scan uses to scan tables at once (spec 013); a source sees this many read-only connections per running scan |
    | `SAHIFA_DUCKDB_MEMORY` | `1GB` | DuckDB's memory limit per scan |
    | `SAHIFA_STATEMENT_TIMEOUT_S` | `60` | per statement against a source |
    | `SAHIFA_LOG_LEVEL` | `info` | |

    **Upload size at nginx.** CapRover's nginx refuses request bodies above its
    `client_max_body_size` with its own 413 page before Sahifa sees them. For uploads up to
    `SAHIFA_MAX_UPLOAD_TOTAL_MB`, open `sahifa-web` → HTTP Settings → *Edit Default Nginx
    Configurations* and set `client_max_body_size 1024m;` (or your value) in the `server`
    block.

    With `SAHIFA_ENV=prod` the api refuses to start unless strangers are kept out (spec 006,
    ADR-0010): either the Keycloak rows are complete (https public URL and issuer, client
    secret, a session secret of 32 characters or more, admin email, none a placeholder), or
    `SAHIFA_ACCESS_GATE=basic-auth-at-proxy` declares the proxy's password (mode `proxy`;
    unset, the mode resolves to `proxy` when the gate is set). `SAHIFA_AUTH_MODE=dev` is
    refused. It also refuses a placeholder password in `SAHIFA_DATABASE_URL` or any
    `SAHIFA_CONN_*`. Staging runs `prod` too.

  - The image runs the schema migration on every start before serving, so a redeploy
    upgrades the database in place; the app log shows the revision and `GET /api/version`
    reports it as `schema_revision`.
  - Persistent directory: `/data`, label `sahifa-data`. Uploads are disposable (deleted after
    `SAHIFA_UPLOAD_TTL_DAYS`), but without the directory a restart loses the files of scans
    still queued. In queue mode the worker mounts the same label (section 3).
  - Container HTTP port: `8000`
  - Memory: in inline mode (the default) scans run inside the api, so give the container at
    least `SAHIFA_DUCKDB_MEMORY` × `SAHIFA_MAX_CONCURRENT_SCANS` plus 512 MB. In queue mode
    (section 3) that budget moves to the worker and the api needs about 512 MB.
- HTTP Settings: no public domain. Tick **Do not expose as web-app**, so the API is reachable
  only through the web app and its password; the web app reaches it as
  `srv-captain--sahifa-api:8000` either way.
- Deployment tab → **Enable App Token**, copy it (used by CI below). For the first deploy,
  *Deploy via ImageName*: `ghcr.io/sira-labs/sahifa-api:latest`, or leave it to the first
  push to `main`.

## 3. Worker app: `sahifa-worker` (queue mode, spec 008)

Optional. Without it the api runs scans in a background thread (`SAHIFA_SCAN_EXECUTION=inline`,
the default) and cleans old uploads itself. With it, scans run in a separate Procrastinate
worker on the same Postgres (ADR-0009), so the api stays responsive and its memory no longer
has to cover DuckDB; a reaper fails scans whose worker died ("interrupted: the worker
stopped") and re-queues scans that were never queued, and the worker deletes old uploads.

1. **Create app** `sahifa-worker` (`sahifa-worker-stg` on staging) with **Has Persistent
   Data** ticked. It runs the api image; nothing else is built.
2. **Environment variables:** copy every variable of the api app (`SAHIFA_ENV`,
   `SAHIFA_DATABASE_URL`, the sign-in rows or `SAHIFA_ACCESS_GATE`, every `SAHIFA_CONN_*`, the
   limits) unchanged, then add:

   | Name | Value |
   |---|---|
   | `SAHIFA_ROLE` | `worker` |
   | `SAHIFA_SCAN_EXECUTION` | `queue` |

   The worker checks the production settings exactly as the api does, so the api's set passes.
   It never migrates: it waits up to 5 minutes for the api to bring the schema to its own
   version, then exits with code 3 (and CapRover restarts it). `SAHIFA_MIGRATION_DATABASE_URL`
   is not needed. Optional: `SAHIFA_REAPER_STALE_MINUTES` (default `10`), the time without a
   heartbeat after which a worker's running scans count as interrupted; `SAHIFA_MAX_CONCURRENT_SCANS`
   is the worker's concurrency; `SAHIFA_UPLOAD_TTL_DAYS` the upload clean-up. In queue mode the
   worker also starts the due schedules (spec 010), so keep `SAHIFA_SCHEDULE_MIN_INTERVAL_MINUTES`
   equal on both apps (the api validates it when a schedule is saved).
3. **Shared uploads.** The api stores uploads under `/data` and the worker reads them, so both
   apps mount the **same** persistent directory: App Configs → Persistent Directories → path in
   app `/data`, **label `sahifa-data`** (`sahifa-stg-data` on staging), exactly the label of
   the api app. CapRover names the Docker volume after the label, so the two apps share one
   volume. This works on a single server (a multi-node swarm needs shared storage, R3).
4. **No HTTP.** The worker serves nothing: tick **Do not expose as web-app**; the container
   HTTP port does not matter. Its healthcheck looks for the running worker process.
5. **App token.** Deployment tab → **Enable App Token**, copy it into the GitHub secret
   `CAPROVER_APP_TOKEN_WORKER` of the environment (`staging`, later `production`). The
   workflows deploy the worker only when that secret exists. First deploy via ImageName:
   `ghcr.io/sira-labs/sahifa-api:latest` (or the `sha-<short>` the api runs).
6. **Switch the api to queue mode:** add `SAHIFA_SCAN_EXECUTION=queue` to the **api** app too,
   Save & Update. From then on the api only records and enqueues scans. Both apps must use the
   same mode: a worker with `inline` refuses to start (exit code 2), and an api in `inline`
   would run scans itself next to the worker.
7. **Check:** `GET /healthz` (through the web app) lists the worker in `workers`, e.g.
   `[{"commit": "<sha>", "connections": 4}]`: the worker names its database connections
   `sahifa-worker/<commit>`. Upload a file; the worker log shows `scan.started` and
   `scan.succeeded` with `worker` = the commit. The deploy workflows wait for that commit in
   `workers` once the token is set.

To go back to inline, set `SAHIFA_SCAN_EXECUTION=inline` (or remove it) on the api and stop the
worker app; scans still queued are marked interrupted at the api's next start.

## 4. Web app: `sahifa-web`

- Create app `sahifa-web` (no persistent data).
- App Configs → Environment variables: `SAHIFA_API_UPSTREAM=srv-captain--sahifa-api:8000`
  (Caddy inside the image proxies `/api` and `/healthz` there; `SAHIFA_DOMAIN` stays unset so
  Caddy serves plain HTTP on :80 behind CapRover).
- Container HTTP port: `80`.
- HTTP Settings: connect the domain (`sahifa.siralabs.org`, on staging
  `sahifa-stg.siralabs.org`), Enable HTTPS, Force HTTPS.
- Deployment tab → **Enable App Token**, copy it. First deploy via ImageName:
  `ghcr.io/sira-labs/sahifa-web:latest`, or leave it to the first push to `main`.

Open the domain: after the password prompt the page shows the API version and lets you
upload a file.

## 4a. Sign-in: Keycloak realm, Google and GitHub (spec 006)

Sahifa signs people in through a Keycloak realm with Google, GitHub and passkeys, no
passwords (ADR-0010). Staging uses realm `sahifa` on the current Keycloak
(`miftachun.apps.data-and-ai-dude.ch`); production gets its own realm (and later its own
Keycloak). Below, `<kc>` is the Keycloak host (staging: `miftachun.apps.data-and-ai-dude.ch`),
`<realm>` the install's realm (staging: `sahifa`) and `<public>` the install's address, e.g.
`https://sahifa-stg.siralabs.org`.

```mermaid
sequenceDiagram
    participant B as Browser
    participant W as sahifa-web (/api)
    participant K as Keycloak realm sahifa
    participant G as Google or GitHub
    B->>W: GET /api/auth/login?method=google
    W-->>B: 302 to K (state, nonce, PKCE)
    B->>K: authorize
    K-->>B: 302 to G (kc_idp_hint)
    B->>G: sign in
    G-->>B: 302 to K broker endpoint
    B->>K: broker callback
    K-->>B: 302 to /api/auth/callback?code
    B->>W: callback
    W->>K: code + verifier + client secret
    K-->>W: ID token
    W-->>B: 302 to the app, session cookie
```

1. **Import the realm.** From a checkout of this repository:

   ```bash
   python3 deploy/keycloak/render.py <public> > sahifa-realm.json
   ```

   Keycloak admin console → realm drop-down → **Create realm** → *Resource file*: the rendered
   file → Create. It sets the `sahifa-api` client's redirect URI
   (`<public>/api/auth/callback`), post-logout redirect (`<public>/`) and back-channel logout
   URL (`<public>/api/auth/backchannel-logout`). A second install renders with its own
   address.
2. **Client secret.** Realm `<realm>` → Clients → `sahifa-api` → Credentials → Regenerate, and
   copy it into the api app's `SAHIFA_OIDC_CLIENT_SECRET`.
3. **Google.** Google Cloud console → APIs & Services:
   - OAuth consent screen: External, app name "Sahifa", scopes `openid`, `email`, `profile`.
   - Credentials → Create credentials → OAuth client ID → *Web application*; authorised
     redirect URI `https://<kc>/realms/<realm>/broker/google/endpoint`.
   - Keycloak → Identity providers → `google`: paste the client ID and secret → Save.
4. **GitHub.** GitHub → Settings (of the `Sira-Labs` organisation, or your account) →
   Developer settings → OAuth Apps → New OAuth App:
   - Homepage URL `<public>`; authorization callback URL
     `https://<kc>/realms/<realm>/broker/github/endpoint`.
   - Generate a client secret; Keycloak → Identity providers → `github`: paste the client ID
     and secret → Save.
   - GitHub accounts whose primary email is not verified cannot sign in (Sahifa refuses
     unverified email).
5. **API settings.** On `sahifa-api` set the Keycloak rows of section 2:

   | Name | Value |
   |---|---|
   | `SAHIFA_AUTH_MODE` | `oidc` |
   | `SAHIFA_PUBLIC_URL` | `<public>` (already set) |
   | `SAHIFA_OIDC_ISSUER` | `https://<kc>/realms/<realm>` |
   | `SAHIFA_OIDC_CLIENT_SECRET` | from step 2 |
   | `SAHIFA_SESSION_SECRET` | `openssl rand -hex 32` |
   | `SAHIFA_ADMIN_EMAIL` | the administrator's address |
   | `SAHIFA_ALLOWED_EMAILS` | deprecated, optional: comma-separated |

   Remove `SAHIFA_ACCESS_GATE`, then Save & Update. `SAHIFA_ADMIN_EMAIL` gets in; everyone else
   needs an invitation link from `/workspaces` (or, until it is removed, an address in
   `SAHIFA_ALLOWED_EMAILS`). Anyone else who signs in sees "No access yet" and gets 403 from the API.
   A changed list takes effect at the next restart.
6. **Basic auth off.** `sahifa-web` → HTTP Settings → untick **Password protect**, and delete
   the GitHub secret `CAPROVER_WEB_BASIC_AUTH` of that environment. Keep the API on **Do not
   expose as web-app**: the web app stays the single entrance, so the cookie, the `Origin`
   check and Caddy's security headers all see one origin.
7. **Check.** Open `<public>`: the sign-in page shows the three buttons. Sign in with Google
   as the admin email; the header shows your name, Account lists the device.
   `curl -s -o /dev/null -w '%{http_code}' <public>/api/scans` answers `401`;
   `/api/version` and `/healthz` stay public for the deploy checks.
8. **Passkeys.** Signed in with Google or GitHub, Account → **Add a passkey**: sign in again
   with the same provider, then confirm the passkey on the device (fingerprint, face or PIN).
   Back on Account it says "Passkey added"; from then on "Sign in with a passkey" works.
   **Manage passkeys** (Keycloak's account console → *Signing in*) renames or removes them.
   A realm imported before 2026-10-02: Identity providers → `google` → turn on
   **Pass login_hint**, so Google preselects the signed-in account.
   A first sign-in always goes through Google or GitHub. Passkeys belong to the Keycloak host:
   a new Keycloak host needs new passkeys.
   Removing a passkey in the account console runs Keycloak's **Delete Credential** required
   action (Keycloak 24+). The realm export enables it; a realm imported before 2026-10-03
   needs Authentication → Required actions → **Delete Credential** → Enabled.

**Recovering someone who lost every passkey** (operator step): confirm the person's identity
out of band. Then in Keycloak → Users → the user → Credentials, delete the passkey (WebAuthn
passwordless) credentials. They sign in with Google or GitHub and set up a new passkey.

### Interim: HTTP basic auth at the proxy

Until the realm is set up (and on installs that do without sign-in), CapRover's nginx asks
for a password in front of the web app, and the api runs in `proxy` mode: every request acts
as one principal, there is no login page and no device list.

1. `sahifa-web` → HTTP Settings → **Password protect**: a user name (e.g. `sira`) and a
   generated password (`openssl rand -base64 24`). Save. The domain now answers `401` without
   the password, on every path including `/api/version`.
2. Keep the API and the worker off the internet: **Do not expose as web-app** on both
   (sections 2 and 3). Otherwise CapRover's default address of the API would bypass the
   password.
3. `sahifa-api` → App Configs: `SAHIFA_ACCESS_GATE=basic-auth-at-proxy` and
   `SAHIFA_AUTH_MODE=proxy` → Save & Update. In prod the api refuses to start without one of
   the two ways in (Keycloak or the gate); with the gate set and no mode, it runs as `proxy`.
4. Put `user:password` into the GitHub secret `CAPROVER_WEB_BASIC_AUTH` of the same
   environment, so the deploy workflows can check the version behind the prompt.
5. Share the password only with the people who test staging (or use production), through the
   password manager. Staging and production have different passwords.

Set the gate variable only after step 1: it records that the gate exists, it does not create
it.

## 5. Continuous deployment: staging, then promotion to production

Two workflows (ADR-0012):

- **`release.yml`**: every push to `main` (and every `v*` tag on a commit on `main`) builds,
  scans and publishes the images, then its `deploy-staging` job deploys them to the `-stg`
  apps and waits until staging serves the commit.
- **`promote.yml`**: Actions → promote → Run workflow on `main`, with the commit staging
  serves (`GET https://sahifa-stg.siralabs.org/api/version` → `commit`). It checks that the
  commit is on `main` and live on staging (web and api, and the worker once staging has one),
  pins the images to their digests, waits for the owner's approval on the `production`
  environment, deploys those digests (`tag@sha256:…`) to the production apps and waits until
  production serves the commit.

```mermaid
flowchart LR
    P["push to main"] --> R["release.yml<br/>build, Trivy, publish<br/>sha-&lt;short&gt;"]
    R --> S["deploy-staging<br/>sahifa-*-stg"]
    S --> WS["wait-live<br/>staging serves the commit"]
    WS -. "owner: Run workflow<br/>with the commit" .-> PR["promote.yml<br/>check staging, pin digests"]
    PR --> AP{"approval on<br/>production"}
    AP --> D["deploy the same digests<br/>sahifa-*"]
    D --> WP["wait-live<br/>production serves the commit"]
```

`sha-<short>` tags are immutable: a re-run of `release.yml` for the same commit leaves them
on the digest staging got, and runs for the same commit are serialised so two cannot create
the tag at once. Promotion resolves that tag to digests and deploys by digest, on CapRover
(`tag@sha256:…`) and on a compose host (`SAHIFA_API_IMAGE`, `SAHIFA_WEB_IMAGE`).

Both wait-until-live checks are `.github/scripts/wait-live.sh`, and both fail when their
environment has no `CAPROVER_WEB_URL`: CapRover accepts a deploy before it pulls the image, so
without the check a failed pull or a container that never starts would leave the run green.
It polls `<url>/version.json` (web image) and `<url>/api/version` (api image) for the commit,
sending `CAPROVER_WEB_BASIC_AUTH` past the password prompt, and, once a worker app exists,
waits until `<url>/healthz` lists a connected worker on that commit (the worker names its
database connections `sahifa-worker/<commit>`). That shows a worker on the commit is
connected, not that the old one has stopped.

### GitHub settings (owner, once)

Settings → Environments:

| Environment | Deployment branches and tags | Protection | Variables | Secrets |
|---|---|---|---|---|
| `staging` | Selected: branch `main`, tag pattern `v*` | none | `CAPROVER_SERVER` (the current server's `https://captain.…`), `CAPROVER_WEB_URL=https://sahifa-stg.siralabs.org`, `CAPROVER_APP_API=sahifa-api-stg`, `CAPROVER_APP_WEB=sahifa-web-stg`, `CAPROVER_APP_WORKER=sahifa-worker-stg` | `CAPROVER_APP_TOKEN_API`, `CAPROVER_APP_TOKEN_WEB` of the staging apps (`CAPROVER_APP_TOKEN_WORKER` once the worker app exists, section 3); `CAPROVER_WEB_BASIC_AUTH` (`user:password` of section 4a) |
| `production` | Selected: branch `main` | Required reviewer: the owner; prevent self-review off | `CAPROVER_SERVER` (the production server), `CAPROVER_WEB_URL=https://sahifa.siralabs.org`; the `CAPROVER_APP_*` variables stay unset (defaults `sahifa-api`, `sahifa-web`, `sahifa-worker`); for a compose host instead: `DEPLOY_HOST`, `DEPLOY_USER` | `CAPROVER_APP_TOKEN_API`, `_WEB` (and `_WORKER` once production has a worker) of the production apps; `CAPROVER_WEB_BASIC_AUTH`; `DEPLOY_SSH_KEY` for a compose host |

Do not create repository-level `CAPROVER_*` variables or secrets (Settings → Secrets and
variables → Actions): repository values reach every job, environment values only the jobs
that bind the environment and pass its rules. The rules hold even if a branch edits a
workflow file: a job that names `production` from any branch other than `main` is refused
before it sees a secret.

Until `CAPROVER_SERVER` is set on `staging`, the `deploy-staging` job is a no-op with a
notice, so CI and image publishing work before CapRover is ready.

Release tags: import `.github/rulesets/protect-release-tags.json` (CONTRIBUTING.md,
"Repository settings") so that only organisation admins can create, move or delete `v*`
tags.

### First setup (owner)

There is no earlier install to move, so the setup is clean and in this order:

1. **Staging.** Point `sahifa-stg.siralabs.org` at the current server, create
   `sahifa-db-stg`, `sahifa-api-stg` and `sahifa-web-stg` as in sections 1, 2 and 4 with the
   staging column of the table in "Staging and production", and set up the sign-in or, in
   the interim, the access gate (section 4a).
2. **GitHub environments.** Create `staging` as in the table above. Create `production` too,
   with its required reviewer and branch rule, but leave its variables and secrets empty
   until step 4: promote.yml stops at its gate with an error until then.
3. **First deploy.** Push to `main` (or re-run the latest `release` run). Check
   `GET https://sahifa-stg.siralabs.org/api/version`.
4. **Production, later.** Once the owner has ordered (or chosen) the production server:
   install CapRover there (strong dashboard password, 2FA, SSH by key only, firewall open
   for 80, 443 and 22), point `sahifa.siralabs.org` at it, create `sahifa-db`, `sahifa-api`
   and `sahifa-web` with production secrets and the production column, set up the access
   gate with its own password, fill in the `production` environment, set up backups
   (section 8), and run promote.yml for the commit staging runs. Check `GET /api/version`
   on the public domain.

Images are public on GHCR, so neither server needs registry credentials; if the repository
ever becomes private, add the registry under CapRover → Cluster → Docker Registries first.

## 6. Connect a database to assess

Sahifa reads sources only, and stores only the name of the variable that holds the
credentials (ADR-0006). For each Postgres database:

1. **A read-only login on the source.** As an owner or admin of that database, with a
   password from `openssl rand -hex 24` (hex, because it sits in a URL):

   ```sql
   CREATE ROLE sahifa_reader LOGIN PASSWORD '<generated>';
   GRANT CONNECT ON DATABASE <db> TO sahifa_reader;

   -- for every schema Sahifa should assess (here: public and sales)
   GRANT USAGE ON SCHEMA public, sales TO sahifa_reader;
   GRANT SELECT ON ALL TABLES IN SCHEMA public, sales TO sahifa_reader;
   -- tables the owning role creates later become readable too
   ALTER DEFAULT PRIVILEGES FOR ROLE <owner role> IN SCHEMA public, sales
     GRANT SELECT ON TABLES TO sahifa_reader;

   -- optional: table and index statistics for the store-health items
   GRANT pg_read_all_stats TO sahifa_reader;
   ```

   No `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE` or `CREATE`. Sahifa additionally opens every
   session as a read-only transaction with a statement timeout
   (`SAHIFA_STATEMENT_TIMEOUT_S`, 60 s), a lock timeout (2 s) and the application name
   `sahifa/<scan id>`, so a scan cannot write, cannot wait on a lock for long, and shows up
   in the source's `pg_stat_activity`. The grants are the first line of defence; the session
   settings are the second.
2. **Network.** The source must accept connections from the CapRover server: another app on
   the same server is `srv-captain--<app>:5432`; a database elsewhere needs its firewall and
   `pg_hba.conf` opened for the server's IP only, and TLS (add `sslmode=require`, or
   `verify-full` with a proper certificate, to the URL).
3. **The variable.** `sahifa-api` → App Configs → add

   ```
   SAHIFA_CONN_SHOP=postgresql://sahifa_reader:<generated>@<host>:5432/<db>?schemas=public,sales
   ```

   `schemas` limits the scan to those schemas. Save & Update. At start the api registers a
   connection named after the variable in lower case (`shop`). With a worker (section 3) add
   the same variable to `sahifa-worker`: the worker reads the source.
4. **Check.** In the web app, the connection list shows `shop`; *Test* succeeds. Start a
   scan. A failure is logged by the api as `conn.failed`
   (connection test or start-up) or `scan.failed` (a scan), with the connection name and the
   database's error message, never the credentials.

Staging connects only to test databases; a database with real people's data is connected
only on production, with its own `sahifa_reader` password. Keep every `SAHIFA_CONN_*` value
in the password manager too: Sahifa's database does not hold it, so a backup cannot restore
it.

## 7. Alternative: let CapRover build from GitHub (Method 3)

Instead of pulling images from GHCR, each app can clone the repository and build its own
image on the server. Both Dockerfiles use the repository root as build context, so the
`captain-definition` files under `deploy/caprover/` point at them:

| App | Deployment tab → captain-definition Relative Path |
|---|---|
| `sahifa-api` | `./deploy/caprover/api/captain-definition` |
| `sahifa-web` | `./deploy/caprover/web/captain-definition` |

In each app's Deployment tab fill in *Repository* (`github.com/Sira-Labs/Sahifa`),
*Branch* (`main`) and, because the repository is public, no username/password. Save, copy
the generated webhook URL, and add it on GitHub under Settings → Webhooks (content type
JSON, "just the push event"). Every push to `main` then rebuilds and redeploys both apps.
The database app keeps using *Deploy via ImageName*.

Trade-offs against the GHCR path in section 5:

- If the Dockerfiles use BuildKit cache mounts, CapRover must be 1.15.0 or newer, the first
  release that builds with BuildKit. Check the version under Settings.
- The Python environment and the web bundle are built on your Hetzner server on every push,
  next to the running apps. The GHCR path does that on GitHub runners.
- No Trivy scan, SBOM or provenance, and no wait-until-live check after the deploy.
- It deploys whatever `main` currently is, not the immutable `sha-<short>` tag the release
  workflow published, so rolling back means pushing a revert, and there is nothing to
  promote to production.
- No app tokens are needed; the `deploy-staging` job stays skipped as long as
  `CAPROVER_SERVER` is unset on the `staging` environment.

Do not enable both paths for the same app, or each push deploys it twice.

## 8. Production backups (ADR-0012)

Required before real users arrive on production; not built yet (`TASKS.md`). Staging needs
none of it: its data can be rebuilt.

- **Point-in-time recovery for Postgres:** continuous WAL archiving with WAL-G or pgBackRest,
  on top of physical base backups: a full every week and a delta every day, at least two
  fulls kept. WAL replays only onto a base backup, so the recovery point of minutes rests on
  them.
- **Nightly logical dump:** `pg_dump -Fc` of `sahifa`, so a single scan, connection or check
  history can be restored without rolling the whole database back.
- **Uploads need no backup.** They are working copies deleted after
  `SAHIFA_UPLOAD_TTL_DAYS`; the scan reports in the database keep what was found.
- **Configuration:** the api's environment (database URL, `SAHIFA_CONN_*`, basic-auth
  password) lives in CapRover, not in the database; keep it in the owner's password manager.
- **Where:** everything encrypted (WAL-G libsodium or pgBackRest `repo-cipher`; the dump with
  `age` or `rclone crypt`), to S3-compatible object storage in a different Hetzner location
  than the production server. The encryption keys also go into the owner's password manager.
- **Restore drill:** restore the latest base backup plus WAL, and the latest dump, into a
  throwaway database on the production server, compare row counts and `GET /api/version`
  against it, time it, drop it, and record the time in `TASKS.md`. Never restore production
  data into staging.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `deploy-staging` or `promote` fails with an HTML `404 Not Found` from nginx | `CAPROVER_SERVER` points at an app domain instead of the dashboard | Set it to `https://captain.<root-domain>` on that environment |
| `deploy-staging` deploys to `sahifa-api` instead of `sahifa-api-stg` and fails | `CAPROVER_APP_API`, `_WEB`, `_WORKER` unset on `staging` | Set them to the `-stg` names (section 5, "GitHub settings") |
| Wait step: `serves web '?', api '?'` although the apps run | the basic-auth prompt answers `401` | Set `CAPROVER_WEB_BASIC_AUTH` (`user:password`) on that environment |
| API log: `db.schema_mismatch` and the container exits with code 3 | the database is at another migration revision than the image (an older image after a newer one migrated, or a migration that failed) | Redeploy the newest image; it migrates on start. Never run two api versions against one database |
| API log: `refusing to start in prod: ... ['SAHIFA_DATABASE_URL']` | the password is `sahifa`, `change-me` or similar; prod rejects placeholders | Use a generated password in both the db app and the URL |
| API log: `refusing to start in prod` naming `SAHIFA_ACCESS_GATE` | neither the sign-in nor the access gate is set up (spec 006, ADR-0010) | Set the Keycloak rows (section 4a), or turn on basic auth for the web app and set `SAHIFA_ACCESS_GATE=basic-auth-at-proxy` (section 4a, "Interim") |
| API log: `refusing to start in prod` naming `SAHIFA_OIDC_*`, `SAHIFA_SESSION_SECRET` or `SAHIFA_ADMIN_EMAIL` | `SAHIFA_AUTH_MODE=oidc` with a missing, short or placeholder setting | Fill in the rows of section 4a, step 5; the session secret needs 32 characters (`openssl rand -hex 32`) |
| Sign-in page: "Sign-in failed (invalid_token)" | the realm's issuer differs from `SAHIFA_OIDC_ISSUER`, or the user's email is not verified | Copy the issuer from `https://<kc>/realms/<realm>/.well-known/openid-configuration`; verify the email at Google or GitHub |
| Signed in, "No access yet" | the person is not the admin and has no workspace yet | A workspace admin creates an invitation link on `/workspaces` and sends it; the person opens it while signed in with the invited address |
| Invitation page: "This invitation is for …" | signed in with another address than the invited one | Sign out and sign in with the invited address, or ask for a link for this address |
| API log: `refusing to start in prod` naming a `SAHIFA_CONN_*` variable | that source URL carries a placeholder password | Put the generated `sahifa_reader` password in it |
| Web log: `dial tcp: lookup api ... no such host` | `SAHIFA_API_UPSTREAM` missing or misspelled on the **web** app | Set it to `srv-captain--sahifa-api:8000` (two dashes) and Save & Update |
| Web log: `lookup srv-captain--... no such host` | the API app has a different name (on staging: `-stg`) | Match the upstream to `srv-captain--<api app name>:8000` |
| Connection missing from the list | the variable does not start with `SAHIFA_CONN_`, or the api was not restarted | Fix the name; Save & Update |
| API log: `conn.failed` with `password authentication failed` | wrong password in `SAHIFA_CONN_*`, or the role lacks `LOGIN` | Reset it with `ALTER ROLE sahifa_reader PASSWORD ...` on the source and update the variable |
| API log: `conn.failed` with `no pg_hba.conf entry` or a timeout | the source does not accept the CapRover server | Open its firewall and `pg_hba.conf` for the server's IP (section 6, step 2) |
| API log: `conn.failed` with `could not translate host name` | a wrong host, or `srv-captain--<app>` of another server | Use the source's public name, or the app name on this server |
| API log: `scan.failed` with `permission denied for table` or `for schema` | the login lacks `USAGE` or `SELECT`, or the table is newer than the grant | Run the grants of section 6 again, with `ALTER DEFAULT PRIVILEGES` for the role that creates tables |
| API log: `scan.failed` with `canceling statement due to statement timeout` or `lock timeout` | a table too large for the sample query in 60 s, or a long lock on the source | Lower `SAHIFA_SAMPLE_ROWS` or raise `SAHIFA_STATEMENT_TIMEOUT_S`; scan outside the source's busy hours |
| Upload answers `413` | the file is larger than `SAHIFA_MAX_UPLOAD_MB`, or than nginx in front allows | Raise the limit, and `client_max_body_size` in the web app's HTTP Settings → nginx configuration |
| The api restarts during a scan; the scan shows `failed: interrupted` | the container ran out of memory (DuckDB) | Give it more memory, or lower `SAHIFA_DUCKDB_MEMORY` or `SAHIFA_MAX_CONCURRENT_SCANS` |
| A scan shows `interrupted: the worker stopped` | the worker died or was redeployed during the scan (out of memory, or stopped before the scan ended); the reaper marked it after `SAHIFA_REAPER_STALE_MINUTES` | Rescan; for memory, as in the row above but on the worker app |
| Worker exits with code 2: `refusing to start the worker: SAHIFA_SCAN_EXECUTION is inline` | the worker app lacks `SAHIFA_SCAN_EXECUTION=queue` | Set it on the worker and the api (section 3) |
| Worker log: `db.schema_mismatch`, exit code 3 | the api has not migrated to the worker's image within 5 minutes | Deploy the same image to the api (it migrates on start); the worker then starts |
| Worker scans fail with `No such file` for an upload | the worker does not share the api's `/data` volume | Give both apps the same persistent directory label (section 3, step 3) |
| Scans stay `queued` | queue mode on the api but no worker running | Start the worker app, or set `SAHIFA_SCAN_EXECUTION=inline` on the api |
| DB log: `superuser password is not specified` | image deployed before the env vars were saved | Save & Update the db app; it initialises on the next start |

Environment variable changes only take effect after **Save & Update** on that app's App
Configs tab.

## Notes

- Keep the Hetzner firewall closed except 80/443 (CapRover) and your SSH port.
- Backups on staging: CapRover persistent volumes live under `/captain/data/`; snapshot the
  server or `pg_dump` from a one-off container on the same network if you want to keep test
  results.
- Resource guidance for a pilot: 2 vCPU / 4 GB is enough for the API, web and database with
  the default limits; the API's memory grows with `SAHIFA_DUCKDB_MEMORY` ×
  `SAHIFA_MAX_CONCURRENT_SCANS`, and the database's disk with the number of scans kept.

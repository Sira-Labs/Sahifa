# Quick start: Sahifa on your own machine

About 15 minutes from nothing to a first report on your own database and files. You need
Docker with the compose plugin; Sahifa runs as four containers (web, api, worker, its own
Postgres). It only ever reads your sources.

The CI job `quickstart` (spec 021) follows these steps on a fresh machine for every change.

## 1. Download

```bash
mkdir -p ~/sahifa && cd ~/sahifa
base=https://raw.githubusercontent.com/Sira-Labs/Sahifa/main/deploy
curl -fsSL "$base/compose.yaml" -o compose.yaml
curl -fsSL "$base/.env.example" -o .env
curl -fsSL "$base/compose.override.example.yaml" -o compose.override.yaml
```

## 2. A password at the edge

Without Keycloak, the web container asks for a password on every page and API call. Make a
hash of the password you want:

```bash
docker compose run --rm --no-deps web caddy hash-password
```

In `.env`, set:

```bash
POSTGRES_PASSWORD=<output of: openssl rand -hex 24>
SAHIFA_AUTH_MODE=proxy
SAHIFA_ACCESS_GATE=basic-auth-at-proxy
SAHIFA_EDGE_AUTH=basic
SAHIFA_BASIC_AUTH_USER=me
SAHIFA_BASIC_AUTH_HASH='<the hash, in single quotes>'
```

Everyone who knows the password sees everything; for several people with their own
accounts and roles, use sign-in through Keycloak instead (`caprover.md`, section 4a).

## 3. Your sources

**A database.** Give Sahifa a read-only login (`docs/guides/read-only-login.md`) and add one
line per database to `.env`:

```bash
SAHIFA_CONN_SHOP=postgresql://sahifa_reader:<password>@<host>:5432/<db>?schemas=public
```

A database on the same machine is reached as `host.docker.internal`. The override file you
downloaded declares that name for the api and the worker.

**A folder of files** (CSV, TSV, Parquet, JSON). Put it, or a link to it, next to
`compose.yaml` as `exports/`, or change the path in `compose.override.yaml`. Keep the `:ro`:
Sahifa gets read-only access. Then add to `.env`:

```bash
SAHIFA_CONN_EXPORTS=/sources/exports
```

Each `SAHIFA_CONN_<NAME>` becomes a connection named `<name>` in lower case.

## 4. Start

```bash
docker compose up -d
docker compose ps        # web, api, worker and db up; web-volume exited 0
```

Open `http://localhost` (or the server's address) and enter the password.

## 5. Check the logins, then scan

- *Connections* → **Test** on each connection. It shows the number of tables or files it
  sees and what the login may do:
  - "Read-only login" is what you want;
  - "This login could write" names the tables or the folder and says what to revoke. Scans
    still run read-only, but fix the login.
- *New scan* → pick the connection → **Start scan**. The report opens when it is done.

## Next

- Scheduled scans: on the connection, *Schedule*.
- TLS and a domain: set `SAHIFA_DOMAIN`, with ports 80 and 443 reachable (`README.md`).
- Updating: `docker compose pull && docker compose up -d`; migrations run on start.
- Something wrong: `docker compose logs api worker`, and the troubleshooting table in
  `caprover.md`, which applies to compose as well.

# A read-only login for Sahifa

Sahifa only reads its sources. It opens every Postgres session as a read-only transaction,
with a statement timeout and a lock timeout (ADR-0006). The login it is given should still be
read-only itself: the grants are the first line of defence, the session settings the second.
The connection's **Test** button, every scan report and `sahifa access` tell you which kind of
login Sahifa has (spec 021).

## Postgres

As an owner or admin of the database, with a password from `openssl rand -hex 24` (hex,
because it sits in a URL):

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

No `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE` or `CREATE`, no table ownership, and none of the
attributes `SUPERUSER`, `BYPASSRLS`, `CREATEROLE`, `CREATEDB` or `REPLICATION`.

On Postgres 14 and older every role may create tables in `public` unless that was revoked.
Sahifa reports it as "may create in schema public"; revoke it for everyone:

```sql
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
```

The URL Sahifa gets names the schemas to assess:

```
SAHIFA_CONN_SHOP=postgresql://sahifa_reader:<generated>@<host>:5432/<db>?schemas=public,sales
```

## What "could write" means

Sahifa says a login **could write** when, in the schemas it assesses, the login:

- has `INSERT`, `UPDATE`, `DELETE` or `TRUNCATE` on a table, or owns one;
- may `CREATE` in a schema, or in the database;
- has one of the attributes above, or is a member of `pg_write_all_data`,
  `pg_write_server_files` or `pg_execute_server_program`.

It names the tables (the first 20) and says what to revoke. Scans still run, read-only as
always; the warning is for the person who set up the login.

## Files

Mount folders into the api and the worker **read-only** (`:ro` in compose, see
`deploy/compose.override.example.yaml`). Sahifa opens files read-only either way, but a
writable mount lets the process change them; the connection test says "could write" and
names the folder.

## Check it

- In the web app: *Connections* → **Test**.
- On the command line, with the core installed: `sahifa access '<url or folder>'`, which exits
  with 0 for a read-only login, 3 for one that could write and 1 when it cannot tell.

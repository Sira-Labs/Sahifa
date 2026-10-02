# ADR-0006: Read-only source access; credentials by reference

- **Status:** Accepted
- **Date:** 2026-10-02
- **Deciders:** owner

## Context

Sahifa holds the keys to other people's databases. A leaked connection string or a query that
locks a production table would do more harm than any quality problem it finds.

## Decision

- **Credentials are never stored in Sahifa's database or logs.** A connection stores
  non-secret settings (host, database, schema filter, S3 prefix) and a `secret_ref`: the name
  of an environment variable that holds the DSN or key, which must start with `SAHIFA_CONN_`.
  R2 adds envelope encryption (a key from `SAHIFA_SECRET_KEY`, AES-GCM) for credentials entered
  in the UI; the env reference stays the recommended path.
- **Read-only:** Postgres sessions run `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY`,
  `statement_timeout` (default 60 s), `lock_timeout` (2 s), `idle_in_transaction_session_timeout`
  and an `application_name` of `sahifa/<scan id>`. Documentation asks for a login with
  `SELECT` grants only (and `pg_read_all_stats` for the health items).
- **Sampling by default** (100,000 rows per asset), full reads opt-in.
- **Personal values masked:** example values of semantic types `email`, `phone_e164`,
  `iban`, `eu_vat` are masked in reports (first two and last two characters kept).
- **Uploads:** limits on size (`SAHIFA_MAX_UPLOAD_MB`, default 200), count (20 files) and
  extension (`.csv`, `.tsv`, `.parquet`, `.json`, `.jsonl`, `.ndjson`); stored under random
  names; deleted after `SAHIFA_UPLOAD_TTL_DAYS` (default 7).

## Alternatives considered

| Option | Pros | Cons | Why not |
|---|---|---|---|
| Store DSNs encrypted from day one | UI-only setup | Key management before there is sign-in | Comes with sign-in in R2 |
| Vault integration | Strong | One more service on a small install | Optional later; env references work with Vault agents already |

## Consequences

- Adding a Postgres connection on CapRover means adding one env var on the API app (and the
  worker) and a connection pointing at its name: `deploy/caprover.md` section 6.
- The prod settings guard refuses `SAHIFA_CONN_*` values containing placeholder passwords.

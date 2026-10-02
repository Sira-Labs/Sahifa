# ADR-0014: SAP data: HANA pushdown as an optional connector, plus an SAP rule pack

- **Status:** Accepted (implementation R2, sprints 7–8)
- **Date:** 2026-10-02
- **Deciders:** owner

## Context

Much of the data that matters to companies lives in SAP: S/4HANA and ECC tables, BW/4HANA, SAP
Datasphere, HANA Cloud. TestGen supports SAP HANA as a target and sells mostly to pharma, an
SAP-heavy industry (research 01). Generic checks miss SAP's conventions: dates stored as
`DATS` (`CHAR(8)`) with `00000000` for "no date", `NUMC` and ALPHA-converted keys with
leading zeros (`MATNR`, `KUNNR`, `LIFNR`), amounts (`CURR`) whose meaning depends on a
currency key column (`WAERS`), quantities (`QUAN`) on a unit column (`MEINS`), the client
column `MANDT` in every table, and deletion flags (`LOEKZ`, `LOEVM`).

SAP's Python driver `hdbcli` is free to use but under SAP's own developer licence, not an
open-source licence. ADR-0008 does not allow it in the shipped images.

## Decision

Three routes, from cheapest to deepest:

1. **Exports (R1, already supported).** CSV or Parquet extracts and Datasphere replication
   flows to S3 or local storage are read through DuckDB like any other file (spec 009 adds S3).
2. **SAP HANA SQL pushdown (R2, sprint 7).** A `HanaDialect` in `sql.py` (regex through
   `LIKE_REGEXPR`, sampling with `TABLESAMPLE SYSTEM`, quoting with SQLGlot's dialect where it
   fits) and a `HanaConnector` covering HANA Cloud, HANA on premises, BW/4HANA and Datasphere
   (its open SQL schemas). The connector lives in a **separate package
   `sahifa-connector-hana`** that depends on `hdbcli` and registers itself through an entry
   point (`sahifa.connectors`). The owner installs it into their own image
   (`pip install sahifa-connector-hana`, or a build argument in `api/Dockerfile`), accepting
   SAP's licence themselves. Sessions are read-only like Postgres (ADR-0006).
3. **SAP rule pack (R2, sprint 8).** Generated when a profile looks like SAP data (a `MANDT`
   column, `DATS`/`NUMC` patterns, or the connector says so), namespace `sap.`:
   - `sap.dats_valid`: a `CHAR(8)` date column holds valid `YYYYMMDD` dates; `00000000` counts
     as null for completeness, not as invalid.
   - `sap.alpha_conversion`: a key column is consistently zero-padded to its length (mixed
     `000000000000001234` and `1234` break joins).
   - `sap.currency_reference`: every non-zero amount has a currency key, and the key is a
     valid ISO 4217 or SAP currency (`TCURC` when readable).
   - `sap.unit_reference`: every non-zero quantity has a unit of measure (`T006` when
     readable).
   - `sap.client_consistency`: rows of one scan belong to the expected client(s); foreign keys
     match within the same `MANDT`.
   - `sap.deletion_flag_share`: share of rows flagged for deletion, reported as store health,
     and excluded from completeness scoring of dependent checks on request.
   - SAP-aware foreign-key inference from the data dictionary (`DD03L`, `DD08L` checks
     tables) when the login can read it, instead of name heuristics.

OData (S/4HANA Cloud APIs) is not a pushdown target; a sampling OData connector is an R3
option if owners ask for it.

## Alternatives considered

| Option | Pros | Cons | Why not |
|---|---|---|---|
| Ship `hdbcli` in the image | One step for SAP users | Puts a non-open licence into an Apache-2.0 product | Breaks ADR-0008 |
| PyHDB (pure Python, Apache-2.0) | Open licence | Unmaintained, no HANA Cloud TLS and auth features | Not safe to depend on |
| ODBC through `pyodbc` + the HANA ODBC driver | Open Python side | The driver itself is SAP-licensed and harder to install | Same licence question, more moving parts |
| Exports only | No licence question | No live pushdown, stale data | Kept as route 1, not the only one |

## Consequences

- An entry-point registry for connectors in `sahifa_core.connectors` (sprint 7), which
  Snowflake and BigQuery also use.
- Owner dependency: a HANA Cloud trial or a HANA instance with a read-only user and, for
  the rule pack, read access to `DD03L`/`DD08L`/`TCURC`/`T006` (sprint plan).
- The product page lists SAP HANA and Datasphere under R2.

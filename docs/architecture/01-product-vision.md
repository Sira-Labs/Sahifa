# Sahifa — Product Vision

> *Ṣaḥīfa* (صحيفة): a written sheet; the charter of Medina that set down in writing what each
> party could expect of the others.

Sahifa is a self-hostable platform that **assesses the quality of whole data stores**:
databases, warehouses, lakehouse tables and plain files. It profiles every table and column,
generates checks from the profile and its history, scores each quality dimension with an
interval that says how sure the number is, explains where bad rows come from, and proposes
fixes and contracts that a person approves. It never writes to the data it assesses.

It is the sister of [Tabayyun](https://github.com/Sira-Labs/Tabayyun), which verifies
industrial time series. Sahifa covers tables and stores; time-series columns it finds are
handed to Tabayyun's core (ADR-0011).

## Why now

- **The reference product is gated.** DataKitchen TestGen shows that "profile, generate
  tests, score" works, but its open-source edition is one user, one connection, one project,
  SQL databases only and US-centric hygiene rules (research 01).
- **The open tools moved away from open.** Soda Core moved to the Elastic License 2.0 in
  January 2026, OpenMetadata's profiler is under the Collate licence, GX Cloud closed in June
  2026, and anomaly detection is a paid cloud feature in Elementary, DataHub and Dagster
  (research 02). A self-hosted product built only on Apache and MIT engines has an opening.
- **Nobody says how sure a score is.** Every open and commercial score is a point value. A
  score computed on a 1 % sample and one computed on every row look identical (research 03).
- **Stores are mixed.** Real estates are Postgres plus a warehouse plus Parquet on S3.
  Existing open tools cover one engine each: Spark (Deequ, DQX), dbt models (Elementary),
  DataFrames (Pandera) or SQL warehouses (TestGen).
- **LLMs write rules well and judge data badly.** A 2026 study found a deterministic
  profiling baseline beat an LLM agent at error detection (F1 0.561 vs 0.421). The safe
  pattern is: the model proposes a rule, a person approves it, the engine runs it
  deterministically (research 03).

## Product principles

1. **Read-only, always.** Sahifa connects with read-only credentials, in read-only
   transactions with statement timeouts. Fixes are proposals; it never writes to a source.
2. **Scores with error bars.** Every score carries a 95 % interval from the rows actually
   read. A full scan has a narrow interval, a sample a wider one (ADR-0004).
3. **Explain, don't just flag.** Every finding names the check, the threshold, the count,
   example values, the SQL that found them and a plain-language summary. From R2 it also
   says where the bad rows cluster.
4. **Generated, then owned.** Checks are generated from the profile; a person locks the ones
   they trust. Regeneration refreshes unlocked checks only. New suggestions, whether from the
   profile or an LLM, wait for approval (ADR-0005).
5. **Every store, one model.** One check vocabulary and one scoring model for SQL databases,
   warehouses, lakehouse tables and files. Checks run where the data lives (ADR-0001,
   ADR-0002).
6. **Open without a paywall.** Apache-2.0, many users, many connections, no telemetry. Only
   Apache- or MIT-licensed engines in the core (ADR-0008).
7. **Rules for the whole world.** IBAN, VAT IDs, postcodes, country and currency codes,
   phone numbers, not only US ZIP codes and states.

## Personas

| Persona | Needs | Typical action |
|---|---|---|
| Data engineer | Which of my 1,200 tables broke since yesterday, and where did the bad rows come from? | Triages findings, fixes the pipeline, locks the checks they trust. |
| Analytics engineer | Can I build a model on this table? Which columns can I trust? | Reads the table report, filters columns by score, exports a contract. |
| Data owner / steward | Is my domain's data fit for purpose, and is it getting better? | Reviews scores per dimension over time, approves proposed rules and contracts. |
| Data scientist | Is this training table complete, unique and plausible? | Runs a scan on a Parquet file, reads the column profile, filters bad rows. |
| Platform engineer | Which tables are unused, duplicated, badly typed or full of small files? | Reads the store health report, plans clean-up. |
| Platform admin | Who can see what? Which connections exist? What did the system do? | Manages users, roles, connections, the audit log. |

## Scope of the releases

- **R0 (research and design, done 2 Oct 2026):** research 01–04, vision, domain model,
  architecture, ADRs, check catalogue, frontend design, roadmap, sprint plan, first specs,
  CapRover deployment plan, product page.
- **R1 (first preview, release 0.1):** connectors for uploaded files, DuckDB over local and
  S3 files (CSV, Parquet, JSON), and Postgres; profiling; the first 30 generated checks;
  ISO 25012 scores per column, table and store with intervals; findings with evidence;
  check lifecycle (proposed, active, locked, retired); scan history; web app; staging on
  CapRover.
- **R2 (history and explanation):** metric history and anomaly thresholds with a chosen
  false-alarm rate, drift with effect sizes, finding lifecycle and dedup across scans,
  explanations of where bad rows cluster, sign-in (Keycloak) and workspace RBAC, alerts,
  Snowflake, BigQuery and SAP HANA / Datasphere (ADR-0014), ODCS contract export, the SAP
  and European rule packs, the Tabayyun hand-off.
- **R3 (platform, release 1.0):** LLM-proposed rules with approval, entity resolution with
  Splink, lineage-aware root cause (OpenLineage, SQLGlot), the store health report, Iceberg
  and Delta tables, scheduling, API tokens, Helm chart.

## Non-goals

- Writing to source data, automatic repair, or a transformation tool. Sahifa proposes; dbt,
  Coalesce or the owner's own pipeline applies.
- Pipeline orchestration or job observability (DataKitchen Observability, Airflow).
- A data catalogue. Sahifa keeps the metadata it needs and exports to catalogues.
- Time-series checks of its own. Those are Tabayyun's.

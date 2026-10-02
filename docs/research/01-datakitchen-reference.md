# Research 01 — DataKitchen TestGen as the reference product

*Research date: 2026-10-01, by three parallel research agents in the Sira Labs planning
session; versions, licences and star counts verified on that date unless noted. What
DataKitchen builds, how TestGen profiles, generates tests and scores, what its open-source
edition withholds, and what Sahifa should copy or do differently. Decisions derived from
this are in `docs/architecture/` and `docs/adr/`.*

Note: the GitHub figures below come from the GitHub search API and shallow clones of the repos, which I read directly. github.com/DataKitchen/dataops-testgen is cited as [TG] and github.com/DataKitchen/dataops-observability as [OBS].

### 1. Company and business model
- **Company:** founded 2013 by Chris Bergh (CEO), Gil Benghiat and Eric Estabrooks. Based in Lexington, MA. Bootstrapped with "$0 outside funding". Co-authored the DataOps Manifesto (30,000+ signers) and the DataOps Cookbook. https://datakitchen.io/about-datakitchen/
- **Size:** 11–50 employees (third-party estimate). Getlatka claims about $18.4M ARR, which is unverified. https://tracxn.com/d/companies/datakitchen/__whpjLwqUxkiV3XAoDuBH6mT21W9kGYNNElXriu43OYI , https://getlatka.com/companies/datakitchen
- **Customers:** mostly commercial pharma. They name Celgene/BMS (Otezla launch), Karuna (Cobenfy) and Acceleron. A large share of the business is pharma services, not just software. https://datakitchen.io/case-studies/ , https://datakitchen.io/blog/the-100-billion-secret/ , https://pharma.datakitchen.io/
- **Pricing (public):** https://datakitchen.io/pricing/
  - **TestGen OSS:** free, Apache-2.0. Limited to 1 user, 1 connection and 1 project, but includes all test types and has no limit on tables or data volume.
  - **TestGen Enterprise:** $100/month per user and per DB connection. Adds unlimited users, projects and connections, "proprietary database support", enterprise security/access, priority releases and support.
  - **Observability:** OSS is 1 user and 1 project. Enterprise is $100/user/agent/month and adds SSO. Cloud is $150/user/agent/month and is DataKitchen-hosted.
  - **Automation (the legacy DataOps orchestration platform, "Kitchens"):** custom pricing.

### 2. Products: GitHub facts
| Repo | Licence | Stars | Latest version / last push | Stack |
|---|---|---|---|---|
| dataops-testgen | Apache-2.0 | 79 | v5.92.2 (commit 2026-09-19) | Python 3.11+, Streamlit UI + JS components, SQL templates, PostgreSQL metadata DB |
| dataops-observability | Apache-2.0 | 55 | push 2026-09-23 | Python (Flask, Peewee, Kafka), MySQL, Angular 16 UI |
| data-observability-installer (dk-installer) | Apache-2.0 | 141 | push 2026-09-30 | Python |
| dataops-observability-agents | Apache-2.0 | 30 | push 2026-08-26 | Python |
Sources: [TG] pyproject.toml, LICENSE, git log; [OBS] pyproject.toml and deploy/charts; GitHub API. Community traction is small: fewer than 150 stars on every repo and 3–12 forks.

**TestGen architecture [TG]:**
- **CLI, UI and API:** a `testgen` Click CLI, a Streamlit UI, a FastAPI-style API and an MCP server (`mcp[cli]`, 20+ tool modules).
- **Metadata DB:** PostgreSQL. A "standalone" pip mode embeds Postgres via `pixeltable-pgserver`.
- **Deployment:** Docker Compose, pip (via dk-installer) and Helm charts (`testgen-app`, `testgen-services`).
- **Execution:** all checks run as SQL pushed down into the target database. There are per-flavour templates for PostgreSQL, Snowflake, BigQuery, Databricks, Redshift, Redshift Spectrum, SQL Server (mssql), Oracle, SAP HANA and Salesforce Data360.
- **Trino:** explicitly removed (upgrade script 0204: "The Trino flavor is not offered").
- **Telemetry:** a Mixpanel telemetry module is present.
- **Docs:** they also list Azure Synapse and "Iceberg, Parquet, external tables" (i.e. through the warehouse). https://docs.datakitchen.io/testgen/what-is-testgen/

**Newer features (2025–2026):**
- **MCP server:** 96 tools across discover, profile, hygiene, test, run, monitor, score and operate (v5.70.2, June 2026). It is in both OSS and Enterprise. https://datakitchen.io/blog/testgen-mcp-cheat-sheet/
- **Agentic "fix" loop (May 2026):** the agent cannot write to the warehouse. It routes fixes (trimming, case normalisation, zero-padding) through dbt or Coalesce and needs human approval. https://datakitchen.io/blog/while-you-slept-an-agent-fixed-14-data-quality-failures/
- **Data Catalog view:** has CDE flags and PII flags (with `view_pii` permission gating). [TG] ui/views/data_catalog.py
- **Quality dashboard / score explorer:** [TG] ui/views/quality_dashboard.py, score_explorer.py
- **Table monitors:** freshness, volume, schema, metric/drift (Aug 2026). https://datakitchen.io/blog/be-the-first-to-know-smart-continuous-table-monitoring-has-arrived-in-testgen/

**Observability:**
- Models "Data Journeys" from an events REST API and SDK, plus agents for Airflow, dbt Core, ADF, Databricks, Power BI, Fivetran, Synapse, Composer, Qlik, Talend, Informatica and AutoSys.
- A rules engine sends alerts to email, Slack, Teams or Jira.
- https://datakitchen.io/products/dataops-observability/

### 3. How TestGen works
1. **Profiling:**
   - Runs SQL that computes about 55 characteristics per column (https://datakitchen.io/comparisons/datakitchen-vs-great-expectations-gx-oss/).
   - Infers semantic/functional data types ([TG] template/profiling/functional_datatype.sql).
   - Columns are classified as A/B/D/T/N. Snowflake VARIANT, OBJECT and ARRAY fall into "X" (other), so semi-structured data is not profiled meaningfully ([TG] flavors/snowflake/data_chars).
2. **Hygiene issues:** 32 anomaly types ([TG] template/dbsetup_anomaly_types). Examples:
   - suggested type, mixed types, non-standard blanks, leading spaces, non-printing characters
   - potential PII, potential duplicates, inconsistent casing, variant-coded values
   - unlikely dates, invalid US ZIP or state
   - There is a strong US-address bias.
3. **Test generation:**
   - The repo has 51 test-type definitions (including CUSTOM). Docs say "47 standard + 12 Commercial Pharma (Enterprise)". Marketing says "120+", which counts generated instances. https://docs.datakitchen.io/testgen/generate-tests/
   - Examples: Required, Unique, LOV_Match, Pattern_Match, Min/Max, Avg_Shift, Distribution_Shift, Outlier_Pct, Daily/Weekly/Monthly_Rec_Ct, Future_Date, Recency, Aggregate_Balance, Combo_Match, Schema_Drift, Table_Freshness, Volume_Trend, Metric_Trend, Freshness_Trend.
   - Thresholds come from the current profile. Regenerating refreshes unlocked tests, while locked and manual tests are kept.
4. **Anomaly thresholds:**
   - Volume and metric trends use a SARIMAX forecast with holiday calendars (`statsmodels`, `holidays`).
   - Tolerance bands use z-scores by sensitivity: ±2.0, ±2.5 or ±3.0, switching to a t-distribution for small samples.
   - Freshness uses a percentile-based "fingerprint" of update events.
   - [TG] testgen/common/time_series_service.py, testgen/commands/test_thresholds_prediction.py
5. **Scoring:**
   - Each failed test or hygiene issue gets a *prevalence* (affected-row share × the test type's `dq_score_risk_factor`).
   - Column score = clean data points / total, with multiple issues combined probabilistically rather than summed.
   - Overall score = profiling_score × testing_score.
   - The rollup is weighted by table importance (Entity 10×, Domain 5×, Summary 1.5×, Transaction 1×) and column semantic type (ID 3×, FK 2.5×, … description 0.5×). PII columns get an extra multiplier.
   - Scores break down by DQ dimension (Accuracy, Completeness, Consistency, Timeliness, Uniqueness, Validity) and by impact dimension (Conformance, Regularity, Reliability, Usability).
   - There is a separate CDE score. Scorecards show a history sparkline, and colour bands are ≥96 / 91–95 / 86–90 / <86.
   - https://docs.datakitchen.io/testgen/quality-scores/ ; [TG] template/rollup_scores/calc_prevalence_test_results.sql
6. **Issue reports:** reports can be downloaded and shared (reportlab and xlsxwriter are dependencies). [TG] pyproject.toml; https://docs.datakitchen.io/testgen/what-is-testgen/

### 4. Methodology DataKitchen promotes
- **DataOps:** Manifesto and Cookbook.
- **"Data Journey" Manifesto / Five Pillars:** observe the whole pipeline across tools and teams, and "don't let customers find problems first". https://datakitchen.io/introducing-the-five-pillars-of-data-journeys/ , https://datakitchen.io/platform/
- **"Data quality coverage":** auto-generate tests for every table in every zone, so that hand-writing tests (the Great Expectations model) does not cap coverage. https://datakitchen.io/comparisons/datakitchen-vs-great-expectations-gx-oss/

### 5. Limits, gaps and criticisms
- **Paywalled:**
  - In practice the OSS edition is a single-user, single-connection, single-project evaluation tier.
  - Multi-user access, extra connections, SSO (Observability) and "proprietary databases" all require Enterprise.
  - The Commercial Pharma test pack is Enterprise-only.
  - The open-core restriction lives in the edition/Docker image, not in the licence.
  - https://datakitchen.io/pricing/ ; https://docs.datakitchen.io/testgen/connect-your-database/
- **Self-admitted gaps:** data contracts are only partial (ODCS v3.1 "in development"), and there is no column-level lineage yet. https://datakitchen.io/comparisons/datakitchen-vs-great-expectations-gx-oss/
- **Not covered:**
  - No file or object-storage engine: it is SQL pushdown only, with no Spark, pandas, S3 or CSV support.
  - No Trino, DuckDB or MySQL as a target.
  - Weak support for semi-structured data (the "X" type).
  - Remediation is suggest-only through the user's own transformation tools.
  - I found no cost-optimisation or warehouse-spend features.
  - Time-series handling is limited to table-level trends (SARIMAX); there are no per-segment or dimensional anomaly drill-downs.
  - Sources: [TG] flavors directory and upgrade 0204; https://datakitchen.io/blog/while-you-slept-an-agent-fixed-14-data-quality-failures/
- **Community:**
  - The community is small: tens of stars, fewer than 15 forks, very few outside contributors, and support runs through Slack only.
  - I found no independent Reddit or G2 reviews. Most comparative material is written by DataKitchen itself.
  - Hygiene rules are US-centric (ZIP and state checks).
  - The UI uses Streamlit, which limits scaling and customisation.

### Takeaways for building our own
- **Worth copying:**
  - profile → auto-generate → lock/regenerate tests
  - prevalence × risk-weighted scoring with semantic importance weights and CDE scoring
  - SARIMAX/holiday-aware thresholds
  - an MCP server
- **Where we could differentiate:**
  - fully un-gated multi-user and multi-connection OSS
  - file/lakehouse sources (Parquet/Iceberg on object storage via DuckDB or Spark)
  - Trino and MySQL support
  - semi-structured profiling
  - non-US rule packs
  - remediation workflows
  - cost awareness

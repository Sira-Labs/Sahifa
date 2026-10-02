# Research 04 — Synthesis: DataKitchen as reference, the landscape, and where Sahifa fits

*Written 2026-10-01 from research 01–03 as the recommendation to the owner. It is the origin
of the product: the vision, ADRs and catalogue in this repository refine it.*


**Recommendation:** build it as a sister product to Tabayyun, not inside it. It would assess whole data stores (databases, warehouses, lakehouses, files). It should follow Tabayyun's existing pattern: profile, then check, then score per dimension, then explain, then correct with lineage. Time-series columns would be passed to `tabayyun_core`. DataKitchen shows the approach works. It also leaves clear gaps that fit our self-hosted, research-based style.

## 1. DataKitchen: the reference

**What it is:**
- A bootstrapped company of roughly 11–50 people, mostly serving pharma.
- **TestGen** is its data quality product: Apache-2.0, Python with a Streamlit interface, PostgreSQL for its own metadata.
- All checks run as SQL inside the customer's database: Postgres, Snowflake, BigQuery, Databricks, Redshift, SQL Server, Oracle, SAP HANA.
- **Observability** is a second product that tracks pipelines from end to end.

**Worth copying:**
- **Profile → auto-generate tests → lock or regenerate.** It computes about 55 statistics per column, finds 32 kinds of "hygiene" issue, and generates tests from 47 test types. The tests are generated from the profile, so nobody has to write them by hand.
- **Scoring:** each issue gets a weight based on the share of affected rows and the risk of the test type. Tables and columns are weighted by importance, for example IDs 3× and entity tables 10×. Scores are shown per DAMA dimension, with a separate score for critical data elements.
- **Thresholds that follow the data:** volume trends use a seasonal forecast with holiday calendars.
- **MCP server** (96 tools, also in the open-source version) and an agent that proposes fixes. The fixes go through dbt and need human approval; the agent never writes to the database.

**Weaknesses:**
- **The open-source version is really an evaluation tier:** 1 user, 1 connection, 1 project. Everything beyond that is $100 per user and connection per month.
- **Only SQL databases:** no files, S3, Parquet or Iceberg directly, and no DuckDB, Trino or MySQL.
- **Semi-structured data** (JSON, VARIANT) is not really profiled.
- **Hygiene rules are US-centric** (ZIP codes, states).
- **Fixes are suggestions only**, and there is no storage or cost optimisation.
- **Time series** only get table-level trends; no per-segment drill-down.
- **Small community:** under 150 GitHub stars per repo. The scores don't follow ISO.

## 2. The wider landscape

The best open-source choices per job:

| Job | Best open-source pick | Watch out |
|---|---|---|
| Profiling | fg-data-profiling (formerly ydata-profiling) for DataFrames; Deequ, DQX or Cuallee at Spark scale | ydata-profiling was renamed in 2026 |
| Rule checks | GX Core (Apache, now looked after by Fivetran), Pandera, Cuallee | Great Expectations shut down its GX Cloud in June 2026 |
| Data contracts | ODCS v3.2 (Bitol, LF AI & Data) and datacontract-cli (runs on DuckDB and Ibis) | Becoming the standard format |
| Anomalies and drift | Elementary (dbt-native), Evidently | ML-based detection is Cloud-only in Elementary, DataHub and Dagster |
| Scores | Only TestGen has built-in scores | Not based on ISO |

**Licence and market trend:**
- Soda Core moved to **ELv2** in January 2026, so it can't be embedded in a hosted product.
- OpenMetadata's profiler and UI are under the **Collate licence**.
- Apache Griffin is retired, re_data is dormant, whylogs is orphaned.
- Consolidation is ongoing:
  - Datadog bought Metaplane.
  - Salesforce bought Informatica.
  - Fivetran merged with dbt.

A self-hosted product built only on Apache or MIT engines has a real opening.

## 3. Research methods ready to use

Two findings from the literature set the boundaries:
- **Automatic repair is still unreliable outside lab conditions.** Fixes should be suggestions a person approves.
- **Mined constraints are mostly noise.** For denial constraints, over 95% of discovered rules are false, so they need ranking and review.

LLMs work best for *proposing* rules and explaining findings, with deterministic execution. In a 2026 study, a plain profiling baseline beat an LLM agent at error detection.

These are the methods most worth building, in order:

1. **ISO 25012/25024 scores with confidence intervals.** No tool, open or commercial, attaches uncertainty to its scores. This would be our main differentiator.
2. **Anomalies on the history of table metrics** (volume, freshness, null share, distinct counts), following Auto-Validate-by-History. It uses seasonal (STL) baselines and **conformal thresholds**, which guarantee a chosen false-alarm rate instead of a sensitivity slider. The same thresholds would help Tabayyun.
3. **Drift with effect sizes** instead of p-values, which all come out significant on large tables. Use critical values for PSI and partition summaries in the style of GATE to cut alert fatigue.
4. **Constraint suggestions:** Deequ-style rules, approximate functional dependencies (HyFD, Metanome), and semantic domains (Auto-Test). Each comes with a validity test and needs human confirmation.
5. **Duplicates and entity resolution with Splink** (MIT, runs on DuckDB, no labelled data needed).
6. **Explanations such as "bad rows are concentrated in source=X since date Y"** (MacroBase DIFF, Data X-Ray). Few tools explain *why*.
7. **Root cause along lineage** using OpenLineage and SQLGlot column lineage. No standard algorithm exists yet, so this is open ground for us.
8. **LLM proposes a rule, a person approves it, it runs deterministically** (the pattern from LLMClean and ZeroED).
9. **A health report for the store itself** ("improve and optimise"):
   - unused tables from query logs,
   - duplicate or overlapping tables via MinHash,
   - Iceberg/Delta small-file and compaction advice (more than 4 files per partition is a good trigger),
   - Postgres index advice via Dexter and HypoPG,
   - normalisation suggestions derived from discovered dependencies.

   No data observability tool combines data quality with store hygiene like this.

**Licences to watch:** Desbordante and Zingg are AGPL, as is cleanlab according to the methods research. The tools research instead read cleanlab as Apache-2.0 from PyPI, so check that before relying on it. Prefer the Apache and MIT alternatives in the core.

## 4. Product sketch and how it relates to Tabayyun

|  | Tabayyun | New product |
|---|---|---|
| Unit of analysis | One time series, or a group of series | Table, column, data store |
| Engine | Rust kernels on Arrow | SQL run inside the database, plus **DuckDB/Ibis** for files and object storage (Parquet, Iceberg, CSV, JSON) |
| Shared concepts | Findings lifecycle, episodes, scores per dimension, corrections as versioned layers, explanations | The same patterns, carried over from Tabayyun's ADRs |
| Time series | Its core domain | Timestamp and metric columns are handed to `tabayyun_core` |

**How we'd stand apart from DataKitchen:**
- multi-user and multi-connection with no paywall,
- files and lakehouse sources,
- ISO scores with uncertainty,
- statistically guaranteed thresholds,
- explanations and root cause,
- fixes as versioned correction layers, as in Tabayyun,
- the store health report,
- ODCS contracts generated from profiles,
- European and other non-US rule packs (IBAN, postcodes, VAT IDs).

**MVP order:**
1. Connectors for Postgres, DuckDB/S3 Parquet and Snowflake, profiling, auto-generated checks, ISO scores.
2. Metric history, conformal anomaly thresholds, drift.
3. Explanations, LLM-proposed rules with approval, ODCS export.
4. Store health report and lineage-based root cause.

## 5. Name ideas from the Sīra

- **Ṣaḥīfa (الصحيفة):** the written charter of Medina, which defined rights and obligations in writing. It matches data contracts and records you can trust. There is also the Sīra episode of the boycott document in the Kaaba, eaten by termites; records decay, which is exactly what a data-quality tool watches for.
- **Iḥṣāʾ (إحصاء):** the Prophet ﷺ had the names of the Muslims written down, often described as the first census. It matches a full inventory and assessment of your own data stores.

I'd lean towards **Ṣaḥīfa** because it covers both the contract and the record.

The owner chose the name **Sahifa** and the repository `Sira-Labs/Sahifa` on 2026-10-02; R0 started the same day.

**Sources (selection):**
- **DataKitchen:** [TestGen repo](https://github.com/DataKitchen/dataops-testgen), [TestGen docs](https://docs.datakitchen.io/testgen/what-is-testgen/), [quality scores](https://docs.datakitchen.io/testgen/quality-scores/), [pricing](https://datakitchen.io/pricing/), [MCP](https://datakitchen.io/blog/testgen-mcp-cheat-sheet/), [comparison with GX](https://datakitchen.io/comparisons/datakitchen-vs-great-expectations-gx-oss/)
- **Tools:** [GX/Fivetran](https://www.fivetran.com/press/fivetran-to-become-steward-of-the-great-expectations-open-source-community-and-gx-core-project), [Soda ELv2](https://soda.io/blog/soda-core-license-update-moving-to-elastic-license), [Elementary OSS vs Cloud](https://docs.elementary-data.com/data-tests/anomaly-detection-tests-oss-vs-cloud), [Deequ](https://github.com/awslabs/deequ), [Cuallee](https://github.com/canimus/cuallee), [DQX](https://github.com/databrickslabs/dqx), [ODCS](https://github.com/bitol-io/open-data-contract-standard), [datacontract-cli](https://github.com/datacontract/datacontract-cli)
- **Market:** [Datadog/Metaplane](https://www.datadoghq.com/blog/datadog-acquires-metaplane/), [Salesforce/Informatica](https://www.businesswire.com/news/home/20251118759580/en/Salesforce-Completes-Acquisition-of-Informatica)
- **Standards and scoring:** [ISO 25024](https://quality.arc42.org/standards/iso-25024), [DQ metric requirements (Heinrich)](https://epub.uni-regensburg.de/36889/1/Requirements%20for%20Data%20Quality%20Metrics.pdf), [OSS tools vs ISO 25012](https://arxiv.org/abs/2407.18649), [LLMs in DQ tools 2026](https://arxiv.org/abs/2604.09163)
- **Repair and constraints:** [repair benchmark VLDB 2024](https://www.vldb.org/pvldb/vol17/p2617-miao.pdf), [denial constraints false-positive rate](https://doi.org/10.14778/3748191.3748209), [LLM agent vs profiling](https://arxiv.org/abs/2608.14765), [Metanome](https://github.com/HPI-Information-Systems/metanome-algorithms), [Raha/Baran](https://github.com/BigDaMa/raha)
- **Validation and anomalies:** [Auto-Validate-by-History](https://arxiv.org/abs/2306.02421), [Auto-Test](https://arxiv.org/pdf/2504.10762), [GATE](https://dl.acm.org/doi/10.1145/3583780.3614786), [PSI critical values](https://files.wmich.edu/s3fs-public/attachments/u730/2022/PSIfinal.pdf), [TSB-AD](https://proceedings.neurips.cc/paper/2024/hash/c3f3c690b7a99fba16d0efd35cb83b2c-Abstract-Datasets_and_Benchmarks_Track.html)
- **Matching, explanations, lineage:** [Splink](https://github.com/moj-analytical-services/splink), [MacroBase DIFF](https://www.bailis.org/papers/diff-vldb2019.pdf), [OpenLineage](https://github.com/OpenLineage/OpenLineage)
- **Store optimisation:** [AutoComp](https://arxiv.org/abs/2504.04186), [Iceberg compaction 2026](https://arxiv.org/abs/2608.08639), [Dexter](https://ankane.org/introducing-dexter), [index selection evaluation](https://www.vldb.org/pvldb/vol13/p2382-kossmann.pdf)

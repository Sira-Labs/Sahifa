# Research 02 — The data-quality tool landscape

*Research date: 2026-10-01, by three parallel research agents in the Sira Labs planning
session; versions, licences and star counts verified on that date unless noted. Open-source
and commercial data-quality tools, their licences and paywalls, the 2024–26 market deals,
the standards and data-contract formats, and the gaps a small team can close. Decisions
derived from this are in `docs/architecture/` and `docs/adr/`.*

**How the numbers were checked:** star counts come from a GitHub search on 2026-10-01. Release dates and licences come from the PyPI JSON API (`pypi.org/project/<pkg>`), and for Deequ from Maven Central. Licence files were read directly from raw.githubusercontent.com.

## 1. Open-source tools

| Tool | Maintainer | Licence | Stars | Latest release | Strengths | Limits / strings attached |
|---|---|---|---|---|---|---|
| **GX Core** | Fivetran is now steward. FICO bought the company, and GX Cloud closed on 2026-06-01 ([GX blog](https://greatexpectations.io/blog/an-update-from-great-expectations/), [Fivetran PR](https://www.fivetran.com/press/fivetran-to-become-steward-of-the-great-expectations-open-source-community-and-gx-core-project)) | Apache-2.0 ([repo](https://github.com/fivetran/great_expectations)) | 11.9k | 1.23.2, 2026-09-25 | Largest expectation library; runs on pandas, Spark and SQL | No anomaly detection or UI in Core. The AI features lived in the closed GX Cloud. Its future depends on Fivetran, which is merging with dbt ([BusinessWire](https://www.businesswire.com/news/home/20260601514374/en/Fivetran-dbt-Labs-Complete-Merger-to-Create-the-Data-Infrastructure-for-Trusted-AI-Agents)) |
| **Soda Core v4** | Soda | **Changed from Apache-2.0 to Elastic License 2.0 in Jan 2026** ([Soda blog](https://soda.io/blog/soda-core-license-update-moving-to-elastic-license)) | 2.4k | 4.25.0, 2026-09-23 | YAML data contracts and 50+ checks across many warehouses ([repo](https://github.com/sodadata/soda-core)) | Anomaly detection needs Soda Cloud. ELv2 forbids offering it as a hosted service, so **we cannot embed it in a product we offer as SaaS** |
| **Deequ / PyDeequ** | AWS Labs | Apache-2.0 | 3.6k / 0.8k | Deequ 3.0.3 (Maven, 2026-09-16); PyDeequ 1.7.0, 2026-09-14 | Spark-scale metrics, constraint suggestion, anomaly detection, DQDL rule language ([repo](https://github.com/awslabs/deequ)) | Spark/JVM only. It is the engine inside AWS Glue Data Quality ([AWS](https://aws.amazon.com/about-aws/whats-new/2024/08/aws-glue-ml-powered-glue-data-quality-capability)) |
| **dbt tests + dbt-expectations** | dbt Labs (now part of Fivetran); the package is maintained by Metaplane | dbt Core is Apache-2.0. dbt Core v2 rebuilt the Fusion engine as Apache, while Fusion stays a proprietary distribution ([dbt blog](https://docs.getdbt.com/blog/dbt-core-v2-is-here)) | 1.2k (calogica) / 164 (metaplane) | dbt-core 1.12.5, 2026-09-15; metaplane package 0.10.10 ([hub](https://hub.getdbt.com/metaplane/dbt_expectations/latest/)) | Tests live next to transformation code | Only covers dbt-modelled warehouse tables. The calogica package is marked "no longer actively supported" ([repo](https://github.com/calogica/dbt-expectations)) |
| **Elementary** | Elementary | Apache-2.0 | 2.4k | 0.26.0, 2026-09-10 | dbt-native observability that stores results in the warehouse | OSS uses Z-score detection you configure by hand. ML detection, BI-level lineage and incident management are Cloud-only ([docs](https://docs.elementary-data.com/data-tests/anomaly-detection-tests-oss-vs-cloud)) |
| **re_data** | re-data | MIT | 1.6k | 0.11.0, 2023-12-27 | dbt anomaly checks | Effectively dormant |
| **whylogs** | WhyLabs, whose team Apple took in Jan 2025; the platform code was open-sourced ([GeekWire](https://www.geekwire.com/2025/founders-at-seattle-startup-whylabs-join-apple-following-under-the-radar-acquisition/)) | Apache-2.0 | 2.8k | 1.6.4, 2024-12-03 | Mergeable statistical profiles (sketches) that keep raw data private | No company behind it now and no release since Dec 2024 |
| **Evidently** | Evidently AI | Apache-2.0 | 8.0k | 0.7.23, 2026-09-11 | 20+ drift tests and a self-hostable UI ([repo](https://github.com/evidentlyai/evidently)) | Built for ML/LLM monitoring, not warehouse governance. Alerting and user management are Cloud-only |
| **ydata-profiling → fg-data-profiling** | YData / Data-Centric-AI-Community | MIT | n/a | Renamed in April 2026; fg 4.20.0, 2026-09-11 | Best one-shot exploratory profiling reports | The old package gets no more updates ([PyPI](https://pypi.org/project/ydata-profiling/), [repo](https://github.com/Data-Centric-AI-Community/fg-data-profiling)). Works on DataFrames, not databases |
| **Pandera** | Union.ai | MIT | 4.5k | 0.33.1, 2026-09-01 | Typed schemas for pandas, Polars, PySpark, Ibis and PyArrow | Schema inference and hypothesis tests are pandas-only ([docs](https://pandera.readthedocs.io/en/stable/)) |
| **Apache Griffin** | ASF | Apache-2.0 | 1.2k | Retired Sept 2025, moved to the Attic ([ASF](https://attic.apache.org/projects/griffin.html)) | n/a | Dead |
| **Cuallee** | H. Vazquez | Apache-2.0 | 250 | 0.15.4, 2025-10-07 | Runs one check set on PySpark, Snowpark, pandas, Polars, DuckDB, BigQuery and Daft; claims about 2x PyDeequ's speed ([repo](https://github.com/canimus/cuallee)) | Small project with essentially one maintainer |
| **OpenMetadata DQ** | Collate | Server is Apache-2.0. **The ingestion framework (which includes the profiler) and the UI use the Collate Community License, which forbids a competing SaaS** ([LICENSE](https://github.com/open-metadata/OpenMetadata/blob/main/openmetadata-ui/LICENSE), [PyPI](https://pypi.org/project/openmetadata-ingestion/)) | 15.4k | 2.0.3.0, 2026-09-30 | Profiler, no-code tests, freshness/volume anomalies, incident manager | AI quality agents are Collate-only ([Collate](https://www.getcollate.io/comparison)) |
| **DataHub assertions** | Acryl (DataHub Inc.) | Apache-2.0 | 12.8k | acryl-datahub 1.7.0.14, 2026-09-29 | Open assertions spec that compiles to dbt, GX or Snowflake checks ([spec](https://docs.datahub.com/docs/assertions/open-assertions-spec)) | Running freshness, volume and SQL monitors is **Cloud-only** ([docs](https://docs.datahub.com/docs/managed-datahub/managed-datahub-overview)) |
| **Dagster asset checks** | Dagster Labs | Apache-2.0 | 16.2k | 1.13.24, 2026-09-21 | Checks tied to orchestrated assets ([docs](https://docs.dagster.io/guides/test/asset-checks)) | Anomaly-based freshness and asset health need Dagster+ ([blog](https://dagster.io/blog/ensuring-reliable-data-dagster-plus)) |
| **LLM rule generators** | Several | n/a | n/a | n/a | Databricks DQX does LLM rule suggestions with DSPy ([repo](https://github.com/databrickslabs/dqx)). GX and Soda AI helpers are in their clouds | An April 2026 study found LLM use "limited to rule creation… direct data validation through LLMs is not yet supported" ([arXiv 2604.09163](https://arxiv.org/abs/2604.09163)) |
| **DataKitchen TestGen** | DataKitchen | Apache-2.0 ([PyPI](https://pypi.org/project/dataops-testgen/)) | 79 | 5.92.2, 2026-09-19 | Profiling, 32 hygiene issue types, 47 auto-generated test types, quality scores across 6 dimensions ([docs](https://docs.datakitchen.io/testgen/what-is-testgen/)) | Some features are Enterprise-only |

**Newer projects (2025–26):**
- **Databricks Labs DQX** (463 stars): PySpark and streaming checks with quarantine. Supplied "as-is" with no SLA ([repo](https://github.com/databrickslabs/dqx)).
- **Provero:** an Apache-2.0 response to Soda's licence change. It has no paid tier but is only 17 stars old ([DEV](https://dev.to/andreahlert/soda-moved-to-elv2-provero-is-apache-20-42l9), [repo](https://github.com/provero-org/provero)).
- **Posit Pointblank** (491 stars, [repo](https://github.com/posit-dev/pointblank)).
- **DQOps** (194 stars, [repo](https://github.com/dqops/dqo)).
- **datafold/data-diff** is archived ([repo](https://github.com/datafold/data-diff)).

## 2. Commercial references and 2024–26 deals

- **Metaplane:** bought by Datadog in April 2025 ([Datadog](https://www.datadoghq.com/blog/datadog-acquires-metaplane/)).
- **Informatica:** bought by Salesforce, closed 2025-11-18 ([BusinessWire](https://www.businesswire.com/news/home/20251118759580/en/Salesforce-Completes-Acquisition-of-Informatica)).
- **Great Expectations:** the company went to FICO and GX Cloud was shut down ([GX](https://greatexpectations.io/blog/an-update-from-great-expectations/)).
- **WhyLabs:** acquired by Apple ([GeekWire](https://www.geekwire.com/2025/founders-at-seattle-startup-whylabs-join-apple-following-under-the-radar-acquisition/)).
- **Still independent:** Monte Carlo, Bigeye, Anomalo, Sifflet and Acceldata ([dataobservability.ai](https://dataobservability.ai/data-observability-market)), and Telmai ([CB Insights](https://www.cbinsights.com/company/telmai)).
- **Not researched here:** Collibra DQ, Ataccama and Validio. A 2026 study found proprietary suites (Informatica, Experian, Ataccama) measure more than OSS tools out of the box ([arXiv](https://arxiv.org/abs/2604.09163)).
- **Licence trend:** Soda (ELv2), OpenMetadata ingestion and UI (Collate licence) and the original dbt Fusion (ELv2) all moved toward restrictive licences.

## 3. Standards and data contracts

- **ISO/IEC 25012** defines 15 characteristics, split into inherent and system-dependent ([iso25000](https://iso25000.com/en/iso-25000-standards/iso-25012)).
- **ISO/IEC 25024:2015** defines measures and "quality measure elements" for each of those characteristics ([ISO](https://www.iso.org/standard/35749.html), [arc42](https://quality.arc42.org/standards/iso-25024)).
- **ISO 8000-8** defines syntactic, semantic and pragmatic quality; **ISO 8000-61** is a process reference model ([arc42](https://quality.arc42.org/standards/iso-8000)).
- **DAMA-DMBOK** uses the core six dimensions: accuracy, completeness, consistency, timeliness, uniqueness and validity ([DAMA-NL DDQ](https://dama-nl.org/wp-content/uploads/2020/09/DDQ-Dimensions-of-Data-Quality-Research-Paper-version-1.2-d.d.-3-Sept-2020.pdf)).
- **ODCS v3.2.0** (Bitol, LF AI & Data, Apache-2.0, 1.2k stars):
  - Quality rules come as text, library metrics, SQL, or custom engine blocks (Soda, GX, dbt, Monte Carlo).
  - It includes a dimension field (accuracy, completeness, conformity, coverage, timeliness…).
  - v3.2 adds enums, maps and an AI context block ([repo](https://github.com/bitol-io/open-data-contract-standard), [CHANGELOG](https://github.com/bitol-io/open-data-contract-standard/blob/main/CHANGELOG.md)).
- **datacontract-cli** (MIT, 1.1k stars, 1.2.2 on 2026-09-25):
  - Lints and tests ODCS contracts against Postgres, Snowflake, BigQuery, Databricks, S3/Parquet, Iceberg, Kafka and more ([repo](https://github.com/datacontract/datacontract-cli)).
  - It now runs checks through DuckDB and Ibis; no Soda package appears in its PyPI dependencies ([PyPI](https://pypi.org/project/datacontract-cli/)).

## (a) Best open-source choice per job

| Job | Pick | Why |
|---|---|---|
| Profiling | fg-data-profiling for DataFrames; Deequ, DQX or Cuallee at Spark scale; whylogs-style mergeable sketches for very large or private data | Each fits a different data size |
| Rule-based checks | GX Core (Apache) as the engine, Cuallee or Pandera for DataFrames, ODCS + datacontract-cli as the contract layer | Avoid Soda (ELv2) as an embedded engine |
| Anomaly detection / observability | Elementary OSS (dbt shops), Evidently (drift), OpenMetadata (freshness/volume) | Mind OpenMetadata's ingestion licence |
| Scoring | TestGen is the only OSS tool with built-in dimension scores | Its scores are not ISO-based |

## (b) Gaps confirmed in the survey

1. **No standards-based scoring.** OSS tool functions map many-to-many onto the ISO 25012 dimensions ([arXiv 2407.18649](https://arxiv.org/abs/2407.18649)). No OSS tool implements ISO 25024 measures or ISO 8000-8 syntactic/semantic/pragmatic quality.
2. **Coverage is fragmented across store types.**
   - Deequ and DQX only work on Spark.
   - Elementary and dbt-expectations only cover dbt-modelled tables.
   - Pandera only validates DataFrames.
   - Nothing assesses an organisation's whole estate (databases, warehouses, lakehouses and object storage) in one pass.
3. **Advanced features sit behind paywalls.** ML anomaly detection, lineage and incident management are in the paid tiers of Elementary, DataHub, Dagster and Soda.
4. **No remediation.** Tools detect problems; at most DQX quarantines rows. None propose fixes such as SQL patches, deduplication or type corrections.
5. **No storage or cost-optimisation advice.** Not found in any of the OSS tools surveyed. Acceldata is the only commercial vendor positioned on cost.
6. **LLMs only help write rules.** They don't explain findings or validate data ([arXiv 2604.09163](https://arxiv.org/abs/2604.09163)).
7. **Weak semi-structured support.** ODCS only added a map type in v3.2, so contracts for nested data are only just maturing.
8. **No impact or cost prioritisation and no lineage-aware root cause in OSS.** Lineage-based triage is a Cloud feature (Elementary, DataHub, Collate).
9. **Licence risk.** Several "open" engines can't legally be embedded in a SaaS offering.

## (c) Gaps a small team could realistically close

**Feasible:**
- **ISO 25012/25024 scoring layer.** Map checks from GX Core, Cuallee or datacontract-cli to ISO characteristics and DAMA dimensions, and produce weighted scores with evidence. This is mostly a mapping and aggregation job.
- **One connector layer across store types.** Use DuckDB/Ibis (the same approach datacontract-cli takes) to reach SQL databases, Parquet/Iceberg on S3, and CSV/JSON files.
- **Plain-language explanations and fix suggestions per finding.** Use an LLM, but keep the deterministic metrics as ground truth.
- **Simple anomaly detection without a paywall.** Z-score or seasonal baselines on stored metric history.
- **Storage-hygiene advice from metadata.** Unused tables, small-files problems, wrong column types, missing partitioning.
- **ODCS as the native format.** Infer contracts from profiles and export them.

**Harder (needs a phased approach):**
- Lineage-aware root cause: possible by reusing OpenLineage or dbt manifests, but not trivial.
- Business-impact prioritisation: needs usage logs.
- Validated ML anomaly models.
- Deep time-series and semi-structured support.

**Licence recommendation:** build on Apache/MIT engines only (GX Core, Cuallee, Pandera, Deequ, datacontract-cli, ODCS). Avoid Soda Core v4 and OpenMetadata's ingestion and UI code as embedded dependencies.

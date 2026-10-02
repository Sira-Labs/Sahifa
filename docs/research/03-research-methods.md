# Research 03 — Research-grade data-quality methods

*Research date: 2026-10-01, by three parallel research agents in the Sira Labs planning
session; versions, licences and star counts verified on that date unless noted. Which
methods from the literature (assessment, constraint discovery, error detection and repair,
anomaly detection, explanation, store optimisation) are mature enough to build on, ranked
into an MVP list. Decisions derived from this are in `docs/architecture/` and `docs/adr/`.*

## Main findings
- The parts that are ready for a product are statistics-based: profiling, constraints suggested from history, metric anomaly detection, drift tests, probabilistic entity resolution and label-error detection. Mature libraries with permissive licences exist for each.
- Automatic **repair** is still risky. A VLDB 2024 study ran 12 repair algorithms on 12 datasets ([Ni et al.](https://www.vldb.org/pvldb/vol17/p2617-miao.pdf)). A 2026 benchmark of real addresses found that existing cleaners "perform well only within controlled environments" ([arXiv 2606.31983](https://arxiv.org/abs/2606.31983)). Treat repair as suggestions a human approves.
- Constraints discovered automatically are noisy. For denial constraints, the share of discovered rules that are false is "rarely below 95%" ([Martin et al., PVLDB 2025](https://doi.org/10.14778/3748191.3748209)). Rules need ranking, statistical validity tests and human confirmation.
- LLMs help with semantic errors and with writing rules, but they are not reliable cleaners on their own.
  - In a 2026 study, a deterministic profiling baseline beat the full LLM agent on detection (F1 0.561 vs 0.421) ([arXiv 2608.14765](https://arxiv.org/abs/2608.14765)).
  - LLM agents miss errors that only show up across many rows, such as trends and biases ([arXiv 2503.06664](https://arxiv.org/abs/2503.06664)).
  - Hybrid designs that use the LLM to label a sample and then train a classifier work best ([ZeroED](https://arxiv.org/abs/2504.05345)).

## 1. Assessment frameworks and metrics
- **ISO/IEC 25012/25024**: a quality model plus defined measures, for example completeness or accuracy as a ratio of passing items to total items. It is a standard, not code, and is easy to implement as the scoring vocabulary. Input is data plus rules. Suitable for automated use ([arc42 summary](https://quality.arc42.org/standards/iso-25024), [ISO sample](https://cdn.standards.iteh.ai/samples/35749/cab51b68a7bf4ae39ceade341bd4605a/ISO-IEC-25024-2015.pdf)).
- **Batini & Scannapieco; TDQM (define, measure, analyze, improve)**: the conceptual taxonomy and process loop, useful for structuring the product rather than as algorithms ([book](https://dl.acm.org/doi/10.5555/2967127), [Wang 1998, CACM](https://www.semanticscholar.org/paper/A-product-perspective-on-total-data-quality-Wang/331f6af761fbe9e2d5166b7cc7cfd4aa9a9b1074)).
- **Aggregating into scores**: Heinrich et al. set five requirements for data quality metrics: bounded range, interval scale, reliable parameters, sound aggregation, cost-efficiency ([paper](https://epub.uni-regensburg.de/36889/1/Requirements%20for%20Data%20Quality%20Metrics.pdf)).
  - Each score is a pass-ratio, so it can carry a confidence interval (Wilson or Beta posterior) from row counts or samples.
  - Bootstrap or hierarchical Bayesian models can carry that uncertainty up from column to table to domain ([arXiv 2501.04234](https://arxiv.org/html/2501.04234v1)).
  - This uncertainty layer is our own design, built from standard statistics; no off-the-shelf library does it. Suitable for automated use.
- **Data quality for ML**:
  - *Google Data Validation / TFDV* infers a schema and checks drift and skew (L-infinity distance for categorical features, Jensen-Shannon divergence for numeric). Production library, Apache-2.0. Input is batches of data ([MLSys 2019](https://mlsys.org/Conferences/2019/doc/2019/167.pdf), [TFDV](https://github.com/tensorflow/data-validation)).
  - *cleanlab (confident learning)* finds label errors, outliers and near-duplicates. When flagged label errors in benchmark test sets were checked by crowdworkers, 54% were confirmed as real errors. Production library, **AGPL-3.0**. Input is labels plus out-of-sample model probabilities ([repo](https://github.com/cleanlab/cleanlab), [NeurIPS 2021](https://arxiv.org/pdf/2103.14749)).

## 2. Automatic constraint and rule discovery
- **HyFD and the Metanome algorithms**: exact discovery of functional dependencies, unique column combinations and inclusion dependencies. Mature research code, Apache-2.0 ([repo](https://github.com/HPI-Information-Systems/metanome-algorithms)).
- **Desbordante**: a high-performance C++ profiler with Python bindings. It covers exact, approximate and probabilistic functional dependencies, denial constraints, inclusion dependencies, order dependencies and more. Actively maintained, **AGPL-3.0** ([repo](https://github.com/Desbordante/desbordante-core)).
- **DCFinder and FastADC (approximate denial constraints)**: FastADC is about 8x faster than DCFinder ([PVLDB 2022](https://www.vldb.org/pvldb/vol16/p269-tan.pdf), [DCFinder](https://dl.acm.org/doi/10.14778/3368289.3368293)). Output volume is huge and mostly false (see above). Use only with ranking and review.
- **Deequ constraint suggestion and metric-history anomaly checks**: production library on Spark, Apache-2.0, with a Python API (PyDeequ). Input is a table plus a metrics repository. Suitable for automated use ([repo](https://github.com/awslabs/deequ), [VLDB 2018](https://www.vldb.org/pvldb/vol11/p1781-schelter.pdf)).
- **Auto-Validate (SIGMOD 2021)**: infers string-pattern domains for a column by looking across a whole data lake ([arXiv](https://arxiv.org/pdf/2104.04659)).
- **Auto-Validate-by-History (KDD 2023)**: uses statistics from the past K runs of a recurring pipeline to program constraints, with statistical guarantees on false alarms. On 2,000 production pipelines it beat commercial tools ([arXiv](https://arxiv.org/abs/2306.02421)).
- **Auto-Test (SIGMOD 2025)**: learns "semantic-domain" constraints from table corpora, with quality guarantees ([arXiv](https://arxiv.org/pdf/2504.10762), [code](https://github.com/qixuchen/AutoTest)).
- For all three Auto-* papers, the algorithms are described clearly enough to reimplement. Only Auto-Test has released code. They are well suited to automated use.
- **Task-aware tests generated by LLMs**: tadv (DEEM 2025) and PrismaDV (2026) read the downstream code to infer which tests matter ([DEEM](https://dl.acm.org/doi/10.1145/3735654.3735939), [arXiv 2604.21765](https://arxiv.org/abs/2604.21765)). Prototypes only.

## 3. Error detection and repair
- **Raha and Baran**: configuration-free detection and correction. They ensemble many base detectors and need about 20 labelled tuples. Research code, Apache-2.0 ([repo](https://github.com/BigDaMa/raha)). Semi-automated, because a human labels the examples.
- **HoloClean**: probabilistic repair using denial constraints and external signals. Apache-2.0 ([repo](https://github.com/HoloClean/holoclean)). Needs constraints as input and is research-grade.
- **BClean (ICDE 2024)**: Bayesian-network cleaning with optional user priors, F1 up to 0.9 ([arXiv](https://arxiv.org/pdf/2311.06517), [code](https://github.com/yyssl88/BClean)).
- **GARF / GARF+ (VLDBJ 2025)**: learns readable repair rules with a SeqGAN; GARF+ adds an LLM ([paper](https://link.springer.com/article/10.1007/s00778-025-00941-9)).
- **UniClean (PVLDB 2025)**: cleans mixed error types at the scale of millions of records ([paper](https://www.vldb.org/pvldb/vol18/p4117-wang.pdf)).
- BClean, GARF and UniClean are research code.
- **Entity resolution and deduplication**:
  - *Splink*: Fellegi-Sunter model fitted with EM, runs on DuckDB, Spark or Athena. MIT licence, production use in government ([repo](https://github.com/moj-analytical-services/splink)). Unsupervised, so suitable for automation.
  - *Dedupe*: active learning, MIT ([repo](https://github.com/dedupeio/dedupe)).
  - *Zingg*: **AGPL-3.0** ([repo](https://github.com/zinggai/zingg)).
  - *LLM entity matching* is competitive but costly; use it on blocked candidate pairs ([Peeters et al., EDBT 2025](https://www.uni-mannheim.de/dws/news/paper-accepted-at-edbt-2025/)).
- **Imputation**: HyperImpute does iterative imputation with automatic model selection and bundles MICE, MissForest and GAIN. MIT ([repo](https://github.com/vanderschaarlab/hyperimpute)). A benchmark on 69 datasets found simple methods often competitive ([Jäger et al. 2021](https://www.frontiersin.org/journals/big-data/articles/10.3389/fdata.2021.693674/full)).
- **LLM-based cleaning**:
  - *Foundation models* (Narayan et al.) reached state of the art on prompted cleaning and integration tasks ([PVLDB 2022](https://www.vldb.org/pvldb/vol16/p738-narayan.pdf), [code](https://github.com/HazyResearch/fm_data_tasks)).
  - *Jellyfish* is a set of local 7–13B models covering error detection, imputation, schema matching and entity matching ([EMNLP 2024](https://aclanthology.org/2024.emnlp-main.497/), [weights](https://huggingface.co/NECOUDBFM/Jellyfish)).
  - *LLMClean* has an LLM generate ontological functional dependencies, which are then applied deterministically ([arXiv](https://arxiv.org/abs/2404.18681)).
  - LLMs beat Raha and Baran on contact data, but not on every error type ([VLDB-W 2025](https://www.vldb.org/2025/Workshops/VLDB-Workshops-2025/DATAI/DATAI25_12.pdf)).
  - The 2026 survey names hallucination, cost and weak evaluation as open problems ([arXiv 2601.17058](https://arxiv.org/abs/2601.17058)).
  - **Verdict**: use LLMs to *propose* rules and semantic checks, then execute those deterministically.

## 4. Anomaly detection on pipelines, tables and time series
- **Volume, freshness and metric anomalies**: Deequ, Evidently (Apache-2.0, [site](https://www.evidentlyai.com/)), Great Expectations (Apache-2.0, [repo](https://github.com/great-expectations/great_expectations)) and Elementary (Apache-2.0, [repo](https://github.com/elementary-data/elementary)) are production-ready. Soda Core moved to **Elastic License 2.0** ([blog](https://soda.io/blog/soda-core-license-update-moving-to-elastic-license)).
- **Drift tests**:
  - KS, Wasserstein and Jensen-Shannon are standard (scipy, TFDV).
  - The common PSI cut-offs of 0.1 and 0.25 have no error-rate basis. PSI is approximately chi-square distributed, so critical values can be computed instead ([Yurdakul](https://files.wmich.edu/s3fs-public/attachments/u730/2022/PSIfinal.pdf)).
  - With large row counts every test becomes significant, so thresholds should be set on effect size.
- **GATE (CIKM 2023)**: summarises each time partition and compares summaries; 2x better precision than prior work at a large tech company. It is aimed directly at alert fatigue ([paper](https://dl.acm.org/doi/10.1145/3583780.3614786)).
- **Time series**:
  - *TSB-AD (NeurIPS 2024)*: across 1,070 series, simple statistical methods often win; it also proposes the VUS evaluation metric ([paper](https://proceedings.neurips.cc/paper/2024/hash/c3f3c690b7a99fba16d0efd35cb83b2c-Abstract-Datasets_and_Benchmarks_Track.html), [PyPI](https://pypi.org/project/TSB-AD/)).
  - *STL plus seasonal baselines* (statsmodels) are a strong default.
  - *Conformal thresholds* turn anomaly scores into false-alarm-rate p-values. Weighted or adaptive variants handle drift ([arXiv 2604.20122](https://arxiv.org/abs/2604.20122), [MAPIE](https://github.com/scikit-learn-contrib/MAPIE)). Mature and suitable for automation, and this part can be shared with the sister product.

## 5. Explanation and root cause
- **Data X-Ray**: Bayesian cost model that finds the common features shared by erroneous elements ([PVLDB 2015](http://www.vldb.org/pvldb/vol8/p1984-wang.pdf)). Research only, but easy to reimplement.
- **MacroBase DIFF**: finds attribute combinations over-represented in bad rows compared with good rows. Apache-2.0 ([VLDB 2019](https://www.bailis.org/papers/diff-vldb2019.pdf), [repo](https://github.com/stanford-futuredata/macrobase)). Good for "errors concentrate in source=X, date>Y" explanations, fully automatable.
- **Lineage-aware root cause**: capture lineage with OpenLineage (Apache-2.0, [repo](https://github.com/OpenLineage/OpenLineage)) and SQLGlot column lineage (MIT, [blog](https://medium.com/@toby.mao/yes-sqlglot-supports-column-level-lineage-9d141fa8d4a1)). Then rank upstream anomalies along the lineage graph.
  - No standard research algorithm exists here, which makes it an opening for us.
  - A taxonomy of root causes exists; incorrect data types are the top cause (33%) ([arXiv 2309.07067](https://arxiv.org/abs/2309.07067)).

## 6. Data store optimisation
- **Unused tables**: practice is query-log and access-history analysis (for example Snowflake ACCESS_HISTORY) ([select.dev](https://select.dev/posts/snowflake-unused-tables)). There is little research; implementing it is simple engineering.
- **Duplicate or overlapping tables**: MinHash and LSH Ensemble containment search with datasketch (MIT, [repo](https://github.com/ekzhu/datasketch)). Starmie learns column embeddings for finding unionable tables ([PVLDB 2023](https://www.vldb.org/pvldb/vol16/p1726-fan.pdf)).
- **Compaction**:
  - *AutoComp* (LinkedIn/Microsoft, SIGMOD 2025) automates compaction for log-structured tables ([arXiv](https://arxiv.org/abs/2504.04186)).
  - *Smart Compaction* (2026, Iceberg) found that a simple rule, max_files_per_partition > 4, is enough to decide when to compact. It also warns that compaction can slow full scans ([arXiv 2608.08639](https://arxiv.org/abs/2608.08639)).
- **Layout and clustering**: Qd-tree and MTO ([SIGMOD 2021](https://www.microsoft.com/en-us/research/wp-content/uploads/2021/04/msr-mto-sigmod.pdf)); WAIR incremental reclustering ([SIGMOD 2026](https://arxiv.org/abs/2602.23289)). Research only.
- **Index recommendation**: Dexter plus HypoPG for Postgres ([Dexter](https://ankane.org/introducing-dexter)), with an evaluation of 8 index-selection algorithms ([PVLDB 2020](https://www.vldb.org/pvldb/vol13/p2382-kossmann.pdf), [repo](https://github.com/hyrise/index_selection_evaluation)). Mature.
- **Normalisation advice**: the Normalize algorithm proposes BCNF from discovered functional dependencies ([EDBT 2017](https://openproceedings.org/2017/conf/edbt/paper-89.pdf)). LLMs need multi-agent checking to normalise schemas reliably ([DNBench/MARS 2026](https://arxiv.org/abs/2609.11141)).
- **Data debt**: only catalogues of "data smells" exist ([arXiv 2203.10384](https://arxiv.org/pdf/2203.10384)). No validated health index exists, which is an opening.

## Ranked MVP list
1. **Profiling plus ISO 25024 scores with confidence intervals and Heinrich-compliant aggregation**: the base for everything else. *Differentiator: commercial scores have no uncertainty.*
2. **Metric-history anomaly detection (volume, freshness, nulls, distinct counts)** following Auto-Validate-by-History, using STL baselines and conformal thresholds that guarantee a false-alarm rate. *Differentiator: statistical guarantees instead of heuristic sensitivity sliders.*
3. **Drift tests with effect-size and PSI critical values, plus GATE-style partition summaries**: tackles alert fatigue directly.
4. **Constraint suggestion** (Deequ-style, plus approximate FDs from HyFD or Desbordante, plus Auto-Test semantic domains), ranked with validity tests that respect the 95%-false finding. *Differentiator: mined FDs and DCs.*
5. **Entity resolution and dedup via Splink** (MIT, unsupervised).
6. **Error explanation with DIFF / Data X-Ray** ("bad rows concentrate in…"). *Differentiator: few tools explain errors.*
7. **Lineage-aware root cause with OpenLineage and SQLGlot**: rank upstream anomalies. *Differentiator.*
8. **Rules proposed by an LLM and run deterministically** (LLMClean / ZeroED pattern), with a human approving them. *Differentiator: safe use of LLMs.*
9. **Store-health report**: unused and duplicate tables from logs plus MinHash, Iceberg/Delta small-file and compaction advice, Dexter index tips. *Differentiator: commercial observability tools rarely combine data quality with store hygiene.*
10. **Label-error and outlier detection for ML datasets** (cleanlab). Its AGPL licence affects distribution, so make it an optional plugin or reimplement confident learning.

**Licence watch:** cleanlab, Zingg and Desbordante are AGPL; Soda Core is ELv2. Prefer the Apache or MIT options listed above for the core product.

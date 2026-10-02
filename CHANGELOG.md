# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). Until 1.0, minor versions may break APIs.

## [Unreleased]

### Added
- R0 research and design: research 01–04 (DataKitchen TestGen as reference, the data-quality
  landscape, methods, synthesis and positioning), product vision, domain model, system
  architecture, ADRs 0001–0013, check specification and the catalogue of the first 30 checks,
  roadmap, first specs, the CapRover deployment plan and the product page.
- First scan pipeline: the `sahifa_core` library profiles every table or file of a source,
  generates checks from the profile, evaluates them in the source (SQL pushdown on Postgres,
  DuckDB on CSV, Parquet and JSON files), scores each quality dimension with a 95 % interval
  and reports findings with evidence; the `sahifa` CLI (`sahifa synth`, `sahifa scan`) runs
  it from a terminal.
- CI for core, api and web; release pipeline publishing `sahifa-api` and `sahifa-web` images
  to GHCR with SBOM, provenance and a Trivy scan, deploying staging and promoting the same
  digests to production (ADR-0012); compose bundles and the CapRover guide in `deploy/`.
- Apache-2.0 licence (ADR-0008), contribution guide, security policy, code of conduct, issue
  and pull request templates, Dependabot, CODEOWNERS and the `main` and release-tag rulesets.

[Unreleased]: https://github.com/Sira-Labs/Sahifa/commits/main

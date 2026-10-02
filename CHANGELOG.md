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
- Sign-in through a Keycloak realm with Google, GitHub and passkeys (spec 006): the API is the
  backend-for-frontend with an HttpOnly session cookie, CSRF header, devices, logout and
  back-channel logout; only the admin and allowed emails get access. Installs behind HTTP
  basic auth keep working in `proxy` mode.

### Fixed
- Product page: the favicon loads (the inline data URL was cut off by unescaped quotes; it now
  uses `assets/favicon.svg`), Tabayyun is linked at tabayyun-stg.siralabs.org, and the page links
  the running preview at sahifa-stg.siralabs.org.

[Unreleased]: https://github.com/Sira-Labs/Sahifa/commits/main

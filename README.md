<div align="center">

![Sahifa](docs/assets/logo-dark.svg#gh-dark-mode-only)
![Sahifa](docs/assets/logo-light.svg#gh-light-mode-only)

</div>

# Sahifa

**Know what your data promises, and whether it keeps it.**

[![CI](https://github.com/Sira-Labs/Sahifa/actions/workflows/ci.yml/badge.svg)](https://github.com/Sira-Labs/Sahifa/actions/workflows/ci.yml)
[![Release](https://github.com/Sira-Labs/Sahifa/actions/workflows/release.yml/badge.svg)](https://github.com/Sira-Labs/Sahifa/actions/workflows/release.yml)
[![Python](https://img.shields.io/badge/python-3.11%2B-3776ab)](core/pyproject.toml)
[![Node](https://img.shields.io/badge/node-22%20LTS-5fa04e)](web/package.json)
[![Images](https://img.shields.io/badge/images-ghcr.io-2496ed)](https://github.com/orgs/Sira-Labs/packages?repo_name=Sahifa)
[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

> *Ṣaḥīfa* (صحيفة): a written sheet; the charter of Medina.

Sahifa is a self-hostable platform that assesses the quality of whole data stores: Postgres
databases, and CSV, Parquet and JSON files (SAP HANA and Datasphere, warehouses and lakehouse tables follow). It
profiles every table and column, generates checks from the profile, scores six quality
dimensions (completeness, validity, accuracy, consistency, uniqueness, currentness; mapped to
ISO/IEC 25012) with a **95 % interval that says how sure each score is**, and explains every
finding with counts, examples, the SQL that found it and a next step. It never writes to the
data it assesses. It is the sister of [Tabayyun](https://github.com/Sira-Labs/Tabayyun), which
verifies industrial time series.

Status: **R1, sprint 1** (`docs/roadmap/sprints.md`). Work follows written specs in
`docs/specs/` with the backlog in `TASKS.md`.

## Why the name

The *Ṣaḥīfa* of Medina was the written charter the Prophet ﷺ agreed with the people of the
city: it set down what each party could expect of the others. A data contract does the same
for a table. The Sīra also tells of another *ṣaḥīfa*, the boycott document hung in the Kaaba
and found eaten by termites except for the name of Allah. Records decay unless someone looks
after them; Sahifa does the looking.

## Quick start

```bash
# CLI: write a small shop dataset with injected faults and assess it
cd core && uv sync
uv run sahifa synth /tmp/shop
uv run sahifa scan /tmp/shop --pretty

# Any Postgres you can read (Sahifa opens read-only transactions)
uv run sahifa scan "postgresql://reader:secret@localhost:5432/shop?schemas=public" --pretty

# API and web in development
make dev-infra     # Postgres 17 for metadata and a demo source (docker compose)
make db-upgrade    # apply the schema migrations
make api-dev       # http://localhost:8000/api/docs
make web-dev       # http://localhost:5173
```

## Documentation

| Area | Document |
|---|---|
| Vision, personas, scope | [docs/architecture/01-product-vision.md](docs/architecture/01-product-vision.md) |
| Domain model and scoring | [docs/architecture/02-domain-model.md](docs/architecture/02-domain-model.md) |
| System architecture | [docs/architecture/03-system-architecture.md](docs/architecture/03-system-architecture.md) |
| Check specification | [docs/checks/00-check-specification.md](docs/checks/00-check-specification.md) |
| **The first 30 checks** | [docs/checks/catalogue.md](docs/checks/catalogue.md) |
| Frontend design | [docs/frontend/01-frontend-design.md](docs/frontend/01-frontend-design.md) |
| Roadmap and sprint plan | [docs/roadmap/roadmap.md](docs/roadmap/roadmap.md), [sprints.md](docs/roadmap/sprints.md) |
| Specs | [docs/specs/](docs/specs/) |
| Deployment (images, compose, CapRover) | [deploy/README.md](deploy/README.md), [deploy/caprover.md](deploy/caprover.md) |
| Decisions (ADRs 0001–0014) | [docs/adr/](docs/adr/) |
| Product page | [site/index.html](site/index.html) |

Research reports (with sources):

1. [DataKitchen TestGen as the reference product](docs/research/01-datakitchen-reference.md)
2. [The data-quality tool landscape](docs/research/02-data-quality-landscape.md)
3. [Research-grade data-quality methods](docs/research/03-research-methods.md)
4. [Synthesis and positioning](docs/research/04-synthesis-and-positioning.md)

## Stack (decided)

- **Core:** Python 3.11+, checks as SQL run where the data lives (ADR-0001); DuckDB for files
  and object storage (ADR-0002); SQLGlot for safe SQL rendering.
- **Backend:** FastAPI, SQLAlchemy 2 async, Alembic; PostgreSQL 17 (ADR-0003); Procrastinate
  worker from sprint 2 (ADR-0009).
- **Frontend:** Vite + React 19 SPA, TanStack Router and Query, Tailwind v4, served by Caddy (ADR-0007).
- **Identity (R2):** Keycloak realm, Google, GitHub and passkeys, BFF cookie sessions (ADR-0010).
- **Deployment:** images on GHCR, CapRover staging and production (ADR-0012), docker compose.

## Principles

Read-only, always · scores with error bars · explain, don't just flag · generated, then
owned · every store, one model · open without a paywall · rules for the whole world.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## Licence

[Apache License 2.0](LICENSE) (ADR-0008). Contributions are accepted under the same licence.

# Sahifa — working notes for Claude Code

Self-hostable data-quality assessment for whole data stores (databases, warehouses, lakehouse
tables, files). Read `docs/` before changing design: `docs/checks/catalogue.md` (the 30
checks), `docs/architecture/02-domain-model.md` (scoring), `docs/architecture/03-system-architecture.md`,
`docs/adr/` (decisions; add a new ADR rather than silently deviating).

## Session protocol (spec-driven, as in Tabayyun and Thawr)

1. One spec per session. The prompt names it (`Implement docs/specs/NNN-name.md. Plan first.`).
   Read this file, `docs/architecture/03-system-architecture.md` and that one spec plus the
   specs it references; do not read all specs.
2. Present the plan, wait for approval, then implement. Deviating from a spec, an ADR or a
   fixed architecture decision needs a question first, or a new ADR.
3. `make lint` and `make test` (or the relevant subset) before every commit; semantic commits,
   one logical change each; a spec may take several commits.
4. When the spec's acceptance criteria are met, tick them in the spec, mark it done in
   `TASKS.md` and add one line per non-obvious decision under its entry.
5. Do not start the next spec in the same session. Do not refactor code the spec does not touch.
6. A story in `docs/roadmap/sprints.md` gets its spec (copy `docs/specs/000-template.md`)
   before any code; a spec that turns out wrong is edited in the same PR, with the reason.

## Layout
- `core/` Python 3.11+ library `sahifa_core` (uv): connectors (DuckDB, Postgres), `sql.py` dialects, profile, semantics (rule packs), checks, score, report, scan, CLI `sahifa`, synth.
- `api/` FastAPI (uv), package `sahifa`, depends on `../core` by path. SQLAlchemy 2 async, Alembic migrations packaged in `sahifa/db/migrations`.
- `web/` Vite + React 19 + TanStack Router/Query + Tailwind v4 SPA (pnpm), served by Caddy.
- `deploy/` compose bundles, CapRover guide; `api/Dockerfile`, `web/Dockerfile`; `.github/workflows/release.yml` publishes images to GHCR and deploys staging; `promote.yml` promotes to production.
- `site/` the product page for siralabs.org. `docs/` design and research.

## Commands
- `make lint` / `make test` run everything. `make demo` writes the faulty shop and scans it.
- Core: `cd core && uv sync --extra dev && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy`
- API: `cd api && uv sync --extra dev && uv run pytest -q && uv run ruff check . && uv run mypy`. Database tests run when `SAHIFA_TEST_DATABASE_URL` is set, Postgres-source tests when `SAHIFA_TEST_SOURCE_URL` is set (`make dev-infra` provides both); `make db-upgrade`, `make db-revision m="..."`.
- Web: `cd web && pnpm install --frozen-lockfile && pnpm lint && pnpm build && pnpm test`

## Conventions
- Sahifa never writes to a source. Source sessions are read-only with timeouts (ADR-0006).
- No value from the data is ever concatenated into SQL; identifiers and literals go through `sql.py` (SQLGlot rendering). Hostile-name tests exist; keep them passing.
- Every check has a test that it fires on the faulty shop and stays silent on the clean shop; every finding has a summary, counts, examples (masked when personal), the SQL and a next step.
- Scores: only active and locked checks count; every score has a 95 % interval (ADR-0004).
- Credentials only by reference (`SAHIFA_CONN_*`); no secrets in code, config or logs; prod refuses placeholders.
- Runtime dependencies Apache/MIT/BSD-compatible only (ADR-0008).
- Semantic commit messages (`feat:`, `fix:`, `docs:`, `refactor:`, `chore:`, `test:`).
- Diagrams are Mermaid in Markdown, not ASCII art.
- Licence Apache-2.0. Backlog and session notes: `TASKS.md`. Specs: `docs/specs/`. Sprint plan: `docs/roadmap/sprints.md`.

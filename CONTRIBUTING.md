# Contributing to Sahifa

Thanks for helping assess the quality of data stores. This page covers the workflow; the
design lives in `docs/` and is the source of truth: read
`docs/architecture/03-system-architecture.md`, `docs/checks/00-check-specification.md` and the
ADRs in `docs/adr/` before changing behaviour.

## Ground rules

- **Design first.** A change that deviates from a documented decision needs a new ADR
  (copy `docs/adr/0000-adr-template.md`), not a silent workaround.
- **Spec first.** Features follow written specs in `docs/specs/` (copy
  `docs/specs/000-template.md`): goal, interface, numbered behaviour, acceptance criteria and
  test cases, one spec per feature, written before the code. `TASKS.md` is the backlog and
  holds one line per non-obvious decision taken while implementing a spec.
- **Never write to a source.** Sahifa connects read-only, in read-only transactions with
  statement and lock timeouts (ADR-0006). Fixes are proposals on a finding, never statements
  run against the source (ADR-0005).
- **Checks are pure.** No I/O inside a check. A check returns a fail predicate or evaluates
  grouped values; the engine runs the query. Every check ships with a synthetic-fault test,
  a clean-data test, evidence and a plain-language summary
  (`docs/checks/00-check-specification.md`).
- **SQL is built, not concatenated.** Identifiers are quoted and literals rendered by SQLGlot
  (`core/src/sahifa_core/sql.py`); no value from the data or the user is ever pasted into SQL
  as text.
- **No secrets** in code, config, fixtures or tests. Environment variables only; connection
  credentials are referenced by the name of a `SAHIFA_CONN_*` variable (ADR-0006).
- **Permissive dependencies only.** Runtime dependencies of the core, API and web are MIT,
  BSD, Apache-2.0, ISC, PSF or MPL-2.0; nothing AGPL, GPL, SSPL, ELv2 or BSL (ADR-0008).
- **Never real customer data** in issues, fixtures or tests. Use `sahifa synth`.

## Development setup

| Part | Toolchain | Commands |
|---|---|---|
| `core/` | Python 3.11+, uv | `uv sync --extra dev && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy` |
| `api/` | Python 3.11+, uv | the same commands; `uv run alembic upgrade head` once against the dev database |
| `web/` | Node 22, pnpm 10 | `pnpm install --frozen-lockfile && pnpm lint && pnpm build && pnpm test` |

`docker compose -f deploy/compose.dev.yaml up -d` starts Postgres 17 on `localhost:5432`: the
metadata database for the API and a small demo source to scan. The core needs nothing else:
`uv run sahifa synth /tmp/shop && uv run sahifa scan /tmp/shop` profiles and checks a
synthetic shop dataset with injected faults on DuckDB.

Postgres integration tests run when `SAHIFA_TEST_DATABASE_URL` (the API's test database) and
`SAHIFA_TEST_SOURCE_URL` (a source to scan) are set; CI provides both, locally they point at
the dev compose database. Without them those tests are skipped, never failed.

## Workflow

1. Open or pick an issue. Label it with an `area:` and, if it is a check, `type: check`.
   Anything that changes a decision gets `needs: design` and an ADR draft.
   A feature needs a spec in `docs/specs/` (see Ground rules); the PR links it.
2. Branch from `main`: `feat/<short-topic>`, `fix/<short-topic>`, `docs/<short-topic>`.
3. Commit in small, logical steps with semantic messages:
   `feat(core): ...`, `fix(api): ...`, `docs: ...`, `refactor(web): ...`, `chore(ci): ...`,
   `test(core): ...`. Scope is the directory or check id. No debug code, no `WIP` commits on
   the final branch (squash locally if needed).
4. Open a pull request against `main` and fill in the template. Link the issue with
   `Closes #n`. Keep PRs reviewable: one concern per PR, under ~500 changed lines where
   possible.
5. CI must be green (`python core`, `python api`, `web`). Review threads must be resolved
   before merge. Merge with a merge commit or squash; rebase-merge is off.

## Adding a check

1. Pick the next id from `docs/checks/catalogue.md`; do not invent ids outside the catalogue
   without a "Check proposal" issue. `sah.` is reserved for built-in checks, `store.` for
   store-health items.
2. Implement it in `core/src/sahifa_core/checks/<name>.py` with the manifest attributes of the
   check specification, register it, and add the fault to `synth.py` so the test can inject
   it.
3. Tests: at least one clean dataset producing no finding and one injected fault producing the
   expected finding with sensible evidence, on DuckDB in memory. A check evaluated in SQL also
   runs against Postgres in the integration tests, so both dialects agree.
4. Update the catalogue status column and any threshold rationale.

## Licence of contributions

Sahifa is licensed under Apache-2.0 (`LICENSE`, ADR-0008). By submitting a contribution you
agree it is licensed under the same terms (inbound = outbound). There is no CLA. Do not
contribute code or data you are not entitled to license this way, and never real customer data.

## Repository settings (maintainers)

Protection for `main` is defined as a ruleset in `.github/rulesets/protect-main.json`:
pull request required, the three CI jobs required, review threads resolved, no force-push,
no deletion, no bypass. Committing the file does not enforce anything: a repository admin
has to import it once under **Settings → Rules → Rulesets → New ruleset → Import a
ruleset**, or with the GitHub CLI:

```bash
gh api -X POST repos/Sira-Labs/Sahifa/rulesets --input .github/rulesets/protect-main.json
```

After editing the JSON, do not re-run the import (`POST` creates a second ruleset). Update the
existing one instead: edit it in the same settings page, or send the file to its ID:

```bash
id=$(gh api repos/Sira-Labs/Sahifa/rulesets --jq '.[] | select(.name=="protect-main") | .id')
gh api -X PUT "repos/Sira-Labs/Sahifa/rulesets/$id" --input .github/rulesets/protect-main.json
```

`.github/rulesets/protect-release-tags.json` lets only organisation admins create, move or
delete `v*` tags (a tag on `main` publishes a release, ADR-0012); import it the same way.

Until the rulesets are active, the CI, review-thread and tag gates above are convention, not
enforcement. Recommended repository settings (Settings → General): automatically delete head
branches, allow auto-merge, always suggest updating pull request branches, rebase merging off.
Settings → Code security: private vulnerability reporting, Dependabot alerts and security
updates, secret scanning with push protection.

## What

<!-- One or two sentences: what changes and why. Link the issue: Closes #123 -->

## Checks

- [ ] Implements a spec in `docs/specs/` (linked above); its acceptance criteria are ticked and `TASKS.md` is updated
- [ ] Lint, type checks and tests pass locally for the parts touched (`uv run ruff check . && uv run mypy && uv run pytest -q` in `core/` or `api/`, `pnpm lint && pnpm test` in `web/`)
- [ ] New or changed checks have a synthetic-fault test, a clean-data test, evidence and a plain-language summary
- [ ] Nothing writes to a source; SQL is built with SQLGlot, never with values pasted in as text
- [ ] Schema changes come with an Alembic migration (`uv run alembic check` is clean)
- [ ] Design deviations are recorded as a new ADR in `docs/adr/` (not silently)
- [ ] Docs updated (`docs/checks/catalogue.md` status, README, `deploy/README.md`, `deploy/caprover.md`) where behaviour changed
- [ ] No secrets, credentials, placeholder values or real customer data in code, config or fixtures
- [ ] Commit messages follow `type(scope): summary` (feat, fix, docs, refactor, chore, test)

## Notes for the reviewer

<!-- Anything non-obvious: trade-offs, follow-ups, how to try it. -->

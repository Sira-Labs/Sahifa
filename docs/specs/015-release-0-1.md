# Spec 015 — Release 0.1

Sprint 3, story S3-5. Depends on: specs 012–014 (gate G1), ADR-0012 (release and promote
pipeline). Packages: `core/`, `api/`, `web/` (version numbers), `site/`, `docs/`.

Status: approved 2026-10-07 by the owner: tag `v0.1.0` now, with the promote dry run deferred
to the first production deploy.

## Goal

Sahifa 0.1 is the first preview. When this spec is done, the following are in place:
- `v0.1.0` is a tag on `main`.
- The images for it are published as `0.1.0` to GHCR.
- Staging runs it and reports version `0.1.0`.
- The changelog, the roadmap and the product page say what 0.1 contains and what it does not.

## User story

As someone trying Sahifa, I can see which version I run and what that version promises, so
that I know what to expect from the preview and what comes next.

## Interface

| What | Before | After |
|---|---|---|
| `core/pyproject.toml`, `sahifa_core.__version__` | `0.1.0.dev0` | `0.1.0` |
| `api/pyproject.toml`, `sahifa.__version__` | `0.1.0.dev0` | `0.1.0` |
| `web/package.json` | `0.1.0` | `0.1.0` (unchanged) |
| `uv.lock` of `core` and `api` | `0.1.0.dev0` | `0.1.0`, regenerated with `uv lock` |
| `CHANGELOG.md` | everything under `[Unreleased]` | `[0.1.0] - 2026-10-07` with known limitations; an empty `[Unreleased]` above it; compare links |
| Product page (`site/index.html`) | "Now: specs and first build"; "October 2026: first preview" | "7 Oct 2026: preview 0.1" with what it holds; the tag `Preview 0.1` at the top |
| `docs/roadmap/roadmap.md` | R1 in progress; G1 open | R1 released; G1 records what was met and what was deferred, by whose decision |
| Git | none | annotated tag `v0.1.0` on the merge commit of this spec's PR |

## Behaviour

1. **Pull request.** The PR carries the version numbers, the changelog, the product page and
   the roadmap. It is merged when CI is green and the review is clean.
2. **Tag.** After the merge, `v0.1.0` is created on the merge commit and pushed.
   `release.yml` checks that the commit is on `main`. It then builds, scans and publishes the
   images with the tags `0.1.0` and `sha-<short>`, and deploys staging.
3. **Check.** Staging reports `{"version": "0.1.0", "commit": <the tagged commit>}` on
   `/api/version`, and `/healthz` shows the worker on the same commit.
4. **G1 as met at the tag.**
   - Met: security baseline (spec 012), performance budget (spec 013), accuracy table
     (spec 014), staging live.
   - Deferred by the owner on 7 Oct: the promote dry run to production (S3-3). It runs with
     the first production deploy, before production serves anyone.
   - The owner's own staging check (sign-in with three methods, a scheduled scan, the score
     history) is recorded with its state at tag time.
5. **Failure.** If the tag's release run fails, the tag is not moved or re-pushed. The fix goes
   to `main` and is released as `v0.1.1`.

## Acceptance criteria

- [x] Versions read `0.1.0` in `core`, `api` and `web`, and the lockfiles agree (`uv lock
      --check`).
- [x] `CHANGELOG.md` has `[0.1.0] - 2026-10-07` with "Known limitations"; `[Unreleased]` is
      empty.
- [x] The product page and the roadmap state the release and the deferred promote dry run.
- [x] `v0.1.0` is on `main`; the release run is green; GHCR has `sahifa-api:0.1.0` and
      `sahifa-web:0.1.0`.
- [x] Staging `/api/version` reports `0.1.0` at the tagged commit.
- [x] `make lint` and `make test` pass.

## Test cases

- **API, `test_health_and_version`:** `/api/version` reports `sahifa.__version__`, and it
  equals `sahifa_core.__version__`, because the API and the engine it ships are released
  together.
- **Commands:** `uv lock --check` in `core` and `api`; `pnpm build` in `web`.

## Implementation notes

- **Where the tag is.** The owner published the release on 9 Oct from `main`. By then `main` also
  held the Dependabot updates (PR #26: Python 3.14 image, Vite 8, Vitest 5, ESLint 10, Pages
  actions), so `v0.1.0` is on efd6f33, not on this spec's merge commit 57d2df9. Those updates
  were tested before the merge and ran on staging for two days, so the tag was kept rather than
  moved, as behaviour 5 asks. `CHANGELOG.md` lists them under `[0.1.0]`.
- **Release date 9 Oct, not 7 Oct.** The changelog section carries the date the tag was
  published.
- **A GitHub Release page exists after all.** The owner published `v0.1.0` as a pre-release, with
  notes taken from the changelog.

## Out of scope

- The promote to production: it runs with the first production deploy, once the owner has
  created the production apps (S3-3).
- A GitHub Release page. The tag, the images and `CHANGELOG.md` are the release. The page can
  be drafted from the changelog once the session has a tool that writes releases.

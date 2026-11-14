# ADR-0016: Nightly development runs without the owner, merging on green CI

- **Status:** Accepted
- **Date:** 2026-11-14
- **Deciders:** owner
- **Amends:** the session protocol in `CLAUDE.md`, the working agreement in `docs/roadmap/sprints.md`

## Context

Until now a session presented its plan and waited for the owner's approval, the owner
reviewed and merged every pull request, and an open question stopped the work. The last merge
to `main` was on 17 October. In the four weeks since:
- six Dependabot pull requests stayed open;
- the required check `python api` turned red on every pull request (new advisories in the
  lockfile) and nobody saw it, because `main` itself ran no CI.

The owner decided on 14 November 2026 that development continues without him.

## Decision

A nightly run works through the backlog on its own, one story per run.

- **Plan, then implement.** The run writes its plan (the spec) and implements it straight
  away. Step 2 of the session protocol (present the plan, wait for approval) does not apply to
  these runs.
- **Deviations are recorded, not asked.** A deviation from a spec or an ADR needs a new ADR in
  the same pull request.
- **The run merges.** Pull requests are opened ready for review with auto-merge enabled. Where
  auto-merge is not available, the run merges once every required check is green and every
  review thread is resolved. It never merges with a red or pending check.
- **Order of a run:**
  1. its own open pull requests, then the last release run and staging; a broken `main` or
     staging is that run's story;
  2. Dependabot pull requests, at most about a third of the run;
  3. the first open, unblocked story in the sprint plan's priority order.
- **Never stall on the owner.** A story that needs something only the owner can give (a
  secret, an account, a server, a licence, a product decision) gets one `Owner:` line in
  `TASKS.md` saying what is needed and why, and the run takes the next story. Where an earlier
  session left a question with a recommended answer, the run takes the recommendation and
  records it, as an ADR when it is hard to reverse.
- **Report.** Open owner items go to the owner in one short mail on Sundays.

Limits, without exception:
- staging only: never production (`promote.yml`), never a major release;
- no secrets in code, config, pull requests or logs;
- no change to rulesets, branch protection, repository settings, tokens or workflow
  permissions;
- no test or lint rule skipped, disabled or weakened to get green; no force-push to `main`; no
  rewriting of other people's branches;
- this repository only.

Everything else in `CLAUDE.md` and `CONTRIBUTING.md` stands: spec first, `make lint` and
`make test` before every commit, semantic commits, one story per session.

## Alternatives considered

| Option | Pros | Cons | Why not |
|---|---|---|---|
| Keep approval and merge with the owner | Every change is seen before it lands | Work stops whenever the owner is away, as it did for four weeks | The owner's time is the bottleneck |
| Runs open pull requests, the owner merges in batches | Review stays human | Pull requests pile up and conflict; staging never shows the work | Same bottleneck, later |
| Merge without required checks | Fastest | A red `main` deploys to staging | CI and review threads are the gate that remains |

## Consequences

- CI, CodeRabbit's review threads and the staging deploy check are the only gates before
  staging, so the tests carry more weight. Production still needs the owner (`promote.yml`).
- Auto-merge needs the ruleset `protect-main` to be active on the repository
  (CONTRIBUTING.md, "Repository settings"); until then a run merges by hand after the checks.
- Decisions taken on the owner's behalf are visible in `TASKS.md` and in ADRs, and can be
  reversed there.
- Interactive sessions with the owner keep the old protocol unless he says otherwise.

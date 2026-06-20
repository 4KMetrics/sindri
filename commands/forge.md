---
description: Start a new sindri optimization run from a goal statement — bounded, target-driven experiments on any deterministic metric.
argument-hint: <goal statement>  e.g. reduce bundle_bytes by 15%
---

# /sindri:forge — start an optimization run

The user's goal statement is in `$ARGUMENTS`. Your job is to start a new run.

## Routing

- **No goal given** (`$ARGUMENTS` is empty): print the three accepted shapes and stop — do **not** guess a goal:
  - `reduce <metric> by <N>%`     e.g. `reduce bundle_bytes by 15%`
  - `increase <metric> by <N>%`   e.g. `increase test_coverage by 10%`

  Ask the user to re-run `/sindri:forge` with one of these.
- **Active run exists** (`.sindri/current/` is present): print a resume/abandon prompt and **do not** start a new run — *"There's already an active run; it resumes on its next wakeup. Abandon it with `/sindri:clear` to start fresh."*
- **Otherwise**: invoke skill `sindri-start` with `$ARGUMENTS` as the goal statement.

## Invariants

- **One run per repo.** Never start a new run while `.sindri/current/` exists.
- **Never start from an unparseable goal.** `sindri-start` normalizes and confirms before touching git.

## After dispatch

Control passes to `sindri-start`, which produces all user-visible output. Once it returns, sindri is running autonomously — `ScheduleWakeup` has been set, and the orchestrator runs on every wakeup until termination. On clean termination with ≥1 kept commit, the loop auto-invokes `sindri-finalize` to push the branch and open the PR.

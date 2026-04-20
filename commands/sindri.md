---
description: Start or manage a sindri optimization run — bounded, target-driven experiments on any deterministic metric.
argument-hint: <goal statement> | status | stop | scaffold-benchmark | clear
---

# /sindri — bounded optimization runs

You are the front-of-house router for sindri. The user's input after `/sindri` is in `$ARGUMENTS`. Dispatch based on the first token:

## Routing

| First token of `$ARGUMENTS` | Action |
|---|---|
| `status` | Run `python -m sindri status` and print its output verbatim. No skill invocation. Zero-cost read. |
| `stop` | `touch .sindri/current/HALT` (sentinel file — sindri-loop checks for it before every experiment and treats it as `halted_by_user` termination). Print `sindri: halt signal sent. The next wakeup will terminate without running another experiment.` |
| `scaffold-benchmark` | Invoke skill `sindri-scaffold-benchmark` (no active run required). |
| `clear` | Destructive. Read the branch name from `.sindri/current/sindri.md` JSON frontmatter **before** deleting anything. Prompt the user for confirmation (`y/N`). If confirmed: `rm -rf .sindri/current/ && git checkout main && git branch -D <branch>`. If not confirmed: print `aborted.` and stop. |
| anything else | Treat as a goal statement. If `.sindri/current/` exists, print a resume/abandon prompt and **do not** start a new run. Otherwise, invoke skill `sindri-start` with the goal statement. |

## Invariants

- **One run per repo.** Never start a new run while `.sindri/current/` exists.
- **Never mutate git state directly in this command.** Skills own that (except the `clear` branch delete, which is user-confirmed).
- **`status` must always be fast.** It reads files, nothing else.
- **`clear` always confirms first.** No silent deletion.

## After dispatch

For `status` and `stop`, you return to the user directly. For `scaffold-benchmark`, `clear`, and a new-goal invocation, control passes to the relevant skill and that skill produces the user-visible output.

For a brand-new goal, after `sindri-start` returns, sindri is running autonomously — `ScheduleWakeup` has been set. The orchestrator skill (`sindri-loop`) runs on every wakeup without further user action until termination. On clean termination with ≥1 kept commit, the loop auto-invokes `sindri-finalize` to push the branch and open the PR.

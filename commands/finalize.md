---
description: ADVANCED/DEBUG. Force a push + PR from the current run's kept commits. Finalize is normally automatic.
---

# /sindri:finalize — manual finalize (advanced)

**Normally automatic.** `sindri-finalize` auto-fires when the loop terminates cleanly with ≥1 kept commit. Use this to force a PR from the current kept commits — e.g. after a manual `/sindri:stop`.

## Guards (run these in this command, before invoking the skill)

1. If `.sindri/current/` does not exist, print `sindri: no active run to finalize.` and stop.
2. Read the branch from `.sindri/current/sindri.md` frontmatter and count kept commits: `git log --oneline --grep "^kept:" | wc -l`. If `0`, print `sindri: nothing to finalize — 0 kept commits. Nothing to push or PR.` and stop.
3. Otherwise, invoke skill `sindri-finalize` (it generates the PR body, pushes the branch, opens the PR, and archives the run).

Note: a previously scheduled autonomous wakeup may still be pending. After a manual finalize archives the run, the next wakeup finds no active run and terminates harmlessly.

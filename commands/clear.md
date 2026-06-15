---
description: Abandon the current sindri run — destructive; deletes run state and the run branch.
---

# /sindri:clear — abandon the run

Destructive. Read the branch name from `.sindri/current/sindri.md` JSON frontmatter **before** deleting anything. Prompt the user for confirmation (`y/N`).

- If confirmed: `rm -rf .sindri/current/ && git checkout main && git branch -D <branch>`.
- If not confirmed: print `aborted.` and stop.

## Invariant

- **Always confirms first.** No silent deletion.

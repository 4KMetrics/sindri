---
name: sindri-finalize
description: Auto-invoked by sindri-loop on clean termination with ≥1 kept commit. Generates the PR body, pushes the branch, opens a PR via gh, surfaces the URL, and archives the current run. Never invoke manually.
tools: Bash, Read
---

# sindri-finalize — ship the run as a PR

You are the last skill in the lifecycle. You run only when the orchestrator has cleanly terminated AND at least one experiment was kept. Your job is fast (<30s), linear, and has no user interaction.

## Steps

### 1. Generate the PR body

```bash
python -m sindri generate-pr-body > .sindri/current/pr-body.md
```

The Python core renders the body from `sindri.md` frontmatter + `sindri.jsonl` history — goal, baseline → final, per-commit table, dead-ends, summary stats.

### 2. Push the branch

Read the branch name from `.sindri/current/sindri.md` JSON frontmatter (`branch:` field).

```bash
git push -u origin "<branch>"
```

If push fails (auth expired, remote missing, branch already on remote with divergent history):

- Print: *"sindri: HALTED during finalize. `git push` failed — <stderr>. State preserved. Re-run `/sindri` after fixing, and it will retry finalize from the same state."*
- STOP. Do not retry destructively. Do not delete or rewrite history.

### 3. Compose the PR title

Read the goal from `sindri.md` frontmatter. Derive a conventional-commit-style title:

- `reduce bundle_bytes by 15%` → `perf: reduce bundle_bytes (−15.2%)`
- `increase test coverage by 10%` → `test: increase coverage (+10.4%)`
- `reduce ci_seconds by 20%` → `perf: reduce CI time (−21.3%)`

Use the **actual** observed delta (from `current_best` vs `baseline`), not the target.

### 4. Open the PR

```bash
TITLE="<composed title>"
gh pr create \
  --base main \
  --head "<branch>" \
  --title "$TITLE" \
  --body-file .sindri/current/pr-body.md
```

If `gh pr create` fails:

- Print: *"sindri: branch pushed to origin, but PR creation failed — <stderr>. Open the PR manually with `gh pr create --base main --body-file .sindri/current/pr-body.md` or via the GitHub UI."*
- Do not halt finalize beyond this — the branch is pushed; user can recover.

### 5. Capture + surface the PR URL

```bash
PR_URL=$(gh pr view --json url -q .url)
```

Print a clean actionable block:

```
✓ sindri: PR opened — <PR_URL>

<N> kept commits, <M> reverted, final Δ<signed>%, target Δ<target>%
Baseline: <baseline value>  →  Final: <current_best value>
Wall clock: <human-readable duration>

Run archived: .sindri/archive/<date>-<slug>/
```

### 6. Archive the run

```bash
python -m sindri archive
```

This moves `.sindri/current/` → `.sindri/archive/<YYYY-MM-DD>-<goal-slug>/`. After this, a fresh `/sindri <goal>` is permitted.

## Anti-patterns

- **Never retry `git push` with `--force`.** Force-pushing a sindri branch destroys the history sindri wrote; the PR body would become inconsistent with origin.
- **Never amend or rewrite kept commits.** Each kept commit is part of the audit log. `git rebase -i` is off-limits in this skill.
- **Never archive before push + PR succeed.** Archive is the last step; it implies "this run is shippable and shipped."
- **Never delete the local branch.** The user may want to check it out. `/sindri clear` is the only path to branch deletion.

# Sindri — first-run dogfood

A ~15-minute guided walkthrough. Run this once in a throwaway git repo before pointing sindri at real code. It exercises every skill path (`sindri-start`, `sindri-scaffold-benchmark`, `sindri-loop`, `sindri-finalize`) and the subagent prompt in the same order they'll run on real goals — so any environment gap or skill-prose bug surfaces before you're locked into an overnight run.

## 0. Prereqs

You've completed the [install](../README.md#install). Specifically:

- `python -m sindri --version` prints `sindri <semver>` in the Python environment Claude Code launches processes from. (If it fails here, nothing else will work.)
- The plugin is symlinked into `~/.claude/plugins/sindri`.
- You've restarted Claude Code since installing.
- `gh auth status` is OK (needed for the finalize step).

## 1. Create the throwaway repo

```bash
mkdir -p /tmp/sindri-dogfood && cd /tmp/sindri-dogfood
git init -q
git config user.email "dogfood@example.com"
git config user.name "Dogfood"

mkdir -p src
for f in a b c d e; do printf 'x = 1\n%.0s' {1..10} > "src/${f}.py"; done

echo '.sindri/' > .gitignore
git add -A && git commit -q -m "seed"
```

The repo now has 5 Python files with 10 lines each — 50 non-blank lines total. The benchmark we'll scaffold counts non-blank lines in `src/**/*.py`. Deleting files is the canonical "candidate that improves the metric."

## 2. Point a GitHub remote at it (optional, skip if you don't want finalize to push)

Skip this step unless you want to exercise `sindri-finalize` with a real PR. If you do, create an empty private repo on GitHub (e.g. `your-user/sindri-dogfood`), then:

```bash
gh repo create your-user/sindri-dogfood --private --source=. --remote=origin
git push -u origin main
```

Without a remote, the dogfood still exercises every skill path except the `git push` + `gh pr create` at the very end — finalize will halt cleanly.

## 3. Launch Claude Code in this repo

```bash
cd /tmp/sindri-dogfood
claude
```

You want Claude Code to see `/tmp/sindri-dogfood` as its cwd so sindri's file paths resolve correctly.

## 4. Scaffold the benchmark

```
/sindri scaffold-benchmark
```

Walk through the `sindri-scaffold-benchmark` skill. When it asks how to measure, reply in natural language:

> *"Count all non-blank lines across `src/**/*.py` and emit `METRIC lines=<total>`."*

Accept the generated `.claude/scripts/sindri/benchmark.py`. Verify it's executable and prints a METRIC line:

```bash
python .claude/scripts/sindri/benchmark.py
# Expect: METRIC lines=50
```

Commit it:

```bash
git add .claude/scripts/sindri/benchmark.py
git commit -q -m "chore: add sindri benchmark"
```

**Watch for:** the skill should never ask you to write or edit Python. If it does, that's a skill-prose bug worth filing. If the script prints the METRIC line on stderr instead of stdout, the orchestrator won't parse it — regenerate.

## 5. Start an actual run

```
/sindri reduce lines by 40%
```

`sindri-start` pre-flight should:

1. Succeed on `python -m sindri --version` (package installed).
2. Succeed on `python -m sindri status` (no active run).
3. Detect `.sindri/` is already in `.gitignore` and move on silently.
4. See a clean tree and proceed.
5. Warn only if `gh` isn't authenticated.

Then it should:

- Parse the goal as `{reduce, lines, 40}`.
- Scan the repo and propose a pool (likely 3–5 candidates like "delete `src/<file>.py`"). It may be short — the repo is tiny. Accept *"approved"* on whatever it proposes.
- Call `python -m sindri init` with your approved pool.
- Create branch `sindri/reduce-lines-40pct`.
- Print the "run started" summary with a baseline of 50 and a target of 30.
- `ScheduleWakeup` to trigger the orchestrator in ~60s.

**Watch for:**

- Wrong verb handling — if you typed `cut lines by 40%`, the skill should normalize to `reduce` before calling `init`. If it passes `cut` verbatim, `init` will reject it. (This is the normalization rule added to `sindri-start` specifically.)
- Baseline should print as a scalar, not an object.
- The branch should actually get created (`git branch --show-current` → `sindri/reduce-lines-40pct`).

## 6. Let the loop run — or simulate

If you wait ~60s, the orchestrator wakeup fires and dispatches the first experiment subagent. It'll apply a candidate (likely deleting a source file), run the benchmark, and return JSON. The orchestrator commits or reverts.

If you don't want to wait, run `/sindri status` every minute. You should see kept/reverted counts increment.

Inspect state files any time:

```bash
cat .sindri/current/sindri.md | head -50     # frontmatter + pool status
tail -5 .sindri/current/sindri.jsonl          # event log
git log --oneline sindri/reduce-lines-40pct   # kept commits
```

**Watch for:**

- Each kept commit should be `kept: <candidate name> (Δ<signed>)`.
- The `.sindri/` dir should NOT appear in `git log` — if it does, the `.gitignore` check failed.
- The jsonl should grow one `experiment` record per wakeup (plus initial `session_start`, `baseline`, `baseline_complete`).

## 7. Finalize

Two ways to terminate:

- **Natural:** wait for the target (metric ≤ 30) or pool exhaustion. If ≥1 kept commit, sindri-finalize auto-fires on the next wakeup.
- **Manual halt:** `/sindri stop` — touches `.sindri/current/HALT`. The next wakeup terminates with reason `halted_by_user`; finalize fires only if at least one kept commit exists.

Finalize should:

1. Run `python -m sindri generate-pr-body` into `.sindri/current/pr-body.md`.
2. `git push -u origin sindri/reduce-lines-40pct` (halts here cleanly if no remote — expected for the no-remote path).
3. `gh pr create ...` (requires the remote + `gh` auth).
4. Print the PR URL.
5. Run `python -m sindri archive` — `.sindri/current/` moves to `.sindri/archive/<date>-<slug>/`.

**Watch for:**

- PR title should have the **actual** observed delta, not the target.
- After archive, `python -m sindri status` should report "no active run" — a fresh `/sindri <goal>` should now be permitted.

## 8. Clean up

```bash
rm -rf /tmp/sindri-dogfood
```

If you pushed to a GitHub remote: `gh repo delete your-user/sindri-dogfood --yes`.

## What to file as bugs

Anything in the **Watch for** sections that didn't behave as described. Open an issue with:

- Which step failed.
- What the skill/CLI actually did (paste `sindri.jsonl` tail + `git log`).
- Your environment: `python --version`, `gh --version`, `git --version`, Claude Code version.

## Next steps after a clean dogfood run

Point sindri at a real repo. Start with a goal you believe is achievable in <1 hour of wall clock (small pool, fast benchmark) before trying an overnight run on a 50-MB bundle or a 20-minute CI pipeline. Sindri is bounded — but your first real run should be a short feedback loop, not a marathon.

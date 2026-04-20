---
name: sindri-start
description: Interactive, one-shot scaffolding for a new sindri optimization run. Parses goal, ensures benchmark.py exists, scans repo for candidates, gets pool approval, calls sindri init (which creates the branch, runs baseline, seeds state), and schedules the orchestrator. Use when the /sindri slash command receives a new goal statement.
tools: Bash, Read, Write, Edit, Glob, Grep
---

# sindri-start — initialize a new optimization run

You are the interactive scaffolder. Your job is to go from *"user typed a goal"* to *"the autonomous orchestrator has been scheduled and sindri.md exists on disk"*. You run **once** per run. You must be rigorous about validation and friendly about explanation — the user is trusting you to set up an overnight autonomous loop.

## Pre-flight (fail fast)

1. Run `python -m sindri status`. If it reports an active run, STOP — print the current run's goal and ask: *"There's already an active run for `<existing goal>`. Continue it with `/sindri` (orchestrator will resume), or abandon with `/sindri clear` and start fresh."* Do not proceed.
2. Run `git status --porcelain`. If the working tree is dirty, STOP — print: *"Working tree has uncommitted changes. Commit or stash before starting a sindri run so the baseline is reproducible."* Do not proceed.
3. Run `gh auth status`. If unauthenticated, warn: *"`gh` is not authenticated. Sindri will still run experiments, but `sindri-finalize` will fail to open a PR at the end. Run `gh auth login` now, or continue without auto-PR."* Continue only if the user acknowledges.

## 1. Parse the goal

Parse `$GOAL_STATEMENT` (the argument after `/sindri`) into three fields:

- `metric_name` — snake_case identifier (e.g., `bundle_bytes`, `ci_seconds`, `p95_latency_ms`)
- `direction` — `reduce` or `increase`
- `target_pct` — a percentage change (integer)

Accepted shapes (the only verbs the downstream CLI accepts are `reduce` and `increase`):

- `reduce bundle_bytes by 15%` → `{reduce, bundle_bytes, 15}`
- `increase test_coverage by 10%` → `{increase, test_coverage, 10}`
- `reduce ci_seconds by 25%` → `{reduce, ci_seconds, 25}`

If the user phrases it differently (e.g., "cut X by N%", "shrink Y"), **normalize** to one of the two verbs above and confirm with the user before continuing — do not pass the raw input to `sindri init`, whose regex will reject anything that doesn't start with `reduce` or `increase`.

If you can't parse it confidently, print **three concrete examples** and ask the user to rephrase. Do not guess.

## 2. Ensure `benchmark.py` exists and works

Check `.claude/scripts/sindri/benchmark.py`:

- **Missing** → invoke skill `sindri-scaffold-benchmark` as a sub-flow, passing the parsed `metric_name` and goal text. Wait for it to complete. Do not proceed until the file exists.
- **Exists** → run `python -m sindri validate-benchmark --expected <metric_name>`. If it fails (non-zero exit, no `METRIC <metric_name>=<number>` line, or wrong metric name), print the error and invoke `sindri-scaffold-benchmark` in *repair* mode.

## 3. Scan for candidates

Read the following (whichever exist; skip what doesn't):

- `package.json`, `pnpm-lock.yaml` / `package-lock.json` / `yarn.lock` / `bun.lock`
- `vite.config.*`, `webpack.config.*`, `next.config.*`, `rollup.config.*`, `esbuild.config.*`, `tsconfig.json`
- `pyproject.toml`, `requirements*.txt`, `poetry.lock`, `uv.lock`
- `Cargo.toml`, `go.mod`, `pom.xml`, `build.gradle*`
- `.github/workflows/*.yml` (if CI time is the metric)
- Top 5 biggest files under `src/`

From what you see, propose **10–30 candidates** — concrete, actionable changes, each with a **rough** expected impact percentage. Examples for `reduce bundle_bytes`:

```
- Replace moment (71 KB) with date-fns (~9 KB tree-shaken)  — expected −7%
- Tree-shake lodash imports → per-method imports              — expected −3%
- Dynamic import heavy routes (admin, reports)                — expected −12%
- Remove unused polyfills (core-js/modules/*)                 — expected −2%
- Compress svg assets via imagemin                            — expected −1%
...
```

Rules:

- One line per candidate (dense — the user must scan fast).
- Expected impact is a guess; do not over-sell.
- Prefer concrete ("replace moment with date-fns") over vague ("optimize dependencies").
- If you have fewer than 10 after scanning, be honest: *"I found 6 candidates. Adding more would be speculative. OK to proceed?"*

## 4. Present the pool; accept edits

Print the pool in a fenced block. Then:

> *"Strike (remove), edit, or add candidates. Reply with the revised list, or 'approved' to proceed."*

Loop on edits until the user approves. When approved, continue.

## 5. Build the state files + branch + baseline via CLI

Serialize the approved pool to a JSON array:

```json
[
  {"id": 1, "name": "Replace moment with date-fns", "expected_impact_pct": -7, "files": ["package.json","src/utils/date.ts"]},
  {"id": 2, "name": "Tree-shake lodash imports", "expected_impact_pct": -3, "files": []}
]
```

Then run (using the **normalized** goal string, always in `reduce|increase <metric> by <N>%` form — never the raw user input):

```bash
python -m sindri init \
  --goal "<normalized goal — e.g. 'reduce bundle_bytes by 15%'>" \
  --pool-json "$POOL_JSON" \
  --script .claude/scripts/sindri/benchmark.py
```

`init` performs **all** of the following in one call:

- Creates the branch `sindri/<slug>` from the current HEAD (fails if it already exists).
- Writes `.sindri/current/sindri.md` with JSON frontmatter (full state) + markdown body (pool as checkboxes).
- Runs the benchmark 3× to compute baseline mean + noise_floor.
- Writes `sindri.jsonl` with `session_start`, three `baseline` records (run 1 = warmup), and `baseline_complete`.
- Auto-detects mode (`local` vs `remote`) from script content + observed CV.
- Returns JSON: `{"ok": true, "branch": "...", "baseline": ..., "noise_floor": ..., "mode": "..."}`.

If init fails (branch exists, benchmark emits no METRIC line, benchmark crashes): surface the stderr verbatim and halt. The user must resolve before `/sindri` can proceed.

## 6. Schedule the orchestrator

Use the `ScheduleWakeup` tool:

```
ScheduleWakeup(
  delay=60,
  prompt="Resume sindri-loop orchestrator. Read state from .sindri/current/ and run one wakeup cycle."
)
```

## 7. Report to the user

Print a concise summary:

> *"sindri: run started.*
> *Goal: reduce bundle_bytes by 15% (baseline 842 KB → target ≤ 715.7 KB, noise floor ±3 KB)*
> *Branch: sindri/reduce-bundle-bytes-15pct*
> *Mode: local*
> *Pool: 18 candidates approved*
> *Orchestrator wakes in 60s. Check in with `/sindri status`. Halt with `/sindri stop`."*

You are done. Control returns to the slash command, which returns to the user. The orchestrator (sindri-loop) takes over on the next wakeup.

## Anti-patterns

- **Do not** proceed past any pre-flight failure. The run must start from a known-good state.
- **Do not** skip the pool-approval step, even if the user seems to want speed. The pool is the contract for what sindri will try.
- **Do not** commit the baseline to git. Baseline lives in state files only.
- **Do not** ScheduleWakeup before `sindri init` returns `ok: true`.

---
title: Sindri — Design Spec
date: 2026-04-19
status: draft
version: 0.1
authors:
  - Nimesh Kumar (architect)
  - Claude Opus 4.7 (1M context) (co-author)
inspirations:
  - https://github.com/karpathy/autoresearch
  - https://github.com/davebcn87/pi-autoresearch
---

## Table of Contents

- [1. Executive summary](#1-executive-summary)
- [2. Context & motivation](#2-context--motivation)
- [3. Goals and non-goals](#3-goals-and-non-goals)
  - [3.1 Goals (v1)](#31-goals-v1)
  - [3.2 Explicit non-goals (v1)](#32-explicit-non-goals-v1)
- [4. Users and workflows](#4-users-and-workflows)
  - [4.1 Primary persona](#41-primary-persona)
  - [4.2 Primary workflow](#42-primary-workflow)
  - [4.3 User touch points, explicit](#43-user-touch-points-explicit)
- [5. Architecture](#5-architecture)
  - [5.1 Two-layer shape](#51-two-layer-shape)
  - [5.2 Three cooperating agents](#52-three-cooperating-agents)
  - [5.3 Key architectural invariants](#53-key-architectural-invariants)
- [6. Components — what ships in the plugin](#6-components--what-ships-in-the-plugin)
  - [6.1 Slash command: `/sindri`](#61-slash-command-sindri)
  - [6.2 Skill: `sindri-start`](#62-skill-sindri-start)
  - [6.3 Skill: `sindri-scaffold-benchmark`](#63-skill-sindri-scaffold-benchmark)
  - [6.4 Skill: `sindri-loop` (orchestrator)](#64-skill-sindri-loop-orchestrator)
  - [6.5 Skill: `sindri-finalize` (auto-invoked on success)](#65-skill-sindri-finalize-auto-invoked-on-success)
  - [6.6 Experiment subagent prompt template](#66-experiment-subagent-prompt-template)
  - [6.7 Python core package (`src/sindri/`)](#67-python-core-package-srcsindri)
- [7. Data flow — the complete lifecycle](#7-data-flow--the-complete-lifecycle)
  - [7.1 Phase 1: Initialization](#71-phase-1-initialization-sindri-start-interactive-15-min)
  - [7.2 Phase 2: The loop](#72-phase-2-the-loop-sindri-loop-autonomous-minutes-to-hours)
  - [7.3 Phase 3: Termination](#73-phase-3-termination)
  - [7.4 Phase 4: Finalize (automatic, <30s)](#74-phase-4-finalize-automatic-30s)
- [8. State files — on-disk layout](#8-state-files--on-disk-layout)
  - [8.1 Repo layout](#81-repo-layout)
  - [8.2 `sindri.md` schema](#82-sindrimd-schema)
  - [8.3 `sindri.jsonl` schema](#83-sindrijsonl-schema)
- [9. Python core — module-by-module](#9-python-core--module-by-module)
  - [9.1 Package layout](#91-package-layout)
  - [9.2 Key APIs](#92-key-apis-test-first-so-these-are-what-the-tests-demand)
- [10. Error handling & guardrails](#10-error-handling--guardrails)
  - [10.1 Error taxonomy](#101-error-taxonomy)
  - [10.2 Guardrails](#102-guardrails-defaults-overridable-in-sindrimd)
  - [10.3 Explicit non-behaviors](#103-explicit-non-behaviors)
- [11. Testing strategy (TDD)](#11-testing-strategy-tdd)
  - [11.1 Test-first discipline](#111-test-first-discipline)
  - [11.2 Test layers](#112-test-layers)
  - [11.3 Specific test cases worth naming now](#113-specific-test-cases-worth-naming-now)
  - [11.4 Continuous integration](#114-continuous-integration)
  - [11.5 Explicit non-tests](#115-explicit-non-tests)
- [12. v1 scope boundaries](#12-v1-scope-boundaries)
  - [12.1 In v1](#121-in-v1)
  - [12.2 Deferred to v2](#122-deferred-to-v2)
  - [12.3 Open risks](#123-open-risks-flagged-for-implementation-phase)
- [13. References](#13-references)
- [14. Appendix A: sample run walkthrough](#14-appendix-a-sample-run-walkthrough)

---

## 1. Executive summary

**Sindri is a Claude Code plugin that runs bounded, target-driven optimization loops against any metric a user can measure deterministically.**

The user states a goal (e.g. *"reduce bundle_bytes by 15%"*). Sindri drafts a pool of candidate optimizations from a repo scan, presents the pool for user approval, establishes a baseline + noise floor, and then autonomously iterates: for each candidate it dispatches a fresh Claude subagent with a clean context, applies the change, runs a user-owned benchmark script, decides to keep or revert based on confident improvement over the noise floor, and moves to the next candidate. On clean termination (target hit or pool exhausted) with at least one kept win, sindri automatically pushes the branch and opens a single PR whose description narrates the entire run.

The name comes from Norse mythology: Sindri was the dwarf smith who forged Mjölnir by iterating under adversity — each strike tested, kept only if it survived. That is the loop's invariant: monotone improvement, never backward.

## 2. Context & motivation

In late-model LLM research, [karpathy/autoresearch](https://github.com/karpathy/autoresearch) established the pattern: give an AI agent one file to edit (`train.py`), one benchmark (5-minute training run measuring `val_bpb`), and let it run overnight. [davebcn87/pi-autoresearch](https://github.com/davebcn87/pi-autoresearch) generalized that pattern to arbitrary optimization domains — bundle size, test speed, build time, Lighthouse score — for the [pi.dev](https://pi.dev) agent platform.

Sindri adapts that generalized pattern to **Claude Code**, respecting three differences:

1. Claude Code's loop primitive (`ScheduleWakeup` / `/loop`-dynamic) is paced, not tight-loop re-injection. That's a better fit for benchmarks whose reps take seconds-to-minutes rather than milliseconds.
2. Claude Code's subagent model (`Task` tool) allows clean-context isolation per experiment — superior to the single-session model pi uses. Context bleed across experiments is an insidious correctness problem; we eliminate it.
3. Claude Code users want finished PRs, not raw branches. Sindri owns the full path from goal to mergeable PR.

## 3. Goals and non-goals

### 3.1 Goals (v1)

1. **Target-driven bounded loop.** User states a goal + target. Loop terminates when target is hit, pool is exhausted, or a guardrail fires.
2. **Domain-agnostic.** Any metric the user can measure with a Python script is a valid goal. Bundle size, test time, CI latency, model loss — all the same to sindri.
3. **Clean-context experiments.** Every candidate is evaluated by a fresh subagent with no memory of prior experiments. No context bleed, no bias from earlier failures.
4. **Trustworthy keep/revert decisions.** A kept change is always a confident, above-noise improvement. Never a lucky single run.
5. **Multi-step benchmarks supported out of the box.** The user can measure GitHub Actions latency, staging-environment metrics, or anything else that requires orchestration — sindri invokes their script and reads the final `METRIC` line.
6. **Cost-aware.** For expensive benchmarks (remote services, rate-limited APIs, paid CI minutes), sindri uses a conservative single-rep-per-experiment policy with a well-characterized baseline instead of burning through the budget on adaptive multi-rep.
7. **Finalized as a reviewable PR.** On successful termination, sindri pushes the branch and opens one PR whose body captures the full run narrative — not fragmented into N micro-branches.
8. **Error transparency.** Structural failures halt the loop and surface in the Claude conversation — not silently in a log.
9. **TDD-built.** Every Python module is designed by tests first.

### 3.2 Explicit non-goals (v1)

- **Optimizing model behavior.** Sindri trusts Claude to make reasonable edits. It does not benchmark Claude itself.
- **Benchmark authoring beyond scaffolding help.** Users who need exotic benchmarks (multi-cluster performance aggregation, proprietary observability pipelines) write their own `benchmark.py`. Sindri does not bundle a library of benchmark templates.
- **Branch splitting into multiple PRs.** One run = one branch = one PR. File-disjoint grouping across commits is out of scope.
- **Concurrent runs in the same repo.** Explicitly single-session, single-active-run.
- **Cross-platform exotica.** Linux/macOS with POSIX git ≥ 2.30 and the `gh` CLI is the supported environment. Windows not a v1 target.
- **A custom dashboard / widget.** Pi's inline editor widget has no clean equivalent in Claude Code. Progress is visible via `/sindri status`, `sindri.md`, and `sindri.jsonl`. No GUI in v1.
- **Automatic PR merging.** Sindri opens PRs. The user merges them.

## 4. Users and workflows

### 4.1 Primary persona

**The architect-developer.** Someone who thinks in systems and directs AI to implement, who cares about PR-review discipline and branch hygiene, and who runs sindri against real projects (Kubernetes Helm charts, TypeScript monorepos, Terraform modules, ML training code). They write the `benchmark.py` themselves (or have Claude help) and hand off the rest.

### 4.2 Primary workflow

1. User has an optimization target in mind. They already know what they want to measure.
2. (Optional) User has a separate conversation with Claude to draft or refine `benchmark.py`. Sindri does not require this conversation — it's just a way to use Claude for script-writing outside the loop.
3. User invokes `/sindri <goal>` in the project repo.
4. Sindri validates or scaffolds `benchmark.py`, scans the repo, drafts ~10–30 candidates, presents them.
5. User approves / edits / strikes from the pool (≤1 minute).
6. Sindri runs a baseline, establishes noise floor, starts the autonomous loop.
7. User walks away.
8. Hours later, sindri has either (a) opened a PR, (b) halted cleanly with no wins + told the user in chat, or (c) halted on an error + surfaced the error in chat.
9. User reviews the PR. Merges, adjusts, or closes.

### 4.3 User touch points, explicit

| # | Moment | Action |
|---|---|---|
| 1 | Goal statement | Types `/sindri <goal>` |
| 2 | Benchmark scaffolding (only if `benchmark.py` missing) | Confirms/refines sindri's proposed benchmark in natural language |
| 3 | Pool approval | Strikes/edits/accepts the drafted candidate list |
| 4 | (Walks away) | — |
| 5 | Review PR | `gh pr view` or browser |

That's it. No `/sindri finalize` to remember. No approval gate mid-loop. No decisions buried in the sub-loop.

## 5. Architecture

### 5.1 Two-layer shape

Sindri has two cooperating but distinct layers. Clean separation of concerns is central to the design.

| Layer | Substrate | Owns |
|---|---|---|
| **Reasoning layer** | Markdown skills + slash commands | Pool drafting from repo scan. Subagent brief authoring. Scaffolding conversation. PR body narrative. Error explanation. Anything requiring judgment. |
| **Deterministic core** | Python 3.10+ (pyproject-based package) | Noise floor math. Confidence computation. Metric parsing. JSONL append/read. State file schema validation. Git operations. Mode detection. Termination predicates. Pool ordering. |

The skills invoke the Python core via the `Bash` tool: `python -m sindri <subcommand>` returning JSON on stdout.

**Why this split:** computation that must be correct (statistics, schema, git) belongs in typed Python with pytest coverage. Decisions that require Claude's reasoning (*is this a reasonable optimization? how do I describe what I did?*) belong in skills where Claude's inference is the feature, not a bug.

### 5.2 Three cooperating agents

```text
┌─────────────────────────────────────────────────────────────────────┐
│                        User (in Claude Code)                         │
│   issues /sindri <goal>, approves pool, walks away, reviews PR       │
└────────────────────────────┬────────────────────────────────────────┘
                             │
             ┌───────────────┴────────────────┐
             │                                │
             ▼                                ▼
  ┌───────────────────────┐        ┌─────────────────────────┐
  │   sindri-start skill  │        │   sindri-scaffold-      │
  │   (interactive, once) │  and/  │   benchmark skill       │
  │   - scan repo         │   or   │   (proposes command     │
  │   - draft pool        │        │    from repo scan; user │
  │   - get approval      │        │    confirms in NL)      │
  │   - run baseline      │        └─────────────────────────┘
  │   - schedule orch     │
  └───────────┬───────────┘
              │
              ▼
  ┌───────────────────────┐          ┌─────────────────────────┐
  │   sindri-loop skill   │          │   experiment subagent   │
  │   (orchestrator,      │  ─ Task→ │   (fresh context,       │
  │    per-wakeup)        │          │    one-shot):           │
  │                       │  ← JSON  │     apply change        │
  │   - read state files  │          │     run benchmark N×    │
  │   - pick next cand.   │          │     return structured   │
  │   - dispatch subagent │          │     result              │
  │   - commit or reset   │          └─────────────────────────┘
  │   - ScheduleWakeup    │
  │   - terminate & auto- │
  │     finalize OR halt  │
  └───────────┬───────────┘
              │ (clean term + ≥1 kept)
              ▼
  ┌───────────────────────┐
  │  sindri-finalize      │
  │  (invoked by          │
  │   orchestrator, auto) │
  │                       │
  │  - generate PR body   │
  │  - git push           │
  │  - gh pr create       │
  │  - surface PR URL     │
  └───────────────────────┘
```

### 5.3 Key architectural invariants

1. **State files are the source of truth.** The orchestrator never trusts its own memory. Every wakeup re-reads `sindri.md` + `sindri.jsonl` from disk.
2. **The orchestrator's per-wakeup context is small.** It reads two files, makes one `Task` call, does a git operation, writes two files, schedules a wakeup. Autocompaction is a non-issue because there's nothing meaningful to compact.
3. **Every experiment starts from a clean subagent.** No context bleed. This is non-negotiable and is the primary reason we chose subagent-per-experiment over single-agent-looping.
4. **Git is the audit log for kept work.** One commit per kept experiment, with the metric delta in the commit message. `sindri.jsonl` is the audit log for the full history (kept + reverted + errored).
5. **The forge runs one way.** A kept commit is never un-kept by later events. Later failures cannot invalidate earlier wins. Monotone improvement is the whole point: each strike either shapes the artifact or returns to the fire.
6. **One active run per repo.** `.sindri/current/` is singleton. A new `/sindri <goal>` invocation when `current/` exists is rejected — user must resolve the existing run first.

## 6. Components — what ships in the plugin

Seven artifacts, each with a single, well-bounded purpose.

### 6.1 Slash command: `/sindri`

The only user-facing entry point. Subcommands:

| Invocation | Behavior |
|---|---|
| `/sindri <goal statement>` | Start a new run, or resume if `.sindri/current/` exists. |
| `/sindri status` | Print current run summary: experiments run, kept, reverted, target delta, confidence, ETA, current candidate. Zero-cost read from state files. |
| `/sindri stop` | Graceful halt. Orchestrator finishes the in-flight experiment, cancels its `ScheduleWakeup`, writes terminated sentinel to `sindri.jsonl`. Does not auto-finalize. |
| `/sindri scaffold-benchmark` | Standalone invocation of the scaffolder, useful for regenerating or tweaking `benchmark.py` outside a live run. |
| `/sindri clear` | Destructive: deletes `.sindri/current/`, deletes the local `sindri/<goal-slug>` branch. Prompts for confirmation. |

### 6.2 Skill: `sindri-start`

Interactive, one-shot scaffolding for a new run.

**Inputs:** user's goal statement (parsed), repo state.

**Behavior:**
1. Parse goal → `{metric_name, direction ∈ {reduce,increase}, target_pct}`. Reject malformed goals with examples.
2. Check `.claude/scripts/sindri/benchmark.py`. If missing, invoke `sindri-scaffold-benchmark` as a sub-flow; do not proceed until it exists.
3. Validate benchmark: run it once, parse `METRIC <name>=<number>` from the last output line, ensure `<name>` matches `metric_name` from goal.
4. Scan repo for candidates: read `package.json`, build configs, framework specifics, detect known optimization patterns. Draft a pool of 10–30 candidates with rough expected impact.
5. Write `.sindri/current/sindri.md` with goal/target/pool (status: `pending`)/baseline: `TBD`.
6. Present pool to user; accept edits/strikes/additions.
7. `git checkout -b sindri/<goal-slug>` from current HEAD.
8. Run baseline 3× (for noise floor). Write noise floor to `sindri.md`.
9. `ScheduleWakeup(delay=60s)` on the orchestrator skill (`sindri-loop`).
10. Return a status summary to the user.

### 6.3 Skill: `sindri-scaffold-benchmark`

Conversational helper that writes `benchmark.py` — without ever asking the user for Python or shell syntax.

**Behavior:**
1. Scan repo: detect build tooling (vite/webpack/next/tsc/esbuild/rollup/hardhat/cargo/maven/etc.), lockfile → package manager (`pnpm`/`npm`/`yarn`/`bun`/`uv`/`poetry`), output directory (`dist/`/`build/`/`out/`/`.next/`), existing CI scripts, relevant binaries (`gh` if GHA, `aws`/`gcloud` if cloud).
2. Propose a measurement approach based on evidence + goal's metric name. Example: *"I see this is a Vite + pnpm project with output in `dist/`. Proposed benchmark: run `pnpm build`, then measure byte size of `dist/`. Outputs: `METRIC bundle_bytes=<number>`."*
3. Accept refinements in natural language ("use npm not pnpm", "measure gzipped", "skip the build"). Translate the user's intent into Python code. Iterate until the user accepts.
4. Optionally propose `checks.py` (tests/lint gate). User can skip.
5. Write the final `benchmark.py` as an executable Python script — proper shebang (`#!/usr/bin/env python3`), docstring, `subprocess` calls for external commands, clear `if __name__ == "__main__"` block, and a final `print(f"METRIC name={value}")` line.
6. Run it once. If it fails or doesn't emit a valid `METRIC` line, surface the error and iterate.

**Fallback for unscoped measurements:** if sindri cannot infer (exotic stacks, multi-cluster performance, proprietary observability), ask in natural language ("describe how you'd measure this") and reason about the answer. Never demand code from the user.

**Multi-step benchmarks** (GHA latency, staging deploys, polling external APIs) are in scope — the scaffolder knows patterns for `gh workflow run`, polling loops, and simple aggregation. For very exotic cases the scaffolder hands off: "this is beyond what I can generate; here's a starter template, customize as needed."

### 6.4 Skill: `sindri-loop` (orchestrator)

The main skill invoked on every wakeup during an active run. Not user-facing in the slash command list; discoverable via the plugin docs.

**Per-wakeup behavior (strictly single-pass, always these steps in this order):**
1. Read `.sindri/current/sindri.md` and `.sindri/current/sindri.jsonl`. Compute state.
2. **Termination check.** If the state meets any termination predicate (target_hit / pool_empty / max_experiments / max_wall_clock / max_reverts_in_a_row / halted_by_user), short-circuit:
   - Append `{"event": "terminated", "reason": ..., "final_metric": ..., "kept": N, "reverted": M}` to `sindri.jsonl`.
   - If `reason ∈ clean_termination_reasons` and kept ≥ 1 → **auto-invoke `sindri-finalize`**. Otherwise write human-readable summary to chat.
   - **Do not schedule another wakeup.** Loop ends.
3. **Pre-flight git check.** If working tree is dirty (leftover from interrupted experiment) → `git reset --hard HEAD`. Defensive.
4. Pick next candidate from the pool (highest remaining expected-impact first; configurable).
5. Dispatch experiment subagent via `Task` tool with the experiment-subagent prompt template (see 6.6).
6. Receive result. Validate schema via pydantic. If malformed: treat as `status: errored`, follow retry-then-dead-end logic.
7. Act on result:
   - `status: improved` → `git add -A && git commit -m "kept: <candidate short name> (<delta>)"`. Update `current_best_metric`. Mark pool entry `kept`.
   - `status: regressed` → `git reset --hard HEAD`. Mark pool entry `reverted`.
   - `status: inconclusive` → `git reset --hard HEAD`. Mark pool entry `reverted`. (We only keep confident wins.)
   - `status: check_failed` → `git reset --hard HEAD`. Mark pool entry `check_failed` — no retry.
   - `status: errored` → `git reset --hard HEAD`. Increment retry count; if retries ≤ 1, leave pool entry `pending` for next wakeup; if > 1, mark `errored`. Check for structural halt (see error handling).
   - `status: timeout` → `git reset --hard HEAD`. Increment timeout count. If 3 consecutive timeouts → structural halt.
8. Append result to `.sindri/current/sindri.jsonl`.
9. Update `.sindri/current/sindri.md` (move candidate between pending/kept/reverted/dead-ends sections; update summary table).
10. Schedule next wakeup: `ScheduleWakeup(delay=60s, prompt=<resume prompt>)`.

### 6.5 Skill: `sindri-finalize` (auto-invoked on success)

Not user-invokable by default. Fired by the orchestrator on clean termination with ≥1 kept commit.

**Behavior:**
1. Read `.sindri/current/sindri.md` + `.sindri/current/sindri.jsonl`.
2. Compute summary (baseline, final, delta%, experiments run, kept count, reverted count, wall-clock time).
3. Generate PR body via `python -m sindri generate-pr-body` (the Python core renders a rich markdown template from the jsonl).
4. `git push -u origin sindri/<goal-slug>`. If push fails, surface error in chat and halt (do not retry destructively).
5. `gh pr create --base main --title "<goal-derived title>" --body-file <generated>`.
6. Emit PR URL to chat in a clear, actionable block.
7. Move `.sindri/current/` → `.sindri/archive/<YYYY-MM-DD>-<goal-slug>/`.

### 6.6 Experiment subagent prompt template

Shipped as `prompts/experiment-subagent.md` within the plugin. Loaded by the orchestrator and passed to `Task`.

**Contract — what the orchestrator passes in:**

```json
{
  "candidate": {
    "id": 7,
    "name": "Replace moment with date-fns",
    "expected_impact_pct": -10,
    "affects": ["package.json", "src/utils/date.ts", "src/components/*"]
  },
  "benchmark_cmd": ".claude/scripts/sindri/benchmark.py",
  "checks_cmd": ".claude/scripts/sindri/checks.py",
  "metric": {"name": "bundle_bytes", "direction": "reduce"},
  "current_best": 720000,
  "noise_floor": 870,
  "mode": "local",
  "reps_policy": {"min": 1, "max": 10, "adaptive": true, "confidence_threshold": 2.0},
  "timeout_seconds": 1800
}
```

**Contract — what the subagent must return (JSON on stdout, matching pydantic schema):**

```json
{
  "metric_value": 719218,
  "reps_used": 3,
  "confidence_ratio": 4.2,
  "status": "improved",
  "files_modified": ["package.json", "src/utils/date.ts", "pnpm-lock.yaml"],
  "notes": "Swapped moment for date-fns; updated 4 call sites. Bundle drop aligns with dep size removal."
}
```

Valid `status` values: `improved`, `regressed`, `inconclusive`, `check_failed`, `errored`, `timeout`.

**Subagent must not:** commit, push, modify files outside the current working tree, write to `.sindri/` directly. Git state changes are the orchestrator's exclusive responsibility.

### 6.7 Python core package (`src/sindri/`)

Runtime dependency: `pydantic>=2.0,<3.0`. Nothing else beyond stdlib.

| Module | Responsibility |
|---|---|
| `sindri/cli.py` | argparse entry point exposed as `python -m sindri`. Dispatches to subcommands. Each subcommand reads from stdin (for JSON input) or args, writes JSON to stdout. |
| `sindri/core/state.py` | Typed read/write/append of `sindri.md` (structured YAML frontmatter + human-readable sections) and `sindri.jsonl` (pydantic models per line). |
| `sindri/core/noise.py` | Baseline stats: mean, std_dev, coefficient of variation, noise_floor (std_dev, discarding warmup run 1). Confidence computation: `confidence_ratio(delta, floor) = abs(delta) / max(floor, eps)`. |
| `sindri/core/pool.py` | Ordering (default: remaining expected-impact descending). Termination predicates: target_hit, pool_empty, max_experiments, max_wall_clock, max_reverts_in_a_row, halted_by_user. |
| `sindri/core/git_ops.py` | Wrappers around `git` subprocess calls: current branch, clean-or-dirty check, create_branch, commit_with_message, reset_hard, delete_branch, push_with_upstream. |
| `sindri/core/metric.py` | Regex-based parsing of `METRIC <name>=<number>` from benchmark output. Handles scientific notation, integer, float. |
| `sindri/core/modes.py` | Local vs remote detection: script-content signal (keyword scan for `gh`/`curl`/`aws`/`gcloud`/`kubectl`/etc. with localhost-whitelist) + observed-noise signal (CV > 15% across baseline runs 2+). Either triggers remote. |
| `sindri/core/pr_body.py` | Renders the final PR markdown from `sindri.jsonl` + `sindri.md`. Structured: goal/target/result → commit-by-commit table → dead-ends → summary stats. |
| `sindri/core/validators.py` | Pydantic models for subagent result, jsonl line, sindri.md frontmatter. Schema drift fails fast. |
| `sindri/core/termination.py` | Clean decision table for whether auto-finalize should fire: `(terminated?, reason, kept_count) → {finalize, announce_no_wins, surface_error}`. |

**CLI subcommands (each maps to a `core/` module):**

```
python -m sindri init --goal "<str>"                 # sindri-start entry
python -m sindri validate-benchmark                  # runs benchmark.py, checks METRIC output
python -m sindri detect-mode                         # returns "local" | "remote"
python -m sindri read-state                          # returns current state as JSON
python -m sindri pick-next                           # picks next candidate, returns JSON
python -m sindri record-result                       # accepts JSON on stdin, appends jsonl + updates md
python -m sindri check-termination                   # returns {"terminated": bool, "reason": str|null, "auto_finalize": bool}
python -m sindri generate-pr-body                    # writes PR markdown to stdout
python -m sindri archive                             # moves current/ to archive/<date>-<slug>/
python -m sindri status                              # human-readable summary for /sindri status
```

## 7. Data flow — the complete lifecycle

### 7.1 Phase 1: Initialization (`sindri-start`, interactive, 1–5 min)

```
User: /sindri reduce bundle_bytes by 15%

Skill:
  parse goal → {metric: bundle_bytes, direction: reduce, target_pct: 15}

  check .claude/scripts/sindri/benchmark.py
    ├ EXISTS → validate it outputs METRIC bundle_bytes=... → ✓
    └ MISSING → invoke sindri-scaffold-benchmark
        ├ scan repo (package.json, lockfile, build tool, output dir)
        ├ PROPOSE "pnpm build && du -sb dist | awk '{print $1}'"
        ├ user refines in NL until accepting
        ├ generate .claude/scripts/sindri/benchmark.py
        ├ optionally scaffold checks.py
        └ run once; verify METRIC line

  scan repo → draft 10–30 candidates ordered by expected impact

  write .sindri/current/sindri.md:
    goal, target, pool (all status=pending), baseline=TBD

  PRESENT pool to user → accept edits

  git checkout -b sindri/reduce-bundle-size-15pct

  run benchmark.py 3× → compute noise_floor = std_dev (runs 2,3; discard run 1)

  write baseline + noise_floor to sindri.md

  detect mode (local vs remote) from script content + observed CV

  ScheduleWakeup(delay=60s, prompt="<resume sindri-loop>")

  return to user:
    "Baseline = 842 KB ±2 KB. Mode: local. Loop starting in 60s.
     /sindri status to check in, /sindri stop to halt."
```

### 7.2 Phase 2: The loop (`sindri-loop`, autonomous, minutes to hours)

One wakeup = one experiment end-to-end. Every wakeup is identical in structure.

```
Wakeup N:

  state = python -m sindri read-state
    → { pool: [...], kept: N, reverted: M, current_best, ... }

  term = python -m sindri check-termination
    → { terminated: false, ... }   OR   { terminated: true, reason, auto_finalize }

  if term.terminated:
    append {"event":"terminated", "reason": term.reason, ...} to sindri.jsonl
    if term.auto_finalize:
      invoke sindri-finalize
    else:
      announce in chat (no-wins or error summary)
    EXIT — no more ScheduleWakeup calls
    return

  git status --porcelain
  if dirty: git reset --hard HEAD       # belt-and-suspenders

  candidate = python -m sindri pick-next

  result = Task(
    subagent_type=experiment_subagent,
    prompt=experiment-subagent.md filled with candidate + benchmark params + current_best + noise_floor + mode
  )

  validate result schema via pydantic

  match result.status:
    "improved":    git add -A; git commit -m "kept: <name> (<delta>)"
    "regressed":   git reset --hard HEAD
    "inconclusive":git reset --hard HEAD
    "check_failed":git reset --hard HEAD
    "errored":     git reset --hard HEAD ; maybe retry
    "timeout":     git reset --hard HEAD ; count consecutive

  python -m sindri record-result < result.json
    (appends jsonl line, updates sindri.md pool status)

  check structural-halt conditions:
    - 3 consecutive timeouts → halt
    - max_reverts_in_a_row hit → halt
    - benchmark unparseable → halt

  ScheduleWakeup(delay=60s)
```

### 7.3 Phase 3: Termination

**Clean termination + ≥1 kept → auto-finalize.** The orchestrator's termination branch invokes `sindri-finalize` directly.

**Clean termination + 0 kept → no PR.** Surface in chat:
> sindri: terminated (pool exhausted). 0 kept experiments — 30 candidates tried, 27 regressed, 3 inconclusive. No PR created. Branch `sindri/reduce-bundle-size-15pct` deleted. Details in `.sindri/archive/<date>-<slug>/sindri.jsonl`.

Then: `git checkout main && git branch -D sindri/<goal-slug>` + `python -m sindri archive`.

**Halt on structural error → no PR.** Surface in chat:
> sindri: HALTED. Reason: <human-readable>. Details: <specifics>. State preserved in `.sindri/current/`. Fix the underlying issue and run `/sindri` to resume, or `/sindri clear` to abandon.

No ScheduleWakeup, no auto-delete of branch. User investigates.

### 7.4 Phase 4: Finalize (automatic, <30s)

```
sindri-finalize (called by orchestrator):

  python -m sindri generate-pr-body > .sindri/current/pr-body.md

  git push -u origin sindri/<goal-slug>
    → if fails (auth, remote missing): halt + surface error

  TITLE="perf: reduce bundle_bytes (−15.2%)"
  gh pr create --base main --title "$TITLE" --body-file .sindri/current/pr-body.md
    → if fails: halt + surface error (branch still pushed; user can recover)

  PR_URL=$(gh pr view --json url -q .url)

  surface to chat:
    "✓ sindri: PR #42 opened — <url>
     5 kept commits, 2 reverted, final −15.2% (target −15%)
     Run moved to .sindri/archive/<date>-<slug>/"

  python -m sindri archive
```

## 8. State files — on-disk layout

### 8.1 Repo layout

```
<repo-root>/
├── .gitignore                       # must contain: .sindri/
├── .claude/
│   └── scripts/
│       └── sindri/
│           ├── benchmark.py         # committed, team-shared
│           └── checks.py            # committed, team-shared (optional)
├── .sindri/                         # GITIGNORED (crucial)
│   ├── current/                     # singleton — only one active run
│   │   ├── sindri.md                # human-readable live doc
│   │   ├── sindri.jsonl             # append-only event log
│   │   └── pr-body.md               # generated at finalize, ephemeral
│   └── archive/
│       ├── 2026-04-18-reduce-bundle-size-15pct/
│       │   ├── sindri.md
│       │   └── sindri.jsonl
│       └── 2026-04-19-reduce-ci-time-20pct/
│           ├── sindri.md
│           └── sindri.jsonl
└── (your repo code, untouched)
```

### 8.2 `sindri.md` schema

Human-readable living document. YAML frontmatter + markdown body. Sindri edits this file on every wakeup; the user can also edit it (to adjust pool, cancel entries, etc.) — sindri re-reads on next wakeup.

```yaml
---
goal: "reduce bundle_bytes by 15%"
metric:
  name: bundle_bytes
  direction: reduce
  target_pct: 15
  target_value: 715700              # computed from baseline
baseline:
  value: 842000
  noise_floor: 870                  # std_dev of runs 2+
  samples: [843100, 841400, 842500]
mode: local                         # or remote
branch: sindri/reduce-bundle-size-15pct
started_at: 2026-04-19T10:23:45-07:00
guardrails:
  max_experiments: 30
  max_wall_clock_seconds: 28800
  max_reverts_in_a_row: 7
  timeout_per_experiment_seconds: 1800
  reps_policy:
    mode: local
    min: 1
    max: 10
    confidence_threshold: 2.0
---

# Goal

Reduce bundle_bytes by 15%. Baseline 842 KB → target ≤ 715.7 KB.

## Pool (30 candidates)

### Pending

- [ ] **Replace moment with date-fns** *(expected: −82 KB)*
- [ ] **Tree-shake lodash imports** *(expected: −41 KB)*
- ...

### Kept ✓

- [x] **Dynamic import heavy routes** — commit `abc1234`, Δ −118 KB, conf 4.3×

### Reverted ✗

- [×] **Remove unused polyfills** — Δ +3 KB (regressed)
- [×] **Inline small SVGs** — Δ −2 KB (inconclusive; below noise floor)

### Dead ends (errored / check_failed)

- [⚠] **Swap webpack for vite** — check_failed: 12 tests failed after swap

## Summary

| Runs | Kept | Reverted | Errored | Current | vs baseline | vs target |
|------|------|----------|---------|---------|-------------|-----------|
| 7    | 4    | 2        | 1       | 714 KB  | −15.2%      | ✓ hit     |
```

### 8.3 `sindri.jsonl` schema

Append-only, one record per line. Pydantic-validated on every append.

Record types (discriminated by `type` field):

**`type: "session_start"`**
```json
{"type":"session_start","ts":"2026-04-19T10:23:45-07:00","goal":"reduce bundle_bytes by 15%","target_pct":-15,"mode":"local"}
```

**`type: "baseline"`**
```json
{"type":"baseline","ts":"2026-04-19T10:24:05-07:00","run_index":1,"value":843100,"is_warmup":true}
{"type":"baseline","ts":"2026-04-19T10:24:18-07:00","run_index":2,"value":841400,"is_warmup":false}
{"type":"baseline_complete","ts":"...","mean":842000,"noise_floor":870}
```

**`type: "experiment"`**
```json
{"type":"experiment","ts":"...","id":7,"candidate":"Replace moment with date-fns","reps_used":3,"metric_before":842000,"metric_after":760000,"delta":-82000,"confidence_ratio":94.2,"status":"improved","commit_sha":"abc1234","files_modified":["package.json","src/utils/date.ts","pnpm-lock.yaml"]}
```

**`type: "event"`** (warnings, halts, mode changes)
```json
{"type":"event","ts":"...","event":"halted","reason":"max_reverts_in_a_row","details":"7 consecutive reverts — investigate benchmark or pool"}
```

**`type: "terminated"`** (final record)
```json
{"type":"terminated","ts":"...","reason":"target_hit","final_metric":714000,"delta_pct":-15.2,"kept":5,"reverted":2,"errored":1,"wall_clock_seconds":18432,"auto_finalize":true}
```

## 9. Python core — module-by-module

### 9.1 Package layout

```
src/sindri/
├── __init__.py
├── cli.py
└── core/
    ├── __init__.py
    ├── state.py
    ├── noise.py
    ├── pool.py
    ├── git_ops.py
    ├── metric.py
    ├── modes.py
    ├── pr_body.py
    ├── termination.py
    └── validators.py
```

### 9.2 Key APIs (test-first, so these are what the tests demand)

```python
# noise.py
def noise_floor(samples: list[float], *, discard_warmup: bool = True) -> float: ...
def confidence_ratio(delta: float, floor: float) -> float: ...
def coefficient_of_variation(samples: list[float]) -> float: ...

# pool.py
class Candidate(BaseModel):
    id: int
    name: str
    expected_impact_pct: float
    status: Literal["pending", "kept", "reverted", "errored", "check_failed"]
    files: list[str] = []

def pick_next(pool: list[Candidate], *, order_by: str = "expected_impact_desc") -> Candidate | None: ...

class TerminationCheck(BaseModel):
    terminated: bool
    reason: Literal["target_hit","pool_empty","max_experiments","max_wall_clock",
                    "max_reverts_in_a_row","halted_by_user","halted_by_error"] | None
    auto_finalize: bool

def check_termination(state: SindriState, *, max_experiments: int, max_wall_clock: int,
                     max_reverts: int) -> TerminationCheck: ...

# metric.py
def parse_metric_line(output: str, *, expected_name: str | None = None) -> tuple[str, float]: ...

# modes.py
def detect_mode(script_path: Path, baseline_samples: list[float]) -> Literal["local","remote"]: ...

# git_ops.py
def current_branch() -> str: ...
def is_working_tree_clean() -> bool: ...
def create_branch(name: str, *, from_ref: str = "HEAD") -> None: ...
def commit_all_with_message(msg: str) -> str: ...  # returns new commit SHA
def reset_hard_to_head() -> None: ...
def push_with_upstream(branch: str, remote: str = "origin") -> None: ...
def delete_branch(name: str, *, force: bool = False) -> None: ...

# pr_body.py
def render_pr_body(state: SindriState, jsonl_records: list[JsonlRecord]) -> str: ...

# state.py
class SindriState(BaseModel):
    goal: Goal
    baseline: Baseline
    pool: list[Candidate]
    branch: str
    started_at: datetime
    guardrails: Guardrails
    mode: Literal["local","remote"]

def read_state(dir: Path = Path(".sindri/current")) -> SindriState: ...
def write_state(state: SindriState, dir: Path = Path(".sindri/current")) -> None: ...
def append_jsonl(record: JsonlRecord, path: Path = Path(".sindri/current/sindri.jsonl")) -> None: ...
```

## 10. Error handling & guardrails

### 10.1 Error taxonomy

| Class | Example | Handling | Surfaced to user? |
|---|---|---|---|
| **Individual experiment — regressed** | Candidate made bundle bigger | revert | no |
| **Individual experiment — inconclusive** | Delta below 2× noise floor | revert | no |
| **Individual experiment — check_failed** | Candidate broke tests | revert, no retry | no |
| **Individual experiment — errored** | Benchmark crashed after candidate applied | revert, retry once, then mark dead | no |
| **Individual experiment — timeout** | Subagent exceeded wall clock | revert, move on | no unless 3 in a row |
| **Structural — benchmark fails at baseline** | `benchmark.py` exits non-zero on initial run | halt | **yes** |
| **Structural — metric unparseable** | Script doesn't emit a `METRIC` line | halt | **yes** |
| **Structural — 3 consecutive timeouts** | Something hangs the system | halt | **yes** |
| **Structural — `max_reverts_in_a_row`** | 7 reverts back-to-back = pool or benchmark is wrong | halt | **yes** |
| **Structural — git op fails** | Dirty tree can't be reset, push auth fail | halt | **yes** |
| **Structural — PR creation fails** | `gh` auth expired, remote doesn't exist | halt after successful push | **yes** |
| **Structural — schema drift** | Subagent returns malformed JSON | retry once, then halt | **yes** |

### 10.2 Guardrails (defaults, overridable in `sindri.md`)

| Guardrail | Default (local mode) | Default (remote mode) | Purpose |
|---|---|---|---|
| `max_experiments` | `min(pool_size, 50)` | `min(pool_size, 50)` | Absolute cap |
| `max_wall_clock_seconds` | 28800 (8h) | 259200 (72h) | Overnight / multi-day fits |
| `max_reverts_in_a_row` | 7 | 7 | Detects systemic failure |
| `timeout_per_experiment_seconds` | 1800 (30m) | 7200 (2h) | Hard cap per subagent |
| `baseline_reps` | 3 | 3 | Minimum viable for noise floor (run 1 discarded as warmup) |
| `reps_policy.adaptive` | true, 1–10 reps | false, exactly 1 rep | Cost / trust tradeoff |
| `reps_policy.confidence_threshold` | 2.0 | 2.0 | Both modes keep same threshold |

### 10.3 Explicit non-behaviors

- **No automatic rollback of prior kept commits.** Forge invariant: once the strike landed, the shape is set. Once kept, forever kept.
- **No "intelligent" recovery of half-applied changes.** `git reset --hard HEAD` is the only recovery primitive.
- **No silent continuation on halt.** A halt is visible in chat. The user decides whether to resume or abandon.
- **No retry on `check_failed`.** Tests are deterministic; retrying is theater.

## 11. Testing strategy (TDD)

### 11.1 Test-first discipline

- No production code ships without a failing test that drove it.
- Each `core/` module's public API is *designed by the tests* that exercise it, written before implementation.
- Coverage target: **100% on `core/` pure functions**, ≥80% on I/O-touching modules (state, git_ops).
- Tests live in `tests/` mirroring `src/sindri/` structure.

### 11.2 Test layers

| Layer | Tool | What it proves |
|---|---|---|
| **1. Unit (pure)** | pytest | Math is right: noise floor, confidence, parsing, ordering, termination, schema |
| **2. Unit (I/O)** | pytest + `tmp_path` | State round-trip, jsonl append atomicity, recovery from corrupt input, resumption after interrupt |
| **3. Git ops** | pytest + real git in `tmp_path` repos | Branch creation, commit with metric delta in message, `reset --hard`, safe delete |
| **4. CLI integration** | pytest + subprocess | `python -m sindri <cmd>` produces expected JSON given fixture state |
| **5. E2E orchestrator** | pytest + fake `benchmark.py` + stub subagent | Full loop on a fixture repo: N kept commits, right jsonl entries, correct termination |
| **6. Smoke** | shell script | `./scripts/smoke.sh` installs plugin locally, runs throwaway goal, validates end-to-end |

### 11.3 Specific test cases worth naming now

**Noise module:**
- `noise_floor([100, 102, 98, 101])` = std_dev([102, 98, 101]) (warmup discarded)
- `confidence_ratio(-50, 25)` = 2.0
- `confidence_ratio(0, 10)` = 0.0 (no division-by-zero blowup)
- `coefficient_of_variation([100, 115, 85, 110])` handles outliers

**Pool module:**
- `pick_next` returns highest expected-impact pending candidate
- `pick_next` returns None when all candidates resolved
- `check_termination` fires `target_hit` when best metric beats target
- `check_termination` fires `pool_empty` before `max_experiments` if pool drains

**Metric module:**
- Parses `METRIC name=42` → `("name", 42.0)`
- Parses `METRIC name=42.5e-3` → correct float
- Handles extra text / noise around the METRIC line
- Errors on missing METRIC line (typed exception)
- Errors on malformed value (typed exception)

**Modes module:**
- Script with `gh workflow run` → `remote`
- Script with `curl http://localhost:3000` → `local` (localhost whitelist)
- Script with no keywords + high observed CV → `remote`
- Script with no keywords + low observed CV → `local`

**State module:**
- Write + read round-trip preserves all fields
- Concurrent appends to jsonl don't corrupt (use `fcntl` advisory lock)
- Recovering from partial-line write (appended but truncated)
- Schema migration: read old-version jsonl, write new-version

**Git ops (in temp repo):**
- `create_branch("foo")` from a clean HEAD
- `commit_all_with_message` rejects if tree clean
- `reset_hard_to_head` clears working tree only, keeps HEAD
- `push_with_upstream` fails cleanly without remote

**E2E:**
- Fixture repo with a deterministic fake `benchmark.py` that counts lines across the source tree and emits `print(f"METRIC lines={total}")`
- Fake pool: 3 candidates that reduce lines, 2 that don't, 1 that errors
- Stub subagent returns predetermined JSON per candidate name
- Assert: after full run, branch has 3 commits, jsonl has 6 experiment records + 1 baseline_complete + 1 terminated, final metric matches expected

### 11.4 Continuous integration

- Layers 1–4 run on every push (<30s).
- Layer 5 runs on PR (~2 min).
- Layer 6 pre-release only (real cost).

### 11.5 Explicit non-tests

- Claude subagent behavior (not a unit test)
- Real benchmark correctness for user-provided scripts (user's problem)
- Cross-platform git edge cases (scope: Linux/macOS, git ≥ 2.30)
- Concurrent `/sindri` runs (explicitly unsupported — single-session assumption)

## 12. v1 scope boundaries

### 12.1 In v1

- Slash command: `/sindri`, subcommands `status`, `stop`, `scaffold-benchmark`, `clear`
- Skills: `sindri-start`, `sindri-scaffold-benchmark`, `sindri-loop`, `sindri-finalize`
- Python core: all 9 `core/` modules
- State protocol: `.sindri/current/` + `.sindri/archive/` with pydantic schema
- Rep modes: `local` + `remote` with auto-detection
- Multi-step benchmarks: fully supported (including GHA patterns)
- Error handling: individual + structural classes, with halt+surface for structural
- Testing: layers 1–5 with TDD discipline from day one

### 12.2 Deferred to v2

- **Remote/scheduled execution** (CronCreate, stateless wake-ups on GHA runners) — simpler to ship once the single-session loop is proven.
- **Parallel subagent dispatch** for file-disjoint experiments. Clean-context architecture supports this trivially once we have disjoint-file analysis — but the gain is speed, not correctness, so defer.
- **Custom pool-ordering heuristics** beyond "highest expected-impact first" — Bayesian bandits, adversarial ordering, etc.
- **Multiple concurrent runs in the same repo** — complexity spike, demand unclear.
- **A GUI dashboard** — not a fit for Claude Code's terminal-first surface.
- **Benchmark template library** shipped with sindri — users bring their own; we provide scaffolding, not catalog.
- **Windows support** — separate platform testing effort.
- **Automatic PR merging** — explicitly not sindri's job.

### 12.3 Open risks (flagged for implementation phase)

- **Subagent timing**: we don't yet know how long a clean-context `Task` subagent round-trip takes in practice. If it's >30s, per-experiment overhead becomes non-trivial. Mitigation: measure during implementation; if bad, batch candidate preparation server-side.
- **`gh pr create` in non-interactive contexts**: we rely on `gh` being authenticated in the user's environment. If it's not, finalize will fail. Scaffolding should probe once at `sindri-start` and flag if `gh auth status` isn't OK.
- **Rapid pool-approval UX**: if the user has 30 candidates to review, approval can take 5+ min. Need to make the present-the-pool UX dense (one-line-per-candidate) so it's quick to scan and strike.
- **Schema evolution**: adding new fields to `sindri.jsonl` mid-v1 must stay backwards-compatible. Pydantic's `extra="ignore"` + optional fields + explicit schema version field.

## 13. References

- [karpathy/autoresearch](https://github.com/karpathy/autoresearch) — the pattern we're adapting
- [davebcn87/pi-autoresearch](https://github.com/davebcn87/pi-autoresearch) — the generalization we're porting
- [Claude Code plugin documentation](https://docs.anthropic.com/en/docs/claude-code) — for plugin primitives (skills, slash commands, hooks)
- [pydantic v2 docs](https://docs.pydantic.dev/) — schema validation library
- Geoffrey Huntley's [Ralph Wiggum technique](https://ghuntley.com/ralph/) — a different loop primitive, considered and rejected for this use case (see §5 rationale above)

## 14. Appendix A: sample run walkthrough

Included as a visual simulation at [`docs/superpowers/specs/assets/sindri-architecture-v2.html`](./assets/sindri-architecture-v2.html) (committed from the design brainstorm session). Open in a browser to step through a full simulated run.

---

*End of spec.*

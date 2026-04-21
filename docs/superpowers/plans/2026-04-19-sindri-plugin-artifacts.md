# Sindri Plugin Artifacts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wrap the Plan 1 Python core in Claude Code plugin artifacts (manifest, slash command, 4 skills, subagent prompt) and prove the full lifecycle works end-to-end with a stub-subagent pytest, a manual smoke script, and CI. After this plan, `/sindri <goal>` is a real, installable plugin.

**Architecture:** The plugin is a thin surface over the Plan 1 CLI. `commands/sindri.md` routes user input to one of four skills. `skills/sindri-start/` runs the interactive Phase 1 flow. `skills/sindri-loop/` is the orchestrator invoked via `ScheduleWakeup`, dispatching experiments to a fresh subagent per wakeup and calling `python -m sindri` for every deterministic operation. `skills/sindri-finalize/` produces a PR. `prompts/experiment-subagent.md` is the contract every experiment subagent consumes. All Claude inference stays in prose (skills); all math/I/O stays in Python (Plan 1 core).

**Tech Stack:** Claude Code plugin format (`.claude-plugin/plugin.json`, `commands/`, `skills/`, `prompts/`), Bash + `gh` CLI for git/PR work, pytest + subprocess for the E2E stub test, GitHub Actions for CI. No new Python runtime deps.

---

## Table of Contents

- [File structure](#file-structure)
- [Prerequisites](#prerequisites)
- [Phase 1 — Plugin skeleton](#phase-1--plugin-skeleton)
  - [Task 1: Plugin manifest + validity test](#task-1-plugin-manifest--validity-test)
  - [Task 2: Slash command `commands/sindri.md`](#task-2-slash-command-commandssindri-md)
  - [Task 3: Plugin README](#task-3-plugin-readme)
- [Phase 2 — Skills](#phase-2--skills)
  - [Task 4: Skill `sindri-start`](#task-4-skill-sindri-start)
  - [Task 5: Skill `sindri-scaffold-benchmark`](#task-5-skill-sindri-scaffold-benchmark)
  - [Task 6: Skill `sindri-loop` (orchestrator)](#task-6-skill-sindri-loop-orchestrator)
  - [Task 7: Skill `sindri-finalize`](#task-7-skill-sindri-finalize)
- [Phase 3 — Subagent contract](#phase-3--subagent-contract)
  - [Task 8: `prompts/experiment-subagent.md`](#task-8-promptsexperiment-subagentmd)
- [Phase 4 — E2E stub test](#phase-4--e2e-stub-test)
  - [Task 9: E2E fixture helpers](#task-9-e2e-fixture-helpers)
  - [Task 10: E2E happy-path test (target hit → auto-finalize)](#task-10-e2e-happy-path-test-target-hit--auto-finalize)
  - [Task 11: E2E terminal-condition tests](#task-11-e2e-terminal-condition-tests)
- [Phase 5 — Smoke, CI, release](#phase-5--smoke-ci-release)
  - [Task 12: `scripts/smoke.sh`](#task-12-scriptssmokesh)
  - [Task 13: `.github/workflows/ci.yml`](#task-13-githubworkflowsciyml)
  - [Task 14: Milestone commit + tag `v0.2.0-plugin`](#task-14-milestone-commit--tag-v020-plugin)

---

## File structure

Everything created or modified by this plan:

```
sindri/
├── .claude-plugin/
│   └── plugin.json                                # NEW — plugin manifest
├── commands/
│   └── sindri.md                                  # NEW — slash command entry
├── skills/
│   ├── sindri-start/
│   │   └── SKILL.md                               # NEW — interactive init skill
│   ├── sindri-scaffold-benchmark/
│   │   └── SKILL.md                               # NEW — benchmark.py generator
│   ├── sindri-loop/
│   │   └── SKILL.md                               # NEW — orchestrator (per-wakeup)
│   └── sindri-finalize/
│       └── SKILL.md                               # NEW — PR creation
├── prompts/
│   └── experiment-subagent.md                     # NEW — experiment subagent template
├── scripts/
│   └── smoke.sh                                   # NEW — manual smoke runner
├── tests/
│   ├── e2e/
│   │   ├── __init__.py                            # NEW
│   │   ├── conftest.py                            # NEW — fixture repo helpers
│   │   ├── stub_subagent.py                       # NEW — canned subagent responses
│   │   └── test_loop_end_to_end.py                # NEW — full lifecycle tests
│   └── unit/
│       └── test_plugin_artifacts.py               # NEW — manifest + skill frontmatter validity
├── .github/
│   └── workflows/
│       └── ci.yml                                 # NEW — pytest on push/PR
├── README.md                                      # NEW — plugin install + usage
└── pyproject.toml                                 # MODIFY — add `pyyaml` to dev deps (skill frontmatter parsing)
```

---

## Prerequisites

Before starting, verify:

- You are on branch `feat/sindri-plugin-artifacts-plan2` (not `main`).
- Plan 1 is merged: `git log --oneline main | head -3` should show `Merge pull request #1 ... feat/sindri-python-core-plan1`.
- Python venv is active: `python -c "import sindri; print(sindri.__file__)"` resolves to `src/sindri/__init__.py`.
- `pytest` runs clean from Plan 1 tests: `pytest -q` → all green.
- `gh --version` works (needed for smoke + finalize skill; not strictly for pytest).

If anything fails, stop and resolve before proceeding.

---

## Phase 1 — Plugin skeleton

### Task 1: Plugin manifest + validity test

**Files:**
- Create: `.claude-plugin/plugin.json`
- Create: `tests/unit/test_plugin_artifacts.py`
- Modify: `pyproject.toml` (add `pyyaml` dev dep)

- [ ] **Step 1: Add `pyyaml` dev dependency**

Edit `pyproject.toml` — in `[project.optional-dependencies]` `dev` list, append `"pyyaml>=6.0"`:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-mock>=3.12",
    "pytest-cov>=4.1",
    "pyyaml>=6.0",
]
```

Run `uv pip install -e ".[dev]"` to install.

- [ ] **Step 2: Write failing manifest validity test**

Create `tests/unit/test_plugin_artifacts.py`:

```python
"""Validate plugin artifacts (manifest, commands, skills, prompts) parse and contain required fields."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def _parse_frontmatter(md_path: Path) -> dict:
    """Extract YAML frontmatter from a markdown file. Returns {} if none."""
    text = md_path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    _, frontmatter, _ = text.split("---\n", 2)
    return yaml.safe_load(frontmatter) or {}


class TestPluginManifest:
    def test_plugin_json_exists(self) -> None:
        assert (REPO_ROOT / ".claude-plugin" / "plugin.json").is_file()

    def test_plugin_json_parses(self) -> None:
        data = json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text())
        assert isinstance(data, dict)

    def test_plugin_json_required_fields(self) -> None:
        data = json.loads((REPO_ROOT / ".claude-plugin" / "plugin.json").read_text())
        for key in ("name", "description", "version", "author"):
            assert key in data, f"missing required field: {key}"
        assert data["name"] == "sindri"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/unit/test_plugin_artifacts.py::TestPluginManifest -v`
Expected: 3 FAILs (file doesn't exist yet).

- [ ] **Step 4: Create the manifest**

Create `.claude-plugin/plugin.json`:

```json
{
  "name": "sindri",
  "description": "Bounded, target-driven optimization loops for any metric you can measure deterministically. Autonomous experiments, kept-or-reverted per git commit, auto-PR on success.",
  "version": "0.2.0",
  "author": {
    "name": "Nimesh Kumar",
    "email": "260103116+4kmetrics@users.noreply.github.com"
  },
  "homepage": "https://github.com/4KMetrics/sindri",
  "license": "MIT"
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/unit/test_plugin_artifacts.py::TestPluginManifest -v`
Expected: 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add .claude-plugin/plugin.json tests/unit/test_plugin_artifacts.py pyproject.toml
git commit -m "feat(plugin): add plugin manifest + validity test"
```

---

### Task 2: Slash command `commands/sindri.md`

**Files:**
- Create: `commands/sindri.md`
- Modify: `tests/unit/test_plugin_artifacts.py` (add slash-command tests)

- [ ] **Step 1: Write failing slash-command validity test**

Append to `tests/unit/test_plugin_artifacts.py`:

```python
class TestSlashCommand:
    COMMAND_PATH = REPO_ROOT / "commands" / "sindri.md"

    def test_command_file_exists(self) -> None:
        assert self.COMMAND_PATH.is_file()

    def test_command_frontmatter_has_description(self) -> None:
        fm = _parse_frontmatter(self.COMMAND_PATH)
        assert "description" in fm and fm["description"].strip(), "command needs a description"

    def test_command_mentions_subcommands(self) -> None:
        body = self.COMMAND_PATH.read_text()
        for sub in ("status", "stop", "scaffold-benchmark", "clear"):
            assert sub in body, f"command body should reference subcommand: {sub}"

    def test_command_routes_to_skills(self) -> None:
        body = self.COMMAND_PATH.read_text()
        for skill in ("sindri-start", "sindri-loop", "sindri-finalize", "sindri-scaffold-benchmark"):
            assert skill in body, f"command body should name skill: {skill}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_plugin_artifacts.py::TestSlashCommand -v`
Expected: 4 FAILs.

- [ ] **Step 3: Create the slash command**

Create `commands/sindri.md`:

```markdown
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
| `clear` | Destructive. Prompt the user for confirmation (`y/N`). If confirmed: `rm -rf .sindri/current/ && git checkout main && git branch -D sindri/<slug>` where `<slug>` is read from `.sindri/current/sindri.md` frontmatter **before** deleting. If not confirmed: print `aborted.` and stop. |
| anything else | Treat as a goal statement. If `.sindri/current/` exists, print a resume/abandon prompt and **do not** start a new run. Otherwise, invoke skill `sindri-start` with the goal statement. |

## Invariants

- **One run per repo.** Never start a new run while `.sindri/current/` exists.
- **Never mutate git state directly in this command.** Skills own that.
- **`status` must always be fast.** It reads files, nothing else.
- **`clear` always confirms first.** No silent deletion.

## After dispatch

For `status` and `stop`, you return to the user directly. For `scaffold-benchmark`, `clear`, and a new-goal invocation, control passes to the relevant skill and that skill produces the user-visible output.

For a brand-new goal, after `sindri-start` returns, sindri is running autonomously — `ScheduleWakeup` has been set. The orchestrator skill (`sindri-loop`) runs on every wakeup without further user action until termination.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_plugin_artifacts.py::TestSlashCommand -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add commands/sindri.md tests/unit/test_plugin_artifacts.py
git commit -m "feat(plugin): add /sindri slash command router"
```

---

### Task 3: Plugin README

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write the README**

Create `README.md`:

```markdown
# sindri

> Bounded, target-driven optimization loops for any metric you can measure deterministically.

Sindri is a Claude Code plugin that turns a one-line goal like *"reduce bundle_bytes by 15%"* into an autonomous, overnight experiment loop. It proposes candidates, applies them in fresh subagent contexts, runs your benchmark, keeps the wins, reverts the losses, and opens a PR with a human-readable log when it's done — or halts and surfaces why it couldn't.

**One commit per kept experiment. Git is the audit log. The forge runs one way.**

## Install

This is a local-dev plugin. To use it in another repo:

```bash
# From this repo
uv pip install -e .

# From a target repo, symlink the plugin into ~/.claude/plugins/
ln -s "$(pwd -P)" ~/.claude/plugins/sindri
```

Restart Claude Code. Verify: `/sindri status` should report "no active run" cleanly.

Requirements:

- Python ≥ 3.10 with `pydantic>=2.0,<3.0` and `pyyaml>=6.0` (dev)
- `git` ≥ 2.30
- `gh` CLI (authenticated) — needed only for `sindri-finalize` PR creation
- Claude Code CLI with `Task` + `ScheduleWakeup` tools

## Quickstart

```bash
# In the repo you want to optimize:
/sindri reduce bundle_bytes by 15%
```

Sindri will:

1. Scaffold `.claude/scripts/sindri/benchmark.py` if missing (interactive; asks you to describe the measurement in natural language).
2. Scan your repo and draft a pool of 10–30 candidates.
3. Ask you to approve / edit the pool.
4. Check out a new branch `sindri/reduce-bundle-size-15pct` and run the baseline 3×.
5. Loop autonomously — one experiment per wakeup, ~60s between them.
6. When the target hits (or the pool drains with ≥1 win), push the branch and open a PR.

Check in anytime with `/sindri status`. Halt with `/sindri stop`. Abandon with `/sindri clear`.

## Architecture

- **Python core** (`src/sindri/`) — pure functions: statistics, state file I/O, git wrappers, pool ordering, termination predicates, PR body rendering. 100% unit-tested.
- **Skills** (`skills/sindri-*/SKILL.md`) — prose prompts for the decisions that need Claude's inference: scaffolding a benchmark, proposing a candidate pool, orchestrating the loop.
- **Subagent prompt** (`prompts/experiment-subagent.md`) — the contract every experiment subagent follows. Fresh context per experiment, no context bleed.

See [`docs/superpowers/specs/2026-04-19-sindri-design.md`](docs/superpowers/specs/2026-04-19-sindri-design.md) for the full design.

## Development

```bash
uv pip install -e ".[dev]"
pytest                                  # all test layers (unit + integration + e2e)
pytest -m "not e2e"                     # skip the slow end-to-end loop test
pytest tests/unit/test_plugin_artifacts.py -v   # just artifact validity checks
```

## License

MIT.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add plugin README with install + quickstart"
```

---

## Phase 2 — Skills

Each skill lives at `skills/<name>/SKILL.md`. Every skill file:

1. Has YAML frontmatter with `name` and `description` (required for Claude Code discovery).
2. Optionally lists allowed `tools`.
3. Has a prose body that reads like instructions to a capable engineer.

Each task in this phase also extends the unit test to validate that skill's frontmatter + CLI references.

### Task 4: Skill `sindri-start`

**Files:**
- Create: `skills/sindri-start/SKILL.md`
- Modify: `tests/unit/test_plugin_artifacts.py`

- [ ] **Step 1: Add a generic skill-validity helper + `sindri-start` tests**

Append to `tests/unit/test_plugin_artifacts.py`:

```python
VALID_CLI_SUBCOMMANDS = {
    "init", "validate-benchmark", "detect-mode", "read-state", "pick-next",
    "record-result", "check-termination", "generate-pr-body", "archive", "status",
}


def _skill_path(name: str) -> Path:
    return REPO_ROOT / "skills" / name / "SKILL.md"


def _cli_calls(body: str) -> set[str]:
    """Extract sub-command names from `python -m sindri <cmd>` references."""
    import re
    return set(re.findall(r"python -m sindri (\S+)", body))


class TestSkillSindriStart:
    PATH = _skill_path("sindri-start")

    def test_exists(self) -> None:
        assert self.PATH.is_file()

    def test_frontmatter_has_name_and_description(self) -> None:
        fm = _parse_frontmatter(self.PATH)
        assert fm.get("name") == "sindri-start"
        assert fm.get("description", "").strip()

    def test_cli_calls_are_known_subcommands(self) -> None:
        for cmd in _cli_calls(self.PATH.read_text()):
            assert cmd in VALID_CLI_SUBCOMMANDS, f"unknown subcommand: {cmd}"

    def test_references_scaffold_benchmark_subflow(self) -> None:
        body = self.PATH.read_text()
        assert "sindri-scaffold-benchmark" in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_plugin_artifacts.py::TestSkillSindriStart -v`
Expected: 4 FAILs.

- [ ] **Step 3: Write the skill**

Create `skills/sindri-start/SKILL.md`:

```markdown
---
name: sindri-start
description: Interactive, one-shot scaffolding for a new sindri optimization run. Parses goal, ensures benchmark.py exists, scans repo for candidates, gets pool approval, runs baseline, schedules the orchestrator. Use when the /sindri slash command receives a new goal statement.
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

Accepted shapes:

- `reduce bundle_bytes by 15%` → `{reduce, bundle_bytes, 15}`
- `increase test coverage by 10%` → `{increase, test_coverage, 10}`
- `cut ci_seconds 25%` → `{reduce, ci_seconds, 25}`

If you can't parse it confidently, print **three concrete examples** and ask the user to rephrase. Do not guess.

## 2. Ensure `benchmark.py` exists and works

Check `.claude/scripts/sindri/benchmark.py`:

- **Missing** → invoke skill `sindri-scaffold-benchmark` as a sub-flow, passing the parsed `metric_name` and goal text. Wait for it to complete. Do not proceed until the file exists.
- **Exists** → run `python -m sindri validate-benchmark`. If it fails (non-zero exit or no `METRIC <metric_name>=<number>` line), print the error and invoke `sindri-scaffold-benchmark` in *repair* mode.

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
  {"id": 2, "name": "Tree-shake lodash imports", "expected_impact_pct": -3, "files": []},
  ...
]
```

Then run:

```bash
python -m sindri init \
  --goal "<original goal statement>" \
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
- **Do not** ScheduleWakeup before the branch + state + baseline are all on disk.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_plugin_artifacts.py::TestSkillSindriStart -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/sindri-start/SKILL.md tests/unit/test_plugin_artifacts.py
git commit -m "feat(skills): add sindri-start skill"
```

---

### Task 5: Skill `sindri-scaffold-benchmark`

**Files:**
- Create: `skills/sindri-scaffold-benchmark/SKILL.md`
- Modify: `tests/unit/test_plugin_artifacts.py`

- [ ] **Step 1: Add tests**

Append to `tests/unit/test_plugin_artifacts.py`:

```python
class TestSkillSindriScaffoldBenchmark:
    PATH = _skill_path("sindri-scaffold-benchmark")

    def test_exists(self) -> None:
        assert self.PATH.is_file()

    def test_frontmatter(self) -> None:
        fm = _parse_frontmatter(self.PATH)
        assert fm.get("name") == "sindri-scaffold-benchmark"
        assert fm.get("description", "").strip()

    def test_cli_calls_are_known(self) -> None:
        for cmd in _cli_calls(self.PATH.read_text()):
            assert cmd in VALID_CLI_SUBCOMMANDS

    def test_mentions_metric_output_contract(self) -> None:
        body = self.PATH.read_text()
        assert "METRIC" in body  # must document the required output line
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_plugin_artifacts.py::TestSkillSindriScaffoldBenchmark -v`
Expected: 4 FAILs.

- [ ] **Step 3: Write the skill**

Create `skills/sindri-scaffold-benchmark/SKILL.md`:

```markdown
---
name: sindri-scaffold-benchmark
description: Scaffold .claude/scripts/sindri/benchmark.py by scanning the repo, proposing a measurement in natural language, translating the user's refinements into Python, and running the script once to verify it emits a valid METRIC line. Never ask the user for Python or shell syntax.
tools: Bash, Read, Write, Edit, Glob, Grep
---

# sindri-scaffold-benchmark — write the benchmark script

Goal: produce `.claude/scripts/sindri/benchmark.py` that, when run, prints one line matching `METRIC <metric_name>=<number>` as its last stdout line. You translate user intent (natural language) into Python; the user never writes code.

## Inputs

- `$METRIC_NAME` — snake_case identifier (e.g., `bundle_bytes`)
- `$GOAL_TEXT` — the user's original goal statement, for context

## 1. Scan the repo

Detect:

- **Package manager:** `pnpm-lock.yaml` → pnpm; `yarn.lock` → yarn; `bun.lock` → bun; `package-lock.json` → npm; `uv.lock` → uv; `poetry.lock` → poetry; `Cargo.lock` → cargo.
- **Build tool:** look for `vite.config.*`, `webpack.config.*`, `next.config.*`, `rollup.config.*`, `esbuild.config.*`. For Python, look for build scripts in `pyproject.toml`.
- **Output directory:** inspect `package.json`'s `"build"` script or the build-tool config. Common: `dist/`, `build/`, `out/`, `.next/`, `public/`.
- **CI script references:** `.github/workflows/*.yml` (helpful when the metric is CI-time).

## 2. Propose a measurement

Based on `$METRIC_NAME` + what you found, propose a concrete measurement. Examples:

| Metric | Stack detected | Proposal |
|---|---|---|
| `bundle_bytes` | Vite + pnpm, output `dist/` | Run `pnpm build`. Sum byte size of `dist/`. |
| `bundle_bytes` | Next.js + npm | Run `npm run build`. Sum byte size of `.next/static/` + `.next/server/`. |
| `ci_seconds` | GHA workflow `ci.yml` exists | Trigger `gh workflow run ci.yml`, poll until done, read the `conclusion` + `duration` from `gh run view --json`. |
| `test_runtime_seconds` | `pytest` in pyproject | Run `pytest --durations=0`, capture total wall-clock. |
| `lighthouse_score` | Next.js + deploy target | **Halt** — ask the user which deployed URL to audit; too stack-specific for inference. |

Print your proposal in plain English first. Example:

> *"I see you're on Vite + pnpm with output in `dist/`. Proposed benchmark: run `pnpm build`, then sum bytes in `dist/` and print `METRIC bundle_bytes=<sum>`. Accept? Refine? (reply with changes in plain English)"*

## 3. Iterate in natural language

Accept refinements like:

- "use npm not pnpm" → swap `pnpm build` for `npm run build`
- "measure gzipped" → pipe through `gzip -c | wc -c` per file, sum
- "skip the build, assume dist/ is already there" → drop the build step
- "also warm the cache first" → prepend a throwaway build

Never ask the user to write or edit Python. Keep the conversation in prose; your job is translation.

## 4. Generate `benchmark.py`

Write the final script to `.claude/scripts/sindri/benchmark.py`. Required shape:

```python
#!/usr/bin/env python3
"""Sindri benchmark — auto-generated. <one-line purpose>.

Emits exactly one `METRIC <name>=<number>` line as the final stdout line.
All other output goes to stderr so the orchestrator can ignore it.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    # <step 1: build/prep>
    # subprocess.run([...], check=True, stderr=sys.stderr, stdout=sys.stderr)

    # <step 2: measure>
    # value = <computed number>

    # <step 3: emit METRIC line as the LAST stdout line>
    # print(f"METRIC <metric_name>={value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Substitute `<metric_name>` with `$METRIC_NAME` exactly. The `METRIC` line must be on stdout; build/prep noise must go to stderr so a downstream parser sees only the metric.

`chmod +x .claude/scripts/sindri/benchmark.py` after writing.

## 5. Validate with one real run

```bash
python -m sindri validate-benchmark
```

If it fails:

- **Non-zero exit:** show the stderr to the user, ask what's wrong, iterate.
- **No `METRIC` line found:** show the user the last 20 lines of stdout, ask which value is the metric, regenerate.
- **Wrong metric name:** regenerate with the right name.

Iterate until `validate-benchmark` exits 0 and prints the parsed value.

## 6. (Optional) Scaffold `checks.py`

Ask: *"Run tests or lint as a gate before each experiment commits? (recommended: yes if you have a fast test suite)"*.

If yes, generate `.claude/scripts/sindri/checks.py`:

```python
#!/usr/bin/env python3
"""Sindri pre-commit check — exits 0 if all checks pass, non-zero if they fail."""
from __future__ import annotations
import subprocess
import sys


def main() -> int:
    # subprocess.run(["pnpm", "test", "--run"], check=True)
    # subprocess.run(["pnpm", "lint"], check=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Make it executable and run once to confirm it passes.

## Fallback — exotic stacks

If the scan yields nothing useful (proprietary observability, multi-cluster k8s, exotic language), ask the user in plain English: *"Describe how you would measure this manually today — what command, what file, what API? I'll translate that into Python."* Then do so. Never demand code from the user.

## Anti-patterns

- Never emit the `METRIC` line anywhere but the last stdout line.
- Never put build logs on stdout — only on stderr.
- Never leave the script non-executable.
- Never declare "done" without running `validate-benchmark` successfully.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_plugin_artifacts.py::TestSkillSindriScaffoldBenchmark -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/sindri-scaffold-benchmark/SKILL.md tests/unit/test_plugin_artifacts.py
git commit -m "feat(skills): add sindri-scaffold-benchmark skill"
```

---

### Task 6: Skill `sindri-loop` (orchestrator)

**Files:**
- Create: `skills/sindri-loop/SKILL.md`
- Modify: `tests/unit/test_plugin_artifacts.py`

- [ ] **Step 1: Add tests**

Append to `tests/unit/test_plugin_artifacts.py`:

```python
class TestSkillSindriLoop:
    PATH = _skill_path("sindri-loop")

    def test_exists(self) -> None:
        assert self.PATH.is_file()

    def test_frontmatter(self) -> None:
        fm = _parse_frontmatter(self.PATH)
        assert fm.get("name") == "sindri-loop"
        assert fm.get("description", "").strip()

    def test_cli_calls_are_known(self) -> None:
        for cmd in _cli_calls(self.PATH.read_text()):
            assert cmd in VALID_CLI_SUBCOMMANDS

    def test_references_experiment_subagent_prompt(self) -> None:
        body = self.PATH.read_text()
        assert "experiment-subagent" in body  # must cite the prompt file

    def test_references_schedule_wakeup(self) -> None:
        body = self.PATH.read_text()
        assert "ScheduleWakeup" in body

    def test_references_finalize_skill(self) -> None:
        body = self.PATH.read_text()
        assert "sindri-finalize" in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_plugin_artifacts.py::TestSkillSindriLoop -v`
Expected: 6 FAILs.

- [ ] **Step 3: Write the skill**

Create `skills/sindri-loop/SKILL.md`:

```markdown
---
name: sindri-loop
description: The sindri orchestrator. Runs one experiment per invocation. Reads state, checks termination, picks next candidate, dispatches an experiment subagent via Task tool, acts on the result (commit or reset), records to state, and schedules the next wakeup — unless terminated. Invoked automatically via ScheduleWakeup during an active run. Never invoke manually.
tools: Bash, Read, Edit, Task
---

# sindri-loop — per-wakeup orchestrator

You run **once per wakeup**. One invocation = one experiment end-to-end. You are deliberately thin: every deterministic step goes through `python -m sindri <cmd>`, every reasoning step goes to a fresh subagent via `Task`. Your own context stays tiny so autocompaction is a non-issue.

**Invariant: every wakeup is identical in structure.** No state persists in your head — it all lives on disk.

## Steps (strict order, no skipping)

### 1. Read state

```bash
python -m sindri read-state
```

Parse the JSON. It includes: `pool`, `kept`, `reverted`, `current_best`, `baseline`, `noise_floor`, `mode`, `guardrails`, `started_at`, and counters (`experiments_run`, `consecutive_timeouts`, `consecutive_reverts`).

### 2. Termination check

Before anything else, check for the user-halt sentinel:

```bash
if [ -f .sindri/current/HALT ]; then
  # User invoked /sindri stop. Terminate with reason halted_by_user.
  # auto_finalize is true iff at least one kept commit exists.
fi
```

If the sentinel exists:

1. Count kept commits on the branch (`git log --oneline --grep "^kept:" | wc -l`).
2. Append a terminated record to `sindri.jsonl`: `{"type":"terminated","reason":"halted_by_user","auto_finalize": <kept > 0>, ...}`.
3. If `kept > 0`, invoke `sindri-finalize`; otherwise announce to chat and stop.
4. `rm .sindri/current/HALT` (clean up after consuming).
5. **Do NOT call `ScheduleWakeup`.** Return.

Otherwise, compute counters from state + jsonl:

- `experiments_run`: count of `type == "experiment"` records in `sindri.jsonl`.
- `consecutive_reverts`: starting from the tail of `sindri.jsonl`, count experiments with `status in {"regressed", "inconclusive", "errored", "timeout"}` until you hit a `status == "improved"` or run out.

Pipe these to `check-termination` on stdin:

```bash
echo '{"experiments_run": <N>, "consecutive_reverts": <K>}' | python -m sindri check-termination
```

Returns JSON: `{"terminated": bool, "reason": str | null, "auto_finalize": bool}`.

If `terminated`:

1. Append a terminated record to `sindri.jsonl` via the Python core (record-result or a direct append — whichever Plan 1 exposes).
2. If `auto_finalize` is `true` AND `kept >= 1`, invoke skill `sindri-finalize`.
3. Otherwise print a human-readable summary:
   - `reason == "pool_empty"` + `kept == 0` → *"sindri: terminated (pool exhausted). 0 kept experiments out of <N> tried. No PR created. Branch `sindri/<slug>` deleted. See `.sindri/archive/<date>-<slug>/`."*
   - Structural halts (timeouts, reverts, benchmark failure, etc.) → surface the halt reason verbatim and tell the user: *"State preserved in `.sindri/current/`. Fix the underlying issue and re-run `/sindri`, or `/sindri clear` to abandon."*
4. **Do NOT call ScheduleWakeup.** The loop ends here.
5. Return.

### 3. Pre-flight git check

```bash
git status --porcelain
```

If output is non-empty (dirty tree from a previous interrupted experiment):

```bash
git reset --hard HEAD
```

This is a belt-and-suspenders recovery — kept commits survive (they're in HEAD); only unstaged/uncommitted changes are discarded.

### 4. Pick next candidate

```bash
python -m sindri pick-next
```

Returns JSON describing the next candidate: `{"id": int, "name": str, "expected_impact_pct": float, "affects": [str, ...]}`. If `null`, re-run step 2 — state should already have told you the pool is empty, so this path is defensive.

### 5. Dispatch the experiment subagent

Load the template at `prompts/experiment-subagent.md` (relative to the plugin install path). Fill in the placeholders from the candidate + state:

- `$CANDIDATE` — the candidate JSON from step 4.
- `$BENCHMARK_CMD` — `.claude/scripts/sindri/benchmark.py` (or whatever state says).
- `$CHECKS_CMD` — `.claude/scripts/sindri/checks.py` or empty if missing.
- `$METRIC` — `{"name": ..., "direction": ...}` from state.
- `$CURRENT_BEST` — the current best metric value.
- `$NOISE_FLOOR` — from state.
- `$MODE` — `"local"` or `"remote"`.
- `$REPS_POLICY` — from state guardrails.
- `$TIMEOUT_SECONDS` — from state guardrails.

Invoke via `Task` tool:

```
Task(
  subagent_type="general-purpose",
  description="sindri experiment: <candidate name>",
  prompt=<filled template>
)
```

### 6. Parse the subagent result

The subagent returns JSON on stdout matching `src/sindri/core/validators.py::SubagentResult`:

```json
{
  "metric_value": 719218,
  "reps_used": 3,
  "confidence_ratio": 4.2,
  "status": "improved",
  "files_modified": ["package.json", "..."],
  "notes": "..."
}
```

If the subagent's output doesn't parse as JSON or fails schema validation, treat it as `status: errored` (synthesize a minimal SubagentResult with `status: "errored"`, `metric_value: 0`, etc.) and continue with the revert path.

### 7. Act on the result

`metric_before` is `state.current_best` if set, else `state.baseline.value`.

| `status` | Git action | Pool status (handled by record-result) |
|---|---|---|
| `improved` | `git add -A && git commit -m "kept: <candidate name> (Δ<delta>)"` — capture the new SHA | `kept` |
| `regressed` | `git reset --hard HEAD` | `reverted` |
| `inconclusive` | `git reset --hard HEAD` | `reverted` (low-confidence = no keep) |
| `check_failed` | `git reset --hard HEAD` | `check_failed` (no retry) |
| `errored` | `git reset --hard HEAD` | `errored` |
| `timeout` | `git reset --hard HEAD` | `errored` (tracked separately for consecutive-timeout halt) |

Commit message format: `kept: <candidate name> (Δ<signed delta>)`, e.g., `kept: Replace moment with date-fns (Δ-82000)`.

### 8. Record the result

Compose the RecordPayload and pipe to `record-result`:

```json
{
  "candidate_id": <int, from step 4>,
  "metric_before": <float, from state.current_best or state.baseline.value>,
  "subagent_result": <subagent JSON verbatim from step 6>,
  "commit_sha": "<new SHA if status == improved, else null>"
}
```

```bash
echo "$PAYLOAD" | python -m sindri record-result
```

`record-result` atomically:

- Updates the candidate's pool status in `sindri.md`.
- Sets `current_best` to the new metric value on `improved`.
- Appends a `type: "experiment"` record to `sindri.jsonl` with full `metric_before`, `metric_after`, `delta`, `confidence_ratio`, `status`, `commit_sha`, `files_modified`.
- Returns `{"ok": true, "new_status": "...", "current_best": ...}` on stdout.

If record-result exits non-zero, surface the stderr and halt — writing state is the one operation that must never silently fail.

### 9. Structural halt check

Re-compute `experiments_run` and `consecutive_reverts` (now including this experiment) and re-pipe them into `check-termination`:

```bash
echo '{"experiments_run": <N+1>, "consecutive_reverts": <updated K>}' | python -m sindri check-termination
```

Structural halts may now fire:

- `max_reverts_in_a_row` hit → halt.
- `max_experiments` exceeded → halt with reason `max_experiments`.
- `target_hit` reached (current_best beats target) → halt + `auto_finalize: true`.

If `terminated`: jump back to step 2's handling (surface → no wakeup).

### 10. Schedule the next wakeup

```
ScheduleWakeup(
  delay=60,
  prompt="Resume sindri-loop orchestrator. Read state from .sindri/current/ and run one wakeup cycle."
)
```

Return. You are done. The next wakeup starts fresh at step 1.

## Anti-patterns

- **Never modify files in the repo directly** outside of git commit/reset. The subagent applies the candidate; you only keep or discard.
- **Never maintain state in your own prompt context.** Every wakeup starts by reading disk.
- **Never skip the pre-flight git check** — a dirty tree from an interrupted run poisons the next experiment.
- **Never finalize unless `auto_finalize: true`.** Some terminations (e.g., `halted_by_user`) should not produce a PR.
- **Never call `ScheduleWakeup` on terminated runs.** That's a bug; the loop must end.
- **Never retry `check_failed`.** Tests are deterministic; retrying is theater.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_plugin_artifacts.py::TestSkillSindriLoop -v`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/sindri-loop/SKILL.md tests/unit/test_plugin_artifacts.py
git commit -m "feat(skills): add sindri-loop orchestrator skill"
```

---

### Task 7: Skill `sindri-finalize`

**Files:**
- Create: `skills/sindri-finalize/SKILL.md`
- Modify: `tests/unit/test_plugin_artifacts.py`

- [ ] **Step 1: Add tests**

Append to `tests/unit/test_plugin_artifacts.py`:

```python
class TestSkillSindriFinalize:
    PATH = _skill_path("sindri-finalize")

    def test_exists(self) -> None:
        assert self.PATH.is_file()

    def test_frontmatter(self) -> None:
        fm = _parse_frontmatter(self.PATH)
        assert fm.get("name") == "sindri-finalize"
        assert fm.get("description", "").strip()

    def test_cli_calls_are_known(self) -> None:
        for cmd in _cli_calls(self.PATH.read_text()):
            assert cmd in VALID_CLI_SUBCOMMANDS

    def test_mentions_gh_pr_create(self) -> None:
        body = self.PATH.read_text()
        assert "gh pr create" in body

    def test_mentions_git_push(self) -> None:
        body = self.PATH.read_text()
        assert "git push" in body

    def test_mentions_archive(self) -> None:
        body = self.PATH.read_text()
        assert "archive" in body.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_plugin_artifacts.py::TestSkillSindriFinalize -v`
Expected: 6 FAILs.

- [ ] **Step 3: Write the skill**

Create `skills/sindri-finalize/SKILL.md`:

```markdown
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

Read the branch name from `.sindri/current/sindri.md` frontmatter (`branch:` field).

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_plugin_artifacts.py::TestSkillSindriFinalize -v`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/sindri-finalize/SKILL.md tests/unit/test_plugin_artifacts.py
git commit -m "feat(skills): add sindri-finalize skill"
```

---

## Phase 3 — Subagent contract

### Task 8: `prompts/experiment-subagent.md`

**Files:**
- Create: `prompts/experiment-subagent.md`
- Modify: `tests/unit/test_plugin_artifacts.py`

- [ ] **Step 1: Add tests**

Append to `tests/unit/test_plugin_artifacts.py`:

```python
class TestExperimentSubagentPrompt:
    PATH = REPO_ROOT / "prompts" / "experiment-subagent.md"

    def test_exists(self) -> None:
        assert self.PATH.is_file()

    def test_declares_output_contract(self) -> None:
        body = self.PATH.read_text()
        # Must document the required JSON output shape with the status enum.
        for field in ("metric_value", "reps_used", "confidence_ratio", "status", "files_modified"):
            assert field in body, f"output contract missing field: {field}"
        for status in ("improved", "regressed", "inconclusive", "check_failed", "errored", "timeout"):
            assert status in body, f"status value missing: {status}"

    def test_declares_input_placeholders(self) -> None:
        body = self.PATH.read_text()
        for placeholder in ("$CANDIDATE", "$BENCHMARK_CMD", "$METRIC", "$CURRENT_BEST", "$NOISE_FLOOR", "$MODE", "$TIMEOUT_SECONDS"):
            assert placeholder in body, f"placeholder missing: {placeholder}"

    def test_prohibits_commit_push_and_sindri_writes(self) -> None:
        body = self.PATH.read_text().lower()
        # The prompt must explicitly prohibit these — subagent autonomy boundary.
        assert "do not commit" in body or "must not commit" in body
        assert "do not push" in body or "must not push" in body
        assert ".sindri/" in body  # must cite the forbidden write target
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_plugin_artifacts.py::TestExperimentSubagentPrompt -v`
Expected: 4 FAILs.

- [ ] **Step 3: Write the prompt template**

Create `prompts/experiment-subagent.md`:

```markdown
# Sindri experiment subagent

You are a fresh subagent running **one** optimization experiment for sindri. You have no memory of other experiments. Your only job: apply the candidate change, measure the result, return structured JSON.

## Context (filled by the orchestrator before you start)

```json
{
  "candidate": $CANDIDATE,
  "benchmark_cmd": "$BENCHMARK_CMD",
  "checks_cmd": "$CHECKS_CMD",
  "metric": $METRIC,
  "current_best": $CURRENT_BEST,
  "noise_floor": $NOISE_FLOOR,
  "mode": "$MODE",
  "reps_policy": $REPS_POLICY,
  "timeout_seconds": $TIMEOUT_SECONDS
}
```

## What you do (strict, no deviation)

### 1. Apply the candidate

Read `candidate.name` + `candidate.affects`. Make the code change the candidate describes. Examples:

- `"Replace moment with date-fns"` → uninstall moment, install date-fns, rewrite call sites, regenerate lockfile.
- `"Tree-shake lodash imports"` → rewrite `import _ from "lodash"` to `import debounce from "lodash/debounce"` per-method.
- `"Dynamic import heavy routes"` → wrap route imports in `React.lazy()` / `import()`.

If the candidate is ambiguous, interpret it in the most obvious direction. Do not ask the orchestrator — you are one-shot.

### 2. Run checks (if `checks_cmd` is non-empty)

```bash
<checks_cmd>
```

If it exits non-zero: return `status: check_failed`. Do not proceed.

### 3. Run the benchmark

Run `benchmark_cmd` 1 to `reps_policy.max` times, adaptively:

- **Mode `remote`**: run exactly 1 rep. `remote` metrics (CI time, deploys) are expensive; one reading is the budget.
- **Mode `local`**: start with `reps_policy.min` reps. Compute `delta = (mean - current_best) * (-1 if direction == "reduce" else 1)`. Compute `confidence_ratio = abs(delta) / max(noise_floor, 1e-9)`. If `confidence_ratio >= reps_policy.confidence_threshold`, stop. Otherwise add reps (up to `max`) until confident or max hit.

Parse the `METRIC <name>=<number>` line from each run (stdout last line). Ignore stderr.

Honor `timeout_seconds` — if any single benchmark invocation exceeds it, kill it and return `status: timeout`.

### 4. Decide status

| Condition | Status |
|---|---|
| `confidence_ratio >= 2.0` AND delta improves metric | `improved` |
| `confidence_ratio >= 2.0` AND delta worsens metric | `regressed` |
| `confidence_ratio < 2.0` | `inconclusive` |
| `checks_cmd` exited non-zero | `check_failed` |
| Benchmark crashed / unparseable output / candidate couldn't be applied | `errored` |
| Hit `timeout_seconds` on any run | `timeout` |

`direction: "reduce"` means lower is better. `direction: "increase"` means higher is better.

### 5. Return structured JSON on stdout

Print exactly one JSON object as your **final** output, matching this schema:

```json
{
  "metric_value": 719218,
  "reps_used": 3,
  "confidence_ratio": 4.2,
  "status": "improved",
  "files_modified": ["package.json", "src/utils/date.ts", "pnpm-lock.yaml"],
  "notes": "Swapped moment for date-fns; updated 4 call sites. Drop aligns with dep size removal."
}
```

Field rules:

- `metric_value`: the mean of all reps (or the single rep in remote mode). Number.
- `reps_used`: integer, ≥ 1.
- `confidence_ratio`: float, ≥ 0. (0 for `check_failed`/`errored`/`timeout`.)
- `status`: one of `improved`, `regressed`, `inconclusive`, `check_failed`, `errored`, `timeout`.
- `files_modified`: list of string paths, repo-relative. Empty if status is `errored` before any edit, or `check_failed`.
- `notes`: short free-text explanation. Max ~200 chars. Optional but strongly encouraged.

## Boundaries (non-negotiable)

- **Do not `git commit`.** The orchestrator owns all commit decisions.
- **Do not `git push`.** Ever.
- **Do not write to `.sindri/`** — `sindri.md`, `sindri.jsonl`, or any subdirectory. The orchestrator owns that state.
- **Do not mutate files outside the current working tree.** No `~/`, no `/tmp` writes that affect the repo.
- **Do not call `ScheduleWakeup`.** Only the orchestrator schedules.
- **Do not dispatch further `Task` subagents.** You are the leaf of the tree.

## What the orchestrator does after you return

- On `improved`: `git add -A && git commit`. Your changes become a kept commit.
- On anything else: `git reset --hard HEAD`. Your changes are discarded.

So if you write extra debug files or touch unrelated paths, they get reverted on non-improvement, but may leak into a kept commit on success. **Keep your edits tight to what the candidate demands.**

## Exit

Print the JSON, then end the conversation. Do not ask clarifying questions. Do not retry on failure — report the failure and exit.
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_plugin_artifacts.py::TestExperimentSubagentPrompt -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add prompts/experiment-subagent.md tests/unit/test_plugin_artifacts.py
git commit -m "feat(plugin): add experiment-subagent prompt template"
```

---

## Phase 4 — E2E stub test

These tests simulate a full sindri run in pytest — no Claude, no real subagent. The "subagent" is a Python function that returns canned JSON keyed on candidate name. The test drives the Plan 1 CLI (`python -m sindri ...`) the same way `sindri-loop` would, validating that the CLI protocol + state file semantics + git ops all compose correctly.

### Task 9: E2E fixture helpers

**Files:**
- Create: `tests/e2e/__init__.py` (empty)
- Create: `tests/e2e/conftest.py`
- Create: `tests/e2e/stub_subagent.py`

- [ ] **Step 1: Create the empty package init**

Create `tests/e2e/__init__.py` with empty content.

- [ ] **Step 2: Create the fixture helpers**

Create `tests/e2e/conftest.py`:

```python
"""E2E fixtures: build a throwaway target repo with a deterministic benchmark."""
from __future__ import annotations

import subprocess
from pathlib import Path
from textwrap import dedent

import pytest


@pytest.fixture
def target_repo(tmp_path: Path) -> Path:
    """Create a tiny git repo with a deterministic benchmark that counts lines.

    Layout:
        <tmp_path>/target/
          ├── src/
          │   ├── a.py        (10 lines)
          │   ├── b.py        (10 lines)
          │   └── c.py        (10 lines)
          └── .claude/scripts/sindri/benchmark.py
               — emits `METRIC lines=<total>` counting src/**/*.py.

    Each "candidate" that deletes a file drops the metric by ~10.
    """
    repo = tmp_path / "target"
    (repo / "src").mkdir(parents=True)
    for name in ("a", "b", "c"):
        (repo / "src" / f"{name}.py").write_text("x = 1\n" * 10, encoding="utf-8")

    bench_dir = repo / ".claude" / "scripts" / "sindri"
    bench_dir.mkdir(parents=True)
    bench = bench_dir / "benchmark.py"
    bench.write_text(
        dedent(
            '''\
            #!/usr/bin/env python3
            """Count total non-blank lines in src/**/*.py, emit METRIC lines=<n>."""
            from __future__ import annotations
            import sys
            from pathlib import Path


            def main() -> int:
                total = 0
                for p in sorted(Path("src").rglob("*.py")):
                    total += sum(1 for line in p.read_text().splitlines() if line.strip())
                print(f"METRIC lines={total}")
                return 0


            if __name__ == "__main__":
                sys.exit(main())
            '''
        ),
        encoding="utf-8",
    )
    bench.chmod(0o755)

    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=repo, check=True)
    return repo
```

- [ ] **Step 3: Create the stub subagent**

Create `tests/e2e/stub_subagent.py`:

```python
"""Stub experiment-subagent for E2E tests.

The real sindri-loop dispatches via `Task`; here we simulate that by mutating
the fixture repo directly, running the real benchmark, and returning JSON that
matches the pydantic SubagentResult schema.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class StubAction:
    """Recipe for a stubbed candidate outcome."""
    delete_file: str | None = None       # if set, rm this file before benchmark
    append_lines: int = 0                # if > 0, add lines to a scratch file
    force_error: bool = False            # if True, return errored without benchmarking
    force_timeout: bool = False          # if True, return timeout without benchmarking
    force_check_failed: bool = False     # if True, return check_failed without benchmarking
    files_modified: list[str] = field(default_factory=list)


def run_stub_experiment(
    repo: Path,
    candidate_name: str,
    recipe: StubAction,
    *,
    current_best: float,
    direction: str = "reduce",
    noise_floor: float = 0.01,
) -> dict:
    """Apply the recipe in-repo, measure, return a SubagentResult-shaped dict.

    Side effects on `repo` (meant to be reverted by the orchestrator sim via
    `git reset --hard HEAD` when status != "improved").
    """
    if recipe.force_error:
        return {
            "metric_value": 0.0,
            "reps_used": 0,
            "confidence_ratio": 0.0,
            "status": "errored",
            "files_modified": [],
            "notes": f"stub: forced error for {candidate_name}",
        }
    if recipe.force_timeout:
        return {
            "metric_value": 0.0,
            "reps_used": 0,
            "confidence_ratio": 0.0,
            "status": "timeout",
            "files_modified": [],
            "notes": f"stub: forced timeout for {candidate_name}",
        }
    if recipe.force_check_failed:
        return {
            "metric_value": 0.0,
            "reps_used": 0,
            "confidence_ratio": 0.0,
            "status": "check_failed",
            "files_modified": [],
            "notes": f"stub: forced check_failed for {candidate_name}",
        }

    if recipe.delete_file:
        (repo / recipe.delete_file).unlink(missing_ok=False)
    if recipe.append_lines > 0:
        scratch = repo / "src" / "_scratch.py"
        current = scratch.read_text() if scratch.exists() else ""
        scratch.write_text(current + ("y = 2\n" * recipe.append_lines))

    # Run the real benchmark in the fixture repo.
    out = subprocess.run(
        ["python", ".claude/scripts/sindri/benchmark.py"],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    last_line = out.stdout.strip().splitlines()[-1]
    assert last_line.startswith("METRIC lines="), f"unexpected benchmark output: {out.stdout!r}"
    metric_value = float(last_line.split("=")[1])

    # Deterministic ratio: the stub uses very low noise so even a single line
    # change is "confident". Confidence ratio = |delta| / max(noise_floor, eps).
    delta = (metric_value - current_best) * (-1 if direction == "reduce" else 1)
    confidence_ratio = abs(delta) / max(noise_floor, 1e-9)

    if confidence_ratio < 2.0:
        status = "inconclusive"
    elif delta > 0:
        status = "improved"
    else:
        status = "regressed"

    return {
        "metric_value": metric_value,
        "reps_used": 1,
        "confidence_ratio": confidence_ratio,
        "status": status,
        "files_modified": recipe.files_modified or (
            [recipe.delete_file] if recipe.delete_file else (
                ["src/_scratch.py"] if recipe.append_lines else []
            )
        ),
        "notes": f"stub: {candidate_name}",
    }


def build_record_payload(
    *, candidate_id: int, metric_before: float, subagent_result: dict, commit_sha: str | None
) -> str:
    """Serialize the exact JSON that `python -m sindri record-result` expects on stdin."""
    return json.dumps({
        "candidate_id": candidate_id,
        "metric_before": metric_before,
        "subagent_result": subagent_result,
        "commit_sha": commit_sha,
    })
```

- [ ] **Step 4: No test to run yet — helpers are scaffolding. Commit.**

```bash
git add tests/e2e/__init__.py tests/e2e/conftest.py tests/e2e/stub_subagent.py
git commit -m "test(e2e): add fixture repo + stub subagent helpers"
```

---

### Task 10: E2E happy-path test (target hit → auto-finalize)

**Files:**
- Create: `tests/e2e/test_loop_end_to_end.py`

- [ ] **Step 1: Write the failing test**

Create `tests/e2e/test_loop_end_to_end.py`:

```python
"""End-to-end simulation of a sindri run.

The test drives `python -m sindri <subcmd>` the same way the sindri-loop skill
would, replacing the Task-based subagent dispatch with `run_stub_experiment`.
Validates that CLI protocol + state + git ops compose correctly across a full
lifecycle: init → N wakeups → terminate.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.e2e.stub_subagent import StubAction, build_record_payload, run_stub_experiment


def _sindri(repo: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    """Run `python -m sindri ...` inside `repo`."""
    env = os.environ.copy()
    return subprocess.run(
        [sys.executable, "-m", "sindri", *args],
        cwd=repo, input=stdin, capture_output=True, text=True, env=env,
    )


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True,
    ).stdout


def _count_counters(repo: Path) -> tuple[int, int]:
    """Return (experiments_run, consecutive_reverts) from the jsonl tail."""
    path = repo / ".sindri" / "current" / "sindri.jsonl"
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    experiments = [r for r in records if r.get("type") == "experiment"]
    experiments_run = len(experiments)
    consecutive_reverts = 0
    for exp in reversed(experiments):
        if exp["status"] == "improved":
            break
        if exp["status"] in ("regressed", "inconclusive", "errored", "timeout"):
            consecutive_reverts += 1
        else:
            break
    return experiments_run, consecutive_reverts


def _check_termination(repo: Path) -> dict:
    exp_run, rev = _count_counters(repo)
    payload = json.dumps({"experiments_run": exp_run, "consecutive_reverts": rev})
    r = _sindri(repo, "check-termination", stdin=payload)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _current_metric_before(repo: Path) -> float:
    state = json.loads(_sindri(repo, "read-state").stdout)
    cb = state.get("current_best")
    return float(cb) if cb is not None else float(state["baseline"]["value"])


@pytest.mark.e2e
def test_happy_path_target_hit(target_repo: Path) -> None:
    """3 file deletions drive metric 30 → 20 → 10 → 0; target 99% forces all 3 kept before target_hit."""
    pool = [
        {"id": 1, "name": "delete a.py", "expected_impact_pct": -33, "files": ["src/a.py"]},
        {"id": 2, "name": "delete b.py", "expected_impact_pct": -33, "files": ["src/b.py"]},
        {"id": 3, "name": "delete c.py", "expected_impact_pct": -33, "files": ["src/c.py"]},
    ]
    r = _sindri(
        target_repo, "init",
        "--goal", "reduce lines by 99%",
        "--pool-json", json.dumps(pool),
        "--script", ".claude/scripts/sindri/benchmark.py",
    )
    assert r.returncode == 0, r.stderr
    init_out = json.loads(r.stdout)
    assert init_out["ok"] is True
    assert init_out["baseline"] == 30.0

    recipes = {
        "delete a.py": StubAction(delete_file="src/a.py", files_modified=["src/a.py"]),
        "delete b.py": StubAction(delete_file="src/b.py", files_modified=["src/b.py"]),
        "delete c.py": StubAction(delete_file="src/c.py", files_modified=["src/c.py"]),
    }

    for _ in range(10):  # safety bound
        term = _check_termination(target_repo)
        if term["terminated"]:
            break

        # Pre-flight git
        if _git(target_repo, "status", "--porcelain").strip():
            subprocess.run(["git", "reset", "--hard", "HEAD"], cwd=target_repo, check=True)

        nxt = _sindri(target_repo, "pick-next")
        assert nxt.returncode == 0, nxt.stderr
        cand = json.loads(nxt.stdout)
        if cand is None:
            break

        metric_before = _current_metric_before(target_repo)
        result = run_stub_experiment(
            target_repo, cand["name"], recipes[cand["name"]],
            current_best=metric_before,
        )

        commit_sha: str | None = None
        if result["status"] == "improved":
            subprocess.run(["git", "add", "-A"], cwd=target_repo, check=True)
            subprocess.run(
                ["git", "commit", "-q", "-m",
                 f"kept: {cand['name']} (Δ{result['metric_value'] - metric_before})"],
                cwd=target_repo, check=True,
            )
            commit_sha = _git(target_repo, "rev-parse", "HEAD").strip()
        else:
            subprocess.run(["git", "reset", "--hard", "HEAD"], cwd=target_repo, check=True)

        payload = build_record_payload(
            candidate_id=cand["id"],
            metric_before=metric_before,
            subagent_result=result,
            commit_sha=commit_sha,
        )
        rec = _sindri(target_repo, "record-result", stdin=payload)
        assert rec.returncode == 0, rec.stderr

    # Final assertions
    final_term = _check_termination(target_repo)
    assert final_term["terminated"] is True
    assert final_term["reason"] in ("target_hit", "pool_empty"), final_term
    assert final_term["auto_finalize"] is True, final_term

    log = _git(target_repo, "log", "--oneline").splitlines()
    kept = [line for line in log if "kept:" in line]
    assert len(kept) == 3, f"expected 3 kept commits, got: {log}"

    jsonl = [
        json.loads(line)
        for line in (target_repo / ".sindri" / "current" / "sindri.jsonl").read_text().splitlines()
        if line.strip()
    ]
    experiments = [r for r in jsonl if r.get("type") == "experiment"]
    assert len(experiments) == 3, experiments
    assert all(e["status"] == "improved" for e in experiments)
    assert experiments[-1]["metric_after"] == 0.0  # all 3 files deleted
```

- [ ] **Step 2: Register the `e2e` marker**

Edit `pyproject.toml`, under `[tool.pytest.ini_options]`, add markers:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
pythonpath = ["src"]
addopts = "-ra --strict-markers"
markers = [
    "e2e: full-lifecycle simulation tests (slow; ~10s+)",
]
```

- [ ] **Step 3: Run the test**

Run: `pytest tests/e2e/test_loop_end_to_end.py::test_happy_path_target_hit -v -s`

Expected: PASS. If it fails, the failure reveals a gap between the plan's assumptions about Plan 1's CLI and its real behavior — fix the gap in the test (not by silently adjusting the plan), and re-run.

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/test_loop_end_to_end.py pyproject.toml
git commit -m "test(e2e): happy-path full-lifecycle simulation (target hit, 3 kept)"
```

---

### Task 11: E2E terminal-condition tests

**Files:**
- Modify: `tests/e2e/test_loop_end_to_end.py`

- [ ] **Step 1: Write additional failing tests**

Append to `tests/e2e/test_loop_end_to_end.py`:

```python
@pytest.mark.e2e
def test_pool_exhausted_no_wins(target_repo: Path) -> None:
    """All candidates regress → terminate with pool_empty, auto_finalize=False, no PR."""
    pool = [
        {"id": 1, "name": "bloat a", "expected_impact_pct": -5, "files": []},
        {"id": 2, "name": "bloat b", "expected_impact_pct": -5, "files": []},
    ]
    r = _sindri(
        target_repo, "init",
        "--goal", "reduce lines by 50%",
        "--pool-json", json.dumps(pool),
        "--script", ".claude/scripts/sindri/benchmark.py",
    )
    assert r.returncode == 0, r.stderr

    recipes = {
        "bloat a": StubAction(append_lines=5, files_modified=["src/_scratch.py"]),
        "bloat b": StubAction(append_lines=5, files_modified=["src/_scratch.py"]),
    }

    for _ in range(5):
        term = _check_termination(target_repo)
        if term["terminated"]:
            break
        if _git(target_repo, "status", "--porcelain").strip():
            subprocess.run(["git", "reset", "--hard", "HEAD"], cwd=target_repo, check=True)
        cand = json.loads(_sindri(target_repo, "pick-next").stdout)
        if cand is None:
            break
        metric_before = _current_metric_before(target_repo)
        result = run_stub_experiment(
            target_repo, cand["name"], recipes[cand["name"]], current_best=metric_before,
        )
        # All regress → always reset.
        subprocess.run(["git", "reset", "--hard", "HEAD"], cwd=target_repo, check=True)
        payload = build_record_payload(
            candidate_id=cand["id"], metric_before=metric_before,
            subagent_result=result, commit_sha=None,
        )
        _sindri(target_repo, "record-result", stdin=payload)

    term = _check_termination(target_repo)
    assert term["terminated"] is True
    assert term["reason"] == "pool_empty", term
    assert term["auto_finalize"] is False, term

    log = _git(target_repo, "log", "--oneline").splitlines()
    kept = [line for line in log if "kept:" in line]
    assert kept == [], f"expected no kept commits, got: {kept}"


@pytest.mark.e2e
def test_check_failed_not_retried(target_repo: Path) -> None:
    """A candidate that check_fails must be marked dead after one run, not retried."""
    pool = [{"id": 1, "name": "fails checks", "expected_impact_pct": -10, "files": []}]
    r = _sindri(
        target_repo, "init",
        "--goal", "reduce lines by 10%",
        "--pool-json", json.dumps(pool),
        "--script", ".claude/scripts/sindri/benchmark.py",
    )
    assert r.returncode == 0, r.stderr

    cand = json.loads(_sindri(target_repo, "pick-next").stdout)
    metric_before = _current_metric_before(target_repo)
    result = run_stub_experiment(
        target_repo, cand["name"], StubAction(force_check_failed=True),
        current_best=metric_before,
    )
    assert result["status"] == "check_failed"
    payload = build_record_payload(
        candidate_id=cand["id"], metric_before=metric_before,
        subagent_result=result, commit_sha=None,
    )
    rec = _sindri(target_repo, "record-result", stdin=payload)
    assert rec.returncode == 0, rec.stderr

    # After record-result, pick-next must return null (check_failed is terminal per-candidate).
    nxt = _sindri(target_repo, "pick-next").stdout.strip()
    assert nxt == "null", f"check_failed candidate was re-picked: {nxt!r}"
```

- [ ] **Step 2: Run the tests**

Run: `pytest tests/e2e/test_loop_end_to_end.py -v`

Expected: all 3 tests PASS. If any fails, the failure is likely in the Plan 1 CLI behavior under these edge cases — file a bug against the Plan 1 module (note in `lessons.md`) and fix narrowly before continuing.

- [ ] **Step 3: Commit**

```bash
git add tests/e2e/test_loop_end_to_end.py
git commit -m "test(e2e): pool-exhausted + check-failed terminal conditions"
```

---

## Phase 5 — Smoke, CI, release

### Task 12: `scripts/smoke.sh`

**Files:**
- Create: `scripts/smoke.sh`

- [ ] **Step 1: Write the smoke script**

Create `scripts/smoke.sh`:

```bash
#!/usr/bin/env bash
# sindri manual smoke test
# Runs the full Python-level lifecycle in a disposable temp repo — no Claude, no PR.
# This is the "did I break the plumbing" check before pushing.
#
# Usage: ./scripts/smoke.sh
# Exit 0 on success, non-zero on any failure.

set -euo pipefail

SINDRI_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo ">> temp repo: $TMP"
cd "$TMP"
git init -q
git config user.email "smoke@example.com"
git config user.name "Smoke"
mkdir -p src .claude/scripts/sindri
for f in a b c; do printf 'x = 1\n%.0s' {1..10} > "src/${f}.py"; done
cat > .claude/scripts/sindri/benchmark.py <<'PY'
#!/usr/bin/env python3
from pathlib import Path
total = sum(1 for p in Path("src").rglob("*.py") for ln in p.read_text().splitlines() if ln.strip())
print(f"METRIC lines={total}")
PY
chmod +x .claude/scripts/sindri/benchmark.py
git add -A && git commit -q -m "seed"

export PYTHONPATH="$SINDRI_REPO/src:${PYTHONPATH:-}"

POOL_JSON='[{"id":1,"name":"dummy","expected_impact_pct":-10,"files":[]}]'

echo ">> sindri init"
python -m sindri init \
  --goal "reduce lines by 10%" \
  --pool-json "$POOL_JSON" \
  --script .claude/scripts/sindri/benchmark.py

echo ">> validate-benchmark"
python -m sindri validate-benchmark

echo ">> detect-mode"
python -m sindri detect-mode --script .claude/scripts/sindri/benchmark.py

echo ">> read-state (should return JSON)"
python -m sindri read-state | python -c "import json, sys; print('  pool size:', len(json.load(sys.stdin).get('pool', [])))"

echo ">> pick-next"
python -m sindri pick-next

echo ">> check-termination (needs counters on stdin)"
echo '{"experiments_run": 0, "consecutive_reverts": 0}' | python -m sindri check-termination

echo ">> status"
python -m sindri status

echo ">> OK — plumbing works."
```

- [ ] **Step 2: Make it executable + run it**

```bash
chmod +x scripts/smoke.sh
./scripts/smoke.sh
```

Expected: exits 0 with `OK — plumbing works.` If it fails, the CLI has a regression — fix in Plan 1 territory before proceeding.

- [ ] **Step 3: Commit**

```bash
git add scripts/smoke.sh
git commit -m "test(smoke): add manual plumbing smoke script"
```

---

### Task 13: `.github/workflows/ci.yml`

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Write the workflow**

Create `.github/workflows/ci.yml`:

```yaml
name: ci

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    name: pytest (${{ matrix.python-version }})
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.10", "3.11", "3.12"]

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
          cache: pip

      - name: Configure git (required for git_ops + e2e)
        run: |
          git config --global user.email "ci@sindri.local"
          git config --global user.name "Sindri CI"

      - name: Install
        run: |
          python -m pip install --upgrade pip
          pip install -e ".[dev]"

      - name: Fast tests (unit + integration, skip e2e)
        run: pytest -m "not e2e" -q

      - name: End-to-end tests
        if: matrix.python-version == '3.12'
        run: pytest -m e2e -q

      - name: Smoke
        if: matrix.python-version == '3.12'
        run: ./scripts/smoke.sh
```

- [ ] **Step 2: Validate the YAML parses**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`
Expected: no output (success).

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add pytest + smoke workflow (py3.10-3.12)"
```

The workflow validates itself on the first push. If it fails in Actions after pushing, fix narrowly and recommit.

---

### Task 14: Milestone commit + tag `v0.2.0-plugin`

**Files:**
- None (tag only)

- [ ] **Step 1: Full test pass**

Run: `pytest -q && ./scripts/smoke.sh`
Expected: all green.

- [ ] **Step 2: Push the branch**

```bash
git push -u origin feat/sindri-plugin-artifacts-plan2
```

Wait for CI to go green. If it fails, fix and recommit before tagging.

- [ ] **Step 3: Open the PR**

```bash
gh pr create \
  --base main \
  --title "feat(plugin): sindri plugin artifacts (Plan 2)" \
  --body "$(cat <<'EOF'
## Summary

- Plugin manifest, `/sindri` slash command, 4 skills (`sindri-start`, `sindri-scaffold-benchmark`, `sindri-loop`, `sindri-finalize`), experiment-subagent prompt template.
- E2E pytest that stubs the subagent and drives the full lifecycle through the Plan 1 CLI.
- Manual smoke script (`scripts/smoke.sh`) for local plumbing checks.
- GitHub Actions CI (pytest matrix py3.10-3.12 + e2e + smoke on 3.12).
- README with install + quickstart.

## Test plan

- [ ] pytest -q (all layers green locally)
- [ ] ./scripts/smoke.sh exits 0
- [ ] CI workflow green on first push
- [ ] Symlink plugin into ~/.claude/plugins/sindri, restart Claude Code, run `/sindri status` → reports "no active run"
- [ ] `/sindri reduce LOC by 5%` on a small scratch repo → skill invokes, pool proposed, abort with /sindri clear

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Tag after merge**

After the PR merges to `main`:

```bash
git checkout main && git pull --ff-only origin main
git tag -a v0.2.0-plugin -m "Plugin artifacts milestone (Plan 2 complete)"
git push origin v0.2.0-plugin
```

- [ ] **Step 5: Archive the plan**

```bash
mkdir -p progress/archive
mv docs/superpowers/plans/2026-04-19-sindri-plugin-artifacts.md progress/archive/plan-2-sindri-plugin-artifacts.md
# OR keep it under docs/superpowers/plans/ — same pattern as Plan 1 archival. Choose consistent with Plan 1's resting place.
git add progress/archive/
git commit -m "chore: archive Plan 2"
git push origin main
```

**Plan 2 produces:**

- Installable Claude Code plugin (`.claude-plugin/plugin.json` + `commands/` + `skills/` + `prompts/`)
- 4 skills covering the full lifecycle (start → loop → finalize, plus scaffolder)
- Experiment subagent prompt template with explicit input/output contract
- E2E pytest that runs the full CLI-level lifecycle in ~10s with a stub subagent
- Manual smoke script for plumbing regression checks
- CI matrix (py3.10-3.12) + e2e + smoke
- Plugin README with install, quickstart, architecture, dev commands

**What's still needed beyond Plan 2 (v2 territory per design spec §12.2):**

- Remote / scheduled execution (CronCreate-based wake-ups on GHA runners)
- Parallel subagent dispatch for file-disjoint experiments
- Custom pool-ordering heuristics (Bayesian bandits)
- Concurrent runs per repo
- Windows support
- Automatic PR merging

After Plan 2 merges, sindri is feature-complete for v1: a bounded, target-driven, single-session optimization plugin.

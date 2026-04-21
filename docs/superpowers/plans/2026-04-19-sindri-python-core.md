# Sindri Python Core + CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the deterministic Python core package for sindri and expose it as a CLI (`python -m sindri <subcommand>`), test-driven throughout. Produces a standalone, shippable Python package that later plans will wrap with Claude Code skills and a slash command.

**Architecture:** One Python package (`src/sindri/`) with 9 core modules + an argparse CLI. Pure functions first (no I/O), then I/O (state files, git subprocess), then CLI dispatcher. Every module designed by tests written first; pydantic v2 enforces the JSON schemas that pass between CLI and future skills.

**Tech Stack:** Python 3.10+, pydantic ≥2, pytest + pytest-mock + pytest-cov, `uv` as the package manager. Zero other runtime deps.

---

## Table of Contents

- [File structure](#file-structure)
- [Prerequisites](#prerequisites)
- [Phase 1 — Scaffolding + validators](#phase-1--scaffolding--validators)
  - [Task 1: Project scaffolding](#task-1-project-scaffolding)
  - [Task 2: Pydantic models (validators)](#task-2-pydantic-models-validators)
- [Phase 2 — Pure-function core modules](#phase-2--pure-function-core-modules)
  - [Task 3: Metric parsing (`core/metric.py`)](#task-3-metric-parsing-coremetricpy)
  - [Task 4: Statistics (`core/noise.py`)](#task-4-statistics-corenoisepy)
  - [Task 5: Pool + termination predicates (`core/pool.py`)](#task-5-pool--termination-predicates-corepoolpy)
  - [Task 6: Mode detection (`core/modes.py`)](#task-6-mode-detection-coremodespy)
  - [Task 7: Termination decision table (`core/termination.py`)](#task-7-termination-decision-table-coreterminationpy)
- [Phase 3 — I/O core modules](#phase-3--io-core-modules)
  - [Task 8: State files (`core/state.py`)](#task-8-state-files-corestatepy)
  - [Task 9: Git operations (`core/git_ops.py`)](#task-9-git-operations-coregit_opspy)
  - [Task 10: PR body rendering (`core/pr_body.py`)](#task-10-pr-body-rendering-corepr_bodypy)
- [Phase 4 — CLI](#phase-4--cli)
  - [Task 11: CLI skeleton + dispatcher](#task-11-cli-skeleton--dispatcher)
  - [Task 12: CLI `validate-benchmark`](#task-12-cli-validate-benchmark)
  - [Task 13: CLI `detect-mode`](#task-13-cli-detect-mode)
  - [Task 14: CLI `read-state`](#task-14-cli-read-state)
  - [Task 15: CLI `pick-next`](#task-15-cli-pick-next)
  - [Task 16: CLI `record-result`](#task-16-cli-record-result)
  - [Task 17: CLI `check-termination`](#task-17-cli-check-termination)
  - [Task 18: CLI `generate-pr-body`](#task-18-cli-generate-pr-body)
  - [Task 19: CLI `archive`](#task-19-cli-archive)
  - [Task 20: CLI `status`](#task-20-cli-status)
  - [Task 21: CLI `init` (end-to-end init wiring)](#task-21-cli-init-end-to-end-init-wiring)
- [Milestone checkpoint](#milestone-checkpoint)

---

## File structure

Everything created by this plan:

```
sindri/
├── pyproject.toml                           # NEW — package metadata, deps
├── .python-version                          # NEW — uv floor (3.10)
├── src/
│   └── sindri/
│       ├── __init__.py                       # NEW
│       ├── __main__.py                       # NEW — entry for `python -m sindri`
│       ├── cli.py                            # NEW — argparse dispatcher
│       └── core/
│           ├── __init__.py                   # NEW
│           ├── validators.py                 # NEW — pydantic models
│           ├── metric.py                     # NEW — METRIC line parsing
│           ├── noise.py                      # NEW — baseline stats, confidence
│           ├── pool.py                       # NEW — candidate ordering
│           ├── modes.py                      # NEW — local/remote detection
│           ├── termination.py                # NEW — termination decision table
│           ├── state.py                      # NEW — read/write md + jsonl
│           ├── git_ops.py                    # NEW — git subprocess wrappers
│           └── pr_body.py                    # NEW — render PR markdown
├── tests/
│   ├── __init__.py                           # NEW
│   ├── conftest.py                           # NEW — shared fixtures
│   ├── unit/
│   │   ├── __init__.py                       # NEW
│   │   ├── test_validators.py                # NEW
│   │   ├── test_metric.py                    # NEW
│   │   ├── test_noise.py                     # NEW
│   │   ├── test_pool.py                      # NEW
│   │   ├── test_modes.py                     # NEW
│   │   ├── test_termination.py               # NEW
│   │   └── test_pr_body.py                   # NEW
│   ├── integration/
│   │   ├── __init__.py                       # NEW
│   │   ├── test_state.py                     # NEW
│   │   ├── test_git_ops.py                   # NEW
│   │   └── test_cli.py                       # NEW
│   └── fixtures/
│       ├── __init__.py                       # NEW
│       ├── sample_state.py                   # NEW — constructors for test states
│       └── sample_jsonl/
│           └── example_run.jsonl             # NEW — sample run data for PR body test
```

Everything in `src/sindri/core/` is pure library code — imported and tested in isolation. `cli.py` is the only module that reads `sys.argv`, touches stdin/stdout at the process boundary, and wires arguments through to the core.

Tests mirror the package structure. `tests/unit/` holds pure-function tests (fast, no disk/git). `tests/integration/` holds tests that hit the filesystem (state files) or invoke real git in temp directories.

## Prerequisites

The executing engineer needs these tools already installed:

- **Python 3.10+** — verify with `python3 --version`
- **uv** — verify with `uv --version`; if missing install with `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **git ≥ 2.30** — verify with `git --version`
- **`gh` CLI** — not required for this plan (only for Plan 2), but check: `gh --version`

Run verification:

```bash
python3 --version && uv --version && git --version
```

If any fail, stop and resolve before proceeding.

---

## Phase 1 — Scaffolding + validators

Goal of this phase: project is installable with `uv sync`, tests can be run with `pytest`, and every downstream module's types exist as pydantic models.

### Task 1: Project scaffolding

**Files:**

- Create: `pyproject.toml`
- Create: `.python-version`
- Create: `src/sindri/__init__.py`
- Create: `src/sindri/core/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/unit/__init__.py`
- Create: `tests/integration/__init__.py`
- Create: `tests/fixtures/__init__.py`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "sindri"
version = "0.1.0"
description = "Claude Code plugin core: bounded, target-driven optimization loops"
requires-python = ">=3.10"
readme = "README.md"
license = {text = "MIT"}
authors = [{name = "4KMetrics"}]
dependencies = [
    "pydantic>=2.0,<3.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-mock>=3.12",
    "pytest-cov>=4.1",
]

[tool.hatch.build.targets.wheel]
packages = ["src/sindri"]

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
pythonpath = ["src"]
addopts = "-ra --strict-markers"

[tool.coverage.run]
source = ["src/sindri"]
branch = true

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "if __name__ == .__main__.:",
    "raise NotImplementedError",
]
```

- [ ] **Step 2: Write `.python-version`**

```
3.10
```

- [ ] **Step 3: Create empty package marker files**

Create these four files, each containing only a single newline:

```bash
mkdir -p src/sindri/core tests/unit tests/integration tests/fixtures
touch src/sindri/__init__.py src/sindri/core/__init__.py
touch tests/__init__.py tests/unit/__init__.py tests/integration/__init__.py tests/fixtures/__init__.py
```

- [ ] **Step 4: Write `tests/conftest.py`**

```python
"""Shared pytest fixtures across the whole suite."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_sindri_dir(tmp_path: Path) -> Path:
    """A temp directory with the standard .sindri/current layout pre-created."""
    sindri_dir = tmp_path / ".sindri" / "current"
    sindri_dir.mkdir(parents=True)
    return sindri_dir


@pytest.fixture
def tmp_git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A temp directory initialized as a git repo with one initial commit on main.

    The current working directory is set to the repo root for the duration of the test.
    """
    import subprocess

    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-b", "main"], check=True, capture_output=True, cwd=tmp_path)
    subprocess.run(["git", "config", "user.email", "test@example.com"], check=True, cwd=tmp_path)
    subprocess.run(["git", "config", "user.name", "Test"], check=True, cwd=tmp_path)
    # Initial commit so the repo has a HEAD
    (tmp_path / "README.md").write_text("# test\n")
    subprocess.run(["git", "add", "README.md"], check=True, cwd=tmp_path)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        check=True,
        capture_output=True,
        cwd=tmp_path,
    )
    return tmp_path
```

- [ ] **Step 5: Run `uv sync --dev` to install dependencies**

```bash
uv sync --all-extras
```

Expected: `uv.lock` generated, `.venv/` created, pydantic + pytest installed. If this fails, fix before proceeding.

- [ ] **Step 6: Verify pytest can run (zero tests yet)**

```bash
uv run pytest
```

Expected output ends with: `no tests ran`. If it errors on import, fix before proceeding.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .python-version src/ tests/ uv.lock
git commit -m "chore: scaffold sindri python package with uv + pytest"
```

---

### Task 2: Pydantic models (validators)

Every later module imports from `sindri.core.validators`. We define the JSON schemas used across the CLI/skill boundary here, once, authoritatively.

**Files:**

- Create: `src/sindri/core/validators.py`
- Test: `tests/unit/test_validators.py`

- [ ] **Step 1: Write failing tests for `Goal` model**

`tests/unit/test_validators.py`:

```python
"""Unit tests for pydantic models in sindri.core.validators."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from sindri.core.validators import (
    Baseline,
    Candidate,
    Goal,
    Guardrails,
    JsonlBaseline,
    JsonlBaselineComplete,
    JsonlEvent,
    JsonlExperiment,
    JsonlSessionStart,
    JsonlTerminated,
    RepsPolicy,
    SindriState,
    SubagentResult,
)


class TestGoal:
    def test_reduce_goal_parses(self) -> None:
        g = Goal(metric_name="bundle_bytes", direction="reduce", target_pct=15.0)
        assert g.metric_name == "bundle_bytes"
        assert g.direction == "reduce"
        assert g.target_pct == 15.0

    def test_increase_goal_parses(self) -> None:
        g = Goal(metric_name="lighthouse_score", direction="increase", target_pct=20.0)
        assert g.direction == "increase"

    def test_invalid_direction_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Goal(metric_name="x", direction="sideways", target_pct=10.0)  # type: ignore[arg-type]

    def test_target_pct_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            Goal(metric_name="x", direction="reduce", target_pct=-5.0)

    def test_metric_name_must_be_snake_case(self) -> None:
        with pytest.raises(ValidationError):
            Goal(metric_name="Bundle Bytes", direction="reduce", target_pct=15.0)
```

- [ ] **Step 2: Run tests — expect import failure**

```bash
uv run pytest tests/unit/test_validators.py -v
```

Expected: `ImportError` or `ModuleNotFoundError` on the imports — none of these models exist yet.

- [ ] **Step 3: Write minimal implementation to make Goal tests pass**

`src/sindri/core/validators.py` (start of file — we'll add more models in later steps):

```python
"""Pydantic models — the authoritative schemas across sindri's boundaries.

Every value that crosses between the CLI and its callers (skills, shell, etc.)
passes through one of these models. Schema drift fails fast.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SNAKE_CASE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class Goal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric_name: str
    direction: Literal["reduce", "increase"]
    target_pct: float = Field(gt=0, description="Percentage delta to reach (always positive)")

    @field_validator("metric_name")
    @classmethod
    def _snake_case_only(cls, v: str) -> str:
        if not SNAKE_CASE_RE.match(v):
            raise ValueError(f"metric_name must be snake_case, got {v!r}")
        return v
```

- [ ] **Step 4: Run Goal tests — expect PASS**

```bash
uv run pytest tests/unit/test_validators.py::TestGoal -v
```

Expected: 5 tests pass.

- [ ] **Step 5: Write failing tests for `Baseline`, `Candidate`, `Guardrails`, `RepsPolicy`, `SindriState`**

Append to `tests/unit/test_validators.py`:

```python
class TestBaseline:
    def test_baseline_parses(self) -> None:
        b = Baseline(value=842000.0, noise_floor=870.0, samples=[843100.0, 841400.0, 842500.0])
        assert b.value == 842000.0
        assert b.noise_floor == 870.0
        assert len(b.samples) == 3

    def test_negative_noise_floor_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Baseline(value=100.0, noise_floor=-1.0, samples=[100.0, 101.0, 99.0])

    def test_samples_must_be_at_least_2(self) -> None:
        with pytest.raises(ValidationError):
            Baseline(value=100.0, noise_floor=1.0, samples=[100.0])


class TestCandidate:
    def test_candidate_parses(self) -> None:
        c = Candidate(id=1, name="Replace moment", expected_impact_pct=-10.0)
        assert c.status == "pending"  # default
        assert c.files == []

    def test_status_enum_enforced(self) -> None:
        with pytest.raises(ValidationError):
            Candidate(id=1, name="x", expected_impact_pct=-5.0, status="maybe")  # type: ignore[arg-type]


class TestRepsPolicy:
    def test_local_defaults(self) -> None:
        p = RepsPolicy(mode="local")
        assert p.min == 1
        assert p.max == 10
        assert p.adaptive is True
        assert p.confidence_threshold == 2.0

    def test_remote_defaults(self) -> None:
        p = RepsPolicy(mode="remote")
        assert p.max == 1
        assert p.adaptive is False


class TestGuardrails:
    def test_defaults_local(self) -> None:
        g = Guardrails(mode="local")
        assert g.max_experiments == 50
        assert g.max_wall_clock_seconds == 28800  # 8h
        assert g.max_reverts_in_a_row == 7
        assert g.baseline_reps == 3
        assert g.reps_policy.adaptive is True

    def test_defaults_remote(self) -> None:
        g = Guardrails(mode="remote")
        assert g.max_wall_clock_seconds == 259200  # 72h
        assert g.reps_policy.adaptive is False


class TestSindriState:
    def test_minimal_state(self) -> None:
        s = SindriState(
            goal=Goal(metric_name="x", direction="reduce", target_pct=10.0),
            baseline=Baseline(value=100.0, noise_floor=1.0, samples=[100.0, 101.0, 99.0]),
            pool=[Candidate(id=1, name="a", expected_impact_pct=-5.0)],
            branch="sindri/reduce-x-10pct",
            started_at=datetime(2026, 4, 19, 10, 0, 0),
            guardrails=Guardrails(mode="local"),
            mode="local",
        )
        assert s.goal.metric_name == "x"
        assert len(s.pool) == 1
```

- [ ] **Step 6: Run tests — expect failures for missing models**

```bash
uv run pytest tests/unit/test_validators.py -v
```

Expected: `TestGoal` passes; everything else fails on import.

- [ ] **Step 7: Add the remaining models**

Append to `src/sindri/core/validators.py`:

```python
class Baseline(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float
    noise_floor: float = Field(ge=0)
    samples: list[float] = Field(min_length=2, description="All raw baseline runs (run 1 may be warmup)")


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    expected_impact_pct: float
    status: Literal["pending", "kept", "reverted", "errored", "check_failed"] = "pending"
    files: list[str] = Field(default_factory=list)
    notes: str | None = None


class RepsPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["local", "remote"]
    min: int = 1
    max: int = 10
    adaptive: bool = True
    confidence_threshold: float = 2.0

    def model_post_init(self, __context: object) -> None:
        # Enforce mode-specific defaults unless explicitly overridden by caller
        if self.mode == "remote":
            # remote mode is single-rep
            if self.max > 1:
                object.__setattr__(self, "max", 1)
            object.__setattr__(self, "adaptive", False)


class Guardrails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["local", "remote"]
    max_experiments: int = 50
    max_wall_clock_seconds: int = 28800  # 8h for local
    max_reverts_in_a_row: int = 7
    baseline_reps: int = 3
    timeout_per_experiment_seconds: int = 1800  # 30m for local
    reps_policy: RepsPolicy | None = None

    def model_post_init(self, __context: object) -> None:
        if self.reps_policy is None:
            object.__setattr__(self, "reps_policy", RepsPolicy(mode=self.mode))
        if self.mode == "remote":
            if self.max_wall_clock_seconds == 28800:
                object.__setattr__(self, "max_wall_clock_seconds", 259200)  # 72h
            if self.timeout_per_experiment_seconds == 1800:
                object.__setattr__(self, "timeout_per_experiment_seconds", 7200)  # 2h


class SindriState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: Goal
    baseline: Baseline
    pool: list[Candidate]
    branch: str
    started_at: datetime
    guardrails: Guardrails
    mode: Literal["local", "remote"]
    current_best: float | None = None
```

- [ ] **Step 8: Run tests — expect PASS**

```bash
uv run pytest tests/unit/test_validators.py -v
```

Expected: all Baseline/Candidate/RepsPolicy/Guardrails/SindriState tests pass.

- [ ] **Step 9: Write failing tests for JSONL record types and SubagentResult**

Append to `tests/unit/test_validators.py`:

```python
class TestSubagentResult:
    def test_valid_improved_result(self) -> None:
        r = SubagentResult(
            metric_value=760000.0,
            reps_used=3,
            confidence_ratio=4.2,
            status="improved",
            files_modified=["package.json"],
            notes="Swapped dep",
        )
        assert r.status == "improved"

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SubagentResult(  # type: ignore[call-arg]
                metric_value=1.0,
                reps_used=1,
                confidence_ratio=1.0,
                status="maybe",
                files_modified=[],
            )

    def test_reps_used_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            SubagentResult(
                metric_value=1.0,
                reps_used=0,
                confidence_ratio=1.0,
                status="improved",
                files_modified=[],
            )


class TestJsonlRecords:
    def test_session_start(self) -> None:
        r = JsonlSessionStart(
            ts=datetime(2026, 4, 19, 10, 0),
            goal="reduce bundle_bytes by 15%",
            target_pct=-15.0,
            mode="local",
        )
        assert r.type == "session_start"

    def test_baseline_run(self) -> None:
        r = JsonlBaseline(ts=datetime.now(), run_index=1, value=842.0, is_warmup=True)
        assert r.type == "baseline"

    def test_baseline_complete(self) -> None:
        r = JsonlBaselineComplete(ts=datetime.now(), mean=842.0, noise_floor=0.78)
        assert r.type == "baseline_complete"

    def test_experiment(self) -> None:
        r = JsonlExperiment(
            ts=datetime.now(),
            id=1,
            candidate="Replace moment",
            reps_used=3,
            metric_before=842.0,
            metric_after=760.0,
            delta=-82.0,
            confidence_ratio=4.2,
            status="improved",
            commit_sha="abc1234",
            files_modified=["package.json"],
        )
        assert r.type == "experiment"

    def test_event(self) -> None:
        r = JsonlEvent(ts=datetime.now(), event="halted", reason="max_reverts", details="7 in a row")
        assert r.type == "event"

    def test_terminated(self) -> None:
        r = JsonlTerminated(
            ts=datetime.now(),
            reason="target_hit",
            final_metric=714.0,
            delta_pct=-15.2,
            kept=5,
            reverted=2,
            errored=0,
            wall_clock_seconds=1800,
            auto_finalize=True,
        )
        assert r.type == "terminated"
```

- [ ] **Step 10: Run tests — expect fail**

```bash
uv run pytest tests/unit/test_validators.py -v
```

Expected: SubagentResult + JsonlRecords tests fail on import.

- [ ] **Step 11: Add JSONL records and SubagentResult to validators**

Append to `src/sindri/core/validators.py`:

```python
class SubagentResult(BaseModel):
    """The JSON contract the experiment subagent returns to the orchestrator."""

    model_config = ConfigDict(extra="forbid")

    metric_value: float
    reps_used: int = Field(gt=0)
    confidence_ratio: float = Field(ge=0)
    status: Literal["improved", "regressed", "inconclusive", "check_failed", "errored", "timeout"]
    files_modified: list[str]
    notes: str | None = None


# ---- JSONL records ----
# Each record type has a discriminator tag; a JSONL line is one record.

class _JsonlBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ts: datetime


class JsonlSessionStart(_JsonlBase):
    type: Literal["session_start"] = "session_start"
    goal: str
    target_pct: float
    mode: Literal["local", "remote"]


class JsonlBaseline(_JsonlBase):
    type: Literal["baseline"] = "baseline"
    run_index: int = Field(ge=1)
    value: float
    is_warmup: bool


class JsonlBaselineComplete(_JsonlBase):
    type: Literal["baseline_complete"] = "baseline_complete"
    mean: float
    noise_floor: float


class JsonlExperiment(_JsonlBase):
    type: Literal["experiment"] = "experiment"
    id: int
    candidate: str
    reps_used: int
    metric_before: float
    metric_after: float
    delta: float
    confidence_ratio: float
    status: Literal["improved", "regressed", "inconclusive", "check_failed", "errored", "timeout"]
    commit_sha: str | None = None
    files_modified: list[str] = Field(default_factory=list)


class JsonlEvent(_JsonlBase):
    type: Literal["event"] = "event"
    event: str
    reason: str | None = None
    details: str | None = None


class JsonlTerminated(_JsonlBase):
    type: Literal["terminated"] = "terminated"
    reason: Literal[
        "target_hit",
        "pool_empty",
        "max_experiments",
        "max_wall_clock",
        "max_reverts_in_a_row",
        "halted_by_user",
        "halted_by_error",
    ]
    final_metric: float
    delta_pct: float
    kept: int
    reverted: int
    errored: int
    wall_clock_seconds: int
    auto_finalize: bool


# Union type used when reading jsonl — pydantic will pick the right subclass by `type`
JsonlRecord = (
    JsonlSessionStart
    | JsonlBaseline
    | JsonlBaselineComplete
    | JsonlExperiment
    | JsonlEvent
    | JsonlTerminated
)
```

- [ ] **Step 12: Run tests — expect PASS**

```bash
uv run pytest tests/unit/test_validators.py -v
```

Expected: all tests pass.

- [ ] **Step 13: Commit**

```bash
git add src/sindri/core/validators.py tests/unit/test_validators.py
git commit -m "feat(core): add pydantic models for state, jsonl, subagent result"
```

---

## Phase 2 — Pure-function core modules

No I/O, no external subprocess, no network. Each module takes typed inputs and returns typed outputs.

### Task 3: Metric parsing (`core/metric.py`)

Parses `METRIC <name>=<number>` lines out of arbitrary benchmark stdout.

**Files:**

- Create: `src/sindri/core/metric.py`
- Test: `tests/unit/test_metric.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_metric.py`:

```python
"""Tests for METRIC line parsing."""
from __future__ import annotations

import pytest

from sindri.core.metric import MetricParseError, parse_metric_line


class TestParseMetricLine:
    def test_simple_integer(self) -> None:
        name, value = parse_metric_line("METRIC bundle_bytes=842000")
        assert name == "bundle_bytes"
        assert value == 842000.0

    def test_simple_float(self) -> None:
        _, value = parse_metric_line("METRIC test_duration_s=12.5")
        assert value == 12.5

    def test_scientific_notation(self) -> None:
        _, value = parse_metric_line("METRIC big=1.5e6")
        assert value == 1_500_000.0

    def test_negative_value(self) -> None:
        _, value = parse_metric_line("METRIC delta=-42.5")
        assert value == -42.5

    def test_takes_last_metric_line_when_multiple(self) -> None:
        output = """\
INFO: build starting
METRIC bundle_bytes=900000
METRIC bundle_bytes=842000
Build complete.
"""
        _, value = parse_metric_line(output)
        assert value == 842000.0  # last wins

    def test_ignores_surrounding_text(self) -> None:
        output = "prefix text\n  METRIC x=42  \ntrailing text\n"
        name, value = parse_metric_line(output)
        assert name == "x"
        assert value == 42.0

    def test_expected_name_validation(self) -> None:
        _, value = parse_metric_line("METRIC bundle_bytes=42", expected_name="bundle_bytes")
        assert value == 42.0

    def test_expected_name_mismatch_raises(self) -> None:
        with pytest.raises(MetricParseError, match="expected 'foo'"):
            parse_metric_line("METRIC bar=42", expected_name="foo")

    def test_missing_metric_raises(self) -> None:
        with pytest.raises(MetricParseError, match="no METRIC line"):
            parse_metric_line("just some build output\nwith no metric\n")

    def test_malformed_number_raises(self) -> None:
        with pytest.raises(MetricParseError, match="parse"):
            parse_metric_line("METRIC x=not-a-number")

    def test_empty_output_raises(self) -> None:
        with pytest.raises(MetricParseError):
            parse_metric_line("")
```

- [ ] **Step 2: Run tests — expect fail on import**

```bash
uv run pytest tests/unit/test_metric.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `metric.py`**

`src/sindri/core/metric.py`:

```python
"""Parse `METRIC <name>=<number>` lines from benchmark stdout."""
from __future__ import annotations

import re

_METRIC_RE = re.compile(
    r"""
    ^\s*METRIC\s+
    (?P<name>[a-z][a-z0-9_]*)
    \s*=\s*
    (?P<value>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)
    \s*$
    """,
    re.VERBOSE,
)


class MetricParseError(ValueError):
    """Raised when stdout does not contain a parseable METRIC line."""


def parse_metric_line(output: str, *, expected_name: str | None = None) -> tuple[str, float]:
    """Parse the LAST `METRIC name=value` line from `output`.

    If `expected_name` is provided, the parsed name must match.
    Multiple METRIC lines are allowed; the last one wins (per the spec's
    "emit the final METRIC line" contract).

    Raises:
        MetricParseError: if no METRIC line is present, or if the parsed
            name doesn't match `expected_name`, or if the value isn't
            a valid number.
    """
    last_match: re.Match[str] | None = None
    for line in output.splitlines():
        m = _METRIC_RE.match(line)
        if m is not None:
            last_match = m

    if last_match is None:
        raise MetricParseError("no METRIC line in output")

    name = last_match.group("name")
    value_str = last_match.group("value")
    try:
        value = float(value_str)
    except ValueError as e:  # pragma: no cover — regex already constrains
        raise MetricParseError(f"failed to parse {value_str!r} as number") from e

    if expected_name is not None and name != expected_name:
        raise MetricParseError(f"metric name {name!r} but expected {expected_name!r}")

    return name, value
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
uv run pytest tests/unit/test_metric.py -v
```

Expected: all 11 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/sindri/core/metric.py tests/unit/test_metric.py
git commit -m "feat(core): add METRIC line parser"
```

---

### Task 4: Statistics (`core/noise.py`)

Baseline statistics (mean, std dev, coefficient of variation, noise floor) and confidence ratios.

**Files:**

- Create: `src/sindri/core/noise.py`
- Test: `tests/unit/test_noise.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_noise.py`:

```python
"""Tests for noise floor and confidence computations."""
from __future__ import annotations

import math

import pytest

from sindri.core.noise import (
    NoiseComputationError,
    coefficient_of_variation,
    confidence_ratio,
    noise_floor,
    sample_mean,
)


class TestSampleMean:
    def test_simple(self) -> None:
        assert sample_mean([2.0, 4.0, 6.0]) == pytest.approx(4.0)

    def test_single_value(self) -> None:
        assert sample_mean([42.0]) == 42.0

    def test_empty_raises(self) -> None:
        with pytest.raises(NoiseComputationError):
            sample_mean([])


class TestNoiseFloor:
    def test_discards_warmup_by_default(self) -> None:
        # Run 1 is an outlier; discarding it gives tight std
        samples = [1000.0, 100.0, 101.0, 99.0, 100.0]
        floor = noise_floor(samples)
        # Without warmup discard, std would be huge (~400); with discard, ~1
        assert floor < 5.0

    def test_keep_warmup_when_requested(self) -> None:
        samples = [1000.0, 100.0, 101.0, 99.0, 100.0]
        floor = noise_floor(samples, discard_warmup=False)
        assert floor > 300.0  # the outlier inflates std

    def test_two_samples_after_warmup(self) -> None:
        # 3 samples, discard run 1, leaves 2: std of [100, 102]
        samples = [500.0, 100.0, 102.0]
        floor = noise_floor(samples)
        # sample_std_dev of [100, 102] = sqrt(((100-101)^2 + (102-101)^2) / 1) = sqrt(2) ≈ 1.414
        assert floor == pytest.approx(math.sqrt(2), rel=1e-6)

    def test_identical_samples_zero_noise(self) -> None:
        assert noise_floor([500.0, 100.0, 100.0, 100.0]) == 0.0

    def test_too_few_samples_raises(self) -> None:
        with pytest.raises(NoiseComputationError):
            noise_floor([100.0])  # only 1 sample → after warmup discard = 0
        with pytest.raises(NoiseComputationError):
            noise_floor([100.0, 101.0], discard_warmup=True)  # warmup discard leaves 1


class TestConfidenceRatio:
    def test_basic_ratio(self) -> None:
        # delta = 10, floor = 2 → ratio = 5
        assert confidence_ratio(delta=10.0, floor=2.0) == pytest.approx(5.0)

    def test_negative_delta(self) -> None:
        assert confidence_ratio(delta=-10.0, floor=2.0) == pytest.approx(5.0)

    def test_zero_floor_doesnt_blow_up(self) -> None:
        # When floor is zero (perfectly deterministic), use eps
        r = confidence_ratio(delta=1.0, floor=0.0)
        assert r > 1e5  # effectively infinite, but finite

    def test_zero_delta(self) -> None:
        assert confidence_ratio(delta=0.0, floor=1.0) == 0.0


class TestCoefficientOfVariation:
    def test_basic(self) -> None:
        # samples with mean 100, std 1 → CV = 1%
        samples = [99.0, 100.0, 101.0, 100.0, 100.0]
        cv = coefficient_of_variation(samples)
        assert 0.005 < cv < 0.02  # roughly 1%

    def test_noisy(self) -> None:
        # mean ~100, std ~20 → CV ≈ 20%
        samples = [80.0, 120.0, 100.0, 80.0, 120.0]
        cv = coefficient_of_variation(samples)
        assert cv > 0.15

    def test_identical_samples_zero_cv(self) -> None:
        assert coefficient_of_variation([5.0, 5.0, 5.0]) == 0.0

    def test_mean_zero_raises(self) -> None:
        with pytest.raises(NoiseComputationError):
            coefficient_of_variation([-1.0, 0.0, 1.0])
```

- [ ] **Step 2: Run tests — expect fail**

```bash
uv run pytest tests/unit/test_noise.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `noise.py`**

`src/sindri/core/noise.py`:

```python
"""Noise floor, confidence, and variation statistics.

All functions are pure: they take floats in, return floats out.
No I/O, no state.
"""
from __future__ import annotations

import math
import statistics

# Small number added to divisors to prevent division by zero on deterministic benchmarks.
# Chosen as a float reasonable for bundle-byte-scale numbers; users with much
# smaller metrics (e.g. 0.001 latency) may want to override in future.
EPSILON = 1e-6


class NoiseComputationError(ValueError):
    """Raised when noise/confidence math can't proceed (too few samples, etc.)."""


def sample_mean(samples: list[float]) -> float:
    if not samples:
        raise NoiseComputationError("cannot compute mean of empty samples")
    return statistics.fmean(samples)


def noise_floor(samples: list[float], *, discard_warmup: bool = True) -> float:
    """Compute the noise floor (sample std dev) of baseline runs.

    Args:
        samples: raw baseline measurements, in run order (samples[0] is run 1).
        discard_warmup: drop samples[0] before computing — JIT/cache cold starts.

    Returns:
        Bessel-corrected sample std dev of the post-warmup samples, or 0.0
        if all post-warmup samples are identical.

    Raises:
        NoiseComputationError: fewer than 2 post-warmup samples available.
    """
    effective = samples[1:] if discard_warmup else samples
    if len(effective) < 2:
        raise NoiseComputationError(
            f"need at least 2 post-warmup samples, got {len(effective)}"
        )
    return statistics.stdev(effective)


def confidence_ratio(*, delta: float, floor: float) -> float:
    """abs(delta) divided by max(floor, epsilon).

    Returns a large-but-finite number when floor is 0 (perfectly deterministic
    benchmarks). Never raises.
    """
    return abs(delta) / max(floor, EPSILON)


def coefficient_of_variation(samples: list[float]) -> float:
    """std_dev / mean — noise relative to signal size.

    Used for mode detection: CV > 15% on baseline runs flags `remote` mode
    (noisy benchmarks dominated by external-system variance).
    """
    if len(samples) < 2:
        raise NoiseComputationError("CV needs at least 2 samples")
    mean = sample_mean(samples)
    if abs(mean) < EPSILON:
        raise NoiseComputationError("mean is ~0; CV undefined")
    std = statistics.stdev(samples)
    return std / abs(mean)
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
uv run pytest tests/unit/test_noise.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/sindri/core/noise.py tests/unit/test_noise.py
git commit -m "feat(core): add noise floor, confidence ratio, CV stats"
```

---

### Task 5: Pool + termination predicates (`core/pool.py`)

Candidate ordering and the per-predicate terminators.

**Files:**

- Create: `src/sindri/core/pool.py`
- Test: `tests/unit/test_pool.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_pool.py`:

```python
"""Tests for pool ordering and termination predicates."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sindri.core.pool import (
    max_experiments_hit,
    max_reverts_hit,
    max_wall_clock_hit,
    pick_next,
    pool_exhausted,
    target_hit,
)
from sindri.core.validators import (
    Baseline,
    Candidate,
    Goal,
    Guardrails,
    SindriState,
)


def _state(
    *,
    pool: list[Candidate],
    current_best: float | None = None,
    direction: str = "reduce",
    target_pct: float = 15.0,
    baseline_value: float = 100.0,
    started_at: datetime | None = None,
) -> SindriState:
    return SindriState(
        goal=Goal(metric_name="x", direction=direction, target_pct=target_pct),  # type: ignore[arg-type]
        baseline=Baseline(value=baseline_value, noise_floor=1.0, samples=[baseline_value, baseline_value + 1, baseline_value - 1]),
        pool=pool,
        branch="sindri/test",
        started_at=started_at or datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc),
        guardrails=Guardrails(mode="local"),
        mode="local",
        current_best=current_best,
    )


class TestPickNext:
    def test_picks_highest_remaining_expected_impact(self) -> None:
        pool = [
            Candidate(id=1, name="small", expected_impact_pct=-2.0),
            Candidate(id=2, name="big", expected_impact_pct=-20.0),
            Candidate(id=3, name="medium", expected_impact_pct=-10.0),
        ]
        nxt = pick_next(pool)
        assert nxt is not None
        assert nxt.id == 2  # biggest absolute reduction

    def test_skips_non_pending(self) -> None:
        pool = [
            Candidate(id=1, name="a", expected_impact_pct=-20.0, status="kept"),
            Candidate(id=2, name="b", expected_impact_pct=-10.0, status="pending"),
        ]
        nxt = pick_next(pool)
        assert nxt is not None
        assert nxt.id == 2

    def test_returns_none_when_all_resolved(self) -> None:
        pool = [
            Candidate(id=1, name="a", expected_impact_pct=-20.0, status="kept"),
            Candidate(id=2, name="b", expected_impact_pct=-10.0, status="reverted"),
        ]
        assert pick_next(pool) is None

    def test_empty_pool_returns_none(self) -> None:
        assert pick_next([]) is None

    def test_direction_aware_for_increase_goals(self) -> None:
        # For "increase" goals, positive expected impacts are better
        pool = [
            Candidate(id=1, name="a", expected_impact_pct=+5.0),
            Candidate(id=2, name="b", expected_impact_pct=+20.0),
        ]
        # default order_by uses abs() — so highest absolute wins
        nxt = pick_next(pool)
        assert nxt is not None
        assert nxt.id == 2


class TestTargetHit:
    def test_reduce_hit(self) -> None:
        # baseline 100, target -15%, so target value is 85
        s = _state(pool=[], current_best=84.0, direction="reduce", target_pct=15.0, baseline_value=100.0)
        assert target_hit(s) is True

    def test_reduce_not_hit(self) -> None:
        s = _state(pool=[], current_best=90.0, direction="reduce", target_pct=15.0, baseline_value=100.0)
        assert target_hit(s) is False

    def test_increase_hit(self) -> None:
        # baseline 100, +15% target = 115
        s = _state(pool=[], current_best=116.0, direction="increase", target_pct=15.0, baseline_value=100.0)
        assert target_hit(s) is True

    def test_increase_not_hit(self) -> None:
        s = _state(pool=[], current_best=110.0, direction="increase", target_pct=15.0, baseline_value=100.0)
        assert target_hit(s) is False

    def test_no_current_best_yet(self) -> None:
        s = _state(pool=[], current_best=None)
        assert target_hit(s) is False


class TestPoolExhausted:
    def test_all_kept_or_reverted(self) -> None:
        pool = [
            Candidate(id=1, name="a", expected_impact_pct=-5, status="kept"),
            Candidate(id=2, name="b", expected_impact_pct=-5, status="reverted"),
        ]
        s = _state(pool=pool)
        assert pool_exhausted(s) is True

    def test_has_pending(self) -> None:
        pool = [
            Candidate(id=1, name="a", expected_impact_pct=-5, status="kept"),
            Candidate(id=2, name="b", expected_impact_pct=-5, status="pending"),
        ]
        s = _state(pool=pool)
        assert pool_exhausted(s) is False


class TestMaxExperimentsHit:
    def test_equal(self) -> None:
        assert max_experiments_hit(experiments_run=50, max_experiments=50) is True

    def test_less(self) -> None:
        assert max_experiments_hit(experiments_run=49, max_experiments=50) is False

    def test_greater(self) -> None:
        assert max_experiments_hit(experiments_run=100, max_experiments=50) is True


class TestMaxWallClockHit:
    def test_hit(self) -> None:
        started = datetime.now(tz=timezone.utc) - timedelta(seconds=100)
        assert max_wall_clock_hit(started_at=started, max_seconds=60) is True

    def test_not_hit(self) -> None:
        started = datetime.now(tz=timezone.utc) - timedelta(seconds=10)
        assert max_wall_clock_hit(started_at=started, max_seconds=60) is False


class TestMaxRevertsHit:
    def test_hit(self) -> None:
        assert max_reverts_hit(consecutive_reverts=7, max_reverts=7) is True

    def test_not_hit(self) -> None:
        assert max_reverts_hit(consecutive_reverts=6, max_reverts=7) is False
```

- [ ] **Step 2: Run tests — expect fail**

```bash
uv run pytest tests/unit/test_pool.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `pool.py`**

`src/sindri/core/pool.py`:

```python
"""Candidate pool ordering and individual termination predicates.

Termination predicates take only the minimal inputs they need (not the whole
state) for easier testing. `termination.py` composes them into the overall
decision table.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sindri.core.validators import Candidate, SindriState


def pick_next(
    pool: list[Candidate],
    *,
    order_by: str = "expected_impact_desc",
) -> Candidate | None:
    """Return the next candidate to run, or None if nothing is pending.

    Default ordering: pending candidates by |expected_impact_pct| descending.
    This assumes candidates are named with a sign that matches the goal
    direction (negative for reduce, positive for increase). Taking absolute
    value makes the ordering direction-agnostic.
    """
    pending = [c for c in pool if c.status == "pending"]
    if not pending:
        return None
    if order_by == "expected_impact_desc":
        pending.sort(key=lambda c: abs(c.expected_impact_pct), reverse=True)
    else:
        raise ValueError(f"unknown order_by: {order_by!r}")
    return pending[0]


def pool_exhausted(state: SindriState) -> bool:
    """True if every pool entry has been resolved (kept/reverted/errored/check_failed)."""
    return all(c.status != "pending" for c in state.pool)


def target_hit(state: SindriState) -> bool:
    """True if current_best crosses the goal's target.

    For 'reduce': current_best ≤ baseline * (1 - target_pct/100).
    For 'increase': current_best ≥ baseline * (1 + target_pct/100).
    """
    if state.current_best is None:
        return False
    baseline = state.baseline.value
    target_pct = state.goal.target_pct
    if state.goal.direction == "reduce":
        threshold = baseline * (1 - target_pct / 100)
        return state.current_best <= threshold
    else:  # increase
        threshold = baseline * (1 + target_pct / 100)
        return state.current_best >= threshold


def max_experiments_hit(*, experiments_run: int, max_experiments: int) -> bool:
    return experiments_run >= max_experiments


def max_wall_clock_hit(*, started_at: datetime, max_seconds: int) -> bool:
    now = datetime.now(tz=timezone.utc) if started_at.tzinfo else datetime.utcnow()
    elapsed = (now - started_at).total_seconds()
    return elapsed >= max_seconds


def max_reverts_hit(*, consecutive_reverts: int, max_reverts: int) -> bool:
    return consecutive_reverts >= max_reverts
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
uv run pytest tests/unit/test_pool.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/sindri/core/pool.py tests/unit/test_pool.py
git commit -m "feat(core): add pool ordering and termination predicates"
```

---

### Task 6: Mode detection (`core/modes.py`)

Auto-selects `local` vs `remote` from script content + observed noise.

**Files:**

- Create: `src/sindri/core/modes.py`
- Test: `tests/unit/test_modes.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_modes.py`:

```python
"""Tests for local vs remote mode detection."""
from __future__ import annotations

from pathlib import Path

import pytest

from sindri.core.modes import detect_mode, script_content_signal


class TestScriptContentSignal:
    def test_simple_local_script(self, tmp_path: Path) -> None:
        script = tmp_path / "benchmark.py"
        script.write_text("import subprocess\nsubprocess.run(['du', '-sb', 'dist'])\n")
        assert script_content_signal(script) == "local"

    def test_gh_workflow_run_flags_remote(self, tmp_path: Path) -> None:
        script = tmp_path / "benchmark.py"
        script.write_text("import subprocess\nsubprocess.run(['gh', 'workflow', 'run', 'ci.yml'])\n")
        assert script_content_signal(script) == "remote"

    def test_aws_cli_flags_remote(self, tmp_path: Path) -> None:
        script = tmp_path / "benchmark.py"
        script.write_text("subprocess.run(['aws', 's3', 'ls'])")
        assert script_content_signal(script) == "remote"

    def test_gcloud_flags_remote(self, tmp_path: Path) -> None:
        script = tmp_path / "benchmark.py"
        script.write_text("subprocess.run(['gcloud', 'run', 'jobs', 'execute'])")
        assert script_content_signal(script) == "remote"

    def test_kubectl_flags_remote(self, tmp_path: Path) -> None:
        script = tmp_path / "benchmark.py"
        script.write_text("subprocess.run(['kubectl', 'get', 'pods'])")
        assert script_content_signal(script) == "remote"

    def test_curl_to_external_host_flags_remote(self, tmp_path: Path) -> None:
        script = tmp_path / "benchmark.py"
        script.write_text("subprocess.run(['curl', 'https://api.example.com/metrics'])")
        assert script_content_signal(script) == "remote"

    def test_curl_to_localhost_stays_local(self, tmp_path: Path) -> None:
        script = tmp_path / "benchmark.py"
        script.write_text("subprocess.run(['curl', 'http://localhost:3000/health'])")
        assert script_content_signal(script) == "local"

    def test_curl_to_127_0_0_1_stays_local(self, tmp_path: Path) -> None:
        script = tmp_path / "benchmark.py"
        script.write_text("subprocess.run(['curl', 'http://127.0.0.1:8080/metrics'])")
        assert script_content_signal(script) == "local"

    def test_missing_script_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            script_content_signal(tmp_path / "no-such-file.py")


class TestDetectMode:
    def test_local_script_low_cv_is_local(self, tmp_path: Path) -> None:
        script = tmp_path / "benchmark.py"
        script.write_text("import subprocess\nsubprocess.run(['du', '-sb', 'dist'])\n")
        # low CV: 100, 100.5, 99.5 → CV ~ 0.5%
        assert detect_mode(script, [500.0, 100.0, 100.5, 99.5]) == "local"

    def test_local_script_high_cv_is_remote(self, tmp_path: Path) -> None:
        # script looks local but CV is noisy → flag as remote
        script = tmp_path / "benchmark.py"
        script.write_text("import subprocess\nsubprocess.run(['du', '-sb', 'dist'])\n")
        # high CV: 100, 80, 120, 70, 130 → CV ~ 25%
        assert detect_mode(script, [500.0, 100.0, 80.0, 120.0, 70.0, 130.0]) == "remote"

    def test_remote_keyword_always_wins(self, tmp_path: Path) -> None:
        # even with low CV, gh keyword → remote
        script = tmp_path / "benchmark.py"
        script.write_text("subprocess.run(['gh', 'workflow', 'run'])")
        assert detect_mode(script, [500.0, 100.0, 100.5, 99.5]) == "remote"
```

- [ ] **Step 2: Run tests — expect fail**

```bash
uv run pytest tests/unit/test_modes.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `modes.py`**

`src/sindri/core/modes.py`:

```python
"""Local vs remote benchmark mode detection.

Two signals — either triggers remote:
  1. Script content references external tools (`gh`, `aws`, `gcloud`, etc.)
     that imply network/third-party cost. Localhost-whitelisted for `curl`/`wget`.
  2. Observed coefficient of variation > 15% across non-warmup baseline runs.

Default is `local`; remote requires positive evidence.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from sindri.core.noise import coefficient_of_variation

# Tools that imply external-service calls (networked, cost-bearing, rate-limited).
_REMOTE_TOOLS = [
    r"\bgh\b",
    r"\bwget\b",
    r"\baws\b",
    r"\bgcloud\b",
    r"\bkubectl\b",
    r"\bssh\b",
    r"\brsync\b",
    r"\bterraform\b",
    r"\bansible\b",
    r"\baz\b",
]

# `curl` is only remote if pointing at a non-localhost URL.
_CURL_WITH_REMOTE_URL = re.compile(
    r"curl\s+[^\n]*?"
    r"(https?://(?!localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])[^\s'\"]+)",
    re.IGNORECASE,
)

_COMBINED_REMOTE_RE = re.compile("|".join(_REMOTE_TOOLS))

# CV threshold above which observed noise triggers remote mode.
CV_REMOTE_THRESHOLD = 0.15


def script_content_signal(script_path: Path) -> Literal["local", "remote"]:
    """Scan script content for external-tool references."""
    text = script_path.read_text()
    # Check tools first (cheap regex)
    if _COMBINED_REMOTE_RE.search(text):
        return "remote"
    # Check curl specifically, with localhost whitelist
    if _CURL_WITH_REMOTE_URL.search(text):
        return "remote"
    return "local"


def detect_mode(
    script_path: Path,
    baseline_samples: list[float],
) -> Literal["local", "remote"]:
    """Combine script-content signal with observed CV to decide local vs remote.

    Baseline samples: all recorded baseline runs (may include warmup at index 0).
    The CV is computed over samples[1:] (post-warmup).
    """
    if script_content_signal(script_path) == "remote":
        return "remote"

    # Observed-noise signal — discard warmup run
    post_warmup = baseline_samples[1:]
    if len(post_warmup) >= 2:
        try:
            cv = coefficient_of_variation(post_warmup)
        except Exception:  # NoiseComputationError — don't crash detection
            cv = 0.0
        if cv > CV_REMOTE_THRESHOLD:
            return "remote"

    return "local"
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
uv run pytest tests/unit/test_modes.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/sindri/core/modes.py tests/unit/test_modes.py
git commit -m "feat(core): add local/remote mode detection"
```

---

### Task 7: Termination decision table (`core/termination.py`)

Composes the per-predicate tests from `pool.py` into a single clean decision.

**Files:**

- Create: `src/sindri/core/termination.py`
- Test: `tests/unit/test_termination.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_termination.py`:

```python
"""Tests for the termination decision table."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sindri.core.termination import check_termination
from sindri.core.validators import (
    Baseline,
    Candidate,
    Goal,
    Guardrails,
    SindriState,
)


def _state(
    *,
    pool: list[Candidate] | None = None,
    current_best: float | None = None,
    started_at: datetime | None = None,
    direction: str = "reduce",
    target_pct: float = 15.0,
    baseline_value: float = 100.0,
) -> SindriState:
    return SindriState(
        goal=Goal(metric_name="x", direction=direction, target_pct=target_pct),  # type: ignore[arg-type]
        baseline=Baseline(value=baseline_value, noise_floor=1.0, samples=[baseline_value, baseline_value + 1, baseline_value - 1]),
        pool=pool if pool is not None else [Candidate(id=1, name="a", expected_impact_pct=-10.0)],
        branch="sindri/test",
        started_at=started_at or datetime.now(tz=timezone.utc),
        guardrails=Guardrails(mode="local"),
        mode="local",
        current_best=current_best,
    )


class TestCheckTermination:
    def test_not_terminated_when_pool_has_pending_and_no_target(self) -> None:
        s = _state()
        result = check_termination(s, experiments_run=0, consecutive_reverts=0)
        assert result.terminated is False
        assert result.reason is None

    def test_target_hit(self) -> None:
        # baseline 100, reduce target 15% → need ≤85
        s = _state(current_best=80.0)
        result = check_termination(s, experiments_run=5, consecutive_reverts=0)
        assert result.terminated is True
        assert result.reason == "target_hit"
        assert result.auto_finalize is True  # target_hit with kept work

    def test_pool_empty_with_wins(self) -> None:
        # No pending, and there's a current_best (so we had wins)
        pool = [
            Candidate(id=1, name="a", expected_impact_pct=-10, status="kept"),
            Candidate(id=2, name="b", expected_impact_pct=-5, status="reverted"),
        ]
        s = _state(pool=pool, current_best=90.0)
        result = check_termination(s, experiments_run=2, consecutive_reverts=1)
        assert result.terminated is True
        assert result.reason == "pool_empty"
        assert result.auto_finalize is True  # has wins

    def test_pool_empty_no_wins(self) -> None:
        pool = [
            Candidate(id=1, name="a", expected_impact_pct=-10, status="reverted"),
            Candidate(id=2, name="b", expected_impact_pct=-5, status="reverted"),
        ]
        s = _state(pool=pool, current_best=None)
        result = check_termination(s, experiments_run=2, consecutive_reverts=2)
        assert result.terminated is True
        assert result.reason == "pool_empty"
        assert result.auto_finalize is False  # no wins to ship

    def test_max_experiments_hit_with_wins(self) -> None:
        s = _state(current_best=95.0)
        result = check_termination(s, experiments_run=50, consecutive_reverts=0)
        assert result.terminated is True
        assert result.reason == "max_experiments"
        assert result.auto_finalize is True

    def test_max_experiments_hit_no_wins(self) -> None:
        s = _state(current_best=None)
        result = check_termination(s, experiments_run=50, consecutive_reverts=0)
        assert result.terminated is True
        assert result.reason == "max_experiments"
        assert result.auto_finalize is False

    def test_max_wall_clock_hit(self) -> None:
        past = datetime.now(tz=timezone.utc) - timedelta(hours=10)
        s = _state(current_best=90.0, started_at=past)
        result = check_termination(s, experiments_run=5, consecutive_reverts=0)
        assert result.terminated is True
        assert result.reason == "max_wall_clock"
        assert result.auto_finalize is True  # has wins

    def test_max_reverts(self) -> None:
        s = _state()
        result = check_termination(s, experiments_run=7, consecutive_reverts=7)
        assert result.terminated is True
        assert result.reason == "max_reverts_in_a_row"
        assert result.auto_finalize is False  # halted on systemic error
```

- [ ] **Step 2: Run tests — expect fail**

```bash
uv run pytest tests/unit/test_termination.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `termination.py`**

`src/sindri/core/termination.py`:

```python
"""Termination decision table.

Given the current state + runtime counters, returns:
  - whether to terminate
  - the reason (or None)
  - whether auto-finalize should fire (only on clean termination with wins)
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from typing import Literal

from sindri.core.pool import (
    max_experiments_hit,
    max_reverts_hit,
    max_wall_clock_hit,
    pool_exhausted,
    target_hit,
)
from sindri.core.validators import SindriState

TerminationReason = Literal[
    "target_hit",
    "pool_empty",
    "max_experiments",
    "max_wall_clock",
    "max_reverts_in_a_row",
    "halted_by_user",
    "halted_by_error",
]

# Clean termination reasons finalize automatically when there are kept commits.
# Halt reasons never auto-finalize regardless of kept count.
_CLEAN_REASONS: frozenset[TerminationReason] = frozenset({
    "target_hit",
    "pool_empty",
    "max_experiments",
    "max_wall_clock",
})


class TerminationCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    terminated: bool
    reason: TerminationReason | None
    auto_finalize: bool


def _has_wins(state: SindriState) -> bool:
    """True if at least one kept commit exists (current_best set to non-baseline)."""
    return state.current_best is not None and state.current_best != state.baseline.value


def check_termination(
    state: SindriState,
    *,
    experiments_run: int,
    consecutive_reverts: int,
) -> TerminationCheck:
    """Return whether the loop should terminate and why.

    Order of checks matters: we check highest-priority terminators first
    (target_hit is the happy path; halts are the red path). All clean
    termination reasons with wins trigger auto-finalize; halts do not.
    """
    g = state.guardrails

    # 1. Target hit — happy path
    if target_hit(state):
        return TerminationCheck(terminated=True, reason="target_hit", auto_finalize=True)

    # 2. Max reverts — halt-class (no auto finalize)
    if max_reverts_hit(consecutive_reverts=consecutive_reverts, max_reverts=g.max_reverts_in_a_row):
        return TerminationCheck(
            terminated=True, reason="max_reverts_in_a_row", auto_finalize=False
        )

    # 3. Pool exhausted — clean termination (auto-finalize only if wins)
    if pool_exhausted(state):
        return TerminationCheck(
            terminated=True, reason="pool_empty", auto_finalize=_has_wins(state)
        )

    # 4. Max experiments cap
    if max_experiments_hit(experiments_run=experiments_run, max_experiments=g.max_experiments):
        return TerminationCheck(
            terminated=True,
            reason="max_experiments",
            auto_finalize=_has_wins(state),
        )

    # 5. Wall-clock cap
    if max_wall_clock_hit(
        started_at=state.started_at, max_seconds=g.max_wall_clock_seconds
    ):
        return TerminationCheck(
            terminated=True,
            reason="max_wall_clock",
            auto_finalize=_has_wins(state),
        )

    # Not terminated
    return TerminationCheck(terminated=False, reason=None, auto_finalize=False)
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
uv run pytest tests/unit/test_termination.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Run the whole unit test suite so far — expect full pass**

```bash
uv run pytest tests/unit/ -v
```

Expected: every test from tasks 2–7 passes.

- [ ] **Step 6: Commit**

```bash
git add src/sindri/core/termination.py tests/unit/test_termination.py
git commit -m "feat(core): add termination decision table composing predicates"
```

---

## Phase 3 — I/O core modules

Modules that touch disk or subprocess. Tested against real temp directories and temp git repos (integration tests).

### Task 8: State files (`core/state.py`)

Read, write, and append the three state files.

**Files:**

- Create: `src/sindri/core/state.py`
- Test: `tests/integration/test_state.py`

- [ ] **Step 1: Write failing tests**

`tests/integration/test_state.py`:

```python
"""Integration tests for state file I/O (reads and writes to tmp dirs)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from sindri.core.state import (
    StateIOError,
    append_jsonl,
    read_jsonl,
    read_state,
    write_state,
)
from sindri.core.validators import (
    Baseline,
    Candidate,
    Goal,
    Guardrails,
    JsonlBaseline,
    JsonlExperiment,
    JsonlSessionStart,
    SindriState,
)


@pytest.fixture
def sample_state() -> SindriState:
    return SindriState(
        goal=Goal(metric_name="bundle_bytes", direction="reduce", target_pct=15.0),
        baseline=Baseline(value=842000.0, noise_floor=870.0, samples=[843100.0, 841400.0, 842500.0]),
        pool=[
            Candidate(id=1, name="Replace moment", expected_impact_pct=-10.0),
            Candidate(id=2, name="Tree-shake lodash", expected_impact_pct=-5.0, status="kept"),
        ],
        branch="sindri/reduce-bundle-bytes-15pct",
        started_at=datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc),
        guardrails=Guardrails(mode="local"),
        mode="local",
    )


class TestStateRoundTrip:
    def test_write_then_read_preserves_fields(self, tmp_sindri_dir: Path, sample_state: SindriState) -> None:
        write_state(sample_state, dir=tmp_sindri_dir)
        assert (tmp_sindri_dir / "sindri.md").exists()
        loaded = read_state(dir=tmp_sindri_dir)
        assert loaded.goal.metric_name == sample_state.goal.metric_name
        assert loaded.baseline.value == sample_state.baseline.value
        assert len(loaded.pool) == 2
        assert loaded.pool[1].status == "kept"

    def test_read_missing_raises(self, tmp_sindri_dir: Path) -> None:
        with pytest.raises(StateIOError):
            read_state(dir=tmp_sindri_dir)

    def test_frontmatter_is_first_thing_in_file(self, tmp_sindri_dir: Path, sample_state: SindriState) -> None:
        write_state(sample_state, dir=tmp_sindri_dir)
        content = (tmp_sindri_dir / "sindri.md").read_text()
        assert content.startswith("---\n")


class TestJsonlAppend:
    def test_append_single_record(self, tmp_sindri_dir: Path) -> None:
        path = tmp_sindri_dir / "sindri.jsonl"
        rec = JsonlSessionStart(
            ts=datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc),
            goal="reduce bundle by 15%",
            target_pct=-15.0,
            mode="local",
        )
        append_jsonl(rec, path=path)
        lines = path.read_text().strip().splitlines()
        assert len(lines) == 1
        assert '"type":"session_start"' in lines[0].replace(" ", "")

    def test_append_multiple_preserves_order(self, tmp_sindri_dir: Path) -> None:
        path = tmp_sindri_dir / "sindri.jsonl"
        append_jsonl(
            JsonlBaseline(ts=datetime.now(tz=timezone.utc), run_index=1, value=100.0, is_warmup=True),
            path=path,
        )
        append_jsonl(
            JsonlBaseline(ts=datetime.now(tz=timezone.utc), run_index=2, value=101.0, is_warmup=False),
            path=path,
        )
        lines = path.read_text().strip().splitlines()
        assert len(lines) == 2

    def test_read_jsonl_returns_typed_records(self, tmp_sindri_dir: Path) -> None:
        path = tmp_sindri_dir / "sindri.jsonl"
        append_jsonl(
            JsonlSessionStart(
                ts=datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc),
                goal="x",
                target_pct=-10.0,
                mode="local",
            ),
            path=path,
        )
        append_jsonl(
            JsonlExperiment(
                ts=datetime(2026, 4, 19, 10, 5, tzinfo=timezone.utc),
                id=1,
                candidate="Replace moment",
                reps_used=3,
                metric_before=100.0,
                metric_after=80.0,
                delta=-20.0,
                confidence_ratio=4.2,
                status="improved",
                commit_sha="abc123",
                files_modified=["package.json"],
            ),
            path=path,
        )
        records = read_jsonl(path)
        assert len(records) == 2
        assert records[0].type == "session_start"
        assert records[1].type == "experiment"

    def test_read_jsonl_missing_returns_empty(self, tmp_sindri_dir: Path) -> None:
        assert read_jsonl(tmp_sindri_dir / "nonexistent.jsonl") == []

    def test_read_jsonl_skips_malformed_but_records_warning(self, tmp_sindri_dir: Path) -> None:
        # Corrupt jsonl (e.g. from a partial write after a crash) — we skip
        # malformed lines rather than refusing to read at all.
        path = tmp_sindri_dir / "sindri.jsonl"
        path.write_text(
            '{"type":"session_start","ts":"2026-04-19T10:00:00+00:00","goal":"x","target_pct":-10.0,"mode":"local"}\n'
            "not valid json\n"
            '{"type":"baseline","ts":"2026-04-19T10:01:00+00:00","run_index":1,"value":100.0,"is_warmup":true}\n'
        )
        records = read_jsonl(path)
        assert len(records) == 2  # malformed line skipped
```

- [ ] **Step 2: Run tests — expect fail**

```bash
uv run pytest tests/integration/test_state.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `state.py`**

`src/sindri/core/state.py`:

```python
"""State file I/O: sindri.md (frontmatter YAML + markdown body) and sindri.jsonl.

sindri.md is rendered with frontmatter containing the full SindriState as JSON
(serialized via pydantic), followed by a human-readable markdown body. On read,
we parse only the frontmatter — the body is for humans.

sindri.jsonl is append-only; each line is one JSON-serialized pydantic model.
"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from sindri.core.validators import (
    JsonlBaseline,
    JsonlBaselineComplete,
    JsonlEvent,
    JsonlExperiment,
    JsonlRecord,
    JsonlSessionStart,
    JsonlTerminated,
    SindriState,
)


class StateIOError(Exception):
    """Raised when state files can't be read or are malformed."""


_FRONTMATTER_DELIM = "---\n"

# Type adapter for the JsonlRecord union — pydantic uses the discriminator `type`
# to pick the right subclass at parse time.
_jsonl_adapter: TypeAdapter[JsonlRecord] = TypeAdapter(JsonlRecord)


def write_state(state: SindriState, *, dir: Path = Path(".sindri/current")) -> None:
    """Write state to `<dir>/sindri.md` as YAML-ish frontmatter + markdown body."""
    dir.mkdir(parents=True, exist_ok=True)
    path = dir / "sindri.md"
    # Serialize as JSON-in-frontmatter (simpler than YAML, no extra dep).
    # Tools that parse YAML frontmatter will reject this; we control the reader.
    frontmatter = state.model_dump_json(indent=2)
    body = _render_human_body(state)
    path.write_text(
        f"{_FRONTMATTER_DELIM}{frontmatter}\n{_FRONTMATTER_DELIM}\n{body}"
    )


def read_state(*, dir: Path = Path(".sindri/current")) -> SindriState:
    """Read and validate sindri.md's frontmatter into a SindriState."""
    path = dir / "sindri.md"
    if not path.exists():
        raise StateIOError(f"state file not found: {path}")
    text = path.read_text()
    if not text.startswith(_FRONTMATTER_DELIM):
        raise StateIOError(f"state file {path} missing frontmatter delimiter")
    # Strip leading delimiter, then find the closing one.
    body_start = text.index(_FRONTMATTER_DELIM, len(_FRONTMATTER_DELIM))
    fm = text[len(_FRONTMATTER_DELIM):body_start]
    try:
        return SindriState.model_validate_json(fm)
    except ValidationError as e:
        raise StateIOError(f"invalid state in {path}: {e}") from e


def append_jsonl(
    record: JsonlRecord,
    *,
    path: Path = Path(".sindri/current/sindri.jsonl"),
) -> None:
    """Append a single pydantic record as one line to the jsonl file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = record.model_dump_json()
    # Single write with append mode — on POSIX, write() < PIPE_BUF is atomic.
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_jsonl(path: Path) -> list[JsonlRecord]:
    """Read all records from a jsonl file. Skips malformed lines (returns only valid)."""
    if not path.exists():
        return []
    out: list[JsonlRecord] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
            rec = _jsonl_adapter.validate_python(raw)
            out.append(rec)
        except (json.JSONDecodeError, ValidationError):
            # Skip malformed lines — a partial-write after a crash is
            # recoverable and shouldn't block reading valid records.
            continue
    return out


def _render_human_body(state: SindriState) -> str:
    """Render a human-readable markdown body below the frontmatter.

    This is for humans inspecting sindri.md; the source of truth is the frontmatter.
    """
    lines = []
    lines.append("# Goal\n")
    sign = "−" if state.goal.direction == "reduce" else "+"
    lines.append(
        f"{state.goal.direction.title()} `{state.goal.metric_name}` by {state.goal.target_pct}%. "
        f"Baseline {state.baseline.value:,.0f} → target {sign}{state.goal.target_pct}%.\n"
    )
    lines.append("## Pool\n")
    pending = [c for c in state.pool if c.status == "pending"]
    kept = [c for c in state.pool if c.status == "kept"]
    reverted = [c for c in state.pool if c.status == "reverted"]
    dead = [c for c in state.pool if c.status in {"errored", "check_failed"}]
    if pending:
        lines.append("### Pending\n")
        for c in pending:
            lines.append(f"- [ ] **{c.name}** *(expected: {c.expected_impact_pct:+.1f}%)*")
        lines.append("")
    if kept:
        lines.append("### Kept ✓\n")
        for c in kept:
            lines.append(f"- [x] **{c.name}** — Δ {c.expected_impact_pct:+.1f}%")
        lines.append("")
    if reverted:
        lines.append("### Reverted ✗\n")
        for c in reverted:
            lines.append(f"- [×] **{c.name}**")
        lines.append("")
    if dead:
        lines.append("### Dead ends\n")
        for c in dead:
            lines.append(f"- [⚠] **{c.name}** — {c.status}")
        lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
uv run pytest tests/integration/test_state.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/sindri/core/state.py tests/integration/test_state.py
git commit -m "feat(core): add state.py for sindri.md and sindri.jsonl I/O"
```

---

### Task 9: Git operations (`core/git_ops.py`)

Subprocess wrappers for git. Tested against real temp repos.

**Files:**

- Create: `src/sindri/core/git_ops.py`
- Test: `tests/integration/test_git_ops.py`

- [ ] **Step 1: Write failing tests**

`tests/integration/test_git_ops.py`:

```python
"""Integration tests for git subprocess wrappers — use real git in tmp repos."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sindri.core.git_ops import (
    GitError,
    commit_all_with_message,
    create_branch,
    current_branch,
    delete_branch,
    is_working_tree_clean,
    reset_hard_to_head,
)


class TestCurrentBranch:
    def test_returns_main(self, tmp_git_repo: Path) -> None:
        assert current_branch() == "main"

    def test_returns_feature_branch(self, tmp_git_repo: Path) -> None:
        subprocess.run(["git", "checkout", "-b", "feature/test"], check=True, cwd=tmp_git_repo, capture_output=True)
        assert current_branch() == "feature/test"


class TestIsWorkingTreeClean:
    def test_clean_after_init(self, tmp_git_repo: Path) -> None:
        assert is_working_tree_clean() is True

    def test_dirty_with_unstaged(self, tmp_git_repo: Path) -> None:
        (tmp_git_repo / "new.txt").write_text("hi")
        assert is_working_tree_clean() is False

    def test_dirty_with_modified_tracked(self, tmp_git_repo: Path) -> None:
        (tmp_git_repo / "README.md").write_text("# modified\n")
        assert is_working_tree_clean() is False


class TestCreateBranch:
    def test_creates_and_checks_out(self, tmp_git_repo: Path) -> None:
        create_branch("sindri/test-goal")
        assert current_branch() == "sindri/test-goal"

    def test_fails_if_name_exists(self, tmp_git_repo: Path) -> None:
        create_branch("sindri/first")
        with pytest.raises(GitError):
            create_branch("sindri/first")


class TestCommitAllWithMessage:
    def test_commits_staged_changes(self, tmp_git_repo: Path) -> None:
        (tmp_git_repo / "new.txt").write_text("content\n")
        sha = commit_all_with_message("kept: test change")
        assert len(sha) >= 7
        # Confirm commit is at HEAD
        out = subprocess.run(
            ["git", "log", "-1", "--format=%s"], check=True, capture_output=True, text=True, cwd=tmp_git_repo,
        ).stdout.strip()
        assert out == "kept: test change"

    def test_raises_if_nothing_to_commit(self, tmp_git_repo: Path) -> None:
        with pytest.raises(GitError):
            commit_all_with_message("empty commit")


class TestResetHardToHead:
    def test_clears_uncommitted_changes(self, tmp_git_repo: Path) -> None:
        (tmp_git_repo / "README.md").write_text("# modified\n")
        (tmp_git_repo / "new.txt").write_text("untracked\n")
        assert is_working_tree_clean() is False
        reset_hard_to_head()
        # modified tracked file reverts; untracked file remains (git reset doesn't touch untracked)
        assert (tmp_git_repo / "README.md").read_text() == "# test\n"


class TestDeleteBranch:
    def test_deletes_after_switch(self, tmp_git_repo: Path) -> None:
        create_branch("sindri/temp")
        subprocess.run(["git", "checkout", "main"], check=True, cwd=tmp_git_repo, capture_output=True)
        delete_branch("sindri/temp", force=True)
        branches = subprocess.run(
            ["git", "branch", "--format=%(refname:short)"],
            check=True, capture_output=True, text=True, cwd=tmp_git_repo,
        ).stdout.strip().splitlines()
        assert "sindri/temp" not in branches

    def test_cannot_delete_current_branch(self, tmp_git_repo: Path) -> None:
        create_branch("sindri/current-feature")
        with pytest.raises(GitError):
            delete_branch("sindri/current-feature", force=True)
```

- [ ] **Step 2: Run tests — expect fail**

```bash
uv run pytest tests/integration/test_git_ops.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `git_ops.py`**

`src/sindri/core/git_ops.py`:

```python
"""Thin subprocess wrappers around git. Each function raises GitError on failure.

All operations run in the current working directory — callers are responsible
for being in the right repo root. Sindri invokes these from the directory the
user ran `/sindri` in.
"""
from __future__ import annotations

import subprocess


class GitError(RuntimeError):
    """Raised when a git operation fails."""


def _run(args: list[str]) -> str:
    """Run git with args, return stdout, raise GitError on non-zero exit."""
    proc = subprocess.run(
        ["git", *args], capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        raise GitError(
            f"git {' '.join(args)} failed (exit {proc.returncode}): {proc.stderr.strip()}"
        )
    return proc.stdout


def current_branch() -> str:
    """Return the current branch name."""
    return _run(["rev-parse", "--abbrev-ref", "HEAD"]).strip()


def is_working_tree_clean() -> bool:
    """True if there are no uncommitted tracked or untracked changes."""
    out = _run(["status", "--porcelain"])
    return out.strip() == ""


def create_branch(name: str, *, from_ref: str = "HEAD") -> None:
    """Create a new branch from `from_ref` and check it out.

    Fails if the branch already exists — callers must handle that.
    """
    _run(["checkout", "-b", name, from_ref])


def commit_all_with_message(msg: str) -> str:
    """Stage all changes and commit with `msg`. Returns the new commit SHA.

    Raises GitError if there's nothing to commit (strict: refuse empty commits).
    """
    _run(["add", "-A"])
    # Check there's something to commit; `git commit` with nothing returns non-zero
    # but we want a clear error
    status = _run(["status", "--porcelain"]).strip()
    if not status:
        raise GitError("nothing to commit — working tree clean after git add")
    _run(["commit", "-m", msg])
    return _run(["rev-parse", "HEAD"]).strip()


def reset_hard_to_head() -> None:
    """`git reset --hard HEAD` — discards all tracked file changes."""
    _run(["reset", "--hard", "HEAD"])


def delete_branch(name: str, *, force: bool = False) -> None:
    """Delete a local branch. Use force=True to delete an unmerged branch."""
    if current_branch() == name:
        raise GitError(f"cannot delete currently-checked-out branch {name!r}")
    flag = "-D" if force else "-d"
    _run(["branch", flag, name])


def push_with_upstream(branch: str, *, remote: str = "origin") -> None:
    """`git push -u <remote> <branch>`. Called by finalize, not by the main loop."""
    _run(["push", "-u", remote, branch])
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
uv run pytest tests/integration/test_git_ops.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/sindri/core/git_ops.py tests/integration/test_git_ops.py
git commit -m "feat(core): add git subprocess wrappers"
```

---

### Task 10: PR body rendering (`core/pr_body.py`)

Generates the rich markdown body that becomes the PR description.

**Files:**

- Create: `src/sindri/core/pr_body.py`
- Test: `tests/unit/test_pr_body.py`

- [ ] **Step 1: Write failing tests**

`tests/unit/test_pr_body.py`:

```python
"""Unit tests for PR body rendering — pure template function."""
from __future__ import annotations

from datetime import datetime, timezone

from sindri.core.pr_body import render_pr_body
from sindri.core.validators import (
    Baseline,
    Candidate,
    Goal,
    Guardrails,
    JsonlExperiment,
    JsonlSessionStart,
    JsonlTerminated,
    SindriState,
)


def _state() -> SindriState:
    return SindriState(
        goal=Goal(metric_name="bundle_bytes", direction="reduce", target_pct=15.0),
        baseline=Baseline(value=842000.0, noise_floor=870.0, samples=[843100.0, 841400.0, 842500.0]),
        pool=[
            Candidate(id=1, name="Replace moment", expected_impact_pct=-10.0, status="kept"),
            Candidate(id=2, name="Inline SVGs", expected_impact_pct=-2.0, status="reverted"),
            Candidate(id=3, name="Swap webpack", expected_impact_pct=-5.0, status="check_failed"),
        ],
        branch="sindri/reduce-bundle-bytes-15pct",
        started_at=datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc),
        guardrails=Guardrails(mode="local"),
        mode="local",
        current_best=760000.0,
    )


def _records() -> list:
    return [
        JsonlSessionStart(
            ts=datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc),
            goal="reduce bundle_bytes by 15%",
            target_pct=-15.0,
            mode="local",
        ),
        JsonlExperiment(
            ts=datetime(2026, 4, 19, 10, 10, tzinfo=timezone.utc),
            id=1,
            candidate="Replace moment",
            reps_used=1,
            metric_before=842000.0,
            metric_after=760000.0,
            delta=-82000.0,
            confidence_ratio=94.2,
            status="improved",
            commit_sha="abc1234",
            files_modified=["package.json", "src/utils/date.ts"],
        ),
        JsonlExperiment(
            ts=datetime(2026, 4, 19, 10, 15, tzinfo=timezone.utc),
            id=2,
            candidate="Inline SVGs",
            reps_used=3,
            metric_before=760000.0,
            metric_after=759500.0,
            delta=-500.0,
            confidence_ratio=0.5,
            status="inconclusive",
            commit_sha=None,
            files_modified=[],
        ),
        JsonlExperiment(
            ts=datetime(2026, 4, 19, 10, 20, tzinfo=timezone.utc),
            id=3,
            candidate="Swap webpack",
            reps_used=1,
            metric_before=760000.0,
            metric_after=758000.0,
            delta=-2000.0,
            confidence_ratio=2.3,
            status="check_failed",
            commit_sha=None,
            files_modified=[],
        ),
        JsonlTerminated(
            ts=datetime(2026, 4, 19, 11, 0, tzinfo=timezone.utc),
            reason="target_hit",
            final_metric=760000.0,
            delta_pct=-9.7,
            kept=1,
            reverted=2,
            errored=0,
            wall_clock_seconds=3600,
            auto_finalize=True,
        ),
    ]


class TestRenderPrBody:
    def test_contains_goal_and_result(self) -> None:
        body = render_pr_body(_state(), _records())
        assert "bundle_bytes" in body
        assert "−9.7%" in body or "-9.7%" in body  # unicode minus or ASCII
        assert "842" in body  # baseline appears
        assert "760" in body  # final appears

    def test_lists_kept_experiments(self) -> None:
        body = render_pr_body(_state(), _records())
        assert "Replace moment" in body
        assert "abc1234" in body  # commit sha

    def test_dead_ends_section(self) -> None:
        body = render_pr_body(_state(), _records())
        assert "Dead" in body or "dead" in body or "didn" in body  # some dead-ends section header
        assert "Swap webpack" in body
        assert "Inline SVGs" in body

    def test_summary_table(self) -> None:
        body = render_pr_body(_state(), _records())
        # We expect a markdown table with at least the kept experiment row
        assert "|" in body
        assert "kept" in body.lower() or "landed" in body.lower()

    def test_wallclock_surfaced(self) -> None:
        body = render_pr_body(_state(), _records())
        assert "3600" in body or "1h" in body or "1 h" in body

    def test_output_is_nonempty_even_with_zero_experiments(self) -> None:
        body = render_pr_body(_state(), _records()[:1])  # just session_start
        assert len(body) > 0
```

- [ ] **Step 2: Run tests — expect fail**

```bash
uv run pytest tests/unit/test_pr_body.py -v
```

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `pr_body.py`**

`src/sindri/core/pr_body.py`:

```python
"""Render the PR description markdown from state + jsonl records.

This is the main user-facing artifact of a successful run. Structure:

    Title summary
    Result block (baseline → final, delta%, target hit or not)
    Kept commits table
    Dead-ends section (reverted + failed)
    Run stats (experiments, wall-clock, mode, noise floor)
"""
from __future__ import annotations

from sindri.core.validators import (
    JsonlExperiment,
    JsonlRecord,
    JsonlTerminated,
    SindriState,
)


def render_pr_body(state: SindriState, records: list[JsonlRecord]) -> str:
    """Assemble the PR body markdown."""
    experiments = [r for r in records if isinstance(r, JsonlExperiment)]
    terminated = next(
        (r for r in reversed(records) if isinstance(r, JsonlTerminated)),
        None,
    )

    sections: list[str] = []
    sections.append(_render_header(state, terminated))
    sections.append(_render_result(state, terminated))
    sections.append(_render_kept_table(experiments))
    sections.append(_render_dead_ends(experiments))
    sections.append(_render_run_stats(state, experiments, terminated))
    sections.append(_render_footer())
    return "\n\n".join(s for s in sections if s)


def _render_header(state: SindriState, terminated: JsonlTerminated | None) -> str:
    sign = "−" if state.goal.direction == "reduce" else "+"
    title = f"perf: {state.goal.direction} {state.goal.metric_name}"
    if terminated is not None:
        title += f" ({sign}{abs(terminated.delta_pct):.1f}%)"
    return f"## {title}\n\n*Autonomous optimization run by sindri.*"


def _render_result(state: SindriState, terminated: JsonlTerminated | None) -> str:
    lines = ["### Result\n"]
    lines.append(f"- **Goal:** {state.goal.direction} `{state.goal.metric_name}` by **{state.goal.target_pct}%**")
    lines.append(f"- **Baseline:** {state.baseline.value:,.0f}")
    lines.append(f"- **Noise floor (σ):** {state.baseline.noise_floor:,.2f}")
    if terminated is not None:
        hit = "✓ target hit" if terminated.reason == "target_hit" else f"({terminated.reason})"
        lines.append(f"- **Final:** {terminated.final_metric:,.0f} "
                     f"({'−' if terminated.delta_pct < 0 else '+'}{abs(terminated.delta_pct):.2f}%) {hit}")
    return "\n".join(lines)


def _render_kept_table(experiments: list[JsonlExperiment]) -> str:
    kept = [e for e in experiments if e.status == "improved"]
    if not kept:
        return ""
    lines = ["### Kept experiments\n"]
    lines.append("| # | Candidate | Δ metric | Confidence | Commit | Files |")
    lines.append("|---|---|---|---|---|---|")
    for e in kept:
        sha = f"`{e.commit_sha[:7]}`" if e.commit_sha else "-"
        files = ", ".join(e.files_modified[:3]) + ("…" if len(e.files_modified) > 3 else "")
        lines.append(
            f"| {e.id} | {e.candidate} | {e.delta:+,.0f} | {e.confidence_ratio:.1f}× | {sha} | {files} |"
        )
    return "\n".join(lines)


def _render_dead_ends(experiments: list[JsonlExperiment]) -> str:
    dead = [e for e in experiments if e.status != "improved"]
    if not dead:
        return ""
    lines = ["### Dead ends (for transparency)\n"]
    lines.append("Things that were tried but didn't land:\n")
    for e in dead:
        status_label = {
            "regressed": "regressed",
            "inconclusive": "inconclusive (below noise)",
            "check_failed": "tests/lint failed",
            "errored": "benchmark errored",
            "timeout": "timed out",
        }.get(e.status, e.status)
        lines.append(
            f"- **{e.candidate}** — {status_label} (Δ {e.delta:+,.0f}, conf {e.confidence_ratio:.1f}×)"
        )
    return "\n".join(lines)


def _render_run_stats(
    state: SindriState,
    experiments: list[JsonlExperiment],
    terminated: JsonlTerminated | None,
) -> str:
    lines = ["### Run stats\n"]
    lines.append(f"- **Mode:** {state.mode}")
    lines.append(f"- **Experiments run:** {len(experiments)} (of {len(state.pool)} in pool)")
    if terminated is not None:
        lines.append(f"- **Kept:** {terminated.kept} · **Reverted:** {terminated.reverted} · **Errored:** {terminated.errored}")
        lines.append(f"- **Wall-clock:** {terminated.wall_clock_seconds}s ({terminated.wall_clock_seconds // 60}m)")
    lines.append(f"- **Branch:** `{state.branch}`")
    return "\n".join(lines)


def _render_footer() -> str:
    return "---\n\n*Generated by [sindri](https://github.com/anthropics/sindri). Review the commit history for per-experiment details.*"
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
uv run pytest tests/unit/test_pr_body.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/sindri/core/pr_body.py tests/unit/test_pr_body.py
git commit -m "feat(core): add PR body markdown renderer"
```

---

## Phase 4 — CLI

The argparse layer. Each subcommand is a thin adapter: parse args, read stdin if relevant, call into `core/`, serialize result as JSON to stdout, exit 0 / non-zero.

### Task 11: CLI skeleton + dispatcher

**Files:**

- Create: `src/sindri/__main__.py`
- Create: `src/sindri/cli.py`
- Test: `tests/integration/test_cli.py`

- [ ] **Step 1: Write failing test for `--version` + `--help`**

`tests/integration/test_cli.py`:

```python
"""Integration tests for the CLI — invoke python -m sindri via subprocess."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


def _run_cli(*args: str, cwd: Path | None = None, input: str | None = None) -> subprocess.CompletedProcess:
    """Invoke `python -m sindri` with args. Returns the completed process."""
    return subprocess.run(
        [sys.executable, "-m", "sindri", *args],
        cwd=cwd,
        input=input,
        capture_output=True,
        text=True,
    )


class TestCliBasics:
    def test_version(self) -> None:
        r = _run_cli("--version")
        assert r.returncode == 0
        assert "0.1.0" in r.stdout

    def test_help_lists_subcommands(self) -> None:
        r = _run_cli("--help")
        assert r.returncode == 0
        # Subcommands should appear in help output
        for sub in ["validate-benchmark", "read-state", "pick-next", "record-result",
                    "check-termination", "generate-pr-body", "archive", "status",
                    "detect-mode", "init"]:
            assert sub in r.stdout, f"{sub} missing from --help"

    def test_unknown_subcommand_exits_nonzero(self) -> None:
        r = _run_cli("totally-made-up")
        assert r.returncode != 0
```

- [ ] **Step 2: Run — expect fail**

```bash
uv run pytest tests/integration/test_cli.py::TestCliBasics -v
```

Expected: ModuleNotFoundError for `sindri.__main__` (not yet written).

- [ ] **Step 3: Write `src/sindri/__main__.py`**

```python
"""Entry point for `python -m sindri`."""
from __future__ import annotations

from sindri.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Write `src/sindri/cli.py` skeleton**

```python
"""CLI entry point — argparse dispatcher for sindri subcommands.

Each subcommand is registered once here and dispatched to a handler function.
Handlers return an exit code (0 on success, non-zero on failure).
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Callable

from sindri import __version__

# Handler registry — populated in later tasks
_HANDLERS: dict[str, Callable[[argparse.Namespace], int]] = {}


def _register(name: str) -> Callable[[Callable[[argparse.Namespace], int]], Callable[[argparse.Namespace], int]]:
    """Decorator: register a subcommand handler."""
    def decorator(fn: Callable[[argparse.Namespace], int]) -> Callable[[argparse.Namespace], int]:
        _HANDLERS[name] = fn
        return fn
    return decorator


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sindri", description="Sindri: bounded optimization loop core")
    p.add_argument("--version", action="version", version=f"sindri {__version__}")
    sub = p.add_subparsers(dest="subcommand", required=False)

    # Subparsers are registered here as they're implemented. For the skeleton,
    # we just list their names so --help shows them.
    for name in [
        "init",
        "validate-benchmark",
        "detect-mode",
        "read-state",
        "pick-next",
        "record-result",
        "check-termination",
        "generate-pr-body",
        "archive",
        "status",
    ]:
        sub.add_parser(name, help=f"(not yet implemented: {name})")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.subcommand is None:
        parser.print_help()
        return 0
    handler = _HANDLERS.get(args.subcommand)
    if handler is None:
        print(f"error: subcommand {args.subcommand!r} not yet implemented", file=sys.stderr)
        return 2
    return handler(args)
```

- [ ] **Step 5: Add `__version__` to `src/sindri/__init__.py`**

```python
"""sindri — Claude Code plugin core for bounded optimization loops."""
from __future__ import annotations

__version__ = "0.1.0"
__all__ = ["__version__"]
```

- [ ] **Step 6: Run CLI basic tests — expect PASS**

```bash
uv run pytest tests/integration/test_cli.py::TestCliBasics -v
```

Expected: all 3 tests pass (version, help lists subcommands, unknown command exits non-zero).

- [ ] **Step 7: Commit**

```bash
git add src/sindri/__main__.py src/sindri/cli.py src/sindri/__init__.py tests/integration/test_cli.py
git commit -m "feat(cli): scaffold argparse dispatcher with subcommand registry"
```

---

### Task 12: CLI `validate-benchmark`

Runs `.claude/scripts/sindri/benchmark.py`, parses the final `METRIC` line, optionally compares against expected name.

**Files:**

- Modify: `src/sindri/cli.py` (add subcommand)
- Modify: `tests/integration/test_cli.py` (add tests)

- [ ] **Step 1: Write failing test**

Append to `tests/integration/test_cli.py`:

```python
class TestValidateBenchmark:
    def test_valid_script_returns_metric(self, tmp_path: Path) -> None:
        script_dir = tmp_path / ".claude" / "scripts" / "sindri"
        script_dir.mkdir(parents=True)
        script = script_dir / "benchmark.py"
        script.write_text(
            "#!/usr/bin/env python3\n"
            "print('METRIC bundle_bytes=842000')\n"
        )
        script.chmod(0o755)

        r = _run_cli("validate-benchmark", "--expected", "bundle_bytes", cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert data["metric_name"] == "bundle_bytes"
        assert data["metric_value"] == 842000.0
        assert data["ok"] is True

    def test_missing_script(self, tmp_path: Path) -> None:
        r = _run_cli("validate-benchmark", cwd=tmp_path)
        assert r.returncode != 0
        assert "benchmark.py" in r.stderr

    def test_script_no_metric_line(self, tmp_path: Path) -> None:
        script_dir = tmp_path / ".claude" / "scripts" / "sindri"
        script_dir.mkdir(parents=True)
        script = script_dir / "benchmark.py"
        script.write_text("#!/usr/bin/env python3\nprint('hello')\n")
        script.chmod(0o755)
        r = _run_cli("validate-benchmark", cwd=tmp_path)
        assert r.returncode != 0

    def test_expected_name_mismatch(self, tmp_path: Path) -> None:
        script_dir = tmp_path / ".claude" / "scripts" / "sindri"
        script_dir.mkdir(parents=True)
        script = script_dir / "benchmark.py"
        script.write_text("#!/usr/bin/env python3\nprint('METRIC bar=42')\n")
        script.chmod(0o755)
        r = _run_cli("validate-benchmark", "--expected", "foo", cwd=tmp_path)
        assert r.returncode != 0
```

Add `import json` to the imports at the top of `test_cli.py`.

- [ ] **Step 2: Run test — expect fail**

```bash
uv run pytest tests/integration/test_cli.py::TestValidateBenchmark -v
```

Expected: all 4 tests fail (subcommand not implemented).

- [ ] **Step 3: Implement the subcommand in `cli.py`**

Add to `src/sindri/cli.py` (replace the `for name in [...]: sub.add_parser(...)` block with explicit subparser building, and add handlers):

Replace the body of `_build_parser()` after `sub = p.add_subparsers(...)` with:

```python
    _add_validate_benchmark(sub)
    # Future subcommands registered here in subsequent tasks.
    return p


def _add_validate_benchmark(sub: argparse._SubParsersAction) -> None:
    vp = sub.add_parser(
        "validate-benchmark",
        help="run benchmark.py, check METRIC output",
    )
    vp.add_argument(
        "--expected",
        help="expected metric name; error if script outputs a different one",
    )
    vp.add_argument(
        "--script",
        default=".claude/scripts/sindri/benchmark.py",
        help="path to benchmark script (default: .claude/scripts/sindri/benchmark.py)",
    )
```

Then add the handler (below `_build_parser`):

```python
@_register("validate-benchmark")
def _handle_validate_benchmark(args: argparse.Namespace) -> int:
    import subprocess
    from pathlib import Path

    from sindri.core.metric import MetricParseError, parse_metric_line

    script = Path(args.script)
    if not script.exists():
        print(f"error: benchmark.py not found at {script}", file=sys.stderr)
        return 1

    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            check=False,
            timeout=300,  # sanity cap during validation
        )
    except subprocess.TimeoutExpired:
        print("error: benchmark timed out during validation (>5min)", file=sys.stderr)
        return 1

    if proc.returncode != 0:
        print(f"error: benchmark exited non-zero: {proc.stderr.strip()}", file=sys.stderr)
        return 1

    try:
        name, value = parse_metric_line(proc.stdout, expected_name=args.expected)
    except MetricParseError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    result = {"ok": True, "metric_name": name, "metric_value": value}
    print(json.dumps(result))
    return 0
```

Also, now that we register handlers explicitly, remove the "not yet implemented" fallback loop from `_build_parser()` — handlers registered via `_register` always appear in the subparser. Replace the old loop with the single `_add_validate_benchmark(sub)` call (already done above).

But the help test expects ALL subcommand names to appear in `--help`. Since we haven't built the parsers yet for the others, they won't appear. Adjust the help test to only check the subcommands implemented so far — or defer those subcommand help-checks to later tasks.

Update `test_help_lists_subcommands` in `tests/integration/test_cli.py`:

```python
    def test_help_lists_subcommands(self) -> None:
        r = _run_cli("--help")
        assert r.returncode == 0
        # Only validate-benchmark implemented in this task; the rest are
        # added in later tasks and their tests.
        assert "validate-benchmark" in r.stdout
```

- [ ] **Step 4: Run tests — expect PASS**

```bash
uv run pytest tests/integration/test_cli.py -v
```

Expected: `TestCliBasics` (3 tests) and `TestValidateBenchmark` (4 tests) all pass.

- [ ] **Step 5: Commit**

```bash
git add src/sindri/cli.py tests/integration/test_cli.py
git commit -m "feat(cli): add validate-benchmark subcommand"
```

---

### Task 13: CLI `detect-mode`

Wraps `core.modes.detect_mode`.

**Files:**

- Modify: `src/sindri/cli.py`
- Modify: `tests/integration/test_cli.py`

- [ ] **Step 1: Write failing test**

Append to `tests/integration/test_cli.py`:

```python
class TestDetectMode:
    def test_local_script(self, tmp_path: Path) -> None:
        script_dir = tmp_path / ".claude" / "scripts" / "sindri"
        script_dir.mkdir(parents=True)
        script = script_dir / "benchmark.py"
        script.write_text("print('METRIC x=42')")
        payload = json.dumps({"baseline_samples": [500.0, 100.0, 101.0, 99.0]})
        r = _run_cli("detect-mode", cwd=tmp_path, input=payload)
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert data["mode"] == "local"

    def test_remote_by_keyword(self, tmp_path: Path) -> None:
        script_dir = tmp_path / ".claude" / "scripts" / "sindri"
        script_dir.mkdir(parents=True)
        script = script_dir / "benchmark.py"
        script.write_text("import subprocess\nsubprocess.run(['gh', 'workflow', 'run'])\nprint('METRIC x=42')")
        payload = json.dumps({"baseline_samples": [500.0, 100.0, 101.0, 99.0]})
        r = _run_cli("detect-mode", cwd=tmp_path, input=payload)
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert data["mode"] == "remote"

    def test_remote_by_cv(self, tmp_path: Path) -> None:
        script_dir = tmp_path / ".claude" / "scripts" / "sindri"
        script_dir.mkdir(parents=True)
        script = script_dir / "benchmark.py"
        script.write_text("print('METRIC x=42')")
        # High variance non-warmup samples
        payload = json.dumps({"baseline_samples": [500.0, 100.0, 80.0, 120.0, 70.0, 130.0]})
        r = _run_cli("detect-mode", cwd=tmp_path, input=payload)
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert data["mode"] == "remote"
```

- [ ] **Step 2: Run test — expect fail**

```bash
uv run pytest tests/integration/test_cli.py::TestDetectMode -v
```

Expected: 3 failures.

- [ ] **Step 3: Implement**

Add to `cli.py` (in `_build_parser`, after `_add_validate_benchmark(sub)`):

```python
    _add_detect_mode(sub)
```

And the subparser + handler:

```python
def _add_detect_mode(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "detect-mode",
        help="auto-detect local vs remote benchmark mode; reads JSON from stdin",
    )
    p.add_argument(
        "--script",
        default=".claude/scripts/sindri/benchmark.py",
        help="path to benchmark script",
    )


@_register("detect-mode")
def _handle_detect_mode(args: argparse.Namespace) -> int:
    from pathlib import Path
    from sindri.core.modes import detect_mode

    try:
        payload = json.loads(sys.stdin.read())
        samples = payload["baseline_samples"]
    except (json.JSONDecodeError, KeyError) as e:
        print(f"error: malformed stdin (need {{'baseline_samples': [...]}}): {e}", file=sys.stderr)
        return 1

    script = Path(args.script)
    if not script.exists():
        print(f"error: script not found: {script}", file=sys.stderr)
        return 1

    mode = detect_mode(script, samples)
    print(json.dumps({"mode": mode}))
    return 0
```

- [ ] **Step 4: Run test — expect PASS**

```bash
uv run pytest tests/integration/test_cli.py::TestDetectMode -v
```

Expected: 3 passes.

- [ ] **Step 5: Commit**

```bash
git add src/sindri/cli.py tests/integration/test_cli.py
git commit -m "feat(cli): add detect-mode subcommand"
```

---

### Task 14: CLI `read-state`

Reads `.sindri/current/sindri.md` and prints state as JSON.

**Files:**

- Modify: `src/sindri/cli.py`
- Modify: `tests/integration/test_cli.py`

- [ ] **Step 1: Write failing test**

Append to `tests/integration/test_cli.py`:

```python
class TestReadState:
    def test_reads_existing_state(self, tmp_path: Path) -> None:
        # Set up valid state
        from datetime import datetime, timezone
        from sindri.core.state import write_state
        from sindri.core.validators import Baseline, Candidate, Goal, Guardrails, SindriState

        sindri_dir = tmp_path / ".sindri" / "current"
        state = SindriState(
            goal=Goal(metric_name="x", direction="reduce", target_pct=15.0),
            baseline=Baseline(value=100.0, noise_floor=1.0, samples=[100.0, 101.0, 99.0]),
            pool=[Candidate(id=1, name="a", expected_impact_pct=-10.0)],
            branch="sindri/test",
            started_at=datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc),
            guardrails=Guardrails(mode="local"),
            mode="local",
        )
        write_state(state, dir=sindri_dir)

        r = _run_cli("read-state", cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert data["goal"]["metric_name"] == "x"
        assert data["mode"] == "local"
        assert len(data["pool"]) == 1

    def test_missing_state_fails(self, tmp_path: Path) -> None:
        r = _run_cli("read-state", cwd=tmp_path)
        assert r.returncode != 0
        assert "state" in r.stderr.lower()
```

- [ ] **Step 2: Run — expect fail**

```bash
uv run pytest tests/integration/test_cli.py::TestReadState -v
```

- [ ] **Step 3: Implement**

Add to `cli.py` (register after detect-mode):

```python
    _add_read_state(sub)
```

And:

```python
def _add_read_state(sub: argparse._SubParsersAction) -> None:
    sub.add_parser("read-state", help="read .sindri/current/sindri.md; emit JSON")


@_register("read-state")
def _handle_read_state(args: argparse.Namespace) -> int:
    from sindri.core.state import StateIOError, read_state

    try:
        state = read_state()
    except StateIOError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(state.model_dump_json())
    return 0
```

- [ ] **Step 4: Run — expect PASS**

```bash
uv run pytest tests/integration/test_cli.py::TestReadState -v
```

- [ ] **Step 5: Commit**

```bash
git add src/sindri/cli.py tests/integration/test_cli.py
git commit -m "feat(cli): add read-state subcommand"
```

---

### Task 15: CLI `pick-next`

Reads state, picks the next pending candidate, returns as JSON (or `null`).

**Files:**

- Modify: `src/sindri/cli.py`
- Modify: `tests/integration/test_cli.py`

- [ ] **Step 1: Write failing test**

Append to `tests/integration/test_cli.py`:

```python
class TestPickNext:
    def test_picks_highest_impact_pending(self, tmp_path: Path) -> None:
        from datetime import datetime, timezone
        from sindri.core.state import write_state
        from sindri.core.validators import Baseline, Candidate, Goal, Guardrails, SindriState

        state = SindriState(
            goal=Goal(metric_name="x", direction="reduce", target_pct=15.0),
            baseline=Baseline(value=100.0, noise_floor=1.0, samples=[100.0, 101.0, 99.0]),
            pool=[
                Candidate(id=1, name="small", expected_impact_pct=-2.0),
                Candidate(id=2, name="big", expected_impact_pct=-20.0),
            ],
            branch="sindri/test",
            started_at=datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc),
            guardrails=Guardrails(mode="local"),
            mode="local",
        )
        write_state(state, dir=tmp_path / ".sindri" / "current")
        r = _run_cli("pick-next", cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        picked = json.loads(r.stdout)
        assert picked["id"] == 2
        assert picked["name"] == "big"

    def test_null_when_all_resolved(self, tmp_path: Path) -> None:
        from datetime import datetime, timezone
        from sindri.core.state import write_state
        from sindri.core.validators import Baseline, Candidate, Goal, Guardrails, SindriState

        state = SindriState(
            goal=Goal(metric_name="x", direction="reduce", target_pct=15.0),
            baseline=Baseline(value=100.0, noise_floor=1.0, samples=[100.0, 101.0, 99.0]),
            pool=[
                Candidate(id=1, name="a", expected_impact_pct=-5.0, status="kept"),
                Candidate(id=2, name="b", expected_impact_pct=-3.0, status="reverted"),
            ],
            branch="sindri/test",
            started_at=datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc),
            guardrails=Guardrails(mode="local"),
            mode="local",
        )
        write_state(state, dir=tmp_path / ".sindri" / "current")
        r = _run_cli("pick-next", cwd=tmp_path)
        assert r.returncode == 0
        assert json.loads(r.stdout) is None
```

- [ ] **Step 2: Run — expect fail**

```bash
uv run pytest tests/integration/test_cli.py::TestPickNext -v
```

- [ ] **Step 3: Implement**

Add registration `_add_pick_next(sub)` in `_build_parser` and:

```python
def _add_pick_next(sub: argparse._SubParsersAction) -> None:
    sub.add_parser("pick-next", help="pick next pending candidate from state")


@_register("pick-next")
def _handle_pick_next(args: argparse.Namespace) -> int:
    from sindri.core.pool import pick_next
    from sindri.core.state import StateIOError, read_state

    try:
        state = read_state()
    except StateIOError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    nxt = pick_next(state.pool)
    if nxt is None:
        print("null")
    else:
        print(nxt.model_dump_json())
    return 0
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/sindri/cli.py tests/integration/test_cli.py
git commit -m "feat(cli): add pick-next subcommand"
```

---

### Task 16: CLI `record-result`

Reads a subagent result JSON from stdin, validates it, and appends an experiment record to sindri.jsonl + updates the candidate's status in sindri.md.

**Files:**

- Modify: `src/sindri/cli.py`
- Modify: `tests/integration/test_cli.py`

- [ ] **Step 1: Write failing test**

Append to `tests/integration/test_cli.py`:

```python
class TestRecordResult:
    def _setup_state_with_pending(self, tmp_path: Path) -> None:
        from datetime import datetime, timezone
        from sindri.core.state import write_state
        from sindri.core.validators import Baseline, Candidate, Goal, Guardrails, SindriState

        state = SindriState(
            goal=Goal(metric_name="x", direction="reduce", target_pct=15.0),
            baseline=Baseline(value=100.0, noise_floor=1.0, samples=[100.0, 101.0, 99.0]),
            pool=[
                Candidate(id=1, name="a", expected_impact_pct=-10.0, status="pending"),
                Candidate(id=2, name="b", expected_impact_pct=-5.0, status="pending"),
            ],
            branch="sindri/test",
            started_at=datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc),
            guardrails=Guardrails(mode="local"),
            mode="local",
        )
        write_state(state, dir=tmp_path / ".sindri" / "current")

    def test_improved_updates_status_and_appends(self, tmp_path: Path) -> None:
        self._setup_state_with_pending(tmp_path)
        payload = json.dumps({
            "candidate_id": 1,
            "metric_before": 100.0,
            "subagent_result": {
                "metric_value": 85.0,
                "reps_used": 1,
                "confidence_ratio": 15.0,
                "status": "improved",
                "files_modified": ["x.py"],
                "notes": "win",
            },
            "commit_sha": "abc1234",
        })
        r = _run_cli("record-result", cwd=tmp_path, input=payload)
        assert r.returncode == 0, r.stderr

        # State updated
        from sindri.core.state import read_state
        state = read_state(dir=tmp_path / ".sindri" / "current")
        cand = next(c for c in state.pool if c.id == 1)
        assert cand.status == "kept"
        assert state.current_best == 85.0

        # JSONL appended
        jsonl = (tmp_path / ".sindri" / "current" / "sindri.jsonl").read_text().strip().splitlines()
        assert len(jsonl) == 1
        rec = json.loads(jsonl[0])
        assert rec["type"] == "experiment"
        assert rec["status"] == "improved"

    def test_regressed_marks_reverted_no_current_best_change(self, tmp_path: Path) -> None:
        self._setup_state_with_pending(tmp_path)
        payload = json.dumps({
            "candidate_id": 2,
            "metric_before": 100.0,
            "subagent_result": {
                "metric_value": 120.0,
                "reps_used": 3,
                "confidence_ratio": 20.0,
                "status": "regressed",
                "files_modified": [],
            },
            "commit_sha": None,
        })
        r = _run_cli("record-result", cwd=tmp_path, input=payload)
        assert r.returncode == 0, r.stderr
        from sindri.core.state import read_state
        state = read_state(dir=tmp_path / ".sindri" / "current")
        cand = next(c for c in state.pool if c.id == 2)
        assert cand.status == "reverted"
        assert state.current_best is None

    def test_invalid_payload_rejected(self, tmp_path: Path) -> None:
        self._setup_state_with_pending(tmp_path)
        r = _run_cli("record-result", cwd=tmp_path, input="not json")
        assert r.returncode != 0
```

- [ ] **Step 2: Run — expect fail**

```bash
uv run pytest tests/integration/test_cli.py::TestRecordResult -v
```

- [ ] **Step 3: Implement**

Add `_add_record_result(sub)` in `_build_parser` and:

```python
def _add_record_result(sub: argparse._SubParsersAction) -> None:
    sub.add_parser(
        "record-result",
        help="record an experiment result; reads JSON from stdin",
    )


@_register("record-result")
def _handle_record_result(args: argparse.Namespace) -> int:
    from datetime import datetime, timezone
    from pydantic import BaseModel, ValidationError

    from sindri.core.state import append_jsonl, read_state, write_state
    from sindri.core.validators import JsonlExperiment, SubagentResult

    class RecordPayload(BaseModel):
        candidate_id: int
        metric_before: float
        subagent_result: SubagentResult
        commit_sha: str | None = None

    try:
        raw = sys.stdin.read()
        payload = RecordPayload.model_validate_json(raw)
    except ValidationError as e:
        print(f"error: invalid payload: {e}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"error: payload is not JSON: {e}", file=sys.stderr)
        return 1

    state = read_state()
    cand = next((c for c in state.pool if c.id == payload.candidate_id), None)
    if cand is None:
        print(f"error: no candidate with id {payload.candidate_id}", file=sys.stderr)
        return 1

    res = payload.subagent_result
    delta = res.metric_value - payload.metric_before

    # Map subagent status → pool-candidate status
    pool_status_map = {
        "improved": "kept",
        "regressed": "reverted",
        "inconclusive": "reverted",
        "check_failed": "check_failed",
        "errored": "errored",
        "timeout": "errored",
    }
    new_status = pool_status_map[res.status]

    # Update pool entry; if improved, update current_best
    new_pool = []
    for c in state.pool:
        if c.id == payload.candidate_id:
            new_pool.append(c.model_copy(update={"status": new_status}))
        else:
            new_pool.append(c)
    updates = {"pool": new_pool}
    if res.status == "improved":
        updates["current_best"] = res.metric_value
    new_state = state.model_copy(update=updates)
    write_state(new_state)

    # Append jsonl experiment record
    rec = JsonlExperiment(
        ts=datetime.now(tz=timezone.utc),
        id=payload.candidate_id,
        candidate=cand.name,
        reps_used=res.reps_used,
        metric_before=payload.metric_before,
        metric_after=res.metric_value,
        delta=delta,
        confidence_ratio=res.confidence_ratio,
        status=res.status,
        commit_sha=payload.commit_sha,
        files_modified=res.files_modified,
    )
    append_jsonl(rec)

    print(json.dumps({"ok": True, "new_status": new_status, "current_best": new_state.current_best}))
    return 0
```

- [ ] **Step 4: Run — expect PASS**

```bash
uv run pytest tests/integration/test_cli.py::TestRecordResult -v
```

- [ ] **Step 5: Commit**

```bash
git add src/sindri/cli.py tests/integration/test_cli.py
git commit -m "feat(cli): add record-result subcommand"
```

---

### Task 17: CLI `check-termination`

Reads state + runtime counters, returns termination decision.

**Files:**

- Modify: `src/sindri/cli.py`
- Modify: `tests/integration/test_cli.py`

- [ ] **Step 1: Write failing test**

Append to `tests/integration/test_cli.py`:

```python
class TestCheckTermination:
    def test_not_terminated(self, tmp_path: Path) -> None:
        from datetime import datetime, timezone
        from sindri.core.state import write_state
        from sindri.core.validators import Baseline, Candidate, Goal, Guardrails, SindriState

        state = SindriState(
            goal=Goal(metric_name="x", direction="reduce", target_pct=15.0),
            baseline=Baseline(value=100.0, noise_floor=1.0, samples=[100.0, 101.0, 99.0]),
            pool=[Candidate(id=1, name="a", expected_impact_pct=-10.0)],
            branch="sindri/test",
            started_at=datetime.now(tz=timezone.utc),
            guardrails=Guardrails(mode="local"),
            mode="local",
        )
        write_state(state, dir=tmp_path / ".sindri" / "current")
        payload = json.dumps({"experiments_run": 0, "consecutive_reverts": 0})
        r = _run_cli("check-termination", cwd=tmp_path, input=payload)
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert data["terminated"] is False

    def test_target_hit(self, tmp_path: Path) -> None:
        from datetime import datetime, timezone
        from sindri.core.state import write_state
        from sindri.core.validators import Baseline, Candidate, Goal, Guardrails, SindriState

        state = SindriState(
            goal=Goal(metric_name="x", direction="reduce", target_pct=15.0),
            baseline=Baseline(value=100.0, noise_floor=1.0, samples=[100.0, 101.0, 99.0]),
            pool=[Candidate(id=1, name="a", expected_impact_pct=-10.0, status="kept")],
            branch="sindri/test",
            started_at=datetime.now(tz=timezone.utc),
            guardrails=Guardrails(mode="local"),
            mode="local",
            current_best=84.0,
        )
        write_state(state, dir=tmp_path / ".sindri" / "current")
        payload = json.dumps({"experiments_run": 1, "consecutive_reverts": 0})
        r = _run_cli("check-termination", cwd=tmp_path, input=payload)
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert data["terminated"] is True
        assert data["reason"] == "target_hit"
        assert data["auto_finalize"] is True
```

- [ ] **Step 2: Run — expect fail**

- [ ] **Step 3: Implement**

Add `_add_check_termination(sub)` and:

```python
def _add_check_termination(sub: argparse._SubParsersAction) -> None:
    sub.add_parser(
        "check-termination",
        help="check whether the loop should terminate; JSON {experiments_run, consecutive_reverts} on stdin",
    )


@_register("check-termination")
def _handle_check_termination(args: argparse.Namespace) -> int:
    from sindri.core.state import read_state
    from sindri.core.termination import check_termination

    try:
        payload = json.loads(sys.stdin.read())
        experiments_run = int(payload["experiments_run"])
        consecutive_reverts = int(payload["consecutive_reverts"])
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
        print(f"error: invalid stdin payload: {e}", file=sys.stderr)
        return 1

    state = read_state()
    result = check_termination(
        state,
        experiments_run=experiments_run,
        consecutive_reverts=consecutive_reverts,
    )
    print(result.model_dump_json())
    return 0
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/sindri/cli.py tests/integration/test_cli.py
git commit -m "feat(cli): add check-termination subcommand"
```

---

### Task 18: CLI `generate-pr-body`

Reads state + jsonl, emits PR markdown to stdout.

**Files:**

- Modify: `src/sindri/cli.py`
- Modify: `tests/integration/test_cli.py`

- [ ] **Step 1: Write failing test**

Append to `tests/integration/test_cli.py`:

```python
class TestGeneratePrBody:
    def test_emits_markdown(self, tmp_path: Path) -> None:
        from datetime import datetime, timezone
        from sindri.core.state import append_jsonl, write_state
        from sindri.core.validators import (
            Baseline, Candidate, Goal, Guardrails,
            JsonlExperiment, JsonlTerminated, SindriState,
        )

        state = SindriState(
            goal=Goal(metric_name="x", direction="reduce", target_pct=15.0),
            baseline=Baseline(value=100.0, noise_floor=1.0, samples=[100.0, 101.0, 99.0]),
            pool=[Candidate(id=1, name="a", expected_impact_pct=-10.0, status="kept")],
            branch="sindri/test",
            started_at=datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc),
            guardrails=Guardrails(mode="local"),
            mode="local",
            current_best=80.0,
        )
        d = tmp_path / ".sindri" / "current"
        write_state(state, dir=d)
        append_jsonl(
            JsonlExperiment(
                ts=datetime(2026, 4, 19, 10, 5, tzinfo=timezone.utc),
                id=1, candidate="a", reps_used=1,
                metric_before=100.0, metric_after=80.0, delta=-20.0,
                confidence_ratio=20.0, status="improved",
                commit_sha="abc1234", files_modified=["x.py"],
            ),
            path=d / "sindri.jsonl",
        )
        append_jsonl(
            JsonlTerminated(
                ts=datetime(2026, 4, 19, 10, 10, tzinfo=timezone.utc),
                reason="target_hit", final_metric=80.0, delta_pct=-20.0,
                kept=1, reverted=0, errored=0, wall_clock_seconds=600, auto_finalize=True,
            ),
            path=d / "sindri.jsonl",
        )
        r = _run_cli("generate-pr-body", cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        assert "## " in r.stdout  # markdown heading
        assert "−20" in r.stdout or "-20" in r.stdout
        assert "abc1234" in r.stdout
```

- [ ] **Step 2: Run — expect fail**

- [ ] **Step 3: Implement**

Add `_add_generate_pr_body(sub)` and:

```python
def _add_generate_pr_body(sub: argparse._SubParsersAction) -> None:
    sub.add_parser("generate-pr-body", help="print PR body markdown to stdout")


@_register("generate-pr-body")
def _handle_generate_pr_body(args: argparse.Namespace) -> int:
    from pathlib import Path
    from sindri.core.pr_body import render_pr_body
    from sindri.core.state import read_jsonl, read_state

    state = read_state()
    records = read_jsonl(Path(".sindri/current/sindri.jsonl"))
    print(render_pr_body(state, records))
    return 0
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/sindri/cli.py tests/integration/test_cli.py
git commit -m "feat(cli): add generate-pr-body subcommand"
```

---

### Task 19: CLI `archive`

Moves `.sindri/current/` → `.sindri/archive/<date>-<slug>/`.

**Files:**

- Modify: `src/sindri/cli.py`
- Modify: `tests/integration/test_cli.py`

- [ ] **Step 1: Write failing test**

Append to `tests/integration/test_cli.py`:

```python
class TestArchive:
    def test_moves_current_to_archive(self, tmp_path: Path) -> None:
        from datetime import datetime, timezone
        from sindri.core.state import write_state
        from sindri.core.validators import Baseline, Candidate, Goal, Guardrails, SindriState

        state = SindriState(
            goal=Goal(metric_name="x", direction="reduce", target_pct=15.0),
            baseline=Baseline(value=100.0, noise_floor=1.0, samples=[100.0, 101.0, 99.0]),
            pool=[Candidate(id=1, name="a", expected_impact_pct=-10.0)],
            branch="sindri/reduce-x-15pct",
            started_at=datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc),
            guardrails=Guardrails(mode="local"),
            mode="local",
        )
        current = tmp_path / ".sindri" / "current"
        write_state(state, dir=current)

        r = _run_cli("archive", cwd=tmp_path)
        assert r.returncode == 0, r.stderr

        # current/ should be gone
        assert not current.exists()
        # archive/<date>-reduce-x-15pct/ should exist with the files
        archive_root = tmp_path / ".sindri" / "archive"
        subdirs = list(archive_root.iterdir())
        assert len(subdirs) == 1
        assert "reduce-x-15pct" in subdirs[0].name
        assert (subdirs[0] / "sindri.md").exists()

    def test_no_current_fails(self, tmp_path: Path) -> None:
        r = _run_cli("archive", cwd=tmp_path)
        assert r.returncode != 0
```

- [ ] **Step 2: Run — expect fail**

- [ ] **Step 3: Implement**

```python
def _add_archive(sub: argparse._SubParsersAction) -> None:
    sub.add_parser("archive", help="move .sindri/current/ to .sindri/archive/<date>-<slug>/")


@_register("archive")
def _handle_archive(args: argparse.Namespace) -> int:
    import shutil
    from datetime import date
    from pathlib import Path

    from sindri.core.state import StateIOError, read_state

    current = Path(".sindri/current")
    if not current.exists():
        print("error: .sindri/current/ does not exist", file=sys.stderr)
        return 1

    try:
        state = read_state(dir=current)
    except StateIOError as e:
        print(f"error: cannot read state: {e}", file=sys.stderr)
        return 1

    # Slug is the branch name minus the 'sindri/' prefix
    branch = state.branch
    slug = branch[len("sindri/"):] if branch.startswith("sindri/") else branch
    archive_name = f"{date.today().isoformat()}-{slug}"
    archive_dir = Path(".sindri") / "archive" / archive_name
    archive_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(current), str(archive_dir))

    print(json.dumps({"ok": True, "archived_to": str(archive_dir)}))
    return 0
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/sindri/cli.py tests/integration/test_cli.py
git commit -m "feat(cli): add archive subcommand"
```

---

### Task 20: CLI `status`

Human-readable status summary. Reads state + jsonl, prints a short report to stdout.

**Files:**

- Modify: `src/sindri/cli.py`
- Modify: `tests/integration/test_cli.py`

- [ ] **Step 1: Write failing test**

Append to `tests/integration/test_cli.py`:

```python
class TestStatus:
    def test_prints_summary(self, tmp_path: Path) -> None:
        from datetime import datetime, timezone
        from sindri.core.state import write_state
        from sindri.core.validators import Baseline, Candidate, Goal, Guardrails, SindriState

        state = SindriState(
            goal=Goal(metric_name="bundle_bytes", direction="reduce", target_pct=15.0),
            baseline=Baseline(value=842000.0, noise_floor=870.0, samples=[843000.0, 841000.0, 842000.0]),
            pool=[
                Candidate(id=1, name="a", expected_impact_pct=-10.0, status="kept"),
                Candidate(id=2, name="b", expected_impact_pct=-5.0, status="pending"),
            ],
            branch="sindri/reduce-bundle-bytes-15pct",
            started_at=datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc),
            guardrails=Guardrails(mode="local"),
            mode="local",
            current_best=760000.0,
        )
        write_state(state, dir=tmp_path / ".sindri" / "current")

        r = _run_cli("status", cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        # Should contain key numbers
        assert "842" in r.stdout  # baseline
        assert "760" in r.stdout  # current
        assert "reduce" in r.stdout.lower() or "bundle_bytes" in r.stdout.lower()
        assert "2" in r.stdout  # pool size
```

- [ ] **Step 2: Run — expect fail**

- [ ] **Step 3: Implement**

```python
def _add_status(sub: argparse._SubParsersAction) -> None:
    sub.add_parser("status", help="human-readable summary of current run")


@_register("status")
def _handle_status(args: argparse.Namespace) -> int:
    from sindri.core.state import StateIOError, read_state

    try:
        state = read_state()
    except StateIOError:
        print("sindri: no active run (.sindri/current/ not found)")
        return 0

    kept = sum(1 for c in state.pool if c.status == "kept")
    reverted = sum(1 for c in state.pool if c.status == "reverted")
    pending = sum(1 for c in state.pool if c.status == "pending")
    dead = sum(1 for c in state.pool if c.status in {"errored", "check_failed"})

    current = state.current_best if state.current_best is not None else state.baseline.value
    delta_pct = ((current - state.baseline.value) / state.baseline.value) * 100

    print(f"sindri: {state.goal.direction} {state.goal.metric_name} by {state.goal.target_pct}%")
    print(f"  branch:    {state.branch}")
    print(f"  mode:      {state.mode}")
    print(f"  baseline:  {state.baseline.value:,.0f} (σ {state.baseline.noise_floor:,.2f})")
    print(f"  current:   {current:,.0f} ({delta_pct:+.2f}%)")
    print(f"  pool:      {len(state.pool)} total · {kept} kept · {reverted} reverted · {dead} dead · {pending} pending")
    return 0
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add src/sindri/cli.py tests/integration/test_cli.py
git commit -m "feat(cli): add status subcommand"
```

---

### Task 21: CLI `init` (end-to-end init wiring)

Initializes a new run: parses goal, validates benchmark, scans repo briefly (stub — full scan is the skill's job), runs baseline 3 times, detects mode, writes initial state.

This subcommand is called by `sindri-start` skill. The skill handles interactive bits (pool draft, approval); this subcommand handles the deterministic setup.

**Files:**

- Modify: `src/sindri/cli.py`
- Modify: `tests/integration/test_cli.py`

- [ ] **Step 1: Write failing test**

Append to `tests/integration/test_cli.py`:

```python
class TestInit:
    def test_init_creates_state_from_goal(self, tmp_path: Path) -> None:
        # Set up repo with a fake deterministic benchmark
        (tmp_path / "README.md").write_text("# test\n")
        script_dir = tmp_path / ".claude" / "scripts" / "sindri"
        script_dir.mkdir(parents=True)
        script = script_dir / "benchmark.py"
        # Print a deterministic metric
        script.write_text(
            "#!/usr/bin/env python3\n"
            "print('METRIC bundle_bytes=100')\n"
        )
        script.chmod(0o755)

        # Init a git repo so the branch creation works
        subprocess.run(["git", "init", "-b", "main"], check=True, cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t"], check=True, cwd=tmp_path)
        subprocess.run(["git", "config", "user.name", "t"], check=True, cwd=tmp_path)
        subprocess.run(["git", "add", "-A"], check=True, cwd=tmp_path)
        subprocess.run(["git", "commit", "-m", "init"], check=True, cwd=tmp_path, capture_output=True)

        # Pool must be provided by caller (the skill drafts it)
        pool_json = json.dumps([
            {"id": 1, "name": "Replace moment", "expected_impact_pct": -10.0},
            {"id": 2, "name": "Tree-shake", "expected_impact_pct": -5.0},
        ])
        r = _run_cli(
            "init",
            "--goal", "reduce bundle_bytes by 15%",
            "--pool-json", pool_json,
            cwd=tmp_path,
        )
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        assert out["ok"] is True

        # State file created
        state_file = tmp_path / ".sindri" / "current" / "sindri.md"
        assert state_file.exists()

        # Branch created
        result = subprocess.run(["git", "branch", "--show-current"], cwd=tmp_path, capture_output=True, text=True)
        assert "sindri/" in result.stdout

    def test_init_rejects_existing_current(self, tmp_path: Path) -> None:
        (tmp_path / ".sindri" / "current").mkdir(parents=True)
        (tmp_path / ".sindri" / "current" / "sindri.md").write_text("existing")
        pool_json = json.dumps([])
        r = _run_cli(
            "init",
            "--goal", "reduce x by 10%",
            "--pool-json", pool_json,
            cwd=tmp_path,
        )
        assert r.returncode != 0
        assert "current" in r.stderr.lower()

    def test_init_rejects_malformed_goal(self, tmp_path: Path) -> None:
        pool_json = json.dumps([])
        r = _run_cli(
            "init",
            "--goal", "make it faster",  # no direction/target
            "--pool-json", pool_json,
            cwd=tmp_path,
        )
        assert r.returncode != 0
```

- [ ] **Step 2: Run — expect fail**

- [ ] **Step 3: Implement**

```python
def _add_init(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser("init", help="initialize a new sindri run from a goal and candidate pool")
    p.add_argument("--goal", required=True, help="goal string, e.g. 'reduce bundle_bytes by 15%'")
    p.add_argument(
        "--pool-json",
        required=True,
        help="JSON array of candidate dicts (id, name, expected_impact_pct, optional files)",
    )
    p.add_argument(
        "--script",
        default=".claude/scripts/sindri/benchmark.py",
        help="path to benchmark script",
    )


_GOAL_RE = __import__("re").compile(
    r"(?P<direction>reduce|increase)\s+(?P<metric>[a-z][a-z0-9_]*)\s+by\s+(?P<pct>\d+(?:\.\d+)?)\s*%",
    __import__("re").IGNORECASE,
)


@_register("init")
def _handle_init(args: argparse.Namespace) -> int:
    import subprocess as sp
    from datetime import datetime, timezone
    from pathlib import Path

    from sindri.core.git_ops import GitError, create_branch
    from sindri.core.metric import MetricParseError, parse_metric_line
    from sindri.core.modes import detect_mode
    from sindri.core.noise import noise_floor
    from sindri.core.state import append_jsonl, write_state
    from sindri.core.validators import (
        Baseline,
        Candidate,
        Goal,
        Guardrails,
        JsonlBaseline,
        JsonlBaselineComplete,
        JsonlSessionStart,
        SindriState,
    )

    current_dir = Path(".sindri/current")
    if current_dir.exists():
        print("error: .sindri/current/ already exists — another run is active", file=sys.stderr)
        return 1

    # Parse goal string
    m = _GOAL_RE.search(args.goal)
    if not m:
        print(
            "error: malformed goal — expected 'reduce|increase <metric> by <N>%'",
            file=sys.stderr,
        )
        return 1
    direction = m.group("direction").lower()
    metric_name = m.group("metric")
    target_pct = float(m.group("pct"))

    try:
        goal = Goal(metric_name=metric_name, direction=direction, target_pct=target_pct)  # type: ignore[arg-type]
    except Exception as e:
        print(f"error: invalid goal: {e}", file=sys.stderr)
        return 1

    # Parse pool
    try:
        pool_raw = json.loads(args.pool_json)
        pool = [Candidate(**c) for c in pool_raw]
    except Exception as e:
        print(f"error: invalid pool-json: {e}", file=sys.stderr)
        return 1

    # Validate benchmark
    script = Path(args.script)
    if not script.exists():
        print(f"error: benchmark.py not found at {script}", file=sys.stderr)
        return 1

    # Run baseline 3 times
    samples: list[float] = []
    for run_idx in range(1, 4):
        try:
            proc = sp.run(
                [sys.executable, str(script)],
                capture_output=True, text=True, check=False, timeout=1800,
            )
        except sp.TimeoutExpired:
            print(f"error: benchmark timed out during baseline run {run_idx}", file=sys.stderr)
            return 1
        if proc.returncode != 0:
            print(f"error: benchmark failed on baseline run {run_idx}: {proc.stderr.strip()}", file=sys.stderr)
            return 1
        try:
            _, value = parse_metric_line(proc.stdout, expected_name=metric_name)
        except MetricParseError as e:
            print(f"error: baseline run {run_idx}: {e}", file=sys.stderr)
            return 1
        samples.append(value)

    try:
        sigma = noise_floor(samples)
    except Exception as e:
        print(f"error: noise floor computation failed: {e}", file=sys.stderr)
        return 1

    mean_val = sum(samples[1:]) / len(samples[1:])  # post-warmup mean
    mode = detect_mode(script, samples)

    # Create branch
    slug = f"{direction}-{metric_name.replace('_', '-')}-{int(target_pct)}pct"
    branch_name = f"sindri/{slug}"
    try:
        create_branch(branch_name)
    except GitError as e:
        print(f"error: could not create branch: {e}", file=sys.stderr)
        return 1

    # Build state + write
    now = datetime.now(tz=timezone.utc)
    state = SindriState(
        goal=goal,
        baseline=Baseline(value=mean_val, noise_floor=sigma, samples=samples),
        pool=pool,
        branch=branch_name,
        started_at=now,
        guardrails=Guardrails(mode=mode),  # type: ignore[arg-type]
        mode=mode,
    )
    write_state(state)

    # Seed jsonl
    sign = "-" if direction == "reduce" else "+"
    append_jsonl(JsonlSessionStart(ts=now, goal=args.goal, target_pct=float(f"{sign}{target_pct}"), mode=mode))
    for i, v in enumerate(samples, start=1):
        append_jsonl(
            JsonlBaseline(ts=now, run_index=i, value=v, is_warmup=(i == 1))
        )
    append_jsonl(JsonlBaselineComplete(ts=now, mean=mean_val, noise_floor=sigma))

    print(json.dumps({"ok": True, "branch": branch_name, "baseline": mean_val, "noise_floor": sigma, "mode": mode}))
    return 0
```

- [ ] **Step 4: Run — expect PASS**

```bash
uv run pytest tests/integration/test_cli.py::TestInit -v
```

- [ ] **Step 5: Commit**

```bash
git add src/sindri/cli.py tests/integration/test_cli.py
git commit -m "feat(cli): add init subcommand for end-to-end run setup"
```

---

## Milestone checkpoint

Run the full suite with coverage:

```bash
uv run pytest --cov=sindri --cov-report=term-missing -v
```

Expected:
- Every test from tasks 1–21 passes.
- Coverage ≥ 95% on `sindri/core/` pure modules, ≥ 80% on I/O-touching modules.

Tag the commit so we can reference this milestone:

```bash
git tag -a v0.1.0-core -m "Python core + CLI milestone (Plan 1 complete)"
```

**What Plan 1 produced:**
- A pip-installable Python package (`uv pip install -e .`)
- 10 core modules, each designed by tests
- 10 CLI subcommands accessible via `python -m sindri <cmd>`
- Full unit test suite + integration tests that hit real git + filesystem
- Zero runtime deps beyond pydantic

**What's still needed (Plan 2 territory):**
- Claude Code plugin manifest (`.claude-plugin/plugin.json`)
- Slash command (`commands/sindri.md`)
- Four skills (`sindri-start`, `sindri-scaffold-benchmark`, `sindri-loop`, `sindri-finalize`)
- Experiment subagent prompt template (`prompts/experiment-subagent.md`)
- End-to-end loop test with stub subagent
- Smoke script, CI workflow

A second plan (`docs/superpowers/plans/2026-04-?-sindri-plugin-artifacts.md`) will cover that layer.

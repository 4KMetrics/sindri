"""Pydantic models — the authoritative schemas across sindri's boundaries.

Every value that crosses between the CLI and its callers (skills, shell, etc.)
passes through one of these models. Schema drift fails fast.
"""
from __future__ import annotations

import re
from datetime import datetime
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
        # Enforce mode-specific defaults unless explicitly overridden by caller.
        # Remote mode is single-rep: trust the baseline, don't pay for multi-rep.
        if self.mode == "remote":
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


# Union type used when reading jsonl — pydantic picks the right subclass by `type`.
JsonlRecord = (
    JsonlSessionStart
    | JsonlBaseline
    | JsonlBaselineComplete
    | JsonlExperiment
    | JsonlEvent
    | JsonlTerminated
)

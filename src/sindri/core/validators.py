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
    # `max` and `adaptive` resolve based on `mode` when not provided.
    # Unset (None) vs. passed-default (e.g. max=10 for remote) used to
    # be conflated, silently stomping a caller's explicit choice.
    model_config = ConfigDict(extra="forbid")

    mode: Literal["local", "remote"]
    min: int = 1
    max: int | None = None
    adaptive: bool | None = None
    confidence_threshold: float = 2.0

    def model_post_init(self, __context: object) -> None:
        if self.max is None:
            object.__setattr__(self, "max", 1 if self.mode == "remote" else 10)
        if self.adaptive is None:
            object.__setattr__(self, "adaptive", self.mode == "local")


_LOCAL_WALL_CLOCK_SECONDS = 8 * 3600
_REMOTE_WALL_CLOCK_SECONDS = 72 * 3600
_LOCAL_EXPERIMENT_TIMEOUT_SECONDS = 30 * 60
_REMOTE_EXPERIMENT_TIMEOUT_SECONDS = 2 * 3600


class Guardrails(BaseModel):
    # `max_wall_clock_seconds` and `timeout_per_experiment_seconds` resolve
    # based on `mode` when not provided. Previous implementation used a
    # "if == local default, promote to remote default" pattern that silently
    # overrode a caller who happened to pass the local value in remote mode.
    model_config = ConfigDict(extra="forbid")

    mode: Literal["local", "remote"]
    max_experiments: int = 50
    max_wall_clock_seconds: int | None = None
    max_reverts_in_a_row: int = 7
    baseline_reps: int = 3
    timeout_per_experiment_seconds: int | None = None
    reps_policy: RepsPolicy | None = None

    def model_post_init(self, __context: object) -> None:
        if self.reps_policy is None:
            object.__setattr__(self, "reps_policy", RepsPolicy(mode=self.mode))
        if self.max_wall_clock_seconds is None:
            object.__setattr__(
                self,
                "max_wall_clock_seconds",
                _REMOTE_WALL_CLOCK_SECONDS
                if self.mode == "remote"
                else _LOCAL_WALL_CLOCK_SECONDS,
            )
        if self.timeout_per_experiment_seconds is None:
            object.__setattr__(
                self,
                "timeout_per_experiment_seconds",
                _REMOTE_EXPERIMENT_TIMEOUT_SECONDS
                if self.mode == "remote"
                else _LOCAL_EXPERIMENT_TIMEOUT_SECONDS,
            )


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

    @field_validator("started_at")
    @classmethod
    def _require_tz_aware(cls, v: datetime) -> datetime:
        # Naive datetimes silently "become UTC" downstream and mask wall-clock
        # bugs; reject them at the boundary instead.
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("started_at must be timezone-aware")
        return v


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

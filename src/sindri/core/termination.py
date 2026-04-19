"""Termination decision table.

Given the current state + runtime counters, returns:
  - whether to terminate
  - the reason (or None)
  - whether auto-finalize should fire (only on clean termination with wins)
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

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

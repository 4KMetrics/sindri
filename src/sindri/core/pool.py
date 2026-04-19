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

    For 'reduce': current_best <= baseline * (1 - target_pct/100).
    For 'increase': current_best >= baseline * (1 + target_pct/100).
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

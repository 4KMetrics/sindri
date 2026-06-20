"""Tests for the termination decision table."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

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
    direction: Literal["reduce", "increase"] = "reduce",
    target_pct: float = 15.0,
    baseline_value: float = 100.0,
) -> SindriState:
    return SindriState(
        goal=Goal(metric_name="x", direction=direction, target_pct=target_pct),
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
        s = _state(current_best=80.0)
        result = check_termination(s, experiments_run=5, consecutive_reverts=0)
        assert result.terminated is True
        assert result.reason == "target_hit"
        assert result.auto_finalize is True

    def test_pool_empty_with_wins(self) -> None:
        pool = [
            Candidate(id=1, name="a", expected_impact_pct=-10, status="kept"),
            Candidate(id=2, name="b", expected_impact_pct=-5, status="reverted"),
        ]
        s = _state(pool=pool, current_best=90.0)
        result = check_termination(s, experiments_run=2, consecutive_reverts=1)
        assert result.terminated is True
        assert result.reason == "pool_empty"
        assert result.auto_finalize is True

    def test_pool_empty_no_wins(self) -> None:
        pool = [
            Candidate(id=1, name="a", expected_impact_pct=-10, status="reverted"),
            Candidate(id=2, name="b", expected_impact_pct=-5, status="reverted"),
        ]
        s = _state(pool=pool, current_best=None)
        result = check_termination(s, experiments_run=2, consecutive_reverts=2)
        assert result.terminated is True
        assert result.reason == "pool_empty"
        assert result.auto_finalize is False

    def test_kept_candidate_at_baseline_value_is_still_a_win(self) -> None:
        # Regression for #32: _has_wins counts kept candidates, NOT
        # current_best != baseline.value. A kept candidate whose metric landed
        # exactly on the baseline (delta below noise) must still count as a win
        # and auto-finalize — the old float-equality check wrongly suppressed it.
        pool = [Candidate(id=1, name="a", expected_impact_pct=-10, status="kept")]
        s = _state(pool=pool, current_best=100.0)  # equal to baseline_value
        result = check_termination(s, experiments_run=1, consecutive_reverts=0)
        assert result.terminated is True
        assert result.reason == "pool_empty"
        assert result.auto_finalize is True

    def test_no_kept_candidate_is_not_a_win(self) -> None:
        # Inverse: a pool with no kept candidate never auto-finalizes, even if
        # current_best happens to be set (e.g. a reverted experiment's value).
        pool = [Candidate(id=1, name="a", expected_impact_pct=-10, status="reverted")]
        s = _state(pool=pool, current_best=90.0)
        result = check_termination(s, experiments_run=1, consecutive_reverts=1)
        assert result.terminated is True
        assert result.reason == "pool_empty"
        assert result.auto_finalize is False

    def test_max_experiments_hit_with_wins(self) -> None:
        # A kept candidate present (and a pending one so the pool isn't
        # exhausted first) → max_experiments halt auto-finalizes.
        pool = [
            Candidate(id=1, name="a", expected_impact_pct=-10, status="kept"),
            Candidate(id=2, name="b", expected_impact_pct=-5),
        ]
        s = _state(pool=pool, current_best=95.0)
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
        pool = [
            Candidate(id=1, name="a", expected_impact_pct=-10, status="kept"),
            Candidate(id=2, name="b", expected_impact_pct=-5),
        ]
        s = _state(pool=pool, current_best=90.0, started_at=past)
        result = check_termination(s, experiments_run=5, consecutive_reverts=0)
        assert result.terminated is True
        assert result.reason == "max_wall_clock"
        assert result.auto_finalize is True

    def test_max_reverts(self) -> None:
        s = _state()
        result = check_termination(s, experiments_run=7, consecutive_reverts=7)
        assert result.terminated is True
        assert result.reason == "max_reverts_in_a_row"
        assert result.auto_finalize is False

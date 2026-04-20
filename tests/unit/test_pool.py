"""Tests for pool ordering and termination predicates."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

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
    direction: Literal["reduce", "increase"] = "reduce",
    target_pct: float = 15.0,
    baseline_value: float = 100.0,
    started_at: datetime | None = None,
) -> SindriState:
    return SindriState(
        goal=Goal(metric_name="x", direction=direction, target_pct=target_pct),
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
        pool = [
            Candidate(id=1, name="a", expected_impact_pct=+5.0),
            Candidate(id=2, name="b", expected_impact_pct=+20.0),
        ]
        nxt = pick_next(pool)
        assert nxt is not None
        assert nxt.id == 2

    def test_unknown_order_by_raises(self) -> None:
        pool = [Candidate(id=1, name="a", expected_impact_pct=-5.0)]
        with pytest.raises(ValueError):
            pick_next(pool, order_by="bogus")  # type: ignore[arg-type]


class TestTargetHit:
    def test_reduce_hit(self) -> None:
        s = _state(pool=[], current_best=84.0, direction="reduce", target_pct=15.0, baseline_value=100.0)
        assert target_hit(s) is True

    def test_reduce_not_hit(self) -> None:
        s = _state(pool=[], current_best=90.0, direction="reduce", target_pct=15.0, baseline_value=100.0)
        assert target_hit(s) is False

    def test_increase_hit(self) -> None:
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

"""Unit tests for core.verify — the pure independent-verification decision.

This is the deterministic replacement for the subagent's self-graded status:
given an INDEPENDENT measurement, decide whether a claimed improvement is real.
"""
from __future__ import annotations

import pytest

from sindri.core.verify import decide_verification


class TestDecideVerification:
    def test_reduce_confirmed_improvement_is_verified(self) -> None:
        # lower-is-better; independent run clearly below baseline, well above noise.
        d = decide_verification(
            independent_value=900.0, metric_before=1000.0,
            direction="reduce", noise_floor=1.0, confidence_threshold=2.0,
        )
        assert d.status == "improved"
        assert d.verified is True
        assert d.delta == pytest.approx(-100.0)
        assert d.confidence_ratio == pytest.approx(100.0)

    def test_reduce_regression_is_not_verified(self) -> None:
        d = decide_verification(
            independent_value=1100.0, metric_before=1000.0,
            direction="reduce", noise_floor=1.0, confidence_threshold=2.0,
        )
        assert d.status == "regressed"
        assert d.verified is False

    def test_increase_confirmed_improvement_is_verified(self) -> None:
        d = decide_verification(
            independent_value=1200.0, metric_before=1000.0,
            direction="increase", noise_floor=10.0, confidence_threshold=2.0,
        )
        assert d.status == "improved"
        assert d.verified is True

    def test_increase_regression_is_not_verified(self) -> None:
        d = decide_verification(
            independent_value=800.0, metric_before=1000.0,
            direction="increase", noise_floor=10.0, confidence_threshold=2.0,
        )
        assert d.status == "regressed"
        assert d.verified is False

    def test_within_noise_is_inconclusive_not_verified(self) -> None:
        # a 1-unit move with a 5-unit noise floor → conf 0.2 < 2.0 → inconclusive.
        d = decide_verification(
            independent_value=999.0, metric_before=1000.0,
            direction="reduce", noise_floor=5.0, confidence_threshold=2.0,
        )
        assert d.status == "inconclusive"
        assert d.verified is False

    def test_confidence_exactly_at_threshold_counts(self) -> None:
        # delta 10, floor 5 → conf exactly 2.0; >= threshold so it decides.
        d = decide_verification(
            independent_value=990.0, metric_before=1000.0,
            direction="reduce", noise_floor=5.0, confidence_threshold=2.0,
        )
        assert d.confidence_ratio == pytest.approx(2.0)
        assert d.status == "improved"
        assert d.verified is True

    def test_zero_noise_floor_is_decided_by_direction(self) -> None:
        # deterministic benchmark: any real delta is high-confidence.
        d = decide_verification(
            independent_value=999.0, metric_before=1000.0,
            direction="reduce", noise_floor=0.0, confidence_threshold=2.0,
        )
        assert d.status == "improved"
        assert d.verified is True

    def test_no_change_is_inconclusive(self) -> None:
        d = decide_verification(
            independent_value=1000.0, metric_before=1000.0,
            direction="reduce", noise_floor=1.0, confidence_threshold=2.0,
        )
        assert d.delta == pytest.approx(0.0)
        assert d.status == "inconclusive"
        assert d.verified is False

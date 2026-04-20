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
        samples = [1000.0, 100.0, 101.0, 99.0, 100.0]
        floor = noise_floor(samples)
        # Without warmup discard, std would be huge (~400); with discard, ~1
        assert floor < 5.0

    def test_keep_warmup_when_requested(self) -> None:
        samples = [1000.0, 100.0, 101.0, 99.0, 100.0]
        floor = noise_floor(samples, discard_warmup=False)
        assert floor > 300.0  # the outlier inflates std

    def test_two_samples_after_warmup(self) -> None:
        samples = [500.0, 100.0, 102.0]
        floor = noise_floor(samples)
        # sample_std_dev of [100, 102] = sqrt(2) ≈ 1.414
        assert floor == pytest.approx(math.sqrt(2), rel=1e-6)

    def test_identical_samples_zero_noise(self) -> None:
        assert noise_floor([500.0, 100.0, 100.0, 100.0]) == 0.0

    def test_too_few_samples_raises(self) -> None:
        with pytest.raises(NoiseComputationError):
            noise_floor([100.0])
        with pytest.raises(NoiseComputationError):
            noise_floor([100.0, 101.0], discard_warmup=True)  # warmup discard leaves 1


class TestConfidenceRatio:
    def test_basic_ratio(self) -> None:
        assert confidence_ratio(delta=10.0, floor=2.0) == pytest.approx(5.0)

    def test_negative_delta(self) -> None:
        assert confidence_ratio(delta=-10.0, floor=2.0) == pytest.approx(5.0)

    def test_zero_floor_doesnt_blow_up(self) -> None:
        r = confidence_ratio(delta=1.0, floor=0.0)
        assert r > 1e5  # effectively infinite, but finite

    def test_zero_delta(self) -> None:
        assert confidence_ratio(delta=0.0, floor=1.0) == 0.0


class TestCoefficientOfVariation:
    def test_basic(self) -> None:
        samples = [99.0, 100.0, 101.0, 100.0, 100.0]
        cv = coefficient_of_variation(samples)
        assert 0.005 < cv < 0.02  # roughly 1%

    def test_noisy(self) -> None:
        samples = [80.0, 120.0, 100.0, 80.0, 120.0]
        cv = coefficient_of_variation(samples)
        assert cv > 0.15

    def test_identical_samples_zero_cv(self) -> None:
        assert coefficient_of_variation([5.0, 5.0, 5.0]) == 0.0

    def test_mean_zero_raises(self) -> None:
        with pytest.raises(NoiseComputationError):
            coefficient_of_variation([-1.0, 0.0, 1.0])

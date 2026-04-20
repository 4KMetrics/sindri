"""Noise floor, confidence, and variation statistics.

All functions are pure: they take floats in, return floats out.
No I/O, no state.
"""
from __future__ import annotations

import statistics

# Small number added to divisors to prevent division by zero on deterministic benchmarks.
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

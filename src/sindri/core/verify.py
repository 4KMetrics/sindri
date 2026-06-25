"""Independent-verification decision — the deterministic replacement for the
experiment subagent's self-graded status.

Pure: takes an INDEPENDENT measurement plus the run's baseline/noise, returns a
decision. No I/O, no state. The orchestrator (and `verify-candidate`) runs the
benchmark itself, then calls this to decide whether a claimed improvement is
real — so the agent that proposes a win is never the one that certifies it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sindri.core.noise import confidence_ratio

Direction = Literal["reduce", "increase"]
VerifiedStatus = Literal["improved", "regressed", "inconclusive"]


@dataclass(frozen=True)
class VerificationDecision:
    verified: bool
    status: VerifiedStatus
    delta: float
    confidence_ratio: float


def decide_verification(
    *,
    independent_value: float,
    metric_before: float,
    direction: Direction,
    noise_floor: float,
    confidence_threshold: float = 2.0,
) -> VerificationDecision:
    """Decide whether an independent re-measurement confirms an improvement.

    `verified` is True ONLY for a confidence-clearing improvement — the single
    condition under which a keep may be committed. A regression or an
    inconclusive (within-noise) result is never verified.
    """
    delta = independent_value - metric_before
    conf = confidence_ratio(delta=delta, floor=noise_floor)
    improves = delta < 0 if direction == "reduce" else delta > 0

    if conf < confidence_threshold:
        status: VerifiedStatus = "inconclusive"
    elif improves:
        status = "improved"
    else:
        status = "regressed"

    return VerificationDecision(
        verified=status == "improved",
        status=status,
        delta=delta,
        confidence_ratio=conf,
    )

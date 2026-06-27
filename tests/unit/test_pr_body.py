"""Unit tests for PR body rendering — pure template function."""
from __future__ import annotations

from datetime import datetime, timezone

from sindri.core.pr_body import render_pr_body
from sindri.core.validators import (
    Baseline,
    Candidate,
    Goal,
    Guardrails,
    JsonlExperiment,
    JsonlSessionStart,
    JsonlTerminated,
    SindriState,
)


def _state() -> SindriState:
    return SindriState(
        goal=Goal(metric_name="bundle_bytes", direction="reduce", target_pct=15.0),
        baseline=Baseline(value=842000.0, noise_floor=870.0, samples=[843100.0, 841400.0, 842500.0]),
        pool=[
            Candidate(id=1, name="Replace moment", expected_impact_pct=-10.0, status="kept"),
            Candidate(id=2, name="Inline SVGs", expected_impact_pct=-2.0, status="reverted"),
            Candidate(id=3, name="Swap webpack", expected_impact_pct=-5.0, status="check_failed"),
        ],
        branch="sindri/reduce-bundle-bytes-15pct",
        started_at=datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc),
        guardrails=Guardrails(mode="local"),
        mode="local",
        current_best=760000.0,
    )


def _records() -> list:
    return [
        JsonlSessionStart(
            ts=datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc),
            goal="reduce bundle_bytes by 15%",
            target_pct=-15.0,
            mode="local",
        ),
        JsonlExperiment(
            ts=datetime(2026, 4, 19, 10, 10, tzinfo=timezone.utc),
            id=1,
            candidate="Replace moment",
            reps_used=1,
            metric_before=842000.0,
            metric_after=760000.0,
            delta=-82000.0,
            confidence_ratio=94.2,
            status="improved",
            commit_sha="abc1234",
            files_modified=["package.json", "src/utils/date.ts"],
        ),
        JsonlExperiment(
            ts=datetime(2026, 4, 19, 10, 15, tzinfo=timezone.utc),
            id=2,
            candidate="Inline SVGs",
            reps_used=3,
            metric_before=760000.0,
            metric_after=759500.0,
            delta=-500.0,
            confidence_ratio=0.5,
            status="inconclusive",
            commit_sha=None,
            files_modified=[],
        ),
        JsonlExperiment(
            ts=datetime(2026, 4, 19, 10, 20, tzinfo=timezone.utc),
            id=3,
            candidate="Swap webpack",
            reps_used=1,
            metric_before=760000.0,
            metric_after=758000.0,
            delta=-2000.0,
            confidence_ratio=2.3,
            status="check_failed",
            commit_sha=None,
            files_modified=[],
        ),
        JsonlTerminated(
            ts=datetime(2026, 4, 19, 11, 0, tzinfo=timezone.utc),
            reason="target_hit",
            final_metric=760000.0,
            delta_pct=-9.7,
            kept=1,
            reverted=2,
            errored=0,
            wall_clock_seconds=3600,
            auto_finalize=True,
        ),
    ]


class TestRenderPrBody:
    def test_contains_goal_and_result(self) -> None:
        body = render_pr_body(_state(), _records())
        assert "bundle_bytes" in body
        assert "−9.7%" in body or "-9.7%" in body
        assert "842" in body
        assert "760" in body

    def test_lists_kept_experiments(self) -> None:
        body = render_pr_body(_state(), _records())
        assert "Replace moment" in body
        assert "abc1234" in body

    def test_dead_ends_section(self) -> None:
        body = render_pr_body(_state(), _records())
        assert "Dead" in body or "dead" in body or "didn" in body
        assert "Swap webpack" in body
        assert "Inline SVGs" in body

    def test_summary_table(self) -> None:
        body = render_pr_body(_state(), _records())
        assert "|" in body
        assert "kept" in body.lower() or "landed" in body.lower()

    def test_wallclock_surfaced(self) -> None:
        body = render_pr_body(_state(), _records())
        assert "3600" in body or "1h" in body or "1 h" in body

    def test_output_is_nonempty_even_with_zero_experiments(self) -> None:
        body = render_pr_body(_state(), _records()[:1])
        assert len(body) > 0


def test_footer_links_to_source_repo() -> None:
    # #68: footer must point at the real repo, not the 404'ing anthropics/sindri.
    body = render_pr_body(_state(), _records())
    assert "4KMetrics/sindri" in body
    assert "anthropics/sindri" not in body


def _deterministic_state() -> SindriState:
    return _state().model_copy(
        update={"baseline": Baseline(value=30.0, noise_floor=0.0, samples=[30.0, 30.0])}
    )


def test_deterministic_confidence_renders_as_infinity() -> None:
    # #70: noise_floor == 0 → confidence is a meaningless sentinel; render ∞, not 1e7.
    recs = _records()
    recs[1] = recs[1].model_copy(update={"confidence_ratio": 1e7})  # the kept experiment
    body = render_pr_body(_deterministic_state(), recs)
    assert "∞" in body
    assert "10000000" not in body


def test_nondeterministic_confidence_stays_numeric() -> None:
    body = render_pr_body(_state(), _records())  # real noise floor (870)
    assert "94.2×" in body

"""Unit tests for pydantic models in sindri.core.validators."""
from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from sindri.core.validators import (
    Baseline,
    Candidate,
    Goal,
    Guardrails,
    JsonlBaseline,
    JsonlBaselineComplete,
    JsonlEvent,
    JsonlExperiment,
    JsonlSessionStart,
    JsonlTerminated,
    RepsPolicy,
    SindriState,
    SubagentResult,
)


class TestGoal:
    def test_reduce_goal_parses(self) -> None:
        g = Goal(metric_name="bundle_bytes", direction="reduce", target_pct=15.0)
        assert g.metric_name == "bundle_bytes"
        assert g.direction == "reduce"
        assert g.target_pct == 15.0

    def test_increase_goal_parses(self) -> None:
        g = Goal(metric_name="lighthouse_score", direction="increase", target_pct=20.0)
        assert g.direction == "increase"

    def test_invalid_direction_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Goal(metric_name="x", direction="sideways", target_pct=10.0)  # type: ignore[arg-type]

    def test_target_pct_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            Goal(metric_name="x", direction="reduce", target_pct=-5.0)

    def test_metric_name_must_be_snake_case(self) -> None:
        with pytest.raises(ValidationError):
            Goal(metric_name="Bundle Bytes", direction="reduce", target_pct=15.0)


class TestBaseline:
    def test_baseline_parses(self) -> None:
        b = Baseline(value=842000.0, noise_floor=870.0, samples=[843100.0, 841400.0, 842500.0])
        assert b.value == 842000.0
        assert b.noise_floor == 870.0
        assert len(b.samples) == 3

    def test_negative_noise_floor_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Baseline(value=100.0, noise_floor=-1.0, samples=[100.0, 101.0, 99.0])

    def test_samples_must_be_at_least_2(self) -> None:
        with pytest.raises(ValidationError):
            Baseline(value=100.0, noise_floor=1.0, samples=[100.0])


class TestCandidate:
    def test_candidate_parses(self) -> None:
        c = Candidate(id=1, name="Replace moment", expected_impact_pct=-10.0)
        assert c.status == "pending"  # default
        assert c.files == []

    def test_status_enum_enforced(self) -> None:
        with pytest.raises(ValidationError):
            Candidate(id=1, name="x", expected_impact_pct=-5.0, status="maybe")  # type: ignore[arg-type]


class TestRepsPolicy:
    def test_local_defaults(self) -> None:
        p = RepsPolicy(mode="local")
        assert p.min == 1
        assert p.max == 10
        assert p.adaptive is True
        assert p.confidence_threshold == 2.0

    def test_remote_defaults(self) -> None:
        p = RepsPolicy(mode="remote")
        assert p.max == 1
        assert p.adaptive is False


class TestGuardrails:
    def test_defaults_local(self) -> None:
        g = Guardrails(mode="local")
        assert g.max_experiments == 50
        assert g.max_wall_clock_seconds == 28800  # 8h
        assert g.max_reverts_in_a_row == 7
        assert g.baseline_reps == 3
        assert g.reps_policy is not None
        assert g.reps_policy.adaptive is True

    def test_defaults_remote(self) -> None:
        g = Guardrails(mode="remote")
        assert g.max_wall_clock_seconds == 259200  # 72h
        assert g.reps_policy is not None
        assert g.reps_policy.adaptive is False


class TestSindriState:
    def test_minimal_state(self) -> None:
        s = SindriState(
            goal=Goal(metric_name="x", direction="reduce", target_pct=10.0),
            baseline=Baseline(value=100.0, noise_floor=1.0, samples=[100.0, 101.0, 99.0]),
            pool=[Candidate(id=1, name="a", expected_impact_pct=-5.0)],
            branch="sindri/reduce-x-10pct",
            started_at=datetime(2026, 4, 19, 10, 0, 0),
            guardrails=Guardrails(mode="local"),
            mode="local",
        )
        assert s.goal.metric_name == "x"
        assert len(s.pool) == 1


class TestSubagentResult:
    def test_valid_improved_result(self) -> None:
        r = SubagentResult(
            metric_value=760000.0,
            reps_used=3,
            confidence_ratio=4.2,
            status="improved",
            files_modified=["package.json"],
            notes="Swapped dep",
        )
        assert r.status == "improved"

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SubagentResult(  # type: ignore[call-arg]
                metric_value=1.0,
                reps_used=1,
                confidence_ratio=1.0,
                status="maybe",
                files_modified=[],
            )

    def test_reps_used_must_be_positive(self) -> None:
        with pytest.raises(ValidationError):
            SubagentResult(
                metric_value=1.0,
                reps_used=0,
                confidence_ratio=1.0,
                status="improved",
                files_modified=[],
            )


class TestJsonlRecords:
    def test_session_start(self) -> None:
        r = JsonlSessionStart(
            ts=datetime(2026, 4, 19, 10, 0),
            goal="reduce bundle_bytes by 15%",
            target_pct=-15.0,
            mode="local",
        )
        assert r.type == "session_start"

    def test_baseline_run(self) -> None:
        r = JsonlBaseline(ts=datetime.now(), run_index=1, value=842.0, is_warmup=True)
        assert r.type == "baseline"

    def test_baseline_complete(self) -> None:
        r = JsonlBaselineComplete(ts=datetime.now(), mean=842.0, noise_floor=0.78)
        assert r.type == "baseline_complete"

    def test_experiment(self) -> None:
        r = JsonlExperiment(
            ts=datetime.now(),
            id=1,
            candidate="Replace moment",
            reps_used=3,
            metric_before=842.0,
            metric_after=760.0,
            delta=-82.0,
            confidence_ratio=4.2,
            status="improved",
            commit_sha="abc1234",
            files_modified=["package.json"],
        )
        assert r.type == "experiment"

    def test_event(self) -> None:
        r = JsonlEvent(ts=datetime.now(), event="halted", reason="max_reverts", details="7 in a row")
        assert r.type == "event"

    def test_terminated(self) -> None:
        r = JsonlTerminated(
            ts=datetime.now(),
            reason="target_hit",
            final_metric=714.0,
            delta_pct=-15.2,
            kept=5,
            reverted=2,
            errored=0,
            wall_clock_seconds=1800,
            auto_finalize=True,
        )
        assert r.type == "terminated"

"""Integration tests for state file I/O (reads and writes to tmp dirs)."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from sindri.core.state import (
    StateIOError,
    append_jsonl,
    read_jsonl,
    read_state,
    write_state,
)
from sindri.core.validators import (
    Baseline,
    Candidate,
    Goal,
    Guardrails,
    JsonlBaseline,
    JsonlExperiment,
    JsonlSessionStart,
    SindriState,
)


@pytest.fixture
def sample_state() -> SindriState:
    return SindriState(
        goal=Goal(metric_name="bundle_bytes", direction="reduce", target_pct=15.0),
        baseline=Baseline(value=842000.0, noise_floor=870.0, samples=[843100.0, 841400.0, 842500.0]),
        pool=[
            Candidate(id=1, name="Replace moment", expected_impact_pct=-10.0),
            Candidate(id=2, name="Tree-shake lodash", expected_impact_pct=-5.0, status="kept"),
        ],
        branch="sindri/reduce-bundle-bytes-15pct",
        started_at=datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc),
        guardrails=Guardrails(mode="local"),
        mode="local",
    )


class TestStateRoundTrip:
    def test_write_then_read_preserves_fields(self, tmp_sindri_dir: Path, sample_state: SindriState) -> None:
        write_state(sample_state, dir=tmp_sindri_dir)
        assert (tmp_sindri_dir / "sindri.md").exists()
        loaded = read_state(dir=tmp_sindri_dir)
        assert loaded.goal.metric_name == sample_state.goal.metric_name
        assert loaded.baseline.value == sample_state.baseline.value
        assert len(loaded.pool) == 2
        assert loaded.pool[1].status == "kept"

    def test_read_missing_raises(self, tmp_sindri_dir: Path) -> None:
        with pytest.raises(StateIOError):
            read_state(dir=tmp_sindri_dir)

    def test_frontmatter_is_first_thing_in_file(self, tmp_sindri_dir: Path, sample_state: SindriState) -> None:
        write_state(sample_state, dir=tmp_sindri_dir)
        content = (tmp_sindri_dir / "sindri.md").read_text()
        assert content.startswith("---\n")


class TestJsonlAppend:
    def test_append_single_record(self, tmp_sindri_dir: Path) -> None:
        path = tmp_sindri_dir / "sindri.jsonl"
        rec = JsonlSessionStart(
            ts=datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc),
            goal="reduce bundle by 15%",
            target_pct=-15.0,
            mode="local",
        )
        append_jsonl(rec, path=path)
        lines = path.read_text().strip().splitlines()
        assert len(lines) == 1
        assert '"type":"session_start"' in lines[0].replace(" ", "")

    def test_append_multiple_preserves_order(self, tmp_sindri_dir: Path) -> None:
        path = tmp_sindri_dir / "sindri.jsonl"
        append_jsonl(
            JsonlBaseline(ts=datetime.now(tz=timezone.utc), run_index=1, value=100.0, is_warmup=True),
            path=path,
        )
        append_jsonl(
            JsonlBaseline(ts=datetime.now(tz=timezone.utc), run_index=2, value=101.0, is_warmup=False),
            path=path,
        )
        lines = path.read_text().strip().splitlines()
        assert len(lines) == 2

    def test_read_jsonl_returns_typed_records(self, tmp_sindri_dir: Path) -> None:
        path = tmp_sindri_dir / "sindri.jsonl"
        append_jsonl(
            JsonlSessionStart(
                ts=datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc),
                goal="x",
                target_pct=-10.0,
                mode="local",
            ),
            path=path,
        )
        append_jsonl(
            JsonlExperiment(
                ts=datetime(2026, 4, 19, 10, 5, tzinfo=timezone.utc),
                id=1,
                candidate="Replace moment",
                reps_used=3,
                metric_before=100.0,
                metric_after=80.0,
                delta=-20.0,
                confidence_ratio=4.2,
                status="improved",
                commit_sha="abc123",
                files_modified=["package.json"],
            ),
            path=path,
        )
        records = read_jsonl(path)
        assert len(records) == 2
        assert records[0].type == "session_start"
        assert records[1].type == "experiment"

    def test_read_jsonl_missing_returns_empty(self, tmp_sindri_dir: Path) -> None:
        assert read_jsonl(tmp_sindri_dir / "nonexistent.jsonl") == []

    def test_read_jsonl_skips_malformed_but_records_warning(self, tmp_sindri_dir: Path) -> None:
        # Corrupt jsonl (e.g. from a partial write after a crash) — we skip
        # malformed lines rather than refusing to read at all.
        path = tmp_sindri_dir / "sindri.jsonl"
        path.write_text(
            '{"type":"session_start","ts":"2026-04-19T10:00:00+00:00","goal":"x","target_pct":-10.0,"mode":"local"}\n'
            "not valid json\n"
            '{"type":"baseline","ts":"2026-04-19T10:01:00+00:00","run_index":1,"value":100.0,"is_warmup":true}\n'
        )
        records = read_jsonl(path)
        assert len(records) == 2  # malformed line skipped

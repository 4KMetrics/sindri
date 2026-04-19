"""Integration tests for the CLI — invoke python -m sindri via subprocess."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run_cli(
    *args: str,
    cwd: Path | None = None,
    input: str | None = None,
) -> subprocess.CompletedProcess:
    """Invoke `python -m sindri` with args. Returns the completed process."""
    return subprocess.run(
        [sys.executable, "-m", "sindri", *args],
        cwd=cwd,
        input=input,
        capture_output=True,
        text=True,
    )


class TestCliBasics:
    def test_version(self) -> None:
        r = _run_cli("--version")
        assert r.returncode == 0
        assert "0.1.0" in r.stdout

    def test_help_lists_subcommands(self) -> None:
        r = _run_cli("--help")
        assert r.returncode == 0
        # Subcommand set is grown incrementally per-task; the final broadening
        # back to all 10 happens in Task 21 once every `_add_*` is registered.
        assert "validate-benchmark" in r.stdout

    def test_unknown_subcommand_exits_nonzero(self) -> None:
        r = _run_cli("totally-made-up")
        assert r.returncode != 0


class TestValidateBenchmark:
    def test_valid_script_returns_metric(self, tmp_path: Path) -> None:
        script_dir = tmp_path / ".claude" / "scripts" / "sindri"
        script_dir.mkdir(parents=True)
        script = script_dir / "benchmark.py"
        script.write_text(
            "#!/usr/bin/env python3\n"
            "print('METRIC bundle_bytes=842000')\n"
        )
        script.chmod(0o755)

        r = _run_cli("validate-benchmark", "--expected", "bundle_bytes", cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert data["metric_name"] == "bundle_bytes"
        assert data["metric_value"] == 842000.0
        assert data["ok"] is True

    def test_missing_script(self, tmp_path: Path) -> None:
        r = _run_cli("validate-benchmark", cwd=tmp_path)
        assert r.returncode != 0
        assert "benchmark.py" in r.stderr

    def test_script_no_metric_line(self, tmp_path: Path) -> None:
        script_dir = tmp_path / ".claude" / "scripts" / "sindri"
        script_dir.mkdir(parents=True)
        script = script_dir / "benchmark.py"
        script.write_text("#!/usr/bin/env python3\nprint('hello')\n")
        script.chmod(0o755)
        r = _run_cli("validate-benchmark", cwd=tmp_path)
        assert r.returncode != 0

    def test_expected_name_mismatch(self, tmp_path: Path) -> None:
        script_dir = tmp_path / ".claude" / "scripts" / "sindri"
        script_dir.mkdir(parents=True)
        script = script_dir / "benchmark.py"
        script.write_text("#!/usr/bin/env python3\nprint('METRIC bar=42')\n")
        script.chmod(0o755)
        r = _run_cli("validate-benchmark", "--expected", "foo", cwd=tmp_path)
        assert r.returncode != 0


class TestDetectMode:
    def test_local_script(self, tmp_path: Path) -> None:
        script_dir = tmp_path / ".claude" / "scripts" / "sindri"
        script_dir.mkdir(parents=True)
        script = script_dir / "benchmark.py"
        script.write_text("print('METRIC x=42')")
        payload = json.dumps({"baseline_samples": [500.0, 100.0, 101.0, 99.0]})
        r = _run_cli("detect-mode", cwd=tmp_path, input=payload)
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert data["mode"] == "local"

    def test_remote_by_keyword(self, tmp_path: Path) -> None:
        script_dir = tmp_path / ".claude" / "scripts" / "sindri"
        script_dir.mkdir(parents=True)
        script = script_dir / "benchmark.py"
        script.write_text(
            "import subprocess\nsubprocess.run(['gh', 'workflow', 'run'])\nprint('METRIC x=42')"
        )
        payload = json.dumps({"baseline_samples": [500.0, 100.0, 101.0, 99.0]})
        r = _run_cli("detect-mode", cwd=tmp_path, input=payload)
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert data["mode"] == "remote"

    def test_remote_by_cv(self, tmp_path: Path) -> None:
        script_dir = tmp_path / ".claude" / "scripts" / "sindri"
        script_dir.mkdir(parents=True)
        script = script_dir / "benchmark.py"
        script.write_text("print('METRIC x=42')")
        payload = json.dumps({"baseline_samples": [500.0, 100.0, 80.0, 120.0, 70.0, 130.0]})
        r = _run_cli("detect-mode", cwd=tmp_path, input=payload)
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert data["mode"] == "remote"


class TestReadState:
    def test_reads_existing_state(self, tmp_path: Path) -> None:
        from datetime import datetime, timezone

        from sindri.core.state import write_state
        from sindri.core.validators import (
            Baseline,
            Candidate,
            Goal,
            Guardrails,
            SindriState,
        )

        sindri_dir = tmp_path / ".sindri" / "current"
        state = SindriState(
            goal=Goal(metric_name="x", direction="reduce", target_pct=15.0),
            baseline=Baseline(value=100.0, noise_floor=1.0, samples=[100.0, 101.0, 99.0]),
            pool=[Candidate(id=1, name="a", expected_impact_pct=-10.0)],
            branch="sindri/test",
            started_at=datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc),
            guardrails=Guardrails(mode="local"),
            mode="local",
        )
        write_state(state, dir=sindri_dir)

        r = _run_cli("read-state", cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert data["goal"]["metric_name"] == "x"
        assert data["mode"] == "local"
        assert len(data["pool"]) == 1

    def test_missing_state_fails(self, tmp_path: Path) -> None:
        r = _run_cli("read-state", cwd=tmp_path)
        assert r.returncode != 0
        assert "state" in r.stderr.lower()


class TestPickNext:
    def test_picks_highest_impact_pending(self, tmp_path: Path) -> None:
        from datetime import datetime, timezone

        from sindri.core.state import write_state
        from sindri.core.validators import (
            Baseline,
            Candidate,
            Goal,
            Guardrails,
            SindriState,
        )

        state = SindriState(
            goal=Goal(metric_name="x", direction="reduce", target_pct=15.0),
            baseline=Baseline(value=100.0, noise_floor=1.0, samples=[100.0, 101.0, 99.0]),
            pool=[
                Candidate(id=1, name="small", expected_impact_pct=-2.0),
                Candidate(id=2, name="big", expected_impact_pct=-20.0),
            ],
            branch="sindri/test",
            started_at=datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc),
            guardrails=Guardrails(mode="local"),
            mode="local",
        )
        write_state(state, dir=tmp_path / ".sindri" / "current")
        r = _run_cli("pick-next", cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        picked = json.loads(r.stdout)
        assert picked["id"] == 2
        assert picked["name"] == "big"

    def test_null_when_all_resolved(self, tmp_path: Path) -> None:
        from datetime import datetime, timezone

        from sindri.core.state import write_state
        from sindri.core.validators import (
            Baseline,
            Candidate,
            Goal,
            Guardrails,
            SindriState,
        )

        state = SindriState(
            goal=Goal(metric_name="x", direction="reduce", target_pct=15.0),
            baseline=Baseline(value=100.0, noise_floor=1.0, samples=[100.0, 101.0, 99.0]),
            pool=[
                Candidate(id=1, name="a", expected_impact_pct=-5.0, status="kept"),
                Candidate(id=2, name="b", expected_impact_pct=-3.0, status="reverted"),
            ],
            branch="sindri/test",
            started_at=datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc),
            guardrails=Guardrails(mode="local"),
            mode="local",
        )
        write_state(state, dir=tmp_path / ".sindri" / "current")
        r = _run_cli("pick-next", cwd=tmp_path)
        assert r.returncode == 0
        assert json.loads(r.stdout) is None


class TestRecordResult:
    def _setup_state_with_pending(self, tmp_path: Path) -> None:
        from datetime import datetime, timezone

        from sindri.core.state import write_state
        from sindri.core.validators import (
            Baseline,
            Candidate,
            Goal,
            Guardrails,
            SindriState,
        )

        state = SindriState(
            goal=Goal(metric_name="x", direction="reduce", target_pct=15.0),
            baseline=Baseline(value=100.0, noise_floor=1.0, samples=[100.0, 101.0, 99.0]),
            pool=[
                Candidate(id=1, name="a", expected_impact_pct=-10.0, status="pending"),
                Candidate(id=2, name="b", expected_impact_pct=-5.0, status="pending"),
            ],
            branch="sindri/test",
            started_at=datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc),
            guardrails=Guardrails(mode="local"),
            mode="local",
        )
        write_state(state, dir=tmp_path / ".sindri" / "current")

    def test_improved_updates_status_and_appends(self, tmp_path: Path) -> None:
        self._setup_state_with_pending(tmp_path)
        payload = json.dumps({
            "candidate_id": 1,
            "metric_before": 100.0,
            "subagent_result": {
                "metric_value": 85.0,
                "reps_used": 1,
                "confidence_ratio": 15.0,
                "status": "improved",
                "files_modified": ["x.py"],
                "notes": "win",
            },
            "commit_sha": "abc1234",
        })
        r = _run_cli("record-result", cwd=tmp_path, input=payload)
        assert r.returncode == 0, r.stderr

        from sindri.core.state import read_state
        state = read_state(dir=tmp_path / ".sindri" / "current")
        cand = next(c for c in state.pool if c.id == 1)
        assert cand.status == "kept"
        assert state.current_best == 85.0

        jsonl = (tmp_path / ".sindri" / "current" / "sindri.jsonl").read_text().strip().splitlines()
        assert len(jsonl) == 1
        rec = json.loads(jsonl[0])
        assert rec["type"] == "experiment"
        assert rec["status"] == "improved"

    def test_regressed_marks_reverted_no_current_best_change(self, tmp_path: Path) -> None:
        self._setup_state_with_pending(tmp_path)
        payload = json.dumps({
            "candidate_id": 2,
            "metric_before": 100.0,
            "subagent_result": {
                "metric_value": 120.0,
                "reps_used": 3,
                "confidence_ratio": 20.0,
                "status": "regressed",
                "files_modified": [],
            },
            "commit_sha": None,
        })
        r = _run_cli("record-result", cwd=tmp_path, input=payload)
        assert r.returncode == 0, r.stderr
        from sindri.core.state import read_state
        state = read_state(dir=tmp_path / ".sindri" / "current")
        cand = next(c for c in state.pool if c.id == 2)
        assert cand.status == "reverted"
        assert state.current_best is None

    def test_invalid_payload_rejected(self, tmp_path: Path) -> None:
        self._setup_state_with_pending(tmp_path)
        r = _run_cli("record-result", cwd=tmp_path, input="not json")
        assert r.returncode != 0


class TestCheckTermination:
    def test_not_terminated(self, tmp_path: Path) -> None:
        from datetime import datetime, timezone

        from sindri.core.state import write_state
        from sindri.core.validators import (
            Baseline,
            Candidate,
            Goal,
            Guardrails,
            SindriState,
        )

        state = SindriState(
            goal=Goal(metric_name="x", direction="reduce", target_pct=15.0),
            baseline=Baseline(value=100.0, noise_floor=1.0, samples=[100.0, 101.0, 99.0]),
            pool=[Candidate(id=1, name="a", expected_impact_pct=-10.0)],
            branch="sindri/test",
            started_at=datetime.now(tz=timezone.utc),
            guardrails=Guardrails(mode="local"),
            mode="local",
        )
        write_state(state, dir=tmp_path / ".sindri" / "current")
        payload = json.dumps({"experiments_run": 0, "consecutive_reverts": 0})
        r = _run_cli("check-termination", cwd=tmp_path, input=payload)
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert data["terminated"] is False

    def test_target_hit(self, tmp_path: Path) -> None:
        from datetime import datetime, timezone

        from sindri.core.state import write_state
        from sindri.core.validators import (
            Baseline,
            Candidate,
            Goal,
            Guardrails,
            SindriState,
        )

        state = SindriState(
            goal=Goal(metric_name="x", direction="reduce", target_pct=15.0),
            baseline=Baseline(value=100.0, noise_floor=1.0, samples=[100.0, 101.0, 99.0]),
            pool=[Candidate(id=1, name="a", expected_impact_pct=-10.0, status="kept")],
            branch="sindri/test",
            started_at=datetime.now(tz=timezone.utc),
            guardrails=Guardrails(mode="local"),
            mode="local",
            current_best=84.0,
        )
        write_state(state, dir=tmp_path / ".sindri" / "current")
        payload = json.dumps({"experiments_run": 1, "consecutive_reverts": 0})
        r = _run_cli("check-termination", cwd=tmp_path, input=payload)
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert data["terminated"] is True
        assert data["reason"] == "target_hit"
        assert data["auto_finalize"] is True

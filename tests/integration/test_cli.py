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
        from importlib.metadata import version

        r = _run_cli("--version")
        assert r.returncode == 0
        # Distribution name differs from module name — PyPI name is sindri-forge.
        assert version("sindri-forge") in r.stdout

    def test_help_lists_subcommands(self) -> None:
        r = _run_cli("--help")
        assert r.returncode == 0
        for sub in [
            "validate-benchmark",
            "detect-mode",
            "read-state",
            "pick-next",
            "record-result",
            "check-termination",
            "generate-pr-body",
            "archive",
            "status",
            "init",
        ]:
            assert sub in r.stdout, f"{sub} missing from --help"

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

    def test_missing_state_degrades_cleanly(self, tmp_path: Path) -> None:
        # No .sindri/current/ — read-state mirrors `status`: friendly line on
        # stdout, exit 0, no traceback (parity locked by TestStatus too).
        r = _run_cli("read-state", cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        assert "no active run" in r.stdout
        assert "Traceback" not in r.stderr


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

    def test_missing_state_clean_error(self, tmp_path: Path) -> None:
        # No .sindri/current/ — handler must print a clean error and exit 1
        # rather than crashing with an unhandled StateIOError traceback.
        payload = json.dumps({
            "candidate_id": 1,
            "metric_before": 100.0,
            "subagent_result": {
                "metric_value": 90.0,
                "reps_used": 1,
                "confidence_ratio": 10.0,
                "status": "improved",
                "files_modified": [],
            },
        })
        r = _run_cli("record-result", cwd=tmp_path, input=payload)
        assert r.returncode == 1
        assert "error:" in r.stderr
        assert "Traceback" not in r.stderr


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

    def test_missing_state_clean_error(self, tmp_path: Path) -> None:
        payload = json.dumps({"experiments_run": 0, "consecutive_reverts": 0})
        r = _run_cli("check-termination", cwd=tmp_path, input=payload)
        assert r.returncode == 1
        assert "error:" in r.stderr
        assert "Traceback" not in r.stderr


class TestGeneratePrBody:
    def test_emits_markdown(self, tmp_path: Path) -> None:
        from datetime import datetime, timezone

        from sindri.core.state import append_jsonl, write_state
        from sindri.core.validators import (
            Baseline,
            Candidate,
            Goal,
            Guardrails,
            JsonlExperiment,
            JsonlTerminated,
            SindriState,
        )

        state = SindriState(
            goal=Goal(metric_name="x", direction="reduce", target_pct=15.0),
            baseline=Baseline(value=100.0, noise_floor=1.0, samples=[100.0, 101.0, 99.0]),
            pool=[Candidate(id=1, name="a", expected_impact_pct=-10.0, status="kept")],
            branch="sindri/test",
            started_at=datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc),
            guardrails=Guardrails(mode="local"),
            mode="local",
            current_best=80.0,
        )
        d = tmp_path / ".sindri" / "current"
        write_state(state, dir=d)
        append_jsonl(
            JsonlExperiment(
                ts=datetime(2026, 4, 19, 10, 5, tzinfo=timezone.utc),
                id=1, candidate="a", reps_used=1,
                metric_before=100.0, metric_after=80.0, delta=-20.0,
                confidence_ratio=20.0, status="improved",
                commit_sha="abc1234", files_modified=["x.py"],
            ),
            path=d / "sindri.jsonl",
        )
        append_jsonl(
            JsonlTerminated(
                ts=datetime(2026, 4, 19, 10, 10, tzinfo=timezone.utc),
                reason="target_hit", final_metric=80.0, delta_pct=-20.0,
                kept=1, reverted=0, errored=0, wall_clock_seconds=600, auto_finalize=True,
            ),
            path=d / "sindri.jsonl",
        )
        r = _run_cli("generate-pr-body", cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        assert "## " in r.stdout
        assert "−20" in r.stdout or "-20" in r.stdout
        assert "abc1234" in r.stdout

    def test_missing_state_clean_error(self, tmp_path: Path) -> None:
        r = _run_cli("generate-pr-body", cwd=tmp_path)
        assert r.returncode == 1
        assert "error:" in r.stderr
        assert "Traceback" not in r.stderr


class TestArchive:
    def test_moves_current_to_archive(self, tmp_path: Path) -> None:
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
            branch="sindri/reduce-x-15pct",
            started_at=datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc),
            guardrails=Guardrails(mode="local"),
            mode="local",
        )
        current = tmp_path / ".sindri" / "current"
        write_state(state, dir=current)

        r = _run_cli("archive", cwd=tmp_path)
        assert r.returncode == 0, r.stderr

        assert not current.exists()
        archive_root = tmp_path / ".sindri" / "archive"
        subdirs = list(archive_root.iterdir())
        assert len(subdirs) == 1
        assert "reduce-x-15pct" in subdirs[0].name
        assert (subdirs[0] / "sindri.md").exists()

    def test_archive_drops_transient_files(self, tmp_path: Path) -> None:
        # #69: lock sidecar + state backup must not leak into the archived record.
        from datetime import datetime, timezone

        from sindri.core.state import write_state
        from sindri.core.validators import Baseline, Candidate, Goal, Guardrails, SindriState

        state = SindriState(
            goal=Goal(metric_name="x", direction="reduce", target_pct=15.0),
            baseline=Baseline(value=100.0, noise_floor=1.0, samples=[100.0, 101.0, 99.0]),
            pool=[Candidate(id=1, name="a", expected_impact_pct=-10.0)],
            branch="sindri/reduce-x-15pct",
            started_at=datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc),
            guardrails=Guardrails(mode="local"),
            mode="local",
        )
        current = tmp_path / ".sindri" / "current"
        write_state(state, dir=current)
        (current / ".RUNNING.acquire").write_text("")     # lock sidecar
        (current / "sindri.md.bak").write_text("old")      # crash-safety backup
        (current / "sindri.jsonl").write_text(
            '{"type":"event","ts":"2026-04-19T10:00:00+00:00","event":"x"}\n'
        )

        r = _run_cli("archive", cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        archived = next((tmp_path / ".sindri" / "archive").iterdir())
        names = {p.name for p in archived.iterdir()}
        assert ".RUNNING.acquire" not in names
        assert "sindri.md.bak" not in names
        assert {"sindri.md", "sindri.jsonl"} <= names  # durable record kept

    def test_no_current_fails(self, tmp_path: Path) -> None:
        r = _run_cli("archive", cwd=tmp_path)
        assert r.returncode != 0

    def test_rejects_path_traversal_in_branch(self, tmp_path: Path) -> None:
        # Simulate a tampered sindri.md whose branch field would escape the
        # archive root. The handler must refuse rather than shutil.move into
        # an attacker-chosen path.
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
            branch="sindri/../../evil",
            started_at=datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc),
            guardrails=Guardrails(mode="local"),
            mode="local",
        )
        current = tmp_path / ".sindri" / "current"
        write_state(state, dir=current)

        r = _run_cli("archive", cwd=tmp_path)
        assert r.returncode != 0
        assert "unsafe" in r.stderr.lower()
        # Nothing outside .sindri/archive/ should have been touched.
        assert current.exists()
        assert not (tmp_path / "evil").exists()
        assert not (tmp_path.parent / "evil").exists()


class TestStatus:
    def test_prints_summary(self, tmp_path: Path) -> None:
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
            goal=Goal(metric_name="bundle_bytes", direction="reduce", target_pct=15.0),
            baseline=Baseline(value=842000.0, noise_floor=870.0, samples=[843000.0, 841000.0, 842000.0]),
            pool=[
                Candidate(id=1, name="a", expected_impact_pct=-10.0, status="kept"),
                Candidate(id=2, name="b", expected_impact_pct=-5.0, status="pending"),
            ],
            branch="sindri/reduce-bundle-bytes-15pct",
            started_at=datetime(2026, 4, 19, 10, 0, tzinfo=timezone.utc),
            guardrails=Guardrails(mode="local"),
            mode="local",
            current_best=760000.0,
        )
        write_state(state, dir=tmp_path / ".sindri" / "current")

        r = _run_cli("status", cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        assert "842" in r.stdout
        assert "760" in r.stdout
        assert "reduce" in r.stdout.lower() or "bundle_bytes" in r.stdout.lower()
        assert "2" in r.stdout

    def test_missing_state_degrades_cleanly(self, tmp_path: Path) -> None:
        # No .sindri/current/ — friendly line on stdout, exit 0, no traceback.
        # Byte-identical to read-state's no-active-run path.
        r = _run_cli("status", cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        assert "no active run" in r.stdout
        assert "Traceback" not in r.stderr


class TestInit:
    def test_init_creates_state_from_goal(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# test\n")
        script_dir = tmp_path / ".claude" / "scripts" / "sindri"
        script_dir.mkdir(parents=True)
        script = script_dir / "benchmark.py"
        script.write_text(
            "#!/usr/bin/env python3\n"
            "print('METRIC bundle_bytes=100')\n"
        )
        script.chmod(0o755)

        subprocess.run(["git", "init", "-b", "main"], check=True, cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t"], check=True, cwd=tmp_path)
        subprocess.run(["git", "config", "user.name", "t"], check=True, cwd=tmp_path)
        subprocess.run(["git", "add", "-A"], check=True, cwd=tmp_path)
        subprocess.run(["git", "commit", "-m", "init"], check=True, cwd=tmp_path, capture_output=True)

        pool_json = json.dumps([
            {"id": 1, "name": "Replace moment", "expected_impact_pct": -10.0},
            {"id": 2, "name": "Tree-shake", "expected_impact_pct": -5.0},
        ])
        r = _run_cli(
            "init",
            "--goal", "reduce bundle_bytes by 15%",
            "--pool-json", pool_json,
            cwd=tmp_path,
        )
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        assert out["ok"] is True

        state_file = tmp_path / ".sindri" / "current" / "sindri.md"
        assert state_file.exists()

        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=tmp_path, capture_output=True, text=True,
        )
        assert "sindri/" in result.stdout

    @staticmethod
    def _init_repo(tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# test\n")
        script_dir = tmp_path / ".claude" / "scripts" / "sindri"
        script_dir.mkdir(parents=True)
        (script_dir / "benchmark.py").write_text("print('METRIC bundle_bytes=100')\n")
        subprocess.run(["git", "init", "-b", "main"], check=True, cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t"], check=True, cwd=tmp_path)
        subprocess.run(["git", "config", "user.name", "t"], check=True, cwd=tmp_path)
        subprocess.run(["git", "add", "-A"], check=True, cwd=tmp_path)
        subprocess.run(["git", "commit", "-m", "init"], check=True, cwd=tmp_path, capture_output=True)

    def test_init_rejects_duplicate_candidate_names(self, tmp_path: Path) -> None:
        self._init_repo(tmp_path)
        pool = json.dumps([
            {"id": 1, "name": "dup", "expected_impact_pct": -10.0},
            {"id": 2, "name": "dup", "expected_impact_pct": -5.0},
        ])
        r = _run_cli("init", "--goal", "reduce bundle_bytes by 15%", "--pool-json", pool, cwd=tmp_path)
        assert r.returncode == 1
        assert "unique" in r.stderr
        assert not (tmp_path / ".sindri" / "current").exists()

    def test_init_ensures_sindri_is_gitignored(self, tmp_path: Path) -> None:
        self._init_repo(tmp_path)  # no .gitignore committed
        pool = json.dumps([{"id": 1, "name": "a", "expected_impact_pct": -10.0}])
        r = _run_cli("init", "--goal", "reduce bundle_bytes by 15%", "--pool-json", pool, cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        gi = (tmp_path / ".gitignore").read_text()
        assert any(ln.strip().rstrip("/") == ".sindri" for ln in gi.splitlines())

    def test_init_threads_run_id_into_baseline_records(self, tmp_path: Path) -> None:
        # #67: baseline + baseline_complete records must carry the run's id, like
        # session_start does — otherwise they can't be correlated in a shared log.
        self._init_repo(tmp_path)
        pool = json.dumps([{"id": 1, "name": "a", "expected_impact_pct": -10.0}])
        r = _run_cli("init", "--goal", "reduce bundle_bytes by 15%", "--pool-json", pool, cwd=tmp_path)
        assert r.returncode == 0, r.stderr
        by_type: dict[str, list] = {}
        for ln in (tmp_path / ".sindri" / "current" / "sindri.jsonl").read_text().splitlines():
            if ln.strip():
                rec = json.loads(ln)
                by_type.setdefault(rec["type"], []).append(rec)
        run_id = by_type["session_start"][0]["run_id"]
        assert run_id  # non-empty
        baseline_recs = by_type.get("baseline", []) + by_type.get("baseline_complete", [])
        assert baseline_recs  # they exist
        assert all(rec["run_id"] == run_id for rec in baseline_recs)

    def test_init_warns_on_reduce_target_over_100pct(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# test\n")
        script_dir = tmp_path / ".claude" / "scripts" / "sindri"
        script_dir.mkdir(parents=True)
        script = script_dir / "benchmark.py"
        script.write_text("#!/usr/bin/env python3\nprint('METRIC bundle_bytes=100')\n")
        script.chmod(0o755)
        subprocess.run(["git", "init", "-b", "main"], check=True, cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t"], check=True, cwd=tmp_path)
        subprocess.run(["git", "config", "user.name", "t"], check=True, cwd=tmp_path)
        subprocess.run(["git", "add", "-A"], check=True, cwd=tmp_path)
        subprocess.run(["git", "commit", "-m", "init"], check=True, cwd=tmp_path, capture_output=True)
        pool_json = json.dumps([{"id": 1, "name": "x", "expected_impact_pct": -10.0}])
        r = _run_cli(
            "init",
            "--goal", "reduce bundle_bytes by 150%",
            "--pool-json", pool_json,
            cwd=tmp_path,
        )
        # Warning is advisory only — init still proceeds.
        assert "warning" in r.stderr.lower()
        assert "150" in r.stderr

    def test_init_rejects_existing_current(self, tmp_path: Path) -> None:
        (tmp_path / ".sindri" / "current").mkdir(parents=True)
        (tmp_path / ".sindri" / "current" / "sindri.md").write_text("existing")
        pool_json = json.dumps([])
        r = _run_cli(
            "init",
            "--goal", "reduce x by 10%",
            "--pool-json", pool_json,
            cwd=tmp_path,
        )
        assert r.returncode != 0
        assert "current" in r.stderr.lower()

    def test_init_rejects_malformed_goal(self, tmp_path: Path) -> None:
        pool_json = json.dumps([])
        r = _run_cli(
            "init",
            "--goal", "make it faster",
            "--pool-json", pool_json,
            cwd=tmp_path,
        )
        assert r.returncode != 0

    def test_init_rejects_goal_with_trailing_junk(self, tmp_path: Path) -> None:
        # A `search`-based parser silently took the prefix; fullmatch refuses.
        pool_json = json.dumps([])
        r = _run_cli(
            "init",
            "--goal", "reduce bundle_bytes by 15% and also make coffee",
            "--pool-json", pool_json,
            cwd=tmp_path,
        )
        assert r.returncode != 0
        assert "malformed goal" in r.stderr

    def test_init_fails_fast_if_branch_exists(self, tmp_path: Path) -> None:
        # Set up a repo where the target branch (sindri/reduce-bundle-bytes-15pct)
        # already exists from a prior aborted run. init must reject BEFORE
        # spending three benchmark runs, and the benchmark script here is a
        # sleep-forever — if the guard fails, the test will hang.
        (tmp_path / "README.md").write_text("# test\n")
        script_dir = tmp_path / ".claude" / "scripts" / "sindri"
        script_dir.mkdir(parents=True)
        script = script_dir / "benchmark.py"
        script.write_text(
            "#!/usr/bin/env python3\n"
            "import time\n"
            "time.sleep(3600)\n"  # never reached if the guard works
        )
        script.chmod(0o755)

        subprocess.run(["git", "init", "-b", "main"], check=True, cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t"], check=True, cwd=tmp_path)
        subprocess.run(["git", "config", "user.name", "t"], check=True, cwd=tmp_path)
        subprocess.run(["git", "add", "-A"], check=True, cwd=tmp_path)
        subprocess.run(["git", "commit", "-m", "init"], check=True, cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "branch", "sindri/reduce-bundle-bytes-15pct"],
            check=True, cwd=tmp_path, capture_output=True,
        )

        pool_json = json.dumps([])
        r = _run_cli(
            "init",
            "--goal", "reduce bundle_bytes by 15%",
            "--pool-json", pool_json,
            cwd=tmp_path,
        )
        assert r.returncode != 0
        assert "already exists" in r.stderr


class TestLock:
    @staticmethod
    def _seed_state(tmp_path: Path) -> None:
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
            goal=Goal(metric_name="x", direction="reduce", target_pct=10.0),
            baseline=Baseline(value=100.0, noise_floor=1.0, samples=[100.0, 101.0, 99.0]),
            pool=[Candidate(id=1, name="a", expected_impact_pct=-10.0)],
            branch="sindri/test",
            started_at=datetime(2026, 6, 19, 10, 0, tzinfo=timezone.utc),
            guardrails=Guardrails(mode="local"),
            mode="local",
        )
        write_state(state, dir=tmp_path / ".sindri" / "current")

    def test_acquire_held_release_cycle(self, tmp_path: Path) -> None:
        self._seed_state(tmp_path)

        r1 = _run_cli("acquire-lock", cwd=tmp_path)
        assert r1.returncode == 0, r1.stderr
        d1 = json.loads(r1.stdout)
        assert d1["acquired"] is True
        token = d1["token"]

        # A second wakeup finds a live holder → exit 1 so it backs off without
        # rescheduling a competing wakeup.
        r2 = _run_cli("acquire-lock", cwd=tmp_path)
        assert r2.returncode == 1
        assert json.loads(r2.stdout)["acquired"] is False

        # Release with the token frees it.
        r3 = _run_cli("release-lock", "--token", token, cwd=tmp_path)
        assert r3.returncode == 0
        assert json.loads(r3.stdout)["released"] is True

        # Now a fresh acquire succeeds again.
        r4 = _run_cli("acquire-lock", cwd=tmp_path)
        assert r4.returncode == 0
        assert json.loads(r4.stdout)["acquired"] is True

    def test_release_wrong_token_is_noop(self, tmp_path: Path) -> None:
        self._seed_state(tmp_path)
        _run_cli("acquire-lock", cwd=tmp_path)
        r = _run_cli("release-lock", "--token", "not-the-token", cwd=tmp_path)
        assert r.returncode == 0
        assert json.loads(r.stdout)["released"] is False

    def test_acquire_no_active_run_is_error_exit_2(self, tmp_path: Path) -> None:
        # No .sindri/current/ — acquire-lock must exit 2 (error), NOT 1 (held),
        # so the orchestrator surfaces the error instead of silently backing off
        # without rescheduling. No traceback.
        r = _run_cli("acquire-lock", cwd=tmp_path)
        assert r.returncode == 2
        assert "Traceback" not in r.stderr

    def test_concurrent_acquire_has_exactly_one_winner(self, tmp_path: Path) -> None:
        # The single-winner property under contention: launch many acquire-lock
        # processes at once against a fresh run; exactly one must win (exit 0),
        # the rest must report held (exit 1).
        self._seed_state(tmp_path)
        procs = [
            subprocess.Popen(
                [sys.executable, "-m", "sindri", "acquire-lock"],
                cwd=tmp_path, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            for _ in range(8)
        ]
        codes = [p.wait() for p in procs]
        assert codes.count(0) == 1, f"expected exactly one winner, got codes {codes}"
        assert codes.count(1) == len(procs) - 1, f"others must report held, got {codes}"


class TestRecordTerminated:
    @staticmethod
    def _seed_mixed_pool(tmp_path: Path) -> None:
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
            goal=Goal(metric_name="bundle_bytes", direction="reduce", target_pct=15.0),
            baseline=Baseline(value=1000.0, noise_floor=10.0, samples=[1000.0, 1001.0, 999.0]),
            pool=[
                Candidate(id=1, name="a", expected_impact_pct=-10.0, status="kept"),
                Candidate(id=2, name="b", expected_impact_pct=-5.0, status="reverted"),
                Candidate(id=3, name="c", expected_impact_pct=-5.0, status="errored"),
                Candidate(id=4, name="d", expected_impact_pct=-5.0, status="check_failed"),
                Candidate(id=5, name="e", expected_impact_pct=-5.0, status="pending"),
            ],
            branch="sindri/reduce-bundle-bytes-15pct",
            started_at=datetime(2026, 6, 19, 10, 0, tzinfo=timezone.utc),
            guardrails=Guardrails(mode="local"),
            mode="local",
            current_best=850.0,
        )
        write_state(state, dir=tmp_path / ".sindri" / "current")

    def _last_terminated(self, tmp_path: Path) -> dict:
        path = tmp_path / ".sindri" / "current" / "sindri.jsonl"
        records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        terminated = [r for r in records if r.get("type") == "terminated"]
        assert terminated, "no terminated record written"
        return terminated[-1]

    def test_derives_counts_and_metrics_from_state(self, tmp_path: Path) -> None:
        self._seed_mixed_pool(tmp_path)
        r = _run_cli(
            "record-terminated", "--reason", "pool_empty", "--auto-finalize", "true",
            cwd=tmp_path,
        )
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        assert out["ok"] is True and out["kept"] == 1

        rec = self._last_terminated(tmp_path)
        assert rec["reason"] == "pool_empty"
        assert rec["auto_finalize"] is True
        assert rec["kept"] == 1
        assert rec["reverted"] == 1
        assert rec["errored"] == 2  # errored + check_failed
        assert rec["final_metric"] == 850.0
        assert rec["delta_pct"] == (850.0 - 1000.0) / 1000.0 * 100

    def test_invalid_reason_rejected(self, tmp_path: Path) -> None:
        self._seed_mixed_pool(tmp_path)
        r = _run_cli(
            "record-terminated", "--reason", "made_up", "--auto-finalize", "false",
            cwd=tmp_path,
        )
        assert r.returncode != 0  # argparse rejects the choice
        assert "made_up" in r.stderr or "invalid choice" in r.stderr

    def test_no_active_run_degrades(self, tmp_path: Path) -> None:
        r = _run_cli(
            "record-terminated", "--reason", "pool_empty", "--auto-finalize", "false",
            cwd=tmp_path,
        )
        assert r.returncode == 1
        assert "Traceback" not in r.stderr


class TestResetTree:
    _REGRESS = json.dumps({
        "candidate_id": 1, "metric_before": 1000.0,
        "subagent_result": {
            "metric_value": 1100.0, "reps_used": 3, "confidence_ratio": 5.0,
            "status": "regressed", "files_modified": ["f.py"],
        },
    })

    @staticmethod
    def _setup(tmp_path: Path) -> None:
        from datetime import datetime, timezone

        from sindri.core.state import write_state
        from sindri.core.validators import (
            Baseline,
            Candidate,
            Goal,
            Guardrails,
            SindriState,
        )

        subprocess.run(["git", "init", "-b", "main"], check=True, cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t"], check=True, cwd=tmp_path)
        subprocess.run(["git", "config", "user.name", "t"], check=True, cwd=tmp_path)
        (tmp_path / "f.py").write_text("x = 1\n")
        (tmp_path / ".gitignore").write_text(".sindri/\n")
        subprocess.run(["git", "add", "-A"], check=True, cwd=tmp_path)
        subprocess.run(["git", "commit", "-m", "base"], check=True, cwd=tmp_path, capture_output=True)
        state = SindriState(
            goal=Goal(metric_name="lines", direction="reduce", target_pct=10.0),
            baseline=Baseline(value=1000.0, noise_floor=1.0, samples=[1000.0, 1001.0, 999.0]),
            pool=[Candidate(id=1, name="a", expected_impact_pct=-10.0)],
            branch="sindri/test",
            started_at=datetime(2026, 6, 19, 10, 0, tzinfo=timezone.utc),
            guardrails=Guardrails(mode="local"),
            mode="local",
        )
        write_state(state, dir=tmp_path / ".sindri" / "current")

    @staticmethod
    def _experiment_lines(tmp_path: Path) -> list[str]:
        path = tmp_path / ".sindri" / "current" / "sindri.jsonl"
        return [ln for ln in path.read_text().splitlines() if '"experiment"' in ln]

    def test_reverts_tree_and_records(self, tmp_path: Path) -> None:
        self._setup(tmp_path)
        (tmp_path / "f.py").write_text("x = 1\nGARBAGE\n")  # dirty change from the failed run
        r = _run_cli("reset-tree", cwd=tmp_path, input=self._REGRESS)
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout)["new_status"] == "reverted"
        assert (tmp_path / "f.py").read_text() == "x = 1\n"  # tree restored
        state = json.loads(_run_cli("read-state", cwd=tmp_path).stdout)
        assert next(c for c in state["pool"] if c["id"] == 1)["status"] == "reverted"
        assert len(self._experiment_lines(tmp_path)) == 1

    def test_rejects_improved(self, tmp_path: Path) -> None:
        self._setup(tmp_path)
        improved = json.dumps({
            "candidate_id": 1, "metric_before": 1000.0,
            "subagent_result": {
                "metric_value": 900.0, "reps_used": 3, "confidence_ratio": 5.0,
                "status": "improved", "files_modified": [],
            },
        })
        r = _run_cli("reset-tree", cwd=tmp_path, input=improved)
        assert r.returncode == 1
        assert "commit-kept" in r.stderr

    def test_idempotent_on_rerun(self, tmp_path: Path) -> None:
        self._setup(tmp_path)
        assert _run_cli("reset-tree", cwd=tmp_path, input=self._REGRESS).returncode == 0
        r2 = _run_cli("reset-tree", cwd=tmp_path, input=self._REGRESS)
        assert r2.returncode == 0
        assert json.loads(r2.stdout).get("skipped") is True
        assert len(self._experiment_lines(tmp_path)) == 1  # no duplicate record

    def test_no_active_run_degrades(self, tmp_path: Path) -> None:
        r = _run_cli("reset-tree", cwd=tmp_path, input=self._REGRESS)
        assert r.returncode == 1
        assert "Traceback" not in r.stderr


_BENCH = (
    "import pathlib\n"
    "n = len([l for l in pathlib.Path('f.py').read_text().splitlines() if l.strip()])\n"
    "print(f'METRIC lines={n}')\n"
)
_BENCH_PATH = ".claude/scripts/sindri/benchmark.py"


class TestCommitKept:
    @staticmethod
    def _improved_payload(metric_value: float = 900.0, *, benchmark: bool = True) -> str:
        body = {
            "candidate_id": 1, "metric_before": 3.0,
            "subagent_result": {
                "metric_value": metric_value, "reps_used": 3, "confidence_ratio": 5.0,
                "status": "improved", "files_modified": ["f.py"],
            },
        }
        if benchmark:
            body["benchmark_cmd"] = _BENCH_PATH  # commit-kept re-measures with this
        return json.dumps(body)

    @staticmethod
    def _setup(tmp_path: Path) -> None:
        from datetime import datetime, timezone

        from sindri.core.state import write_state
        from sindri.core.validators import (
            Baseline,
            Candidate,
            Goal,
            Guardrails,
            SindriState,
        )

        subprocess.run(["git", "init", "-b", "main"], check=True, cwd=tmp_path, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t"], check=True, cwd=tmp_path)
        subprocess.run(["git", "config", "user.name", "t"], check=True, cwd=tmp_path)
        (tmp_path / "f.py").write_text("a = 1\nb = 2\nc = 3\n")  # 3 non-blank lines == baseline
        bench = tmp_path / _BENCH_PATH
        bench.parent.mkdir(parents=True, exist_ok=True)
        bench.write_text(_BENCH)
        (tmp_path / ".gitignore").write_text(".sindri/\n")
        subprocess.run(["git", "add", "-A"], check=True, cwd=tmp_path)
        subprocess.run(["git", "commit", "-m", "base"], check=True, cwd=tmp_path, capture_output=True)
        state = SindriState(
            goal=Goal(metric_name="lines", direction="reduce", target_pct=10.0),
            baseline=Baseline(value=3.0, noise_floor=0.1, samples=[3.0, 3.0]),
            pool=[Candidate(id=1, name="a", expected_impact_pct=-10.0)],
            branch="sindri/test",
            started_at=datetime(2026, 6, 19, 10, 0, tzinfo=timezone.utc),
            guardrails=Guardrails(mode="local"),
            mode="local",
        )
        write_state(state, dir=tmp_path / ".sindri" / "current")

    @staticmethod
    def _kept_commits(tmp_path: Path) -> list[str]:
        out = subprocess.run(
            ["git", "log", "--format=%s"], cwd=tmp_path, capture_output=True, text=True,
        ).stdout
        return [ln for ln in out.splitlines() if ln.startswith("kept:")]

    @staticmethod
    def _experiment_lines(tmp_path: Path) -> list[str]:
        path = tmp_path / ".sindri" / "current" / "sindri.jsonl"
        return [ln for ln in path.read_text().splitlines() if '"experiment"' in ln]

    def test_commits_and_records(self, tmp_path: Path) -> None:
        self._setup(tmp_path)
        (tmp_path / "f.py").write_text("a = 1\n")  # 3 -> 1 line: a real improvement
        # Subagent claims 900.0; commit-kept re-measures → commits the real 1.0.
        r = _run_cli("commit-kept", cwd=tmp_path, input=self._improved_payload())
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        assert out["new_status"] == "kept"
        assert out["current_best"] == 1.0
        assert len(self._kept_commits(tmp_path)) == 1
        assert out["commit_sha"]
        state = json.loads(_run_cli("read-state", cwd=tmp_path).stdout)
        assert next(c for c in state["pool"] if c["id"] == 1)["status"] == "kept"

    def test_rejects_non_improved(self, tmp_path: Path) -> None:
        self._setup(tmp_path)
        bad = json.dumps({
            "candidate_id": 1, "metric_before": 3.0,
            "subagent_result": {
                "metric_value": 1100.0, "reps_used": 3, "confidence_ratio": 5.0,
                "status": "regressed", "files_modified": [],
            },
        })
        r = _run_cli("commit-kept", cwd=tmp_path, input=bad)
        assert r.returncode == 1
        assert "reset-tree" in r.stderr

    def test_refuses_when_no_net_change(self, tmp_path: Path) -> None:
        # "improved" claimed but the tree is unchanged → re-measurement shows no
        # improvement → refuse (no keep). (The empty-commit downgrade is now only
        # reachable via the bypass; the seam catches no-change first.)
        self._setup(tmp_path)
        r = _run_cli("commit-kept", cwd=tmp_path, input=self._improved_payload())
        assert r.returncode != 0
        assert self._kept_commits(tmp_path) == []

    def test_tier_a_already_recorded_skips_and_reconciles(self, tmp_path: Path) -> None:
        self._setup(tmp_path)
        (tmp_path / "f.py").write_text("a = 1\n")  # real improvement (3 -> 1)
        assert _run_cli("commit-kept", cwd=tmp_path, input=self._improved_payload()).returncode == 0
        # Re-run the same candidate (crash-recovery) — must not double-commit/record.
        r2 = _run_cli("commit-kept", cwd=tmp_path, input=self._improved_payload())
        assert r2.returncode == 0
        assert json.loads(r2.stdout).get("skipped") is True
        assert len(self._kept_commits(tmp_path)) == 1
        assert len(self._experiment_lines(tmp_path)) == 1

    def test_tier_b_commit_landed_but_record_missing(self, tmp_path: Path) -> None:
        # Crash between `git commit` and the jsonl append: the kept commit exists
        # but there's no experiment record and the candidate is still pending.
        self._setup(tmp_path)
        (tmp_path / "f.py").write_text("a = 1\n")  # real improvement
        subprocess.run(["git", "add", "-A"], check=True, cwd=tmp_path)
        subprocess.run(
            ["git", "commit", "-m", "kept: a (Δ-2)"],
            check=True, cwd=tmp_path, capture_output=True,
        )
        # No record written. commit-kept re-measures the committed tree (1 line, an
        # improvement) → honors recovery, no duplicate commit.
        r = _run_cli("commit-kept", cwd=tmp_path, input=self._improved_payload())
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout)["new_status"] == "kept"
        assert len(self._kept_commits(tmp_path)) == 1  # no duplicate commit
        assert len(self._experiment_lines(tmp_path)) == 1  # record now written

    def test_no_active_run_degrades(self, tmp_path: Path) -> None:
        r = _run_cli("commit-kept", cwd=tmp_path, input=self._improved_payload())
        assert r.returncode == 1
        assert "Traceback" not in r.stderr

    def test_kept_commit_sha_no_prefix_false_positive(self, tmp_path: Path) -> None:
        # A candidate whose name is a prefix of a longer one must NOT match the
        # longer one's commit (the HIGH the reviewer caught).
        from sindri.cli import _kept_commit_sha

        self._setup(tmp_path)
        (tmp_path / "f.py").write_text("")
        subprocess.run(["git", "add", "-A"], check=True, cwd=tmp_path)
        subprocess.run(
            ["git", "commit", "-m", "kept: add cache (lru) (Δ-10)"],
            check=True, cwd=tmp_path, capture_output=True,
        )
        assert _kept_commit_sha("add cache", cwd=tmp_path) is None
        assert _kept_commit_sha("add cache (lru)", cwd=tmp_path) is not None


class TestPushBranch:
    @staticmethod
    def _setup(tmp_path: Path):
        from datetime import datetime, timezone

        from sindri.core.state import write_state
        from sindri.core.validators import (
            Baseline,
            Candidate,
            Goal,
            Guardrails,
            SindriState,
        )

        remote = tmp_path / "remote.git"
        subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-b", "main"], check=True, cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.email", "t@t"], check=True, cwd=repo)
        subprocess.run(["git", "config", "user.name", "t"], check=True, cwd=repo)
        subprocess.run(["git", "remote", "add", "origin", str(remote)], check=True, cwd=repo)
        (repo / ".gitignore").write_text(".sindri/\n")
        (repo / "f.py").write_text("x = 1\n")
        subprocess.run(["git", "add", "-A"], check=True, cwd=repo)
        subprocess.run(["git", "commit", "-m", "base"], check=True, cwd=repo, capture_output=True)
        subprocess.run(["git", "checkout", "-b", "sindri/test"], check=True, cwd=repo, capture_output=True)
        state = SindriState(
            goal=Goal(metric_name="x", direction="reduce", target_pct=10.0),
            baseline=Baseline(value=100.0, noise_floor=1.0, samples=[100.0, 101.0, 99.0]),
            pool=[Candidate(id=1, name="a", expected_impact_pct=-10.0, status="kept")],
            branch="sindri/test",
            started_at=datetime(2026, 6, 19, 10, 0, tzinfo=timezone.utc),
            guardrails=Guardrails(mode="local"),
            mode="local",
        )
        write_state(state, dir=repo / ".sindri" / "current")
        return repo, remote

    def test_pushes_run_branch(self, tmp_path: Path) -> None:
        repo, remote = self._setup(tmp_path)
        r = _run_cli("push-branch", cwd=repo)
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout)["branch"] == "sindri/test"
        ls = subprocess.run(
            ["git", "ls-remote", "--heads", str(remote)], capture_output=True, text=True,
        ).stdout
        assert "refs/heads/sindri/test" in ls

    def test_refuses_when_not_on_run_branch(self, tmp_path: Path) -> None:
        repo, remote = self._setup(tmp_path)
        subprocess.run(["git", "checkout", "main"], check=True, cwd=repo, capture_output=True)
        r = _run_cli("push-branch", cwd=repo)
        assert r.returncode == 1
        assert "refusing to push" in r.stderr
        ls = subprocess.run(
            ["git", "ls-remote", "--heads", str(remote)], capture_output=True, text=True,
        ).stdout
        assert "sindri/test" not in ls  # nothing pushed

    def test_no_active_run_degrades(self, tmp_path: Path) -> None:
        r = _run_cli("push-branch", cwd=tmp_path)
        assert r.returncode == 1
        assert "Traceback" not in r.stderr


class TestLogEvent:
    @staticmethod
    def _seed(tmp_path: Path, run_id: str = "testrun123") -> None:
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
            goal=Goal(metric_name="x", direction="reduce", target_pct=10.0),
            baseline=Baseline(value=100.0, noise_floor=1.0, samples=[100.0, 101.0, 99.0]),
            pool=[Candidate(id=1, name="a", expected_impact_pct=-10.0)],
            branch="sindri/test",
            started_at=datetime(2026, 6, 19, 10, 0, tzinfo=timezone.utc),
            guardrails=Guardrails(mode="local"),
            mode="local",
            run_id=run_id,
        )
        write_state(state, dir=tmp_path / ".sindri" / "current")

    @staticmethod
    def _events(tmp_path: Path) -> list[dict]:
        path = tmp_path / ".sindri" / "current" / "sindri.jsonl"
        if not path.exists():
            return []
        out = []
        for ln in path.read_text().splitlines():
            if ln.strip():
                d = json.loads(ln)
                if d.get("type") == "event":
                    out.append(d)
        return out

    def test_appends_event_with_run_id_and_details(self, tmp_path: Path) -> None:
        self._seed(tmp_path)
        r = _run_cli(
            "log-event", "--event", "candidate_dispatched",
            "--details", json.dumps({"candidate_id": 1, "name": "a"}),
            cwd=tmp_path,
        )
        assert r.returncode == 0, r.stderr
        events = self._events(tmp_path)
        assert len(events) == 1
        assert events[0]["event"] == "candidate_dispatched"
        assert events[0]["run_id"] == "testrun123"  # correlated to the run
        assert events[0]["details"] == {"candidate_id": 1, "name": "a"}

    def test_verbose_only_gating(self, tmp_path: Path) -> None:
        import os

        self._seed(tmp_path)
        # Without the flag set → skipped (not written).
        env = {k: v for k, v in os.environ.items() if k != "SINDRI_FORGE_VERBOSE"}
        r = subprocess.run(
            [sys.executable, "-m", "sindri", "log-event", "--event", "noisy", "--verbose-only"],
            cwd=tmp_path, capture_output=True, text=True, env=env,
        )
        assert r.returncode == 0
        assert json.loads(r.stdout).get("skipped") == "verbose-only"
        assert self._events(tmp_path) == []
        # With it set → written.
        r2 = subprocess.run(
            [sys.executable, "-m", "sindri", "log-event", "--event", "noisy", "--verbose-only"],
            cwd=tmp_path, capture_output=True, text=True, env={**env, "SINDRI_FORGE_VERBOSE": "1"},
        )
        assert r2.returncode == 0
        assert len(self._events(tmp_path)) == 1

    def test_invalid_details_rejected(self, tmp_path: Path) -> None:
        self._seed(tmp_path)
        r = _run_cli("log-event", "--event", "x", "--details", "[1,2,3]", cwd=tmp_path)
        assert r.returncode == 1
        assert "JSON object" in r.stderr

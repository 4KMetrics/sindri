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

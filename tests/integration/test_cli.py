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

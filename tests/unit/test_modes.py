"""Tests for local vs remote mode detection."""
from __future__ import annotations

from pathlib import Path

import pytest

from sindri.core.modes import detect_mode, script_content_signal


class TestScriptContentSignal:
    def test_simple_local_script(self, tmp_path: Path) -> None:
        script = tmp_path / "benchmark.py"
        script.write_text("import subprocess\nsubprocess.run(['du', '-sb', 'dist'])\n")
        assert script_content_signal(script) == "local"

    def test_gh_workflow_run_flags_remote(self, tmp_path: Path) -> None:
        script = tmp_path / "benchmark.py"
        script.write_text("import subprocess\nsubprocess.run(['gh', 'workflow', 'run', 'ci.yml'])\n")
        assert script_content_signal(script) == "remote"

    def test_aws_cli_flags_remote(self, tmp_path: Path) -> None:
        script = tmp_path / "benchmark.py"
        script.write_text("subprocess.run(['aws', 's3', 'ls'])")
        assert script_content_signal(script) == "remote"

    def test_gcloud_flags_remote(self, tmp_path: Path) -> None:
        script = tmp_path / "benchmark.py"
        script.write_text("subprocess.run(['gcloud', 'run', 'jobs', 'execute'])")
        assert script_content_signal(script) == "remote"

    def test_kubectl_flags_remote(self, tmp_path: Path) -> None:
        script = tmp_path / "benchmark.py"
        script.write_text("subprocess.run(['kubectl', 'get', 'pods'])")
        assert script_content_signal(script) == "remote"

    def test_curl_to_external_host_flags_remote(self, tmp_path: Path) -> None:
        script = tmp_path / "benchmark.py"
        script.write_text("subprocess.run(['curl', 'https://api.example.com/metrics'])")
        assert script_content_signal(script) == "remote"

    def test_curl_to_localhost_stays_local(self, tmp_path: Path) -> None:
        script = tmp_path / "benchmark.py"
        script.write_text("subprocess.run(['curl', 'http://localhost:3000/health'])")
        assert script_content_signal(script) == "local"

    def test_curl_to_127_0_0_1_stays_local(self, tmp_path: Path) -> None:
        script = tmp_path / "benchmark.py"
        script.write_text("subprocess.run(['curl', 'http://127.0.0.1:8080/metrics'])")
        assert script_content_signal(script) == "local"

    def test_missing_script_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            script_content_signal(tmp_path / "no-such-file.py")


class TestDetectMode:
    def test_local_script_low_cv_is_local(self, tmp_path: Path) -> None:
        script = tmp_path / "benchmark.py"
        script.write_text("import subprocess\nsubprocess.run(['du', '-sb', 'dist'])\n")
        assert detect_mode(script, [500.0, 100.0, 100.5, 99.5]) == "local"

    def test_local_script_high_cv_is_remote(self, tmp_path: Path) -> None:
        script = tmp_path / "benchmark.py"
        script.write_text("import subprocess\nsubprocess.run(['du', '-sb', 'dist'])\n")
        assert detect_mode(script, [500.0, 100.0, 80.0, 120.0, 70.0, 130.0]) == "remote"

    def test_remote_keyword_always_wins(self, tmp_path: Path) -> None:
        script = tmp_path / "benchmark.py"
        script.write_text("subprocess.run(['gh', 'workflow', 'run'])")
        assert detect_mode(script, [500.0, 100.0, 100.5, 99.5]) == "remote"

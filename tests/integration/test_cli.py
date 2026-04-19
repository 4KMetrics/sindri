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
            "read-state",
            "pick-next",
            "record-result",
            "check-termination",
            "generate-pr-body",
            "archive",
            "status",
            "detect-mode",
            "init",
        ]:
            assert sub in r.stdout, f"{sub} missing from --help"

    def test_unknown_subcommand_exits_nonzero(self) -> None:
        r = _run_cli("totally-made-up")
        assert r.returncode != 0

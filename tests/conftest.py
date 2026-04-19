"""Shared pytest fixtures across the whole suite."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_sindri_dir(tmp_path: Path) -> Path:
    """A temp directory with the standard .sindri/current layout pre-created."""
    sindri_dir = tmp_path / ".sindri" / "current"
    sindri_dir.mkdir(parents=True)
    return sindri_dir


@pytest.fixture
def tmp_git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A temp directory initialized as a git repo with one initial commit on main.

    The current working directory is set to the repo root for the duration of the test.
    """
    import subprocess

    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init", "-b", "main"], check=True, capture_output=True, cwd=tmp_path)
    subprocess.run(["git", "config", "user.email", "test@example.com"], check=True, cwd=tmp_path)
    subprocess.run(["git", "config", "user.name", "Test"], check=True, cwd=tmp_path)
    # Initial commit so the repo has a HEAD
    (tmp_path / "README.md").write_text("# test\n")
    subprocess.run(["git", "add", "README.md"], check=True, cwd=tmp_path)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        check=True,
        capture_output=True,
        cwd=tmp_path,
    )
    return tmp_path

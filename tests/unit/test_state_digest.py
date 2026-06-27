"""Unit tests for state_digest — the integrity fingerprint of .sindri/current/.

Used as a 6a-style guard: snapshot before dispatching the experiment subagent,
re-check after it returns; a change means the subagent wrote protected state.
"""
from __future__ import annotations

from pathlib import Path

from sindri.core.state import state_digest


def _d(tmp_path: Path) -> Path:
    d = tmp_path / ".sindri" / "current"
    d.mkdir(parents=True)
    return d


def test_stable_for_identical_content(tmp_path: Path) -> None:
    d = _d(tmp_path)
    (d / "sindri.jsonl").write_text('{"a": 1}\n')
    (d / "sindri.md").write_text("---\nx\n")
    assert state_digest(dir=d) == state_digest(dir=d)


def test_changes_when_jsonl_changes(tmp_path: Path) -> None:
    d = _d(tmp_path)
    (d / "sindri.jsonl").write_text('{"a": 1}\n')
    before = state_digest(dir=d)
    with (d / "sindri.jsonl").open("a") as f:
        f.write('{"forged": "improved"}\n')
    assert state_digest(dir=d) != before


def test_changes_when_md_changes(tmp_path: Path) -> None:
    d = _d(tmp_path)
    (d / "sindri.jsonl").write_text("")
    (d / "sindri.md").write_text("a")
    before = state_digest(dir=d)
    (d / "sindri.md").write_text("b")
    assert state_digest(dir=d) != before


def test_missing_dir_returns_stable_sentinel(tmp_path: Path) -> None:
    d = tmp_path / ".sindri" / "current"  # does not exist
    assert state_digest(dir=d) == state_digest(dir=d)


def test_cli_state_digest_changes_after_forged_append(tmp_path: Path) -> None:
    """The `state-digest` verb prints a fingerprint that changes if the jsonl is
    written to — the orchestrator's hook for catching subagent state tampering."""
    import subprocess
    import sys

    d = _d(tmp_path)
    (d / "sindri.jsonl").write_text('{"a": 1}\n')
    (d / "sindri.md").write_text("---\n")

    def digest() -> str:
        r = subprocess.run(
            [sys.executable, "-m", "sindri", "state-digest"],
            cwd=tmp_path, capture_output=True, text=True,
        )
        assert r.returncode == 0, r.stderr
        return r.stdout.strip()

    before = digest()
    assert before
    with (d / "sindri.jsonl").open("a") as f:
        f.write('{"forged": "improved"}\n')
    assert digest() != before


def test_changes_when_halt_sentinel_planted(tmp_path: Path) -> None:
    # A subagent planting HALT (to force premature terminate/finalize) must be
    # caught by the whole-dir digest, even though jsonl/md are untouched.
    d = _d(tmp_path)
    (d / "sindri.jsonl").write_text('{"a": 1}\n')
    (d / "sindri.md").write_text("---\n")
    before = state_digest(dir=d)
    (d / "HALT").write_text("")
    assert state_digest(dir=d) != before

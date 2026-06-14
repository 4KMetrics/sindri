"""Guard: skills/commands must invoke the backend via forge.sh, not `python -m sindri`."""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Files that must be fully migrated to the wrapper.
MIGRATED = [
    REPO_ROOT / "commands" / "sindri.md",
    REPO_ROOT / "skills" / "sindri-start" / "SKILL.md",
    REPO_ROOT / "skills" / "sindri-loop" / "SKILL.md",
    REPO_ROOT / "skills" / "sindri-finalize" / "SKILL.md",
    REPO_ROOT / "skills" / "sindri-scaffold-benchmark" / "SKILL.md",
]


@pytest.mark.parametrize("path", MIGRATED, ids=lambda p: p.parent.name + "/" + p.name)
def test_no_bare_python_module_invocation(path):
    text = path.read_text()
    assert "python -m sindri" not in text, f"{path} still calls `python -m sindri` directly"


@pytest.mark.parametrize("path", MIGRATED, ids=lambda p: p.parent.name + "/" + p.name)
def test_references_forge_wrapper(path):
    text = path.read_text()
    assert "scripts/forge.sh" in text, f"{path} does not reference the forge wrapper"

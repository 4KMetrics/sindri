"""Tests for scripts/forge.sh — the uvx backend launcher."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
FORGE = REPO_ROOT / "scripts" / "forge.sh"
MANIFEST = REPO_ROOT / ".claude-plugin" / "plugin.json"


def _plugin_version() -> str:
    return json.loads(MANIFEST.read_text())["version"]


def _run(args, env=None, **kw):
    base = dict(os.environ)
    if env:
        base.update(env)
    return subprocess.run(
        ["bash", str(FORGE), *args],
        capture_output=True, text=True, env=base, **kw,
    )


def test_forge_is_executable():
    assert os.access(FORGE, os.X_OK), "forge.sh must be chmod +x"


def test_resolves_pinned_version_from_manifest():
    # DEBUG mode prints the resolved source and exits before any uv use.
    r = _run([], env={"SINDRI_FORGE_DEBUG": "1"})
    assert r.returncode == 0
    assert f"FORGE_SOURCE=sindri-forge=={_plugin_version()}" in r.stderr


def test_source_override_wins():
    r = _run([], env={"SINDRI_FORGE_DEBUG": "1", "SINDRI_FORGE_SOURCE": "/some/local/path"})
    assert r.returncode == 0
    assert "FORGE_SOURCE=/some/local/path" in r.stderr


def test_friendly_message_when_uv_missing():
    # Strip every PATH dir that contains a uv executable so the check trips,
    # while keeping coreutils. (uv may be installed in more than one location,
    # e.g. ~/.local/bin via the installer and /opt/homebrew/bin via Homebrew.)
    uv_dirs = {
        d
        for d in os.environ["PATH"].split(":")
        if d and os.access(os.path.join(d, "uv"), os.X_OK)
    }
    path = ":".join(p for p in os.environ["PATH"].split(":") if p not in uv_dirs)
    r = _run(["read-state"], env={"PATH": path})
    assert r.returncode != 0
    assert "astral.sh/uv/install.sh" in r.stderr
    assert "Traceback" not in r.stderr


def _fake_uv_dir(tmp_path: Path) -> Path:
    """Create a dir with fake `uv` and `uvx` executables that exit 0 silently.

    forge.sh only checks `command -v uv` for presence, but the actual backend
    call is `uvx --from ... python -m sindri ...`. Both must exist on PATH for
    the wrapper to reach (and complete) the warmed-marker logic without network.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name in ("uv", "uvx"):
        exe = bindir / name
        exe.write_text("#!/bin/sh\nexit 0\n")
        exe.chmod(0o755)
    return bindir


def test_first_run_notice_then_suppressed(tmp_path):
    bindir = _fake_uv_dir(tmp_path)
    cache = tmp_path / "cache"
    home = tmp_path / "home"
    cache.mkdir()
    home.mkdir()
    # No SINDRI_FORGE_SOURCE here: the notice/warmed-marker path only runs for
    # the pinned package. (It is not set in the ambient test environment.)
    env = {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "XDG_CACHE_HOME": str(cache),
        "HOME": str(home),
    }

    first = _run(["read-state"], env=env)
    assert first.returncode == 0
    assert "Fetching sindri backend (first run only)" in first.stderr

    warmed = cache / "sindri" / f"warmed-{_plugin_version()}"
    assert warmed.exists(), f"expected warmed marker at {warmed}"

    second = _run(["read-state"], env=env)
    assert second.returncode == 0
    assert "Fetching sindri backend (first run only)" not in second.stderr


def test_no_notice_when_source_override_set(tmp_path):
    bindir = _fake_uv_dir(tmp_path)
    cache = tmp_path / "cache"
    home = tmp_path / "home"
    cache.mkdir()
    home.mkdir()
    env = {
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "XDG_CACHE_HOME": str(cache),
        "HOME": str(home),
        "SINDRI_FORGE_SOURCE": str(tmp_path / "some-local-source"),
    }
    r = _run(["read-state"], env=env)
    assert r.returncode == 0
    assert "Fetching sindri backend" not in r.stderr


@pytest.mark.e2e
def test_runs_backend_against_local_source():
    if shutil.which("uv") is None:
        pytest.skip("uv not installed")
    r = _run(["--version"], env={"SINDRI_FORGE_SOURCE": str(REPO_ROOT)})
    assert r.returncode == 0
    assert "sindri" in r.stdout.lower()

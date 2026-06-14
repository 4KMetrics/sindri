# Sindri UX Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Sindri run its Python backend on demand via `uvx` so users install the plugin from the marketplace and run `/sindri <goal>` with zero manual Python setup.

**Architecture:** A single self-locating wrapper script (`scripts/forge.sh`) resolves the pinned `sindri-forge` version from `.claude-plugin/plugin.json`, checks for `uv`, prints a one-time first-run fetch notice to stderr, and execs `uvx --from sindri-forge==<version> python -m sindri <cmd>`. Every skill/command call site calls the wrapper instead of `python -m sindri`. All wrapper diagnostics go to **stderr** so the backend's stdout stays clean for the JSON parsers in the skills.

**Tech Stack:** Bash, `uv`/`uvx`, Python 3.10+ (`sindri-forge` on PyPI), pytest (for guard + wrapper tests).

---

## Refinements to the spec (discovered during planning)

The approved spec (`docs/superpowers/specs/2026-06-14-sindri-ux-overhaul-design.md`) is correct in intent; three implementation details changed once the `CLAUDE_PLUGIN_ROOT` constraint was verified. These are noted here and should be synced back into the spec:

1. **Version resolution is wrapper-mediated, not env-var-mediated.** `CLAUDE_PLUGIN_ROOT` is only documented for hooks, not skill Bash. So `scripts/forge.sh` self-locates via `BASH_SOURCE` and reads `plugin.json` relative to itself. Skills invoke the wrapper by absolute path (Claude fills it from the skill's base dir).
2. **`SINDRI_FORGE_SOURCE` takes a path or package spec, not literally `.`.** `uvx --from .` resolves against the *current working directory* — which during a run is the user's target repo, not the sindri checkout. The override must be an explicit path (e.g. the sindri repo root) or a package spec.
3. **`smoke.sh` runs against local source, not the published pin.** It is a pre-push "did I break the plumbing" test, so it must exercise local code: it calls the wrapper with `SINDRI_FORGE_SOURCE="$SINDRI_REPO"`. This still tests the real uvx invocation path, against the working tree.

---

## File structure

| File | Responsibility | Action |
|---|---|---|
| `scripts/forge.sh` | Self-locating backend launcher: version pin + uv check + first-run notice + uvx exec | **Create** |
| `tests/unit/test_forge_wrapper.py` | Unit/integration tests for the wrapper | **Create** |
| `tests/unit/test_uvx_invocation.py` | Guard: no `python -m sindri` left in skills/commands; wrapper is referenced | **Create** |
| `commands/sindri.md` | `status` route → wrapper | **Modify** |
| `skills/sindri-start/SKILL.md` | Pre-flight + `validate-benchmark` + `init` → wrapper; fix install-check message | **Modify** |
| `skills/sindri-loop/SKILL.md` | `read-state`, `check-termination`×2, `pick-next`, `record-result` → wrapper | **Modify** |
| `skills/sindri-finalize/SKILL.md` | `generate-pr-body`, `archive` → wrapper | **Modify** |
| `skills/sindri-scaffold-benchmark/SKILL.md` | `validate-benchmark` → wrapper | **Modify** |
| `scripts/install-plugin.sh` | Slim to symlink-only | **Modify** |
| `scripts/smoke.sh` | Run lifecycle through the wrapper against local source | **Modify** |
| `README.md` | One install path, `/reload-plugins`, remove `uv pip install`, fix stale copy | **Modify** |

**The skill-invocation convention** (used in every skill/command edit below):

> Resolve `FORGE` to the absolute path of `scripts/forge.sh` in this plugin (this skill lives at `<plugin-root>/skills/<name>/SKILL.md`, so the wrapper is at `<plugin-root>/scripts/forge.sh`). Then call `"$FORGE" <subcommand>` exactly where `python -m sindri <subcommand>` was called before.

---

## Task 1: Create the `forge.sh` wrapper

**Files:**
- Create: `scripts/forge.sh`
- Test: `tests/unit/test_forge_wrapper.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_forge_wrapper.py`:

```python
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
    uv = shutil.which("uv")
    if uv:
        # Strip uv's directory from PATH so the check trips, keep coreutils.
        uv_dir = str(Path(uv).parent)
        path = ":".join(p for p in os.environ["PATH"].split(":") if p != uv_dir)
    else:
        path = os.environ["PATH"]
    r = _run(["read-state"], env={"PATH": path})
    assert r.returncode != 0
    assert "astral.sh/uv/install.sh" in r.stderr
    assert "Traceback" not in r.stderr


@pytest.mark.e2e
def test_runs_backend_against_local_source():
    if shutil.which("uv") is None:
        pytest.skip("uv not installed")
    r = _run(["--version"], env={"SINDRI_FORGE_SOURCE": str(REPO_ROOT)})
    assert r.returncode == 0
    assert "sindri" in r.stdout.lower()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/unit/test_forge_wrapper.py -v`
Expected: FAIL — `forge.sh` does not exist yet (collection/`test_forge_is_executable` fails).

- [ ] **Step 3: Write `scripts/forge.sh`**

```bash
#!/usr/bin/env bash
# sindri forge — backend launcher.
#
# Resolves the pinned sindri-forge version from the plugin manifest and runs the
# Python backend in an isolated environment via uvx. Centralizes:
#   - version pinning (matched to .claude-plugin/plugin.json)
#   - uv presence check (friendly message, never a traceback)
#   - first-run fetch notice (stderr only; stdout stays clean for JSON parsers)
#   - local-dev source override via SINDRI_FORGE_SOURCE (a path or package spec)
#
# Usage: forge.sh <sindri-subcommand> [args...]
# All wrapper diagnostics go to stderr; the backend's stdout passes through clean.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MANIFEST="$PLUGIN_ROOT/.claude-plugin/plugin.json"

# Read version from the manifest WITHOUT python (uv may be bootstrapping python).
VERSION="$( { grep -m1 '"version"' "$MANIFEST" || true; } \
  | sed -E 's/.*"version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/' )"
if [ -z "$VERSION" ]; then
  echo "sindri: could not read version from $MANIFEST" >&2
  exit 1
fi

# Default to the pinned PyPI package; allow a local path/spec override for dev.
SOURCE="${SINDRI_FORGE_SOURCE:-sindri-forge==$VERSION}"

# Debug hook (tests): print resolved source and exit before any uv use.
if [ "${SINDRI_FORGE_DEBUG:-}" = "1" ]; then
  echo "FORGE_SOURCE=$SOURCE" >&2
  exit 0
fi

# uv presence check — friendly, copy-pasteable, no traceback.
if ! command -v uv >/dev/null 2>&1; then
  cat >&2 <<'MSG'
sindri needs `uv` (it runs the backend in an isolated environment).
Install it, then re-run /sindri:
  curl -LsSf https://astral.sh/uv/install.sh | sh
MSG
  exit 1
fi

# First-run fetch notice (stderr), only for the pinned package and only once
# per version. Skipped when a source override is set (local dev doesn't fetch).
if [ -z "${SINDRI_FORGE_SOURCE:-}" ]; then
  CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/sindri"
  WARMED="$CACHE_DIR/warmed-$VERSION"
  if [ ! -e "$WARMED" ]; then
    echo "Fetching sindri backend (first run only)…" >&2
  fi
fi

set +e
uvx --from "$SOURCE" python -m sindri "$@"
status=$?
set -e

# Mark this version warmed so the notice only shows once.
if [ "$status" -eq 0 ] && [ -z "${SINDRI_FORGE_SOURCE:-}" ]; then
  mkdir -p "$CACHE_DIR" 2>/dev/null && : > "$WARMED" 2>/dev/null || true
fi
exit "$status"
```

- [ ] **Step 4: Make it executable**

Run: `chmod +x scripts/forge.sh`

- [ ] **Step 5: Run the tests to verify they pass**

Run: `pytest tests/unit/test_forge_wrapper.py -v`
Expected: PASS (the `@pytest.mark.e2e` test passes if `uv` is installed, otherwise skips).

- [ ] **Step 6: Commit**

```bash
git add scripts/forge.sh tests/unit/test_forge_wrapper.py
git commit -m "feat: add forge.sh uvx backend launcher with version pin + uv check"
```

---

## Task 2: Guard test — no bare `python -m sindri` in skills/commands

This test drives the conversion in Tasks 3–7: it fails now and passes once every call site is migrated.

**Files:**
- Test: `tests/unit/test_uvx_invocation.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_uvx_invocation.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/unit/test_uvx_invocation.py -v`
Expected: FAIL — all five files still contain `python -m sindri` and don't yet reference `scripts/forge.sh`.

- [ ] **Step 3: Commit the guard**

```bash
git add tests/unit/test_uvx_invocation.py
git commit -m "test: guard against bare python -m sindri in skills/commands"
```

---

## Task 3: Migrate `commands/sindri.md` (status route)

**Files:**
- Modify: `commands/sindri.md:14`

- [ ] **Step 1: Edit the `status` row**

Replace the `status` table row (currently line 14):

```markdown
| `status` | Run `python -m sindri status` and print its output verbatim. No skill invocation. Zero-cost read. |
```

with:

```markdown
| `status` | Resolve `FORGE` to this plugin's `scripts/forge.sh` (absolute path; the command file lives at `<plugin-root>/commands/sindri.md`, so the wrapper is `<plugin-root>/scripts/forge.sh`). Run `"$FORGE" status` and print its output verbatim. No skill invocation. Fast read (the first-ever call does a one-time backend fetch; subsequent calls are cached). |
```

- [ ] **Step 2: Verify the guard's status-file checks pass**

Run: `pytest tests/unit/test_uvx_invocation.py -v -k sindri.md`
Expected: PASS for `commands/sindri.md` (both guard tests).

- [ ] **Step 3: Commit**

```bash
git add commands/sindri.md
git commit -m "feat: route /sindri status through forge.sh"
```

---

## Task 4: Migrate `skills/sindri-start/SKILL.md`

Four call sites plus the stale install-check message.

**Files:**
- Modify: `skills/sindri-start/SKILL.md` (lines ~13, ~14, ~45, ~98)

- [ ] **Step 1: Add the wrapper-resolution note + fix pre-flight #1 (install check)**

Replace pre-flight item 1 (line 13):

```markdown
1. **Python package available.** Run `python -m sindri --version`. If it fails with `No module named sindri` (or similar), STOP — print: *"The `sindri` Python package isn't installed in the current Python environment. From the plugin directory (`~/.claude/plugins/sindri`) run `./scripts/install-plugin.sh`, or `uv pip install sindri` once it's published to PyPI. Then re-run `/sindri`."* Do not proceed.
```

with:

```markdown
0. **Resolve the backend launcher.** Set `FORGE` to the absolute path of this plugin's `scripts/forge.sh` (this skill lives at `<plugin-root>/skills/sindri-start/SKILL.md`, so the wrapper is `<plugin-root>/scripts/forge.sh`). Every backend call below uses `"$FORGE" <cmd>`.
1. **Backend reachable.** Run `"$FORGE" --version`. If it prints the `uv`-missing guidance (no `uv` on PATH), relay that message verbatim and STOP — the user must install `uv` (`curl -LsSf https://astral.sh/uv/install.sh | sh`) and re-run `/sindri`. Do not proceed.
```

- [ ] **Step 2: Migrate pre-flight #2 (status)**

In pre-flight item 2 (line 14), replace `Run \`python -m sindri status\`` with `Run \`"$FORGE" status\``.

- [ ] **Step 3: Migrate the validate-benchmark call**

In section 2 (line 45), replace `run \`python -m sindri validate-benchmark --expected <metric_name>\`` with `run \`"$FORGE" validate-benchmark --expected <metric_name>\``.

- [ ] **Step 4: Migrate the init call**

In section 5, replace the fenced block (lines ~97-102):

```bash
python -m sindri init \
  --goal "<normalized goal — e.g. 'reduce bundle_bytes by 15%'>" \
  --pool-json "$POOL_JSON" \
  --script .claude/scripts/sindri/benchmark.py
```

with:

```bash
"$FORGE" init \
  --goal "<normalized goal — e.g. 'reduce bundle_bytes by 15%'>" \
  --pool-json "$POOL_JSON" \
  --script .claude/scripts/sindri/benchmark.py
```

- [ ] **Step 5: Verify the guard passes for this file**

Run: `pytest tests/unit/test_uvx_invocation.py -v -k sindri-start`
Expected: PASS (no `python -m sindri`; references `scripts/forge.sh`).

- [ ] **Step 6: Commit**

```bash
git add skills/sindri-start/SKILL.md
git commit -m "feat: route sindri-start backend calls through forge.sh; fix install-check message"
```

---

## Task 5: Migrate `skills/sindri-loop/SKILL.md`

Five call sites. Note the orchestrator's intro line also describes the mechanism.

**Files:**
- Modify: `skills/sindri-loop/SKILL.md` (lines ~9, 18, 50, 82, 157, 174)

- [ ] **Step 1: Update the intro + add wrapper resolution**

Replace the intro sentence (line 9) fragment `every deterministic step goes through \`python -m sindri <cmd>\`` with `every deterministic step goes through the backend wrapper \`"$FORGE" <cmd>\` (resolve \`FORGE\` to this plugin's \`scripts/forge.sh\` — the skill lives at \`<plugin-root>/skills/sindri-loop/SKILL.md\`, so the wrapper is \`<plugin-root>/scripts/forge.sh\`)`.

- [ ] **Step 2: Migrate `read-state` (line 18)**

Replace `python -m sindri read-state` with `"$FORGE" read-state`.

- [ ] **Step 3: Migrate `check-termination` (line 50)**

Replace `echo '{"experiments_run": <N>, "consecutive_reverts": <K>}' | python -m sindri check-termination`
with `echo '{"experiments_run": <N>, "consecutive_reverts": <K>}' | "$FORGE" check-termination`.

- [ ] **Step 4: Migrate `pick-next` (line 82)**

Replace `python -m sindri pick-next` with `"$FORGE" pick-next`.

- [ ] **Step 5: Migrate `record-result` (line 157)**

Replace `echo "$PAYLOAD" | python -m sindri record-result` with `echo "$PAYLOAD" | "$FORGE" record-result`.

- [ ] **Step 6: Migrate the second `check-termination` (line 174)**

Replace `echo '{"experiments_run": <N+1>, "consecutive_reverts": <updated K>}' | python -m sindri check-termination`
with `echo '{"experiments_run": <N+1>, "consecutive_reverts": <updated K>}' | "$FORGE" check-termination`.

- [ ] **Step 7: Verify the guard passes for this file**

Run: `pytest tests/unit/test_uvx_invocation.py -v -k sindri-loop`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add skills/sindri-loop/SKILL.md
git commit -m "feat: route sindri-loop backend calls through forge.sh"
```

---

## Task 6: Migrate `skills/sindri-finalize/SKILL.md`

Two call sites.

**Files:**
- Modify: `skills/sindri-finalize/SKILL.md` (lines ~16, 81)

- [ ] **Step 1: Add wrapper resolution to the intro**

After the opening paragraph (after line 9), add:

```markdown
Resolve `FORGE` to this plugin's `scripts/forge.sh` (this skill lives at `<plugin-root>/skills/sindri-finalize/SKILL.md`, so the wrapper is `<plugin-root>/scripts/forge.sh`). Backend calls below use `"$FORGE" <cmd>`.
```

- [ ] **Step 2: Migrate `generate-pr-body` (line 16)**

Replace `python -m sindri generate-pr-body > .sindri/current/pr-body.md`
with `"$FORGE" generate-pr-body > .sindri/current/pr-body.md`.

- [ ] **Step 3: Migrate `archive` (line 81)**

Replace `python -m sindri archive` with `"$FORGE" archive`.

- [ ] **Step 4: Verify the guard passes for this file**

Run: `pytest tests/unit/test_uvx_invocation.py -v -k sindri-finalize`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/sindri-finalize/SKILL.md
git commit -m "feat: route sindri-finalize backend calls through forge.sh"
```

---

## Task 7: Migrate `skills/sindri-scaffold-benchmark/SKILL.md`

One call site.

**Files:**
- Modify: `skills/sindri-scaffold-benchmark/SKILL.md` (lines ~14-15 inputs, ~93)

- [ ] **Step 1: Add wrapper resolution to the Inputs section**

After the Inputs list (after line 14), add:

```markdown
- Resolve `FORGE` to this plugin's `scripts/forge.sh` (this skill lives at `<plugin-root>/skills/sindri-scaffold-benchmark/SKILL.md`, so the wrapper is `<plugin-root>/scripts/forge.sh`). The validation step below uses `"$FORGE"`.
```

- [ ] **Step 2: Migrate `validate-benchmark` (line 93)**

Replace `python -m sindri validate-benchmark --expected $METRIC_NAME`
with `"$FORGE" validate-benchmark --expected $METRIC_NAME`.

- [ ] **Step 3: Verify the full guard passes**

Run: `pytest tests/unit/test_uvx_invocation.py -v`
Expected: PASS — all five files migrated.

- [ ] **Step 4: Commit**

```bash
git add skills/sindri-scaffold-benchmark/SKILL.md
git commit -m "feat: route sindri-scaffold-benchmark validate through forge.sh"
```

---

## Task 8: Slim `scripts/install-plugin.sh` to symlink-only

**Files:**
- Modify: `scripts/install-plugin.sh`

- [ ] **Step 1: Rewrite the script**

Replace the entire file with:

```bash
#!/usr/bin/env bash
# sindri plugin installer — local-dev symlink helper.
#
# Symlinks this plugin directory into ~/.claude/plugins/sindri so Claude Code
# discovers it. The Python backend is NOT installed here — it is fetched on
# demand by uvx (see scripts/forge.sh). To test LOCAL Python edits, export
# SINDRI_FORGE_SOURCE pointing at this repo before running /sindri:
#   export SINDRI_FORGE_SOURCE="$(pwd)"
#
# Idempotent. Usage: ./scripts/install-plugin.sh
# Exit 0 on success, non-zero on any failure.

set -euo pipefail

SINDRI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLAUDE_PLUGINS="${CLAUDE_PLUGINS_DIR:-$HOME/.claude/plugins}"
LINK="$CLAUDE_PLUGINS/sindri"

echo ">> Linking plugin into $CLAUDE_PLUGINS"
mkdir -p "$CLAUDE_PLUGINS"
ln -sfn "$SINDRI_DIR" "$LINK"

cat <<EOF

OK. Sindri plugin linked.

Next steps:
  1. Run /reload-plugins in Claude Code (or relaunch) so the plugin is picked up.
  2. In a repo you want to optimize, run:
       /sindri <goal>            e.g. /sindri reduce bundle_bytes by 15%
     or                          /sindri status / stop / clear
  3. See README.md + docs/DOGFOOD.md for a guided first-run walkthrough.

The Python backend is fetched on demand by uvx — no pip install needed.
To test local backend edits: export SINDRI_FORGE_SOURCE="$SINDRI_DIR"

Plugin link: $LINK -> $SINDRI_DIR
EOF
```

- [ ] **Step 2: Verify it runs and is a no-op-safe symlink**

Run: `CLAUDE_PLUGINS_DIR="$(mktemp -d)" bash scripts/install-plugin.sh`
Expected: prints the "OK. Sindri plugin linked." block; exit 0; no pip output.

- [ ] **Step 3: Commit**

```bash
git add scripts/install-plugin.sh
git commit -m "feat: slim install-plugin.sh to symlink-only (backend via uvx)"
```

---

## Task 9: Convert `scripts/smoke.sh` to run through the wrapper

The smoke test must exercise the real uvx path against **local** source.

**Files:**
- Modify: `scripts/smoke.sh` (lines ~32 PYTHONPATH, 37, 43, 46, 49, 52, 55, 58)

- [ ] **Step 1: Replace the PYTHONPATH export with a wrapper alias**

Replace line 32:

```bash
export PYTHONPATH="$SINDRI_REPO/src:${PYTHONPATH:-}"
```

with:

```bash
# Exercise the real uvx launch path, but against THIS working tree (not PyPI).
export SINDRI_FORGE_SOURCE="$SINDRI_REPO"
FORGE="$SINDRI_REPO/scripts/forge.sh"
```

- [ ] **Step 2: Replace each backend invocation**

Replace, in order:
- Line 37-40 `python -m sindri init \ ...` → `"$FORGE" init \ ...` (keep the same flags/args).
- Line 43 `python -m sindri validate-benchmark` → `"$FORGE" validate-benchmark`.
- Line 46 `echo '{"baseline_samples": [30.0, 30.0, 30.0]}' | python -m sindri detect-mode --script .claude/scripts/sindri/benchmark.py` → `echo '{"baseline_samples": [30.0, 30.0, 30.0]}' | "$FORGE" detect-mode --script .claude/scripts/sindri/benchmark.py`.
- Line 49 `python -m sindri read-state | python -c "..."` → `"$FORGE" read-state | python3 -c "..."` (keep the python3 parse helper — it only reads stdout).
- Line 52 `python -m sindri pick-next` → `"$FORGE" pick-next`.
- Line 55 `echo '{"experiments_run": 0, "consecutive_reverts": 0}' | python -m sindri check-termination` → `echo '{"experiments_run": 0, "consecutive_reverts": 0}' | "$FORGE" check-termination`.
- Line 58 `python -m sindri status` → `"$FORGE" status`.

- [ ] **Step 3: Run the smoke test end-to-end**

Run: `./scripts/smoke.sh`
Expected: prints each step header and ends with `>> OK — plumbing works.` (requires `uv`).

- [ ] **Step 4: Commit**

```bash
git add scripts/smoke.sh
git commit -m "test: run smoke.sh through forge.sh against local source"
```

---

## Task 10: README overhaul

**Files:**
- Modify: `README.md` (Install section, lines ~11-63; Development section ~91-99)

- [ ] **Step 1: Replace the Install section**

Replace everything from `## Install` (line 11) through the end of the "Requirements" list (line 63) with:

````markdown
## Install

```
/plugin install sindri@claude-community
/reload-plugins            # or relaunch Claude Code; commands are then live
```

Then, in any repo you want to optimize:

```
/sindri reduce bundle_bytes by 15%
```

That's it. No `pip install`, no virtualenv. The Python backend (`sindri-forge`)
is fetched on demand by [`uv`](https://docs.astral.sh/uv/). If `uv` isn't
installed, `/sindri` prints a one-line install command and stops.

> Sindri is published in the Anthropic community marketplace
> (`anthropics/claude-plugins-community`). If you haven't added it yet:
> `/plugin marketplace add anthropics/claude-plugins-community`.

Requirements:

- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) — runs the backend in an isolated environment
- `git` ≥ 2.30
- `gh` CLI (authenticated) — needed only for `sindri-finalize` PR creation
- Claude Code with `Task` + `ScheduleWakeup` tools

**First-run dogfood:** walk through [`docs/DOGFOOD.md`](docs/DOGFOOD.md) on a throwaway repo before pointing sindri at real code.
````

- [ ] **Step 2: Add a Contributing footnote for local dev**

In the `## Development` section, after the existing fenced commands (after line 99), append:

````markdown
### Local plugin install (contributors)

```bash
git clone https://github.com/4KMetrics/sindri.git ~/src/sindri
cd ~/src/sindri && ./scripts/install-plugin.sh   # symlinks the plugin only
```

To test local backend edits (instead of the published package), point the
launcher at your checkout before running `/sindri`:

```bash
export SINDRI_FORGE_SOURCE="$(pwd)"
```
````

- [ ] **Step 3: Lint the README**

Run: `npx markdownlint-cli README.md` (or `markdownlint README.md` if installed; the repo has `.markdownlint.json`).
Expected: no errors. Fix any that appear.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: collapse README to one install path; uvx, /reload-plugins, fix stale copy"
```

---

## Task 11: Full verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `pytest -q`
Expected: PASS, including the new `test_forge_wrapper.py` and `test_uvx_invocation.py` (e2e wrapper test skips if `uv` absent).

- [ ] **Step 2: Run the smoke test**

Run: `./scripts/smoke.sh`
Expected: ends with `>> OK — plumbing works.`

- [ ] **Step 3: Confirm no stray bare invocations remain anywhere user-facing**

Run: `grep -rn "python -m sindri" commands skills scripts/install-plugin.sh README.md || echo CLEAN`
Expected: `CLEAN` (smoke.sh legitimately has none after Task 9; docs/ and the spec may still reference it for explanatory purposes and are intentionally excluded).

- [ ] **Step 4: Confirm the stale "Pending Anthropic review" copy is gone**

Run: `grep -rn "Pending Anthropic review" README.md || echo CLEAN`
Expected: `CLEAN`.

- [ ] **Step 5: Final commit (if any lint/verification fixups were needed)**

```bash
git add -A
git commit -m "chore: verification fixups for uvx UX overhaul" || echo "nothing to commit"
```

---

## Self-review (completed during planning)

- **Spec coverage:** §1 invocation → Tasks 1,3-7,9; §2 version pin → Task 1 (manifest read); §3 local-dev escape hatch → Tasks 1,8 (+README Task 10); §4 uv check → Task 1; §5 first-run message → Task 1; §6 docs → Tasks 4,8,10. All spec sections map to tasks.
- **Placeholders:** none — every code/edit step shows the actual before/after text or full file.
- **Type/name consistency:** the wrapper is `scripts/forge.sh` and the shell var is `FORGE` everywhere; the override var is `SINDRI_FORGE_SOURCE` and the debug var `SINDRI_FORGE_DEBUG` consistently; subcommand names (`read-state`, `check-termination`, `pick-next`, `record-result`, `init`, `validate-benchmark`, `generate-pr-body`, `archive`, `status`, `detect-mode`, `--version`) match the current CLI surface verified in the existing skills/`smoke.sh`.
- **Refinements vs spec:** three, listed at the top — sync into the spec.

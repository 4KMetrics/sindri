# Sindri UX Overhaul — Design Spec

**Date:** 2026-06-14
**Status:** Approved (brainstorming complete; pending implementation plan)
**Supersedes:** `plan/ux-overhaul.md` (earlier draft; this spec is the authoritative version)

## Goal

Make Sindri install and run like a native Claude Code plugin: a user installs it from
the marketplace and runs `/sindri <goal>` with **no manual Python environment management**
(no `uv pip install`, no venvs, no editable installs). The Python backend
(`sindri-forge` on PyPI) is fetched on demand by `uvx`.

## Scope

**In scope:** install experience and how the skills invoke the Python backend.

**Out of scope:** the autonomous experiment-loop UX (candidate proposal, benchmark
scaffolding flow, PR rendering). Those are unchanged by this work.

## Verified ground truth (as of 2026-06-14)

These facts were checked directly, not assumed:

- `sindri-forge` **is published on PyPI** at version `0.3.2` (`requires-python >=3.10`).
- The published `0.3.2` wheel has **no `[project.scripts]` console entry point**
  (`entry_points: None`). Confirmed via PyPI metadata and by `uv` refusing to run it.
- Invocation behaviour, tested against the live package with `uv 0.11.3`:
  | Command | Result |
  |---|---|
  | `uvx sindri-forge …` | ❌ `Package sindri-forge does not provide any executables` |
  | `uvx --from sindri-forge sindri …` | ❌ same (no console script) |
  | `uvx --from sindri-forge==0.3.2 python -m sindri …` | ✅ prints `sindri 0.3.2` |
- Sindri **is listed in the Anthropic community marketplace**
  (`anthropics/claude-plugins-community`, internal marketplace name `claude-community`),
  sourced from this repo by git SHA. The README's "Pending Anthropic review" copy is
  therefore **stale**.
- Installing a plugin does **not** require a full Claude Code restart: `/reload-plugins`
  activates commands/skills/agents/hooks in the current session
  (per official docs, `discover-plugins.md#apply-plugin-changes-without-restarting`).
  It is otherwise live on next launch.

## Design decisions

### 1. Backend invocation — module form (no republish)

All deterministic backend calls move from `python -m sindri <cmd>` to:

```
uvx --from ${SINDRI_FORGE_SOURCE:-sindri-forge==<version>} python -m sindri <cmd>
```

We use the **`python -m sindri` module form** rather than a console subcommand because it
works against the package already on PyPI — no new release, no `[project.scripts]` wiring
required. The verbosity lives entirely inside skill/command files and is never seen by the
end user.

**Call sites to update (~15 total):**

- `commands/sindri.md` — the `status` route.
- `skills/sindri-start/SKILL.md` — `--version` precheck, `status`, `validate-benchmark`, `init`.
- `skills/sindri-loop/SKILL.md` — `read-state`, `check-termination` (×2), `pick-next`, `record-result`.
- `skills/sindri-finalize/SKILL.md` — `generate-pr-body`, `archive`.
- `skills/sindri-scaffold-benchmark/SKILL.md` — `validate-benchmark`.
- `scripts/smoke.sh` — all `python -m sindri` invocations.

Stdin-piped commands keep their pipe, e.g.
`echo "$PAYLOAD" | uvx --from … python -m sindri record-result`.

### 2. Matched-pair version pinning

`<version>` is **derived from the plugin's own version** (`.claude-plugin/plugin.json`),
so plugin `x.y.z` always pulls backend `==x.y.z`. release-please bumps both in lockstep.

Rationale:
- **No mid-run drift.** An overnight run cannot have the backend change underneath it,
  because the pin is exact and tied to the installed plugin.
- **No manual multi-site edits.** The version is resolved once, not hardcoded at 15 sites.
- **Simplest mental model:** the plugin and its backend are the same version.

Version resolution is handled by a self-locating wrapper script (`scripts/forge.sh`, see
§3), **not** an environment variable: `CLAUDE_PLUGIN_ROOT` is documented for hooks only and
is not guaranteed in skill-invoked Bash. The wrapper finds itself via `BASH_SOURCE`, reads
`.claude-plugin/plugin.json` relative to its own path (with `grep`/`sed`, no Python
dependency, since `uv` may be bootstrapping Python), and uses the result as the
`sindri-forge==<version>` default. Skills invoke the wrapper by absolute path, which Claude
fills in from the skill's known base directory.

### 3. Local-dev escape hatch

- `SINDRI_FORGE_SOURCE` env var overrides the pinned source. It takes an **explicit path
  or package spec** (e.g. the sindri repo root), **not** a bare `.` — `uvx --from .`
  resolves against the current working directory, which during a run is the user's target
  repo, not the sindri checkout. A contributor exports
  `SINDRI_FORGE_SOURCE="$(pwd)"` from their sindri checkout so uvx builds from local
  Python source — preserving the edit-test loop without stale published code.
- `scripts/install-plugin.sh` is slimmed to **symlink the plugin only**. All pip/venv
  manipulation is removed. Contributors who want to test backend edits set
  `SINDRI_FORGE_SOURCE`.

### 4. `uv`-missing graceful check (Postel's Law)

Before the first backend call, `/sindri` checks for `uv` on PATH. If missing, it prints a
single copy-pasteable line and stops — never a Python traceback, never auto-executing a
remote installer:

```
sindri needs `uv` (it runs the backend in an isolated environment).
Install it, then re-run /sindri:
  curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 5. First-run latency message (Doherty Threshold)

The first `uvx` call triggers a one-time cold download (seconds); cached calls are
~tens of ms. To prevent the cold fetch reading as a hang, print before the first call:

```
Fetching sindri backend (first run only)…
```

The `commands/sindri.md` `status` route description is updated to acknowledge that the
**first ever** call incurs a one-time fetch; subsequent calls remain fast/zero-cost.

### 6. Documentation overhaul (Hick's Law + Jakob's Law)

`README.md`:
- Collapse the Install section to **one primary path**:
  ```
  /plugin install sindri@claude-community
  /reload-plugins            # or just relaunch; commands are then live
  /sindri reduce bundle_bytes by 15%
  ```
- Demote the local-dev install to a short **Contributing** footnote.
- Remove all end-user `uv pip install` instructions.
- Fix the stale "Pending Anthropic review" copy — Sindri is live in `claude-community`.
- Replace "Restart Claude Code" wording with the `/reload-plugins` instruction.

`skills/sindri-start/SKILL.md`:
- Update the hardcoded install-check error message (currently points users at
  `install-plugin.sh` / `uv pip install sindri`) to reflect the uvx model and the
  `uv`-missing guidance from §4.

## Out of scope / explicitly NOT doing

- Adding a `[project.scripts]` console entry point to `sindri-forge` (deferred; the module
  form removes the need). If added later, the pin and invocation can be revisited.
- Any change to PyPI publishing — `0.3.2` is sufficient for this work.
- Touching the experiment-loop reasoning, candidate pool, or PR-body content.

## Testing

- `scripts/smoke.sh` runs end-to-end through the wrapper with
  `SINDRI_FORGE_SOURCE="$SINDRI_REPO"` in a throwaway repo and must pass. It is a pre-push
  "did I break the plumbing" check, so it exercises the real uvx launch path against the
  **local working tree**, not the published package.
- A `uv`-missing simulation (temporarily shadow `uv` off PATH) must produce the friendly
  message from §4, not a traceback.
- `SINDRI_FORGE_SOURCE=.` must cause uvx to build from local source (verify a deliberate
  local edit is reflected).
- Manual: fresh-machine first-run shows the §5 fetch message; second run does not.

## Open questions

None outstanding. All five design forks resolved during brainstorming on 2026-06-14.

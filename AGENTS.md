# AGENTS.md — sindri

Canonical, tool-neutral context for any AI agent (Claude Code, Gemini CLI, …) working in this repo.
`CLAUDE.md` and `GEMINI.md` are loaders that point here — edit **this** file, not the loaders.

## What sindri is

A Claude Code plugin for **bounded, target-driven optimization loops**: make a change, benchmark it,
keep it if it's better, revert otherwise — repeat until the target is hit or the idea pool is
exhausted. One commit per kept experiment; git is the audit log. Named for the dwarf smith who forged
Mjölnir by iterating under adversity.

The published PyPI distribution is **`sindri-forge`** (the name `sindri` was taken by an unrelated
ZK-proof SDK); the imported module is still `sindri`.

## Architecture

- **Python core** — `src/sindri/`. Pure functions only: statistics, state file I/O
  (`core/state.py`), git wrappers, pool ordering, termination predicates, PR-body rendering. The CLI
  (`src/sindri/cli.py`, entry `src/sindri/__main__.py`) dispatches subcommands
  (`init`, `validate-benchmark`, `detect-mode`, `read-state`, `pick-next`, `record-result`,
  `check-termination`, `generate-pr-body`, `archive`, `status`).
- **Skills** — `skills/sindri-*/SKILL.md`. Prose prompts for decisions needing inference:
  `sindri-start`, `sindri-loop` (the per-wakeup orchestrator), `sindri-finalize`,
  `sindri-scaffold-benchmark`. Auto/model-invoked, never typed by users.
- **Commands** — `commands/<name>.md` → `/sindri:<name>`. Eight discrete user commands:
  `forge` (start), `status`, `stop`, `clear`, `setup`, `help`, plus advanced `loop`, `finalize`.
- **Subagent contract** — `prompts/experiment-subagent.md`. Fresh context per experiment, no bleed.

See `docs/superpowers/specs/2026-04-19-sindri-design.md` for the full design. The `docs/superpowers/`
plans/specs are point-in-time historical snapshots — do not retro-edit them to match later changes.

## How the backend is invoked (important)

Skills and commands **never** call `python -m sindri` directly. They go through the wrapper
`scripts/forge.sh` (resolved to a shell var `FORGE`), which runs the pinned published package via
`uvx --from sindri-forge==<version> python -m sindri "$@"` — zero-install, no venv. There is **no**
`[project.scripts]` console entry point, so bare `uvx sindri-forge` fails by design; the wrapper
invokes the module form (`python -m sindri`), never a console script.

- All diagnostics go to **stderr**; **stdout stays clean** for JSON consumers (`read-state` etc.).
- `SINDRI_FORGE_SOURCE=<path>` overrides the source to a local checkout for backend dev.
- Two unit guards enforce this: `tests/unit/test_uvx_invocation.py` (no bare `python -m sindri`; must
  reference `scripts/forge.sh`) and `tests/unit/test_plugin_artifacts.py` (command/skill structure).

## Conventions

- **CLI no-active-run degradation:** human-facing/inspection commands (`status`, `read-state`) print
  `sindri: no active run (.sindri/current/ not found)` to stdout and exit **0**. Machine-only mid-run
  commands (`pick-next`, `record-result`, `check-termination`, `generate-pr-body`, `archive`) exit
  **1** (non-zero = "no JSON, don't parse").
- **State lives on disk**, never in an agent's head: `.sindri/current/sindri.md` (frontmatter state) +
  `.sindri/current/sindri.jsonl` (append-only records). Every wakeup re-reads fresh.
- `progress/` is gitignored local scratch — not a source of truth. Completed root plans get moved
  there (into `progress/archive/`), i.e. removed from the tracked tree.

## Development

```bash
uv pip install -e ".[dev]"
pytest                                            # all layers
pytest -m "not e2e" -q                            # skip the slow end-to-end loop test
pytest tests/unit/test_plugin_artifacts.py -v     # artifact validity only
./scripts/smoke.sh                                # plumbing smoke in a throwaway repo
```

Note: `uv run …` may modify `uv.lock` as a side-effect — `git checkout uv.lock` before committing.

## Release flow

`release-please` drives releases. Merging conventional-commit PRs to `main` updates a rolling
**Release PR**; merging that tags `v<semver>` and fires `publish.yml` → PyPI (trusted publishing).
Versioning is **matched-pair**: `pyproject.toml` and `.claude-plugin/plugin.json` bump together, and
the plugin pins `sindri-forge==<own version>`.

Marketplace distribution is via `anthropics/claude-plugins-community` — a **read-only mirror** whose
pinned SHA is auto-bumped by Anthropic's **nightly catalog sync** (not PR-based; direct PRs are
auto-closed). A release reaches marketplace users only after that next nightly sync.

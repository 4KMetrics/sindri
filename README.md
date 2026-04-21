# sindri

A Claude Code plugin for bounded, target-driven optimization loops.

> In the myth, Sindri is the dwarf smith who forged Mjölnir by iterating under adversity — each hammer-strike tested, kept only if it survived. This plugin is the same pattern: make a change, benchmark it, keep it if it's better, revert otherwise, repeat until the target is hit or the pool of ideas is exhausted.

Inspired by [karpathy/autoresearch](https://github.com/karpathy/autoresearch) and [davebcn87/pi-autoresearch](https://github.com/davebcn87/pi-autoresearch), adapted to Claude Code.

**One commit per kept experiment. Git is the audit log. The forge runs one way.**

## Install

One command:

```bash
git clone https://github.com/4KMetrics/sindri.git ~/src/sindri
cd ~/src/sindri && ./scripts/install-plugin.sh
```

That script installs the `sindri` Python package into your active environment and symlinks the plugin into `~/.claude/plugins/sindri`. Restart Claude Code afterward. Verify: `/sindri status` should report "no active run" cleanly.

To target a specific Python (e.g. a venv), pass it via env var:

```bash
SINDRI_PYTHON=/path/to/venv/bin/python ./scripts/install-plugin.sh
```

Requirements:

- Python ≥ 3.10 (pydantic 2 is the only runtime dep; pyyaml is dev-only)
- `git` ≥ 2.30
- `gh` CLI (authenticated) — needed only for `sindri-finalize` PR creation
- Claude Code CLI with `Task` + `ScheduleWakeup` tools
- `uv` (optional, faster install) or `pip`

**First-run dogfood:** walk through [`docs/DOGFOOD.md`](docs/DOGFOOD.md) on a throwaway repo before pointing sindri at real code — it verifies every skill path and catches environment gaps before you commit an overnight run.

## Quickstart

```bash
# In the repo you want to optimize:
/sindri reduce bundle_bytes by 15%
```

Sindri will:

1. Scaffold `.claude/scripts/sindri/benchmark.py` if missing (interactive; asks you to describe the measurement in natural language).
2. Scan your repo and draft a pool of 10–30 candidates.
3. Ask you to approve / edit the pool.
4. Check out a new branch `sindri/reduce-bundle-bytes-15pct` and run the baseline 3×.
5. Loop autonomously — one experiment per wakeup, ~60s between them.
6. When the target hits (or the pool drains with ≥1 win), push the branch and open a PR.

Check in anytime with `/sindri status`. Halt with `/sindri stop`. Abandon with `/sindri clear`.

## Architecture

- **Python core** (`src/sindri/`) — pure functions: statistics, state file I/O, git wrappers, pool ordering, termination predicates, PR body rendering.
- **Skills** (`skills/sindri-*/SKILL.md`) — prose prompts for the decisions that need Claude's inference: scaffolding a benchmark, proposing a candidate pool, orchestrating the loop.
- **Subagent prompt** (`prompts/experiment-subagent.md`) — the contract every experiment subagent follows. Fresh context per experiment, no context bleed.

See [`docs/superpowers/specs/2026-04-19-sindri-design.md`](docs/superpowers/specs/2026-04-19-sindri-design.md) for the full design.

## Development

```bash
uv pip install -e ".[dev]"
pytest                                            # all test layers
pytest -m "not e2e" -q                            # skip the slow end-to-end loop test
pytest tests/unit/test_plugin_artifacts.py -v     # just artifact validity checks
./scripts/smoke.sh                                # plumbing smoke in a throwaway repo
```

## License

MIT

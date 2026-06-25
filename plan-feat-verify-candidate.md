# Plan — feat/verify-candidate (close the measurement seam)

## Problem
Sindri pulled *git authority* out of the LLM (commit-kept/reset-tree) but not *measurement authority*. The experiment subagent applies the change AND grades its own benchmark; `commit-kept` commits using the subagent's **self-reported** `metric_value`. The measurer and the optimizer are the same agent → self-certified keeps.

## Goal (Toyota: reliable, frictionless, always works)
A kept commit is **structurally impossible without an independent measurement**.
- **poka-yoke:** `commit-kept` refuses to create a keep commit without a passing verification recorded at the current HEAD.
- **jidoka:** any doubt (benchmark tampered, can't run, inconclusive, regressed) → revert, never keep.
- **frictionless:** no new user action; verify runs automatically with the run's reps_policy (remote = 1 rep, so a keep costs one extra run, reverts cost none).
- **deterministic:** the Python core re-runs the benchmark and decides — not the LLM.

## Design
1. **`core/verify.py`** (pure) — `decide_verification(independent_value, metric_before, direction, noise_floor, confidence_threshold)` → `{verified, status, delta, confidence_ratio}`. Mirrors the subagent's decision table; reuses `noise.confidence_ratio`.
2. **`verify-candidate` CLI verb** — given candidate_id + benchmark/checks paths + metric{name,direction} + metric_before + noise_floor + reps_policy + timeout:
   - **tamper gate:** if the benchmark/checks script is modified vs HEAD (`git diff --quiet HEAD -- <paths>`), or `.sindri/` is dirty → `verified=false, reason=benchmark_tampered`. (The instrument we measure with must be the committed, trusted one.)
   - re-run the benchmark N times against the working tree (candidate applied), `parse_metric_line`, compute mean + confidence, `decide_verification`.
   - append `JsonlEvent(event="verify", details={candidate_id, base_sha, verified, metric_value, status, confidence_ratio, reps_used, reason})`.
   - stdout JSON for the orchestrator.
3. **`commit-kept` enforcement** — on the **new-commit path only** (not the crash-recovery tiers a/b): require the latest `verify` event for this candidate_id to have `verified==true` AND `base_sha == HEAD`. Use the **verified** metric_value for `current_best` + the commit Δ (never the subagent's). Missing/false/stale → refuse (exit 1), no commit. Guarded emergency override `SINDRI_ALLOW_UNVERIFIED_KEEP=1` records a loud `verify_bypassed` event.
4. **Prose:** `sindri-loop/SKILL.md` new step 6b (verify before apply; reset on unverified); `experiment-subagent.md` measurement downgraded to advisory; `sindri-finalize` final re-validation of branch tip vs original baseline.

## Build order (TDD — test first, watch fail, minimal green)
- [x] `core/verify.py` (`decide_verification`) + `tests/unit/test_verify.py`
- [x] `verify-candidate` verb (advisory 6b) + `tests/integration/test_verify_candidate.py`
- [x] `commit-kept` gate + tests; `tests/unit/test_plugin_artifacts.py` += verify-candidate
- [x] `tests/e2e/test_loop_end_to_end.py` apply step
- [x] prose: SKILL.md (sindri-loop), experiment-subagent.md, sindri-finalize
- [x] full `pytest` (302 green) + ruff clean on changed files

## What the two adversarial reviews changed (important)
Round 1 found: TOCTOU (verify HEAD not tree), tier-b forgeable `kept:` subject, untracked benchmark, checks never executed. Round 2 found the deeper root: **the `verify` event is subagent-writable, so any event-trusting gate is forgeable** (proven repro: forged event → self-certified keep), plus forged `experiment` record (tier-a) and untracked-instrument/state gaming.

**Pivot (user chose "inline re-measure"):** `commit-kept` is now the SINGLE measurement authority — it re-runs the trusted benchmark **itself** at commit time (`_measure_candidate`) and trusts **no** jsonl event. The `verify` event is downgraded to an advisory 6b signal. This makes a forged event/record unable to land a keep by construction.
- Integrity gates in `_measure_candidate`: instrument tracked at HEAD, instrument + its dir unmodified vs HEAD, no untracked siblings in the instrument dir, checks re-run, reps policy-derived (not caller-shrinkable).
- tier-a honors an "improved" record only if a real `kept:` commit backs it; tier-b re-measures the committed tree.
- `commit-kept` payload carries `benchmark_cmd`/`checks_cmd`.

## Documented residuals (NOT closed in this scope — would need the "Full sandbox" option)
- Out-of-repo gaming: a benchmark importing code outside its dir, or reading a cache/env/network, isn't sandboxed. Fix: measure in an isolated worktree (HEAD + candidate diff).
- jsonl poisoning of non-keep state (counters/termination/finalize) via subagent writes to `.sindri/`. Fix: 6a-style `.sindri/` integrity snapshot in the orchestrator.
Both are flagged in `sindri-loop/SKILL.md` (§6b guarantee note) and tracked as the next phase.

## Invariants preserved
- jsonl-first ordering, idempotency tiers (a/b), single-writer lock, name-shell-safety, stdout-clean/stderr-diagnostics, exit-code conventions.
```

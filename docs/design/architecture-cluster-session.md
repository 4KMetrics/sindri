# Design session — the architecture cluster

A working agenda for deciding the five deferred architectural issues from the SRE review. These are
the ones that need design judgment, not just a fix — they're labeled
[`deferred:design-session`](https://github.com/4KMetrics/sindri/labels/deferred%3Adesign-session).

| # | Title | Severity |
|---|---|---|
| [#36](https://github.com/4KMetrics/sindri/issues/36) | Move git mutations into tested backend subcommands — **the seam** (keystone) | HIGH |
| [#29](https://github.com/4KMetrics/sindri/issues/29) | No single-writer lock — overlapping wakeups corrupt tree + state | HIGH |
| [#35](https://github.com/4KMetrics/sindri/issues/35) | Subagent git-safety is prompt-only — can force-push / clobber main | HIGH |
| [#31](https://github.com/4KMetrics/sindri/issues/31) | `pick-next` has no `in_progress` status — crash re-runs candidate | MED |
| [#37](https://github.com/4KMetrics/sindri/issues/37) | No structured run log — can't debug a failed overnight run | HIGH |

## The central tension

Today sindri is **thin-backend / thick-skill**: the tested Python core (`src/sindri/`) is pure and
injection-safe, but every *mutation* that matters — `git commit/reset/push`, the terminated record,
the experiment dispatch — runs as **LLM-authored Bash in `skills/sindri-loop/SKILL.md`**, bypassing
the backend. The tested `git_ops` wrappers (`commit_all_with_message`, `reset_hard_to_head`,
`push_with_upstream`) are **dead code** — present, tested, never called in production.

Every issue in this cluster is downstream of where that seam sits. **#36 is the keystone**: decide it
first, and #31/#37 largely fall out of it; #29 and #35 are semi-independent but interact.

## Goals / non-goals

**Goals:** decide, for each issue, *which* approach and *how it sequences*; produce an ADR + a TDD
implementation plan; update the issues. **Non-goals:** writing implementation code in the session;
re-litigating the already-shipped fixes; changing the user command surface.

## Pre-reads (≈20 min)

- The five issue threads above (each has the file:line findings + proposed fix).
- Key files: `skills/sindri-loop/SKILL.md` (the orchestrator — steps 1–10), `src/sindri/core/git_ops.py`
  (the dead wrappers), `src/sindri/core/state.py` (now atomic, post-#48), `src/sindri/cli.py`
  (subcommand dispatch), `prompts/experiment-subagent.md` (the subagent contract).
- Context already shipped that changes the calculus: state writes are now atomic + recover from
  `.bak` (#48), and `record-result` is jsonl-first (#28) — so the *persistence* layer is solid; the
  gap is the *orchestration* seam.

## Decisions to make

Each decision below lists options and a starting recommendation. The recommendation is a starting
point for discussion, **not** a foregone conclusion — these are architecture calls.

### D1 — Seam placement (#36) · keystone · ~30 min

How much moves from skill-Bash into tested backend subcommands?

- **A · Minimal.** Add subcommands wrapping the existing `git_ops`: `commit-kept --candidate-id`,
  `reset-tree`, `push-branch`, `record-terminated`. Skill calls these instead of raw Bash. Kills the
  dead code; makes mutations tested + injection-safe. Dispatch + counter-derivation stay in the skill.
- **B · Seam + coupled state transition** *(recommended)*. A, plus fold the keep/revert **state
  write into the same call** (`commit-kept` commits *and* marks the candidate `kept` + bumps
  `current_best`, returning the authoritative `commit_sha`). Shrinks the crash window that #31 exists
  for, and the SHA is captured by the backend, not scraped by the LLM.
- **C · Orchestration subcommand.** A `begin-wakeup` / `end-experiment` pair (or a `run-experiment`
  that does everything except the `Task` dispatch). Backend owns the wakeup lifecycle; the skill
  becomes a thin dispatcher. Best long-term home for #29/#31/#37 — but the largest redesign and risk.

**Unblocks:** #31 (D4), #37 (D5). **Decide:** A / B / C, and the exact subcommand list + signatures.

### D2 — Single-writer lock (#29) · ~15 min

A wakeup spans a long `Task` dispatch and *several* short-lived backend processes — so a held-`fd`
`flock` can't span it. The lock must be a **file that outlives any single process**.

- **A · `flock` per backend call.** Rejected for the cross-process reason above — doesn't span the wakeup.
- **B · PID + mtime sentinel** *(recommended)*. `.sindri/current/RUNNING` written at wakeup start
  (PID + timestamp), checked at the top of every wakeup; a second wakeup exits without rescheduling if
  the holder is alive. Stale-lock recovery via PID-liveness + a max-age. Cleared on normal termination
  and by the pre-flight reset.

**Decide:** sentinel semantics (liveness check, max-age, who clears it), and where it's acquired — a
standalone `acquire-lock`/`release-lock` subcommand vs folded into D1=C's `begin-wakeup`.

### D3 — Subagent git isolation (#35) · ~15 min

The experiment runs as `subagent_type="general-purpose"` with full Bash; nothing technically stops a
`git push --force` or a `checkout main`.

- **A · `git worktree` per experiment** *(recommended if appetite allows)*. Run the experiment in a
  throwaway worktree; benchmark + measure there; cherry-pick the kept change back. True blast-radius
  containment. Cost: ~200–500ms + disk per experiment, and the benchmark must tolerate the worktree
  path.
- **B · Restricted tool allowlist.** Dispatch the `Task` with a Bash allowlist excluding
  `push`/`checkout`/`reset`. Lighter, but depends on per-dispatch tool restriction being enforceable
  and granular enough.
- **C · Post-hoc verification** *(cheap stopgap)*. Keep current dispatch; after the subagent returns,
  assert `current_branch()` unchanged + no unexpected pushes (reflog) before committing; abort if
  tampered. Detects rather than prevents — can't undo a force-push.

**Decide:** A vs C now (B if tool-restriction proves reliable). Largely independent of D1.

### D4 — `in_progress` reconciliation (#31) · ~10 min

The trap (why a naive fix regresses): a `kept:` commit can exist in git HEAD even though state says
the candidate is `pending` (crash after commit, before `record-result`). Resetting `in_progress` →
`pending` then re-running produces a **duplicate** kept commit.

- **A · Status field + git reconciliation.** Add `in_progress` to the `Candidate` status literals; on
  wakeup start, reconcile a stale `in_progress` against git (`git log --grep "^kept: <candidate>"`):
  if the commit exists, recover the result; else reset to `pending`.
- **B · Falls out of D1=B/C.** If commit + state write are coupled (D1=B), the crash window is
  near-zero, so `in_progress` becomes a simple pick-time marker that's always safe to reset.

**Decide:** tie to D1. D1=B → mostly B; D1=A → need A's git reconciliation.

### D5 — Observability / run log (#37) · ~15 min

No structured log today; `SINDRI_FORGE_DEBUG` is only a `forge.sh` test hook. An operator finding a
dead 3am run has only the jsonl (backend events) + git log.

- **Recommendation:** add a `run_id` to `SindriState` (stamped onto every jsonl record for
  correlation); a real `--verbose` / `SINDRI_FORGE_DEBUG` that emits structured JSONL events to
  `.sindri/current/sindri.log`; backend subcommands (from D1) become the emit points for the
  currently-LLM-only steps (dispatch, terminated, git actions).

**Decide:** `run_id` placement, log format (JSONL vs human), retention. **Depends on:** D1.

## Dependency graph & sequence

```
D1 (seam) ──┬──▶ D4 (in_progress)
            └──▶ D5 (observability)
D2 (lock) ── semi-independent (placement aligns with D1=C)
D3 (isolation) ── independent of D1
```

**Decide in order:** D1 → (D2, D3 in parallel) → D4, D5. **Implement (post-session, TDD):**
1. Seam subcommands + reroute skill + tests (D1).
2. Lock sentinel (D2).
3. Subagent isolation (D3).
4. `in_progress` (D4).
5. Run log + `run_id` (D5).

## Intended outputs

- An **ADR** capturing the five decisions + rationale (here under `docs/design/`, or a
  `docs/superpowers/specs/` design doc).
- A **TDD implementation plan** (`plan-feat-*.md`) with the task breakdown above.
- **Issue updates:** record the chosen approach on each; likely **split #36** into one issue per
  subcommand so it's shippable incrementally.

## Logistics

Timebox ≈ 90 min: pre-read 20 · D1 30 · D2/D3/D4/D5 ~10–15 each · wrap 10. Keep code out of the room —
the output is decisions + a plan, then implementation lands as the usual TDD PRs.

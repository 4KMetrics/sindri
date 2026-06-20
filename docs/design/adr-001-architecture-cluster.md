# ADR-001 — Architecture cluster: orchestration seam, locking, isolation, recovery, observability

- **Status:** Accepted — design session 2026-06-19
- **Issues:** [#36](https://github.com/4KMetrics/sindri/issues/36) (keystone), [#29](https://github.com/4KMetrics/sindri/issues/29), [#35](https://github.com/4KMetrics/sindri/issues/35), [#31](https://github.com/4KMetrics/sindri/issues/31), [#37](https://github.com/4KMetrics/sindri/issues/37)
- **Supersedes the open questions in:** [`docs/design/architecture-cluster-session.md`](architecture-cluster-session.md)

## Context

sindri is **thin-backend / thick-skill**: the Python core (`src/sindri/`) is pure, tested, and
injection-safe, but every *mutation* that matters — `git commit/reset/push`, the terminated record,
the experiment dispatch — runs as **LLM-authored Bash in `skills/sindri-loop/SKILL.md`**, bypassing
the backend. The tested `git_ops` wrappers (`commit_all_with_message`, `reset_hard_to_head`,
`push_with_upstream`) are **dead code**: present, tested, never called in production.

Prior fixes changed the calculus: state writes are now atomic + recover from `.bak` (#48) and
`record-result` is jsonl-first (#28). So the *persistence layer* is solid; the gap is the
*orchestration seam*. These five decisions were taken in a facilitated session backed by a workflow of
per-decision analyses, each adversarially stress-tested. The adversarial pass overturned three of the
analysis's initial recommendations and caught a latent double-count bug — both reflected below.

## Decisions

### D1 — Seam placement (#36) · **B: seam + coupled keep/revert state transition**

Move the git mutations into tested backend subcommands —
`commit-kept`, `reset-tree`, `push-branch`, `record-terminated` — and have **`commit-kept` commit AND
write the pool status + `current_best` + jsonl in one backend process**, capturing the commit SHA
in-process rather than scraping it through the LLM. This relocates the already-tested `record-result`
machinery one layer inward; it is **not** a new design.

**Consequences / rules:**
- A shared `_record()` helper backs `commit-kept` and `reset-tree` so the **jsonl-first ordering**
  (`cli.py:279-280`) lives in exactly one place and can't silently rot.
- `pool_status_map` split: `improved → commit-kept`, everything else → `reset-tree`. A miswire silently
  keeps a regression or reverts an improvement.
- `record-terminated` is **in scope** — the finalize-gating terminate record stops being LLM-built shell.
- **Honest framing (must not be oversold):** a git ref update and a Python file write can never be
  mutually atomic, so B **narrows the #31 crash window to milliseconds but does not close it.** D4's
  guard stays.
- Counter-derivation (`experiments_run`, `consecutive_reverts`) does **not** move in this PR — it ships
  as **its own follow-up PR after the D5 run-log lands** (roadmap step 5's tail), so the seam's blast
  radius stays bounded.

### D2 — Single-writer lock (#29) · **B: standalone `RUNNING` sentinel, shipped now**

`flock` is unusable: a wakeup spans ~5 separate `uvx` processes plus a long `Task` dispatch, so no
held fd spans it. Use a sentinel file `.sindri/current/RUNNING` holding `{pid, host, started_at,
token}` written via the atomic writer, with dedicated `acquire-lock` / `release-lock` subcommands.
Ship it **independent of D1** — it is the highest-severity corruption bug in the cluster and is
shippable today; do not hold it hostage to any larger redesign.

**Implementation correction (discovered while building — supersedes the session-doc liveness
design): liveness is AGE-based, not PID-based.** The process that writes `RUNNING` (`acquire-lock`)
is an ephemeral `uvx` process that **exits immediately**, so its pid is dead by the time the next
wakeup checks — an `os.kill(pid, 0)` probe would mark *every* lock stale and give zero protection.
`pid`/`host` are therefore recorded as forensic metadata only.

**Consequences / rules (as built — `src/sindri/core/lock.py`):**
- **Liveness = age only:** a holder is live while `RUNNING` is younger than
  `STALE_AGE_MULTIPLIER × guardrails.timeout_per_experiment_seconds` (`validators.py:111`; multiplier
  = 2, the longest a legit wakeup can hold the lock) — no new magic constant.
- **Release is token-scoped:** `acquire-lock` returns a `token`; the orchestrator threads it to
  `release-lock --token`, which removes `RUNNING` only on a token match — so a wakeup can never release
  another's lock.
- **Acquire AFTER the HALT check** so `/sindri:stop` can always terminate a wedged-holder run.
  Non-negotiable.
- **Release on every exit path** (structural terminate, record-result-failure halt, a thrown/timed-out
  experiment `Task`, normal end), with the age fallback as the safety net for a missed release. (The
  HALT terminate path returns *before* the acquire, so it never holds the lock.)
- **Single-winner via flock (better than the session-doc's claim-then-verify):** the acquire/release
  *decision* is serialized by a short-lived `flock` on a sidecar file (`.RUNNING.acquire`). flock can't
  span the wakeup (the original reason it was rejected for the wakeup lock), but it cleanly serializes
  the brief read-decide-write of one `acquire-lock` process against another — so the sentinel write is
  a **true single-winner** with no TOCTOU / no compare-and-swap gymnastics. The wakeup-level overlap is
  still *contained* (a second wakeup that finds a live holder backs off), not OS-level prevented.
- **Exit-code contract:** `acquire-lock` exits **0** (acquired), **1** (held by a live holder → back
  off **without** rescheduling), or **2** (error, e.g. no active run → surface and halt; must NOT be
  treated as a silent backoff, or a transient state-read error would kill the loop). The orchestrator
  branches on all three.
- **Clock caveat:** liveness is wall-clock age, so it assumes a single host with a roughly stable
  clock. A backward NTP step is handled (negative age ⇒ recent ⇒ live); a large *forward* jump could
  prematurely age out a live holder — the 2× margin makes that unlikely.
- **Also prevent, not just contain:** when `acquire-lock` reports a live holder, the orchestrator
  backs off **without** calling `ScheduleWakeup` (the holder schedules the next tick).
- **Correction to the session doc:** its claim that the pre-flight `git reset` clears `RUNNING` is
  **false** — `.sindri/current/` is gitignored, so reset never touches it. Stale recovery is the age
  fallback + explicit release only.

### D3 — Subagent git isolation (#35) · **C: post-hoc verification, shipped now; A (worktree) deferred**

The threat model is an **LLM mistake**, not a hostile actor. Before the orchestrator's commit/reset
step, assert `current_branch()` is the sindri branch and `HEAD` is the expected SHA; halt without
committing if either is off. Ships as honest skill-Bash, independent of D1/D2.

**Consequences / rules:**
- **Placement:** the assertion runs **before** the step-7 git action — after-the-keep is too late
  (a stray `git checkout main` would make the orchestrator commit on the wrong branch first).
- **Do not** make C a backend subcommand — that smuggles in D1 and breaks the "ship in an afternoon,
  independent" premise. Skill-Bash is the right altitude.
- **Limit:** C is detection, not prevention — it cannot undo a `git push --force` to origin. Detecting
  an unexpected *push* needs an `ls-remote` before/after (a network round-trip per experiment in remote
  mode). Accepted for now; D1=B + D2 close most of the realistic blast radius.
- **Option B (Bash allowlist) rejected:** unenforceable — the subagent needs open Bash, and a denied
  verb is reachable via `sh -c` / `$(...)` / the benchmark script; no `allowed_tools` mechanism exists
  in the repo.
- **A (worktree) is deferred, appetite-gated:** worktrees don't copy untracked `.venv`/`node_modules`,
  so dependency-swap candidates may not run without a per-worktree install step (the ~200-500ms
  estimate ignores this). Revisit only if an adversarial force-push to origin is judged the dominant
  residual risk after D1+D2 ship — and resolve the toolchain-reconstruction problem empirically first.

### D4 — `in_progress` reconciliation (#31) · **pick-time marker + jsonl-keyed entry-guard**

Given D1=B, this largely falls out. A lightweight `in_progress` marker is set at pick time and is
always safe to reset (D2's lock excludes a concurrent re-pick). `commit-kept` is made **idempotent on
entry**, keyed on *"does a `type==experiment` record with this candidate id already exist?"* — checked
**before both the commit and the jsonl append.**

**Consequences / rules:**
- **The key is the JsonlExperiment record by candidate id** (a stable int, `validators.py:50`) — **not**
  `git log --grep`. Keying on git double-counts in the append-then-write window that `cli.py:279-280`
  exists to protect (this was the latent bug the adversarial pass caught in the obvious approaches).
- If `git log` is consulted at all, it is only to confirm the commit physically landed, anchored
  exact-subject with `--fixed-strings` (names allow dots/parens/dashes/colons/%).
- **Unrecoverable on a crashed keep:** `metric_after` / `delta` / `confidence_ratio` were lost with the
  crashed subagent. `delta` is parseable from the commit subject (`Δ…`); the rest are unknown. Decision:
  mark the recovered record **partial/recovered** and leave the unknown metrics null — do **not**
  synthesize fake metric values into the audit log.
- A durable `in_progress` *status literal* (touching every `status==` site) is **not** taken — it's only
  required if D1 had stayed A.

### D5 — Structured run log (#37) · **A: single stream + `run_id`**

Add `run_id` to `SindriState`, threaded into `_JsonlBase`. Emit the currently-invisible orchestration
events (`candidate_dispatched`, `git_action`+sha, `schedule_wakeup`, `halt_consumed`,
`preflight_reset`, plus D2's `lock_acquired`/`lock_stale_recovered`/`wakeup_skipped_holder_alive` and
D4's `in_progress_set`/`in_progress_reconciled`) as the **already-defined-but-dead `JsonlEvent`** type
into the **same `sindri.jsonl`**.

**Consequences / rules:**
- `render_pr_body` selects records by `isinstance(JsonlExperiment/JsonlTerminated)`, so `JsonlEvent`
  records are **structurally invisible to PRs** yet first-class to `jq`/`grep`. No second file, no second
  durability-critical write path. (The two-stream option's justification — "debug events pollute the
  PR" — was a misread; rejected.)
- **Verbosity gates at emission** via a **new `SINDRI_FORGE_VERBOSE`** flag — `SINDRI_FORGE_DEBUG` is a
  test-pinned `forge.sh` early-exit hook (`test_forge_wrapper.py:37,43`) and cannot carry runtime
  verbosity.
- **Two high-value fixes ride along (both depend on D1):** route `JsonlTerminated` through the
  `record-terminated` subcommand (today it's LLM-hand-built JSON via Bash — the least-validated record
  in the file); and **add the missing tz validator to `_JsonlBase.ts`** (`validators.py:175`) — a naive
  `ts` currently passes and silently corrupts wall-clock post-mortem math.
- `JsonlEvent`'s schema (`type/event/reason/details`, all str) may want a small `details`-dict extension
  for `commit_sha`/timing/exit-codes. Retention is a non-question: it archives with the run and is capped
  by `max_experiments=50`.

## Implementation roadmap (TDD, sequenced)

Decide-order was D1→D5; **ship-order** maximizes independent value and respects dependencies. #36 is
**split per subcommand** so it lands incrementally.

1. **D2 — `RUNNING` sentinel** (independent, highest severity). `acquire-lock`/`release-lock`
   subcommands + atomic `O_EXCL` claim; skill acquires after HALT, releases on all exits; refuse
   reschedule if holder live. Tests: overlap is contained, stale recovery by PID/age, HALT still wins,
   **and `ScheduleWakeup` is refused when a live PID+host holder exists** (the prevent path, distinct
   from contain).
2. **D3 — post-hoc verify** (independent, ~afternoon). Branch+SHA assertion before step 7; halt on
   mismatch. Tests: stray checkout/reset is caught before any commit.
3. **D1 — seam, per subcommand** (keystone): `record-terminated` → `reset-tree` → `commit-kept`
   (coupled state via shared `_record()`) → `push-branch`. Reroute the skill cell-by-cell; delete the
   dead `git_ops`-bypassing Bash. Tests: each subcommand; pool_status_map split; jsonl-first preserved.
4. **D4 — in_progress marker + entry-guard** (needs D1=B's `commit-kept`). Tests: crashed-keep recovery
   produces no duplicate commit and no miscount; recovery record marked partial.
5. **D5 — run log + run_id** (needs D1's subcommands as emit points). `run_id` on state + `_JsonlBase`;
   `JsonlEvent` emission behind `SINDRI_FORGE_VERBOSE`; tz validator on `_JsonlBase.ts`. **Decide
   `JsonlEvent.details` up front** — it is `str | None` today (`validators.py:216`), but events must
   carry `commit_sha`/timing/exit-codes, so extend it to a small typed dict in this PR rather than
   shipping the stringly-typed schema by default. Then, as a separate follow-up PR, the
   counter-derivation move out of the skill.

**Deferred:** D3-A (worktree isolation) — appetite-gated, revisit after D1+D2.

## Cross-cutting honesty (carry into every PR description)

- D1=B **narrows, does not close**, the #31 window. D4's guard is load-bearing, not optional.
- D2's sentinel **contains overlap; it does not truly serialize** (no CAS). Acceptable at 60s spacing.
- The pre-flight `git reset` does **not** clear `RUNNING` (gitignored). Recovery is PID/age only.
- D3-C is **detection, not prevention** — it cannot undo a force-push to origin.

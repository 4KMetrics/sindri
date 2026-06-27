---
name: sindri-loop
description: The sindri orchestrator. Runs one experiment per invocation. Reads state, checks the HALT sentinel and termination predicates, picks next candidate, dispatches an experiment subagent via the Task tool, acts on the result (commit or reset), records to state, and schedules the next wakeup — unless terminated. Invoked automatically via ScheduleWakeup during an active run. A single manual tick is available via /sindri:loop (advanced/debug); otherwise do not invoke directly.
tools: Bash, Read, Edit, Task
---

# sindri-loop — per-wakeup orchestrator

You run **once per wakeup**. One invocation = one experiment end-to-end. You are deliberately thin: every deterministic step goes through the backend wrapper `"$FORGE" <cmd>` (resolve `FORGE` to this plugin's `scripts/forge.sh` — the skill lives at `<plugin-root>/skills/sindri-loop/SKILL.md`, so the wrapper is `<plugin-root>/scripts/forge.sh`), every reasoning step goes to a fresh subagent via `Task`. Your own context stays tiny so autocompaction is a non-issue.

**Invariant: every wakeup is identical in structure.** No state persists in your head — it all lives on disk.

## Steps (strict order, no skipping)

### 1. Read state

```bash
"$FORGE" read-state
```

Parse the JSON. It includes: `pool`, `baseline`, `current_best`, `branch`, `mode`, `guardrails`, `started_at`.

### 2. Termination check

Before anything else, check for the user-halt sentinel:

```bash
if [ -f .sindri/current/HALT ]; then
  # User invoked /sindri:stop. Terminate with reason halted_by_user.
  # auto_finalize is true iff at least one kept commit exists.
fi
```

If the sentinel exists:

1. Count kept commits on the branch (`git log --oneline --grep "^kept:" | wc -l`).
2. Append the terminated record via the backend (which derives the metric/count fields from state and validates the schema — never hand-build this JSON):

   ```bash
   "$FORGE" record-terminated --reason halted_by_user --auto-finalize <true|false>   # true iff kept > 0
   ```
3. If `kept > 0`, invoke `sindri-finalize`; otherwise announce to chat and stop.
4. `rm .sindri/current/HALT` (clean up after consuming).
5. **Do NOT call `ScheduleWakeup`.** Return.

### 2a. Acquire the single-writer lock

A slow experiment `Task` can still be running when the next wakeup fires, putting two orchestrators on one git tree. Claim the lock now — **after** the HALT check above (so `/sindri:stop` can always halt even a wedged run), before any other work:

```bash
LOCK_JSON=$("$FORGE" acquire-lock)
LOCK_RC=$?
```

Branch on the exit code — they mean different things:

- **`LOCK_RC == 1` (held):** a live wakeup already holds the lock. **Announce** *"sindri: another wakeup is active — backing off."* and **return immediately. Do NOT call `ScheduleWakeup`** — the active holder will schedule the next tick.
- **`LOCK_RC >= 2` (error, e.g. no active run / unreadable state):** this is **not** a normal backoff. Surface the stderr and **halt** — do not back off silently and do not `ScheduleWakeup`. (Treat like a `record-result` failure.)
- **`LOCK_RC == 0` (acquired):** capture the token and hold it for the rest of the wakeup:

```bash
TOKEN=$(printf '%s' "$LOCK_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['token'])")
```

Once acquired, you **must** run `"$FORGE" release-lock --token "$TOKEN"` on **every** way this wakeup can end — a structural/terminate halt, a `record-result` failure, a thrown/timed-out experiment `Task`, **and any other abnormal exit**, as well as the normal end-of-wakeup just before `ScheduleWakeup`. (A missed release is reclaimed only after the age fallback, blocking the next wakeup or two — so always release explicitly.)

Otherwise, compute counters from state + jsonl:

- `experiments_run`: count of `type == "experiment"` records in `sindri.jsonl`.
- `consecutive_reverts`: starting from the tail of `sindri.jsonl`, count experiments with `status in {"regressed", "inconclusive", "check_failed", "errored", "timeout"}` until you hit a `status == "improved"` or run out. (`check_failed` is a non-improvement like the rest — a pool that systematically fails its checks must trip `max_reverts_in_a_row` rather than burning the whole pool.)

Pipe these to `check-termination` on stdin:

```bash
echo '{"experiments_run": <N>, "consecutive_reverts": <K>}' | "$FORGE" check-termination
```

Returns JSON: `{"terminated": bool, "reason": str | null, "auto_finalize": bool}`.

If `terminated`:

1. Append the terminated record via the backend, passing the `reason` and `auto_finalize` from `check-termination`'s output (the metric/count fields are derived from state and validated by the backend):

   ```bash
   "$FORGE" record-terminated --reason "<reason>" --auto-finalize "<auto_finalize>"
   ```
2. If `auto_finalize` is `true` AND `kept >= 1`, invoke skill `sindri-finalize`.
3. Otherwise print a human-readable summary:
   - `reason == "pool_empty"` + kept == 0 → *"sindri: terminated (pool exhausted). 0 kept experiments out of <N> tried. No PR created. See `.sindri/current/`."*
   - Structural halts (`max_reverts_in_a_row`, `max_experiments`) → surface the halt reason and tell the user: *"State preserved in `.sindri/current/`. Fix the underlying issue and re-run `/sindri:forge`, or `/sindri:clear` to abandon."*
4. `"$FORGE" release-lock --token "$TOKEN"` (the lock you acquired in step 2a).
5. **Do NOT call ScheduleWakeup.** The loop ends here.
6. Return.

### 3. Pre-flight git check

```bash
git status --porcelain
```

If output is non-empty (dirty tree from a previous interrupted experiment):

```bash
git reset --hard HEAD
```

This is a belt-and-suspenders recovery — kept commits survive (they're in HEAD); only unstaged/uncommitted changes are discarded.

Now record the git state you are handing to the experiment — the subagent must only touch the **working tree**, never move `HEAD` or switch branches. Step 6a verifies this before any commit/reset:

```bash
EXPECTED_BRANCH="<state.branch>"   # e.g. sindri/reduce-bundle-bytes-15pct
EXPECTED_SHA=$(git rev-parse HEAD)
```

### 4. Pick next candidate

```bash
"$FORGE" pick-next
```

Returns JSON describing the next candidate: `{"id": int, "name": str, "expected_impact_pct": float, "status": "pending", "files": [...], "notes": null}`. If `null`, re-run step 2 — state should already have told you the pool is empty, so this path is defensive.

### 5. Dispatch the experiment subagent

Load the template at `prompts/experiment-subagent.md` (relative to the plugin install path). Fill in the placeholders from the candidate + state:

- `$CANDIDATE` — the candidate JSON from step 4.
- `$BENCHMARK_CMD` — `.claude/scripts/sindri/benchmark.py` (or whatever the benchmark path is in state).
- `$CHECKS_CMD` — `.claude/scripts/sindri/checks.py` or empty if missing.
- `$METRIC` — `{"name": ..., "direction": ...}` from state.
- `$CURRENT_BEST` — state.current_best if non-null, else state.baseline.value.
- `$NOISE_FLOOR` — from state.baseline.
- `$MODE` — `"local"` or `"remote"`.
- `$REPS_POLICY` — from state.guardrails.reps_policy.
- `$TIMEOUT_SECONDS` — from state.guardrails.timeout_per_experiment_seconds.

Mark the candidate in-flight in the run log (so a crash mid-experiment is visible, and the `run_id` correlates it to this run):

```bash
"$FORGE" log-event --event candidate_dispatched --details "{\"candidate_id\": <id>, \"name\": \"<candidate name>\"}"
```

Snapshot the run's protected state **after** that log-event and **before** handing control to the (untrusted) subagent. The expected value lives here in the orchestrator's tick context — the subagent can't forge it. Re-checked in step 6a:

```bash
EXPECTED_STATE_DIGEST=$("$FORGE" state-digest)
```

Invoke via `Task` tool:

```
Task(
  subagent_type="general-purpose",
  description="sindri experiment: <candidate name>",
  prompt=<filled template>
)
```

### 6. Parse the subagent result

The subagent returns JSON on stdout matching `src/sindri/core/validators.py::SubagentResult`:

```json
{
  "metric_value": 719218,
  "reps_used": 3,
  "confidence_ratio": 4.2,
  "status": "improved",
  "files_modified": ["package.json", "..."],
  "notes": "..."
}
```

If the subagent's output doesn't parse as JSON or fails schema validation, treat it as `status: errored` (synthesize a minimal SubagentResult with `status: "errored"`, `metric_value: 0`, etc.) and continue with the revert path.

### 6a. Verify the subagent didn't touch git

The experiment subagent runs with full Bash and is *instructed* not to commit, push, checkout, or reset — but nothing enforces it. **Before any git action in step 7**, confirm it only touched the working tree:

```bash
ACTUAL_BRANCH=$(git rev-parse --abbrev-ref HEAD)
ACTUAL_SHA=$(git rev-parse HEAD)
```

If `ACTUAL_BRANCH != EXPECTED_BRANCH` **or** `ACTUAL_SHA != EXPECTED_SHA`, the subagent moved `HEAD` or switched branches. **Do NOT run step 7's commit/reset** — committing or `git reset --hard` now would land on the wrong branch or over the wrong base, compounding the damage. Instead:

1. `git checkout "$EXPECTED_BRANCH"` to restore the local run branch (best-effort).
2. `"$FORGE" release-lock --token "$TOKEN"`.
3. Surface to the user: *"sindri: aborting this tick — the experiment subagent altered git state (branch/HEAD changed unexpectedly). No commit made; state preserved in `.sindri/current/`. Investigate before resuming."*
4. **Do NOT `ScheduleWakeup`.** Return.

This is **detection, not prevention**: it catches the realistic accident (a stray `checkout`/`reset`/local commit). It cannot detect or undo a `git push --force` to the remote — `HEAD` is unchanged in that case (detecting a remote clobber would need a `git ls-remote` snapshot before and after, a network round-trip per experiment, deliberately out of scope here).

### 6a-bis. Verify the subagent didn't touch `.sindri/` state

The subagent can also write the run's state files directly (it has Bash) — forging `experiment`/`verify`/`terminated` records to poison the counters, the termination predicates, or the finalize accounting. Compare the snapshot from step 5 (the `.sindri` twin of the git check above):

```bash
if [ "$("$FORGE" state-digest)" != "$EXPECTED_STATE_DIGEST" ]; then
  # The subagent wrote .sindri/current/ — abort the tick (jidoka).
  "$FORGE" release-lock --token "$TOKEN"
  # Surface: "sindri: aborting this tick — the experiment subagent altered .sindri/
  #   state (jsonl/md changed unexpectedly). No commit made; state preserved in
  #   .sindri/current/. Investigate before resuming."
  # Do NOT ScheduleWakeup. Return.
fi
```

The keep path is *already* safe without this (`commit-kept` re-measures and trusts no record); this guard protects the **non-keep** state — `experiments_run`, `consecutive_reverts`, the termination predicates, and the finalize summary — from a subagent that forges jsonl lines. The expected digest lives only in the orchestrator's tick context, so it can't be forged on disk.

### 6b. Independent verification — the measurement seam (only when the subagent claims `improved`)

The subagent both *applies* the change and *grades its own benchmark*. Never keep on that self-report. Re-measure with the backend, which runs the **trusted (committed) benchmark** itself and decides independently. This is the measurement twin of the git seam in 6a: the agent that proposes a win does not certify it.

Only a claimed `improved` needs this (a revert discards regardless):

```bash
if [ "<status from step 6>" = "improved" ]; then
  VERIFY=$(echo '{"candidate_id": <id>, "benchmark_cmd": "<benchmark path>", "checks_cmd": "<checks path or omit>"}' | "$FORGE" verify-candidate)
  VERIFIED=$(printf '%s' "$VERIFY" | python3 -c "import json,sys; print(json.load(sys.stdin)['verified'])")
  VSTATUS=$(printf '%s' "$VERIFY" | python3 -c "import json,sys; print(json.load(sys.stdin)['status'])")
fi
```

`verify-candidate` re-runs the benchmark `reps` times (remote mode = 1) and refuses if the instrument isn't trustworthy. It appends an **advisory** `verify` event used *only* for this keep-vs-reset decision — it is **not** a trust anchor (it returns `verified` plus an independently-measured `metric_value`; `commit-kept` re-measures authoritatively in step 7, so a forged event can't make a keep land).

- **`VERIFIED == True`** → go to step 7 and `commit-kept` (which re-measures and commits the independent number).
- **`VERIFIED == False`** (didn't reproduce, within noise, tampered, untracked, or errored) → **do not keep (jidoka — stop the line).** Substitute `VSTATUS` (e.g. `inconclusive`/`regressed`/`errored`) into the SubagentResult and take the `reset-tree` path in step 7. The disagreement is preserved in the jsonl.

> **What the seam guarantees (and what it does not).** `commit-kept` is the single **measurement authority**: on a new keep it re-runs the *trusted (tracked, unmodified)* benchmark itself and commits *its own* measured number — it trusts no subagent-writable record (a forged `verify`/`experiment` jsonl line cannot make it commit; tier-a recovery additionally requires a real kept commit). The benchmark/checks must be **tracked and unmodified vs `HEAD`** (instrument directory + no untracked siblings), `checks` are re-run, and the measurement runs in an **isolated git worktree** checked out from the candidate's staged tracked tree — so untracked / gitignored cruft in the live working dir (a planted cache file, `.sindri` state, stray cwd files) cannot influence the metric, and the main tree/branch is never touched. Gitignored top-level dependency dirs (`node_modules`, `.venv`, …) are symlinked in so build-based benchmarks still run.
>
> Non-keep state (counters, termination, finalize) is guarded separately by the **step 6a-bis `.sindri/` integrity snapshot** — a subagent that forges jsonl records aborts the tick. Remaining residuals (v1): code the candidate legitimately edits is necessarily measured (inherent — that's the optimization); a benchmark reading **out-of-repo** state via an absolute path / env / network is not sandboxed; and a benchmark that *writes* into a symlinked gitignored dep/build dir touches the live copy. Next hardening: OS-level network/filesystem confinement of the benchmark process (environment-level — run sindri in a sandbox/container).

### 7. Apply the result (commit or revert) and record it

`metric_before` is `state.current_best` if set, else `state.baseline.value`. Compose the RecordPayload from this experiment:

```json
{
  "candidate_id": <int, from step 4>,
  "metric_before": <float, from state.current_best or state.baseline.value>,
  "subagent_result": <subagent JSON verbatim from step 6>,
  "benchmark_cmd": "<benchmark path>",
  "checks_cmd": "<checks path or omit>"
}
```

`commit-kept` needs `benchmark_cmd` (and optional `checks_cmd`) so it can re-measure inline; `reset-tree` ignores them.

Pipe it to the backend subcommand for the result class — the subcommand does the git action **and** the pool-status + `current_best` + jsonl write in one validated, crash-safe call. **You no longer run `git commit` / `git reset` yourself** (that's exactly the LLM-authored git the seam removed):

```bash
# improved AND verified (6b) → commit-kept  (git-commits the kept change, records
#                 kept, bumps current_best to the VERIFIED value, captures the SHA)
# anything else / unverified → reset-tree   (git reset --hard HEAD, records the
#                 revert/dead-end under the verified status)
if [ "<status from step 6>" = "improved" ] && [ "$VERIFIED" = "True" ]; then
  echo "$PAYLOAD" | "$FORGE" commit-kept
else
  echo "$PAYLOAD" | "$FORGE" reset-tree   # PAYLOAD carries VSTATUS for an unverified "improved"
fi
```

`commit-kept` is the authority: it **re-runs the trusted benchmark itself** and refuses the keep unless *its own* re-measurement verifies the improvement — committing the independently-measured number, never the subagent's. It trusts no recorded `verify` event (those are subagent-writable), so even a forged event or a buggy orchestrator can't land a self-certified keep. (Emergency-only override: `SINDRI_ALLOW_UNVERIFIED_KEEP=1`, which records a loud `verify_bypassed` event.)

The pool-status mapping is handled inside the subcommand: `improved → kept`, `regressed`/`inconclusive → reverted`, `check_failed → check_failed`, `errored`/`timeout → errored`. Both subcommands are **idempotent on a crash re-run** (they skip a candidate already recorded and never double-commit) and keep the jsonl-first ordering internally. If `commit-kept` finds the subagent claimed `improved` but left no net change, it records `errored` — no phantom keep.

If the subcommand exits non-zero, run `"$FORGE" release-lock --token "$TOKEN"`, surface the stderr, and halt — writing state is the one operation that must never silently fail. (Do **not** call `ScheduleWakeup`.)

### 9. Structural halt check

Re-compute `experiments_run` and `consecutive_reverts` (now including this experiment) and re-pipe them into `check-termination`:

```bash
echo '{"experiments_run": <N+1>, "consecutive_reverts": <updated K>}' | "$FORGE" check-termination
```

Structural halts may now fire:

- `max_reverts_in_a_row` hit → halt.
- `max_experiments` exceeded → halt with reason `max_experiments`.
- `target_hit` reached (current_best beats target) → halt + `auto_finalize: true`.

If `terminated`: jump back to step 2's handling (surface → no wakeup).

### 10. Schedule the next wakeup

First release the lock you've held since step 2a, then schedule the next tick (in that order, so the next wakeup can acquire):

```bash
"$FORGE" release-lock --token "$TOKEN"
```

```
ScheduleWakeup(
  delay=60,
  prompt="Resume sindri-loop orchestrator. Read state from .sindri/current/ and run one wakeup cycle."
)
```

`ScheduleWakeup` runs only on this autonomous path. A manual `/sindri:loop` tick runs steps 1–9 and **stops before this step**, so it never creates a wakeup competing with the already-pending auto-loop.

Return. You are done. The next wakeup starts fresh at step 1.

## Anti-patterns

- **Never modify files in the repo directly** outside of git commit/reset. The subagent applies the candidate; you only keep or discard.
- **Never maintain state in your own prompt context.** Every wakeup starts by reading disk.
- **Never skip the pre-flight git check** — a dirty tree from an interrupted run poisons the next experiment.
- **Never finalize unless `auto_finalize: true`.** Some terminations (e.g., `halted_by_user` with 0 kept) should not produce a PR.
- **Never call `ScheduleWakeup` on terminated runs.** That's a bug; the loop must end.
- **Never retry `check_failed`.** Tests are deterministic; retrying is theater.
- **Never proceed without the run lock, and never `ScheduleWakeup` when you couldn't acquire it.** A failed `acquire-lock` means another wakeup owns this tick — back off silently.
- **Never commit or reset when the step-6a tamper check fails.** If the subagent moved `HEAD` or switched branches, acting in step 7 lands the orchestrator on the wrong branch — abort the tick instead.
- **Never keep on the subagent's self-reported metric.** A claimed `improved` is committed only after `verify-candidate` (6b) independently confirms it; an unverified claim is reset, not kept. The subagent measures for its *own* decision, but the committed number is one it did not produce.

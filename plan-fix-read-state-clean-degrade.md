# Plan: `read-state` degrades cleanly (no active run) — full `status` parity

## Context

`"$FORGE" read-state` is the backend's "emit current run state as JSON" subcommand. Today, when
there's no active run (`.sindri/current/` absent), it routes through the `_load_state_or_exit()`
helper, which prints a developer-ugly `error: state file not found: .sindri/current/sindri.md` to
**stderr** and exits **1**. No traceback — but the message reads like a bug, not a state.

Its sibling `status` already handles this case gracefully: it catches `StateIOError`, prints the
human-friendly `sindri: no active run (.sindri/current/ not found)` to **stdout**, and exits **0**.

This was flagged as an out-of-scope follow-up at the tail of the command-split plan (PR #20). The
fix: make `read-state` mirror `status` exactly. **User decision (this session): full status parity —
friendly line on stdout, exit 0.** So `read-state` and `status` give byte-identical no-active-run
output. (`status` is the only other handler that takes this friendly path; the remaining
state-loading handlers — `pick-next`, `record-result`, `check-termination`, `generate-pr-body`,
`archive` — are machine-only mid-run commands where exit 1 = "no JSON, don't parse" is correct, and
stay as-is. Deliberately out of scope.)

Why this is safe: the only machine consumer of `read-state` is `skills/sindri-loop/SKILL.md` step 1,
which is reached only *during* an active run (the auto-loop runs mid-run; manual `/sindri:loop`
pre-flight-guards on `.sindri/current/` existing first). `scripts/smoke.sh` runs `init` before
`read-state`, so it always has state. No real caller parses `read-state` stdout with no active run.

## Scope

**In:** `src/sindri/cli.py` `_handle_read_state` (3-line behavior change); the one existing test that
asserts the old exit-1 behavior. **Also in (cheap, strengthens the shared contract):** add the
missing no-active-run test for `status` so both commands have explicit coverage of the parity they
now share. **Out:** the other `_load_state_or_exit()` handlers; the helper itself (still used by the
exit-1 commands); `scripts/forge.sh`; any skill/command/doc (no user-facing surface changes).

## Change

### `src/sindri/cli.py` — `_handle_read_state` (currently lines ~166–172)

Replace the `_load_state_or_exit()` path with the same `try/except StateIOError` pattern `status`
already uses (lines ~385–392). Reuse the **exact** message string `status` prints so the two stay
byte-identical:

```python
@_register("read-state")
def _handle_read_state(args: argparse.Namespace) -> int:
    from sindri.core.state import StateIOError, read_state

    try:
        state = read_state()
    except StateIOError:
        print("sindri: no active run (.sindri/current/ not found)")
        return 0
    print(state.model_dump_json())
    return 0
```

Reuse, don't re-author: this is a copy of `status`'s no-state guard (`src/sindri/cli.py:388–392`),
swapping the success body for `read-state`'s existing `print(state.model_dump_json())`. Do **not**
add a shared helper — `status` already inlines the same three lines; matching that local style keeps
the diff minimal and the two handlers obviously parallel.

### `tests/integration/test_cli.py` — update + add

- **Update `TestReadState::test_missing_state_fails`** (lines ~167–170). It currently asserts
  `returncode != 0` and `"state" in r.stderr.lower()` — both now false. Rename to
  `test_missing_state_degrades_cleanly` and assert the new parity contract:
  ```python
  def test_missing_state_degrades_cleanly(self, tmp_path: Path) -> None:
      r = _run_cli("read-state", cwd=tmp_path)
      assert r.returncode == 0
      assert "no active run" in r.stdout
      assert "Traceback" not in r.stderr
  ```
- **Add `TestStatus::test_missing_state_degrades_cleanly`** (the Explore pass confirmed `TestStatus`
  has no no-active-run test today). Same three assertions, run against `status`. This locks the
  byte-identical behavior both commands now promise.

## Verification

- `uv run pytest tests/integration/test_cli.py -k "missing_state or read_state or status" -v` —
  the updated + new tests pass; nothing else in those classes regresses.
- `uv run pytest -m "not e2e" -q` — full unit/integration sweep stays green (confirms no other test
  depended on `read-state` exiting non-zero with no state).
- `./scripts/smoke.sh` → unchanged `>> OK — plumbing works.` (it `init`s first, so `read-state` always
  has state — regression guard that the success path still emits JSON).
- Manual parity check in a throwaway dir with no `.sindri/`:
  `diff <(forge.sh read-state) <(forge.sh status)` → identical single line, both exit 0.
- After running `uv run …`, `git checkout uv.lock` if it was touched (known side-effect), so the
  commit stays clean.

## Execution preamble (post-approval, per SDLC discipline)

1. `git checkout -b fix/read-state-clean-degrade` (never work on `main`).
2. Copy this plan into the repo as `plan-fix-read-state-clean-degrade.md` and create `progress/`.
3. Implement → verify → `gh pr create` to `main`. (Standalone; can merge before or after the PR #20
   command-split release — no shared files.)

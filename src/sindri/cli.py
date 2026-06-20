"""CLI entry point — argparse dispatcher for sindri subcommands.

Each subcommand is registered once here and dispatched to a handler function.
Handlers return an exit code (0 on success, non-zero on failure).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from sindri import __version__

if TYPE_CHECKING:
    from sindri.core.validators import SindriState

_HANDLERS: dict[str, Callable[[argparse.Namespace], int]] = {}


def _register(
    name: str,
) -> Callable[[Callable[[argparse.Namespace], int]], Callable[[argparse.Namespace], int]]:
    """Decorator: register a subcommand handler."""
    def decorator(fn: Callable[[argparse.Namespace], int]) -> Callable[[argparse.Namespace], int]:
        _HANDLERS[name] = fn
        return fn
    return decorator


def _load_state_or_exit(**kwargs: Path) -> SindriState | None:
    """Read state; on StateIOError, print `error: ...` to stderr and return None.

    Handlers that want the "no active run" friendly path (e.g. `status`) should
    catch StateIOError themselves — this helper is for the exit-1 path.
    """
    from sindri.core.state import StateIOError, read_state

    try:
        return read_state(**kwargs)
    except StateIOError as e:
        print(f"error: {e}", file=sys.stderr)
        return None


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sindri", description="Sindri: bounded optimization loop core"
    )
    p.add_argument("--version", action="version", version=f"sindri {__version__}")
    sub = p.add_subparsers(dest="subcommand", required=False)

    _add_validate_benchmark(sub)
    _add_detect_mode(sub)
    _add_read_state(sub)
    _add_pick_next(sub)
    _add_record_result(sub)
    _add_check_termination(sub)
    _add_generate_pr_body(sub)
    _add_archive(sub)
    _add_status(sub)
    _add_init(sub)
    _add_acquire_lock(sub)
    _add_release_lock(sub)
    _add_record_terminated(sub)
    _add_reset_tree(sub)
    _add_commit_kept(sub)
    return p


def _add_validate_benchmark(sub: argparse._SubParsersAction) -> None:
    vp = sub.add_parser(
        "validate-benchmark",
        help="run benchmark.py, check METRIC output",
    )
    vp.add_argument(
        "--expected",
        help="expected metric name; error if script outputs a different one",
    )
    vp.add_argument(
        "--script",
        default=".claude/scripts/sindri/benchmark.py",
        help="path to benchmark script (default: .claude/scripts/sindri/benchmark.py)",
    )


@_register("validate-benchmark")
def _handle_validate_benchmark(args: argparse.Namespace) -> int:
    import json
    import subprocess
    from pathlib import Path

    from sindri.core.metric import MetricParseError, parse_metric_line

    script = Path(args.script)
    if not script.exists():
        print(f"error: benchmark.py not found at {script}", file=sys.stderr)
        return 1

    try:
        proc = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        print("error: benchmark timed out during validation (>5min)", file=sys.stderr)
        return 1

    if proc.returncode != 0:
        print(f"error: benchmark exited non-zero: {proc.stderr.strip()}", file=sys.stderr)
        return 1

    try:
        name, value = parse_metric_line(proc.stdout, expected_name=args.expected)
    except MetricParseError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(json.dumps({"ok": True, "metric_name": name, "metric_value": value}))
    return 0


def _add_detect_mode(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "detect-mode",
        help="auto-detect local vs remote benchmark mode; reads JSON from stdin",
    )
    p.add_argument(
        "--script",
        default=".claude/scripts/sindri/benchmark.py",
        help="path to benchmark script",
    )


@_register("detect-mode")
def _handle_detect_mode(args: argparse.Namespace) -> int:
    import json
    from pathlib import Path

    from sindri.core.modes import detect_mode

    try:
        payload = json.loads(sys.stdin.read())
        samples = payload["baseline_samples"]
    except (json.JSONDecodeError, KeyError) as e:
        print(
            f"error: malformed stdin (need {{'baseline_samples': [...]}}): {e}",
            file=sys.stderr,
        )
        return 1

    script = Path(args.script)
    if not script.exists():
        print(f"error: script not found: {script}", file=sys.stderr)
        return 1

    mode = detect_mode(script, samples)
    print(json.dumps({"mode": mode}))
    return 0


def _add_read_state(sub: argparse._SubParsersAction) -> None:
    sub.add_parser("read-state", help="read .sindri/current/sindri.md; emit JSON")


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


def _add_pick_next(sub: argparse._SubParsersAction) -> None:
    sub.add_parser("pick-next", help="pick next pending candidate from state")


@_register("pick-next")
def _handle_pick_next(args: argparse.Namespace) -> int:
    from sindri.core.pool import pick_next

    state = _load_state_or_exit()
    if state is None:
        return 1
    nxt = pick_next(state.pool)
    if nxt is None:
        print("null")
    else:
        print(nxt.model_dump_json())
    return 0


def _add_record_result(sub: argparse._SubParsersAction) -> None:
    sub.add_parser(
        "record-result",
        help="record an experiment result; reads JSON from stdin",
    )


# The subagent's experiment status → the candidate's pool status.
_POOL_STATUS_MAP = {
    "improved": "kept",
    "regressed": "reverted",
    "inconclusive": "reverted",
    "check_failed": "check_failed",
    "errored": "errored",
    "timeout": "errored",
}


def _read_record_payload():  # type: ignore[no-untyped-def]
    """Parse the experiment-result payload from stdin.

    Returns the validated payload, or None after printing an error (the caller
    returns exit 1). Shared by record-result, reset-tree, and commit-kept.
    """
    import json

    from pydantic import BaseModel, ValidationError

    from sindri.core.validators import SubagentResult

    class RecordPayload(BaseModel):
        candidate_id: int
        metric_before: float
        subagent_result: SubagentResult
        commit_sha: str | None = None

    try:
        return RecordPayload.model_validate_json(sys.stdin.read())
    except ValidationError as e:
        print(f"error: invalid payload: {e}", file=sys.stderr)
        return None
    except json.JSONDecodeError as e:
        print(f"error: payload is not JSON: {e}", file=sys.stderr)
        return None


def _experiment_already_recorded(
    candidate_id: int, *, dir: Path = Path(".sindri/current")
) -> bool:
    """True if a `type==experiment` record for this candidate id is already in
    the jsonl — the idempotency key for crash-recovery re-runs (D4)."""
    from sindri.core.state import read_jsonl

    for r in read_jsonl(dir / "sindri.jsonl"):
        if getattr(r, "type", None) == "experiment" and getattr(r, "id", None) == candidate_id:
            return True
    return False


def _apply_and_record(state, cand, payload, *, commit_sha):  # type: ignore[no-untyped-def]
    """Update the candidate's pool status (+ current_best on improved), then
    append the jsonl experiment record FIRST and write state — the single home
    of the jsonl-first ordering (#28) shared by record-result / reset-tree /
    commit-kept. Returns (new_status, new_state)."""
    from datetime import datetime, timezone

    from sindri.core.state import append_jsonl, write_state
    from sindri.core.validators import JsonlExperiment

    res = payload.subagent_result
    new_status = _POOL_STATUS_MAP[res.status]
    new_pool = [
        c.model_copy(update={"status": new_status}) if c.id == payload.candidate_id else c
        for c in state.pool
    ]
    updates: dict[str, object] = {"pool": new_pool}
    if res.status == "improved":
        updates["current_best"] = res.metric_value
    new_state = state.model_copy(update=updates)

    rec = JsonlExperiment(
        ts=datetime.now(tz=timezone.utc),
        id=payload.candidate_id,
        candidate=cand.name,
        reps_used=res.reps_used,
        metric_before=payload.metric_before,
        metric_after=res.metric_value,
        delta=res.metric_value - payload.metric_before,
        confidence_ratio=res.confidence_ratio,
        status=res.status,
        commit_sha=commit_sha,
        files_modified=res.files_modified,
    )
    # Append the audit record FIRST, then write state. A crash between the two
    # must not leave the pool showing a resolved candidate with no jsonl record
    # (which would make the loop's experiments_run / consecutive_reverts counters
    # undercount and silently evade the budget/runaway halts).
    append_jsonl(rec)
    write_state(new_state)
    return new_status, new_state


@_register("record-result")
def _handle_record_result(args: argparse.Namespace) -> int:
    import json

    payload = _read_record_payload()
    if payload is None:
        return 1
    state = _load_state_or_exit()
    if state is None:
        return 1
    cand = next((c for c in state.pool if c.id == payload.candidate_id), None)
    if cand is None:
        print(f"error: no candidate with id {payload.candidate_id}", file=sys.stderr)
        return 1

    new_status, new_state = _apply_and_record(state, cand, payload, commit_sha=payload.commit_sha)
    print(
        json.dumps(
            {"ok": True, "new_status": new_status, "current_best": new_state.current_best}
        )
    )
    return 0


def _add_check_termination(sub: argparse._SubParsersAction) -> None:
    sub.add_parser(
        "check-termination",
        help="check whether the loop should terminate; "
        "JSON {experiments_run, consecutive_reverts} on stdin",
    )


@_register("check-termination")
def _handle_check_termination(args: argparse.Namespace) -> int:
    import json

    from sindri.core.termination import check_termination

    try:
        payload = json.loads(sys.stdin.read())
        experiments_run = int(payload["experiments_run"])
        consecutive_reverts = int(payload["consecutive_reverts"])
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
        print(f"error: invalid stdin payload: {e}", file=sys.stderr)
        return 1

    state = _load_state_or_exit()
    if state is None:
        return 1
    result = check_termination(
        state,
        experiments_run=experiments_run,
        consecutive_reverts=consecutive_reverts,
    )
    print(result.model_dump_json())
    return 0


def _add_generate_pr_body(sub: argparse._SubParsersAction) -> None:
    sub.add_parser("generate-pr-body", help="print PR body markdown to stdout")


@_register("generate-pr-body")
def _handle_generate_pr_body(args: argparse.Namespace) -> int:
    from sindri.core.pr_body import render_pr_body
    from sindri.core.state import read_jsonl

    state = _load_state_or_exit()
    if state is None:
        return 1
    records = read_jsonl(Path(".sindri/current/sindri.jsonl"))
    print(render_pr_body(state, records))
    return 0


def _add_archive(sub: argparse._SubParsersAction) -> None:
    sub.add_parser(
        "archive",
        help="move .sindri/current/ to .sindri/archive/<date>-<slug>/",
    )


@_register("archive")
def _handle_archive(args: argparse.Namespace) -> int:
    import json
    import shutil
    from datetime import date

    current = Path(".sindri/current")
    if not current.exists():
        print("error: .sindri/current/ does not exist", file=sys.stderr)
        return 1

    state = _load_state_or_exit(dir=current)
    if state is None:
        return 1

    # Slug is the branch name minus the 'sindri/' prefix. Sanitize it: a
    # tampered sindri.md could carry a branch like "sindri/../../etc/whatever"
    # and we must not let shutil.move follow that out of .sindri/archive/.
    branch = state.branch
    raw_slug = branch[len("sindri/"):] if branch.startswith("sindri/") else branch
    slug = raw_slug.replace("/", "-").replace("\\", "-")
    if slug in {"", ".", ".."} or slug.startswith("."):
        print(
            f"error: refusing to archive with unsafe slug {raw_slug!r}",
            file=sys.stderr,
        )
        return 1
    archive_name = f"{date.today().isoformat()}-{slug}"
    archive_dir = Path(".sindri") / "archive" / archive_name
    archive_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(current), str(archive_dir))

    print(json.dumps({"ok": True, "archived_to": str(archive_dir)}))
    return 0


def _add_status(sub: argparse._SubParsersAction) -> None:
    sub.add_parser("status", help="human-readable summary of current run")


@_register("status")
def _handle_status(args: argparse.Namespace) -> int:
    from sindri.core.state import StateIOError, read_state

    try:
        state = read_state()
    except StateIOError:
        print("sindri: no active run (.sindri/current/ not found)")
        return 0

    kept = sum(1 for c in state.pool if c.status == "kept")
    reverted = sum(1 for c in state.pool if c.status == "reverted")
    pending = sum(1 for c in state.pool if c.status == "pending")
    dead = sum(1 for c in state.pool if c.status in {"errored", "check_failed"})

    current = state.current_best if state.current_best is not None else state.baseline.value
    delta_pct = ((current - state.baseline.value) / state.baseline.value) * 100

    print(
        f"sindri: {state.goal.direction} {state.goal.metric_name} by "
        f"{state.goal.target_pct}%"
    )
    print(f"  branch:    {state.branch}")
    print(f"  mode:      {state.mode}")
    print(
        f"  baseline:  {state.baseline.value:,.0f} "
        f"(σ {state.baseline.noise_floor:,.2f})"
    )
    print(f"  current:   {current:,.0f} ({delta_pct:+.2f}%)")
    print(
        f"  pool:      {len(state.pool)} total · {kept} kept · {reverted} reverted "
        f"· {dead} dead · {pending} pending"
    )
    return 0


_GOAL_RE = re.compile(
    r"\s*(?P<direction>reduce|increase)\s+(?P<metric>[a-z][a-z0-9_]*)"
    r"\s+by\s+(?P<pct>\d+(?:\.\d+)?)\s*%\s*",
    re.IGNORECASE,
)


def _add_acquire_lock(sub: argparse._SubParsersAction) -> None:
    sub.add_parser(
        "acquire-lock",
        help="acquire the single-writer wakeup lock; exit 0 if acquired, 1 if held",
    )


@_register("acquire-lock")
def _handle_acquire_lock(args: argparse.Namespace) -> int:
    import json

    from sindri.core.lock import STALE_AGE_MULTIPLIER, acquire_lock

    state = _load_state_or_exit()
    if state is None:
        # Distinct from the "held" exit (1): a state read error must NOT make the
        # orchestrator silently back off without rescheduling. exit 2 = error.
        return 2
    # Max-age = a small multiple of the per-experiment timeout (the longest a
    # legit wakeup holds the lock). The resolved guardrail is an int post-init;
    # fall back conservatively if somehow unset.
    timeout = state.guardrails.timeout_per_experiment_seconds or 1800
    res = acquire_lock(max_age_seconds=STALE_AGE_MULTIPLIER * float(timeout))
    print(
        json.dumps(
            {
                "acquired": res.acquired,
                "took_over_stale": res.took_over_stale,
                "token": res.holder.token,
                "holder": {
                    "pid": res.holder.pid,
                    "host": res.holder.host,
                    "started_at": res.holder.started_at.isoformat(),
                },
            }
        )
    )
    # Exit non-zero when a live holder already owns the lock so the orchestrator
    # can back off WITHOUT rescheduling a competing wakeup.
    return 0 if res.acquired else 1


def _add_release_lock(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "release-lock",
        help="release the wakeup lock if we hold its token",
    )
    p.add_argument("--token", required=True, help="the token returned by acquire-lock")


@_register("release-lock")
def _handle_release_lock(args: argparse.Namespace) -> int:
    import json

    from sindri.core.lock import release_lock

    released = release_lock(token=args.token)
    print(json.dumps({"released": released}))
    return 0


_TERMINATION_REASONS = (
    "target_hit",
    "pool_empty",
    "max_experiments",
    "max_wall_clock",
    "max_reverts_in_a_row",
    "halted_by_user",
    "halted_by_error",
)


def _add_record_terminated(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "record-terminated",
        help="append a validated terminated record to sindri.jsonl",
    )
    p.add_argument("--reason", required=True, choices=_TERMINATION_REASONS)
    p.add_argument(
        "--auto-finalize",
        required=True,
        choices=("true", "false"),
        help="whether a PR should be auto-created (from check-termination)",
    )


@_register("record-terminated")
def _handle_record_terminated(args: argparse.Namespace) -> int:
    import json
    from datetime import datetime, timezone

    from sindri.core.state import append_jsonl
    from sindri.core.validators import JsonlTerminated

    state = _load_state_or_exit()
    if state is None:
        return 1

    # Everything except reason/auto_finalize (the orchestrator's decision inputs)
    # is derived from state here, so the orchestrator no longer hand-builds JSON.
    final_metric = state.current_best if state.current_best is not None else state.baseline.value
    base = state.baseline.value
    delta_pct = ((final_metric - base) / base) * 100 if base else 0.0
    kept = sum(1 for c in state.pool if c.status == "kept")
    reverted = sum(1 for c in state.pool if c.status == "reverted")
    errored = sum(1 for c in state.pool if c.status in {"errored", "check_failed"})
    now = datetime.now(tz=timezone.utc)
    wall = max(0, int((now - state.started_at).total_seconds()))

    rec = JsonlTerminated(
        ts=now,
        reason=args.reason,
        final_metric=final_metric,
        delta_pct=delta_pct,
        kept=kept,
        reverted=reverted,
        errored=errored,
        wall_clock_seconds=wall,
        auto_finalize=(args.auto_finalize == "true"),
    )
    append_jsonl(rec)
    print(
        json.dumps(
            {"ok": True, "reason": rec.reason, "auto_finalize": rec.auto_finalize, "kept": kept}
        )
    )
    return 0


def _add_reset_tree(sub: argparse._SubParsersAction) -> None:
    sub.add_parser(
        "reset-tree",
        help="git reset --hard HEAD and record a non-improved experiment result",
    )


@_register("reset-tree")
def _handle_reset_tree(args: argparse.Namespace) -> int:
    import json

    from sindri.core.git_ops import GitError, reset_hard_to_head

    payload = _read_record_payload()
    if payload is None:
        return 1
    if payload.subagent_result.status == "improved":
        print(
            "error: reset-tree is for non-improved results; use commit-kept",
            file=sys.stderr,
        )
        return 1
    state = _load_state_or_exit()
    if state is None:
        return 1
    cand = next((c for c in state.pool if c.id == payload.candidate_id), None)
    if cand is None:
        print(f"error: no candidate with id {payload.candidate_id}", file=sys.stderr)
        return 1

    # D4 idempotency: a crash-recovery re-run of an already-recorded candidate
    # must not append a duplicate experiment record.
    if _experiment_already_recorded(payload.candidate_id):
        print(json.dumps({"ok": True, "skipped": True, "reason": "already recorded"}))
        return 0

    try:
        reset_hard_to_head()
    except GitError as e:
        print(f"error: git reset failed: {e}", file=sys.stderr)
        return 1

    new_status, _ = _apply_and_record(state, cand, payload, commit_sha=None)
    print(json.dumps({"ok": True, "new_status": new_status}))
    return 0


def _kept_commit_sha(name: str, *, cwd: Path | None = None) -> str | None:
    """SHA of an existing `kept: <name> (Δ...)` commit on the current branch, or
    None — confirms a keep commit physically landed (D4 tier b).

    Anchored on the SUBJECT (not the body, not a substring): the subject must
    start with `kept: <name> (Δ`. The `(Δ` delimiter after the exact name avoids
    the false-positive where a candidate name is a prefix of a longer one (e.g.
    `add cache` must NOT match `kept: add cache (lru) (Δ-10)`). Per ADR-001.
    """
    import re
    import subprocess

    pattern = re.compile(r"^kept: " + re.escape(name) + r" \(Δ")
    try:
        out = subprocess.run(
            ["git", "log", "--format=%H %s"],
            capture_output=True, text=True, check=True, cwd=cwd,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    for line in out.splitlines():
        sha, _, subject = line.partition(" ")
        if pattern.match(subject):
            return sha  # most recent matching commit (git log is newest-first)
    return None


def _reconcile_pool_from_record(
    state, candidate_id: int, *, dir: Path = Path(".sindri/current")
) -> None:  # type: ignore[no-untyped-def]
    """Complete a crash-interrupted write: set the candidate's pool status (+
    current_best) from its already-appended jsonl record, WITHOUT appending a
    duplicate. Idempotent."""
    from sindri.core.state import read_jsonl, write_state

    rec = None
    for r in read_jsonl(dir / "sindri.jsonl"):
        if getattr(r, "type", None) == "experiment" and getattr(r, "id", None) == candidate_id:
            rec = r
    if rec is None:
        return
    new_status = _POOL_STATUS_MAP[rec.status]
    new_pool = [
        c.model_copy(update={"status": new_status}) if c.id == candidate_id else c
        for c in state.pool
    ]
    updates: dict[str, object] = {"pool": new_pool}
    if rec.status == "improved":
        updates["current_best"] = rec.metric_after
    write_state(state.model_copy(update=updates))


def _add_commit_kept(sub: argparse._SubParsersAction) -> None:
    sub.add_parser(
        "commit-kept",
        help="git-commit the kept change and record an improved result in one step",
    )


@_register("commit-kept")
def _handle_commit_kept(args: argparse.Namespace) -> int:
    import json

    from sindri.core.git_ops import GitError, commit_all_with_message

    payload = _read_record_payload()
    if payload is None:
        return 1
    if payload.subagent_result.status != "improved":
        print(
            "error: commit-kept is for improved results only; use reset-tree",
            file=sys.stderr,
        )
        return 1
    state = _load_state_or_exit()
    if state is None:
        return 1
    cand = next((c for c in state.pool if c.id == payload.candidate_id), None)
    if cand is None:
        print(f"error: no candidate with id {payload.candidate_id}", file=sys.stderr)
        return 1

    # D4 tier (a): the experiment is already recorded (crash after the jsonl
    # append). Reconcile the pool from the existing record — no duplicate append,
    # no duplicate commit — and skip.
    if _experiment_already_recorded(payload.candidate_id):
        _reconcile_pool_from_record(state, payload.candidate_id)
        print(json.dumps({"ok": True, "skipped": True, "reason": "already recorded"}))
        return 0

    # D4 tier (b): the kept commit landed in a prior crashed run but the record
    # didn't (crash between commit and append). Reuse that SHA — never double-commit.
    sha = _kept_commit_sha(cand.name)
    if sha is None:
        delta = payload.subagent_result.metric_value - payload.metric_before
        try:
            sha = commit_all_with_message(f"kept: {cand.name} (Δ{delta:+g})")
        except GitError:
            # Subagent claimed "improved" but left no net change — git refuses the
            # empty commit. It's not a real keep; record it as errored instead.
            downgraded = payload.model_copy(
                update={
                    "subagent_result": payload.subagent_result.model_copy(
                        update={"status": "errored"}
                    )
                }
            )
            _apply_and_record(state, cand, downgraded, commit_sha=None)
            print(
                json.dumps(
                    {"ok": True, "new_status": "errored", "reason": "empty commit (no net change)"}
                )
            )
            return 0

    new_status, new_state = _apply_and_record(state, cand, payload, commit_sha=sha)
    print(
        json.dumps(
            {
                "ok": True,
                "new_status": new_status,
                "commit_sha": sha,
                "current_best": new_state.current_best,
            }
        )
    )
    return 0


def _add_init(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "init",
        help="initialize a new sindri run from a goal and candidate pool",
    )
    p.add_argument(
        "--goal",
        required=True,
        help="goal string, e.g. 'reduce bundle_bytes by 15%%'",
    )
    p.add_argument(
        "--pool-json",
        required=True,
        help="JSON array of candidate dicts "
        "(id, name, expected_impact_pct, optional files)",
    )
    p.add_argument(
        "--script",
        default=".claude/scripts/sindri/benchmark.py",
        help="path to benchmark script",
    )


@_register("init")
def _handle_init(args: argparse.Namespace) -> int:
    import json
    import subprocess as sp
    from datetime import datetime, timezone
    from pathlib import Path

    from sindri.core.git_ops import GitError, branch_exists, create_branch
    from sindri.core.metric import MetricParseError, parse_metric_line
    from sindri.core.modes import detect_mode
    from sindri.core.noise import noise_floor
    from sindri.core.state import append_jsonl, write_state
    from sindri.core.validators import (
        Baseline,
        Candidate,
        Goal,
        Guardrails,
        JsonlBaseline,
        JsonlBaselineComplete,
        JsonlSessionStart,
        SindriState,
    )

    current_dir = Path(".sindri/current")
    if current_dir.exists():
        print(
            "error: .sindri/current/ already exists — another run is active",
            file=sys.stderr,
        )
        return 1

    # fullmatch rejects goals like "reduce x by 15% and make coffee" — `search`
    # used to silently consume only the prefix and drop the trailing junk.
    m = _GOAL_RE.fullmatch(args.goal)
    if not m:
        print(
            "error: malformed goal — expected 'reduce|increase <metric> by <N>%'",
            file=sys.stderr,
        )
        return 1
    direction = m.group("direction").lower()
    metric_name = m.group("metric")
    target_pct = float(m.group("pct"))

    if direction == "reduce" and target_pct >= 100:
        print(
            f"warning: reduce target of {target_pct:g}% implies a metric of <= 0, "
            "which a benchmark likely can't reach — proceeding anyway.",
            file=sys.stderr,
        )

    try:
        goal = Goal(
            metric_name=metric_name,
            direction=direction,  # type: ignore[arg-type]
            target_pct=target_pct,
        )
    except Exception as e:
        print(f"error: invalid goal: {e}", file=sys.stderr)
        return 1

    try:
        pool_raw = json.loads(args.pool_json)
        pool = [Candidate(**c) for c in pool_raw]
    except Exception as e:
        print(f"error: invalid pool-json: {e}", file=sys.stderr)
        return 1

    script = Path(args.script)
    if not script.exists():
        print(f"error: benchmark.py not found at {script}", file=sys.stderr)
        return 1

    # Fail fast on a taken branch name BEFORE spending three baseline runs
    # — reusing them would silently clobber a prior aborted run's history.
    prospective_slug = (
        f"{direction}-{metric_name.replace('_', '-')}-{int(target_pct)}pct"
    )
    prospective_branch = f"sindri/{prospective_slug}"
    if branch_exists(prospective_branch):
        print(
            f"error: branch {prospective_branch!r} already exists — "
            f"delete it or archive the prior run first",
            file=sys.stderr,
        )
        return 1

    samples: list[float] = []
    for run_idx in range(1, 4):
        try:
            proc = sp.run(
                [sys.executable, str(script)],
                capture_output=True,
                text=True,
                check=False,
                timeout=1800,
            )
        except sp.TimeoutExpired:
            print(
                f"error: benchmark timed out during baseline run {run_idx}",
                file=sys.stderr,
            )
            return 1
        if proc.returncode != 0:
            print(
                f"error: benchmark failed on baseline run {run_idx}: "
                f"{proc.stderr.strip()}",
                file=sys.stderr,
            )
            return 1
        try:
            _, value = parse_metric_line(proc.stdout, expected_name=metric_name)
        except MetricParseError as e:
            print(f"error: baseline run {run_idx}: {e}", file=sys.stderr)
            return 1
        samples.append(value)

    try:
        sigma = noise_floor(samples)
    except Exception as e:
        print(f"error: noise floor computation failed: {e}", file=sys.stderr)
        return 1

    # Post-warmup mean: drop the first sample (JIT / cold cache).
    post_warmup = samples[1:]
    mean_val = sum(post_warmup) / len(post_warmup)
    mode = detect_mode(script, samples)

    branch_name = prospective_branch
    try:
        create_branch(branch_name)
    except GitError as e:
        print(f"error: could not create branch: {e}", file=sys.stderr)
        return 1

    now = datetime.now(tz=timezone.utc)
    state = SindriState(
        goal=goal,
        baseline=Baseline(value=mean_val, noise_floor=sigma, samples=samples),
        pool=pool,
        branch=branch_name,
        started_at=now,
        guardrails=Guardrails(mode=mode),  # type: ignore[arg-type]
        mode=mode,
    )
    write_state(state)

    sign = "-" if direction == "reduce" else "+"
    append_jsonl(
        JsonlSessionStart(
            ts=now,
            goal=args.goal,
            target_pct=float(f"{sign}{target_pct}"),
            mode=mode,
        )
    )
    for i, v in enumerate(samples, start=1):
        append_jsonl(JsonlBaseline(ts=now, run_index=i, value=v, is_warmup=(i == 1)))
    append_jsonl(JsonlBaselineComplete(ts=now, mean=mean_val, noise_floor=sigma))

    print(
        json.dumps(
            {
                "ok": True,
                "branch": branch_name,
                "baseline": mean_val,
                "noise_floor": sigma,
                "mode": mode,
            }
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.subcommand is None:
        parser.print_help()
        return 0
    handler = _HANDLERS.get(args.subcommand)
    if handler is None:
        print(
            f"error: subcommand {args.subcommand!r} not yet implemented",
            file=sys.stderr,
        )
        return 2
    return handler(args)

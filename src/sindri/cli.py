"""CLI entry point — argparse dispatcher for sindri subcommands.

Each subcommand is registered once here and dispatched to a handler function.
Handlers return an exit code (0 on success, non-zero on failure).
"""
from __future__ import annotations

import argparse
import sys
from typing import Callable

import re

from sindri import __version__

_HANDLERS: dict[str, Callable[[argparse.Namespace], int]] = {}


def _register(
    name: str,
) -> Callable[[Callable[[argparse.Namespace], int]], Callable[[argparse.Namespace], int]]:
    """Decorator: register a subcommand handler."""
    def decorator(fn: Callable[[argparse.Namespace], int]) -> Callable[[argparse.Namespace], int]:
        _HANDLERS[name] = fn
        return fn
    return decorator


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
    except StateIOError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(state.model_dump_json())
    return 0


def _add_pick_next(sub: argparse._SubParsersAction) -> None:
    sub.add_parser("pick-next", help="pick next pending candidate from state")


@_register("pick-next")
def _handle_pick_next(args: argparse.Namespace) -> int:
    from sindri.core.pool import pick_next
    from sindri.core.state import StateIOError, read_state

    try:
        state = read_state()
    except StateIOError as e:
        print(f"error: {e}", file=sys.stderr)
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


@_register("record-result")
def _handle_record_result(args: argparse.Namespace) -> int:
    import json
    from datetime import datetime, timezone

    from pydantic import BaseModel, ValidationError

    from sindri.core.state import StateIOError, append_jsonl, read_state, write_state
    from sindri.core.validators import JsonlExperiment, SubagentResult

    class RecordPayload(BaseModel):
        candidate_id: int
        metric_before: float
        subagent_result: SubagentResult
        commit_sha: str | None = None

    try:
        raw = sys.stdin.read()
        payload = RecordPayload.model_validate_json(raw)
    except ValidationError as e:
        print(f"error: invalid payload: {e}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"error: payload is not JSON: {e}", file=sys.stderr)
        return 1

    try:
        state = read_state()
    except StateIOError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    cand = next((c for c in state.pool if c.id == payload.candidate_id), None)
    if cand is None:
        print(f"error: no candidate with id {payload.candidate_id}", file=sys.stderr)
        return 1

    res = payload.subagent_result
    delta = res.metric_value - payload.metric_before

    pool_status_map = {
        "improved": "kept",
        "regressed": "reverted",
        "inconclusive": "reverted",
        "check_failed": "check_failed",
        "errored": "errored",
        "timeout": "errored",
    }
    new_status = pool_status_map[res.status]

    new_pool = []
    for c in state.pool:
        if c.id == payload.candidate_id:
            new_pool.append(c.model_copy(update={"status": new_status}))
        else:
            new_pool.append(c)
    updates: dict[str, object] = {"pool": new_pool}
    if res.status == "improved":
        updates["current_best"] = res.metric_value
    new_state = state.model_copy(update=updates)
    write_state(new_state)

    rec = JsonlExperiment(
        ts=datetime.now(tz=timezone.utc),
        id=payload.candidate_id,
        candidate=cand.name,
        reps_used=res.reps_used,
        metric_before=payload.metric_before,
        metric_after=res.metric_value,
        delta=delta,
        confidence_ratio=res.confidence_ratio,
        status=res.status,
        commit_sha=payload.commit_sha,
        files_modified=res.files_modified,
    )
    append_jsonl(rec)

    print(
        json.dumps(
            {
                "ok": True,
                "new_status": new_status,
                "current_best": new_state.current_best,
            }
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

    from sindri.core.state import StateIOError, read_state
    from sindri.core.termination import check_termination

    try:
        payload = json.loads(sys.stdin.read())
        experiments_run = int(payload["experiments_run"])
        consecutive_reverts = int(payload["consecutive_reverts"])
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
        print(f"error: invalid stdin payload: {e}", file=sys.stderr)
        return 1

    try:
        state = read_state()
    except StateIOError as e:
        print(f"error: {e}", file=sys.stderr)
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
    from pathlib import Path

    from sindri.core.pr_body import render_pr_body
    from sindri.core.state import StateIOError, read_jsonl, read_state

    try:
        state = read_state()
    except StateIOError as e:
        print(f"error: {e}", file=sys.stderr)
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
    from pathlib import Path

    from sindri.core.state import StateIOError, read_state

    current = Path(".sindri/current")
    if not current.exists():
        print("error: .sindri/current/ does not exist", file=sys.stderr)
        return 1

    try:
        state = read_state(dir=current)
    except StateIOError as e:
        print(f"error: cannot read state: {e}", file=sys.stderr)
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
    r"(?P<direction>reduce|increase)\s+(?P<metric>[a-z][a-z0-9_]*)"
    r"\s+by\s+(?P<pct>\d+(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)


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

    from sindri.core.git_ops import GitError, create_branch
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

    m = _GOAL_RE.search(args.goal)
    if not m:
        print(
            "error: malformed goal — expected 'reduce|increase <metric> by <N>%'",
            file=sys.stderr,
        )
        return 1
    direction = m.group("direction").lower()
    metric_name = m.group("metric")
    target_pct = float(m.group("pct"))

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

    slug = f"{direction}-{metric_name.replace('_', '-')}-{int(target_pct)}pct"
    branch_name = f"sindri/{slug}"
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

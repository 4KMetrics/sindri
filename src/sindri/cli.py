"""CLI entry point — argparse dispatcher for sindri subcommands.

Each subcommand is registered once here and dispatched to a handler function.
Handlers return an exit code (0 on success, non-zero on failure).
"""
from __future__ import annotations

import argparse
import sys
from typing import Callable

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

    from sindri.core.state import append_jsonl, read_state, write_state
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

    state = read_state()
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

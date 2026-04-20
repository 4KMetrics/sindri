"""Stub experiment-subagent for E2E tests.

The real sindri-loop dispatches via `Task`; here we simulate that by mutating
the fixture repo directly, running the real benchmark, and returning JSON that
matches the pydantic SubagentResult schema.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class StubAction:
    """Recipe for a stubbed candidate outcome."""
    delete_file: str | None = None       # if set, rm this file before benchmark
    append_lines: int = 0                # if > 0, add lines to a scratch file
    force_error: bool = False            # if True, return errored without benchmarking
    force_timeout: bool = False          # if True, return timeout without benchmarking
    force_check_failed: bool = False     # if True, return check_failed without benchmarking
    files_modified: list[str] = field(default_factory=list)


def run_stub_experiment(
    repo: Path,
    candidate_name: str,
    recipe: StubAction,
    *,
    current_best: float,
    direction: str = "reduce",
    noise_floor: float = 0.01,
) -> dict:
    """Apply the recipe in-repo, measure, return a SubagentResult-shaped dict.

    Side effects on `repo` (meant to be reverted by the orchestrator sim via
    `git reset --hard HEAD` when status != "improved").
    """
    if recipe.force_error:
        return {
            "metric_value": 0.0,
            "reps_used": 0,
            "confidence_ratio": 0.0,
            "status": "errored",
            "files_modified": [],
            "notes": f"stub: forced error for {candidate_name}",
        }
    if recipe.force_timeout:
        return {
            "metric_value": 0.0,
            "reps_used": 0,
            "confidence_ratio": 0.0,
            "status": "timeout",
            "files_modified": [],
            "notes": f"stub: forced timeout for {candidate_name}",
        }
    if recipe.force_check_failed:
        return {
            "metric_value": 0.0,
            "reps_used": 0,
            "confidence_ratio": 0.0,
            "status": "check_failed",
            "files_modified": [],
            "notes": f"stub: forced check_failed for {candidate_name}",
        }

    if recipe.delete_file:
        (repo / recipe.delete_file).unlink(missing_ok=False)
    if recipe.append_lines > 0:
        scratch = repo / "src" / "_scratch.py"
        current = scratch.read_text() if scratch.exists() else ""
        scratch.write_text(current + ("y = 2\n" * recipe.append_lines))

    # Run the real benchmark in the fixture repo.
    out = subprocess.run(
        ["python", ".claude/scripts/sindri/benchmark.py"],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    last_line = out.stdout.strip().splitlines()[-1]
    assert last_line.startswith("METRIC lines="), f"unexpected benchmark output: {out.stdout!r}"
    metric_value = float(last_line.split("=")[1])

    # Deterministic ratio: low noise_floor → confident even for 1-line changes.
    delta = (metric_value - current_best) * (-1 if direction == "reduce" else 1)
    confidence_ratio = abs(delta) / max(noise_floor, 1e-9)

    if confidence_ratio < 2.0:
        status = "inconclusive"
    elif delta > 0:
        status = "improved"
    else:
        status = "regressed"

    return {
        "metric_value": metric_value,
        "reps_used": 1,
        "confidence_ratio": confidence_ratio,
        "status": status,
        "files_modified": recipe.files_modified or (
            [recipe.delete_file] if recipe.delete_file else (
                ["src/_scratch.py"] if recipe.append_lines else []
            )
        ),
        "notes": f"stub: {candidate_name}",
    }


def build_record_payload(
    *, candidate_id: int, metric_before: float, subagent_result: dict, commit_sha: str | None,
) -> str:
    """Serialize the exact JSON that `python -m sindri record-result` expects on stdin."""
    return json.dumps({
        "candidate_id": candidate_id,
        "metric_before": metric_before,
        "subagent_result": subagent_result,
        "commit_sha": commit_sha,
    })

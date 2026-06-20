"""End-to-end simulation of a sindri run.

The test drives `python -m sindri <subcmd>` the same way the sindri-loop skill
would, replacing the Task-based subagent dispatch with `run_stub_experiment`.
Validates that CLI protocol + state + git ops compose correctly across a full
lifecycle: init → N wakeups → terminate.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.e2e.stub_subagent import StubAction, build_record_payload, run_stub_experiment


def _sindri(repo: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    """Run `python -m sindri ...` inside `repo`."""
    env = os.environ.copy()
    return subprocess.run(
        [sys.executable, "-m", "sindri", *args],
        cwd=repo, input=stdin, capture_output=True, text=True, env=env,
    )


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True,
    ).stdout


def _count_counters(repo: Path) -> tuple[int, int]:
    """Return (experiments_run, consecutive_reverts) from the jsonl tail."""
    path = repo / ".sindri" / "current" / "sindri.jsonl"
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    experiments = [r for r in records if r.get("type") == "experiment"]
    experiments_run = len(experiments)
    consecutive_reverts = 0
    for exp in reversed(experiments):
        if exp["status"] == "improved":
            break
        if exp["status"] in ("regressed", "inconclusive", "check_failed", "errored", "timeout"):
            consecutive_reverts += 1
        else:
            break
    return experiments_run, consecutive_reverts


def _check_termination(repo: Path) -> dict:
    exp_run, rev = _count_counters(repo)
    payload = json.dumps({"experiments_run": exp_run, "consecutive_reverts": rev})
    r = _sindri(repo, "check-termination", stdin=payload)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _current_metric_before(repo: Path) -> float:
    state = json.loads(_sindri(repo, "read-state").stdout)
    cb = state.get("current_best")
    return float(cb) if cb is not None else float(state["baseline"]["value"])


def _apply_result(repo: Path, cand: dict, result: dict, metric_before: float) -> subprocess.CompletedProcess:
    """Apply a result the way sindri-loop step 7 now does: commit-kept for an
    improvement, reset-tree otherwise — the subcommand does the git op AND the
    record in one call (no test-side git commit/reset)."""
    payload = build_record_payload(
        candidate_id=cand["id"], metric_before=metric_before,
        subagent_result=result, commit_sha=None,
    )
    cmd = "commit-kept" if result["status"] == "improved" else "reset-tree"
    r = _sindri(repo, cmd, stdin=payload)
    assert r.returncode == 0, r.stderr
    return r


@pytest.mark.e2e
def test_happy_path_target_hit(target_repo: Path) -> None:
    """3 file deletions drive metric 30 → 20 → 10 → 0; target 99% forces all 3 kept before target_hit."""
    pool = [
        {"id": 1, "name": "delete a.py", "expected_impact_pct": -33, "files": ["src/a.py"]},
        {"id": 2, "name": "delete b.py", "expected_impact_pct": -33, "files": ["src/b.py"]},
        {"id": 3, "name": "delete c.py", "expected_impact_pct": -33, "files": ["src/c.py"]},
    ]
    r = _sindri(
        target_repo, "init",
        "--goal", "reduce lines by 99%",
        "--pool-json", json.dumps(pool),
        "--script", ".claude/scripts/sindri/benchmark.py",
    )
    assert r.returncode == 0, r.stderr
    init_out = json.loads(r.stdout)
    assert init_out["ok"] is True
    assert init_out["baseline"] == 30.0

    recipes = {
        "delete a.py": StubAction(delete_file="src/a.py", files_modified=["src/a.py"]),
        "delete b.py": StubAction(delete_file="src/b.py", files_modified=["src/b.py"]),
        "delete c.py": StubAction(delete_file="src/c.py", files_modified=["src/c.py"]),
    }

    for _ in range(10):  # safety bound
        term = _check_termination(target_repo)
        if term["terminated"]:
            break

        if _git(target_repo, "status", "--porcelain").strip():
            subprocess.run(["git", "reset", "--hard", "HEAD"], cwd=target_repo, check=True)

        nxt = _sindri(target_repo, "pick-next")
        assert nxt.returncode == 0, nxt.stderr
        cand = json.loads(nxt.stdout)
        if cand is None:
            break

        metric_before = _current_metric_before(target_repo)
        result = run_stub_experiment(
            target_repo, cand["name"], recipes[cand["name"]],
            current_best=metric_before,
        )

        _apply_result(target_repo, cand, result, metric_before)

    final_term = _check_termination(target_repo)
    assert final_term["terminated"] is True
    assert final_term["reason"] in ("target_hit", "pool_empty"), final_term
    assert final_term["auto_finalize"] is True, final_term

    log = _git(target_repo, "log", "--oneline").splitlines()
    kept = [line for line in log if "kept:" in line]
    assert len(kept) == 3, f"expected 3 kept commits, got: {log}"

    jsonl = [
        json.loads(line)
        for line in (target_repo / ".sindri" / "current" / "sindri.jsonl").read_text().splitlines()
        if line.strip()
    ]
    experiments = [r for r in jsonl if r.get("type") == "experiment"]
    assert len(experiments) == 3, experiments
    assert all(e["status"] == "improved" for e in experiments)
    assert experiments[-1]["metric_after"] == 0.0  # all 3 files deleted


@pytest.mark.e2e
def test_pool_exhausted_no_wins(target_repo: Path) -> None:
    """All candidates regress → terminate with pool_empty, auto_finalize=False, no PR."""
    pool = [
        {"id": 1, "name": "bloat a", "expected_impact_pct": -5, "files": []},
        {"id": 2, "name": "bloat b", "expected_impact_pct": -5, "files": []},
    ]
    r = _sindri(
        target_repo, "init",
        "--goal", "reduce lines by 50%",
        "--pool-json", json.dumps(pool),
        "--script", ".claude/scripts/sindri/benchmark.py",
    )
    assert r.returncode == 0, r.stderr

    recipes = {
        "bloat a": StubAction(append_lines=5, files_modified=["src/_scratch.py"]),
        "bloat b": StubAction(append_lines=5, files_modified=["src/_scratch.py"]),
    }

    for _ in range(5):
        term = _check_termination(target_repo)
        if term["terminated"]:
            break
        if _git(target_repo, "status", "--porcelain").strip():
            subprocess.run(["git", "reset", "--hard", "HEAD"], cwd=target_repo, check=True)
        cand = json.loads(_sindri(target_repo, "pick-next").stdout)
        if cand is None:
            break
        metric_before = _current_metric_before(target_repo)
        result = run_stub_experiment(
            target_repo, cand["name"], recipes[cand["name"]], current_best=metric_before,
        )
        # All regress → reset-tree reverts + records.
        _apply_result(target_repo, cand, result, metric_before)

    term = _check_termination(target_repo)
    assert term["terminated"] is True
    assert term["reason"] == "pool_empty", term
    assert term["auto_finalize"] is False, term

    log = _git(target_repo, "log", "--oneline").splitlines()
    kept = [line for line in log if "kept:" in line]
    assert kept == [], f"expected no kept commits, got: {kept}"


@pytest.mark.e2e
def test_check_failed_not_retried(target_repo: Path) -> None:
    """A candidate that check_fails must be marked dead after one run, not retried."""
    pool = [{"id": 1, "name": "fails checks", "expected_impact_pct": -10, "files": []}]
    r = _sindri(
        target_repo, "init",
        "--goal", "reduce lines by 10%",
        "--pool-json", json.dumps(pool),
        "--script", ".claude/scripts/sindri/benchmark.py",
    )
    assert r.returncode == 0, r.stderr

    cand = json.loads(_sindri(target_repo, "pick-next").stdout)
    metric_before = _current_metric_before(target_repo)
    result = run_stub_experiment(
        target_repo, cand["name"], StubAction(force_check_failed=True),
        current_best=metric_before,
    )
    assert result["status"] == "check_failed"
    _apply_result(target_repo, cand, result, metric_before)

    # After record-result, pick-next must return null (check_failed is terminal per-candidate).
    nxt = _sindri(target_repo, "pick-next").stdout.strip()
    assert nxt == "null", f"check_failed candidate was re-picked: {nxt!r}"


@pytest.mark.e2e
def test_errored_storm_trips_max_reverts(target_repo: Path) -> None:
    """A storm of errored experiments must trip max_reverts_in_a_row BEFORE the
    pool is exhausted — the runaway halt for a systematically broken setup.

    Pool (11) is larger than max_reverts_in_a_row (7, local default), so if the
    halt didn't fire the loop would burn the whole pool. Checks termination at
    the TOP of each iteration, exactly as the sindri-loop orchestrator does.
    """
    pool = [
        {"id": i, "name": f"err {i}", "expected_impact_pct": -10, "files": []}
        for i in range(1, 12)
    ]
    r = _sindri(
        target_repo, "init",
        "--goal", "reduce lines by 10%",
        "--pool-json", json.dumps(pool),
        "--script", ".claude/scripts/sindri/benchmark.py",
    )
    assert r.returncode == 0, r.stderr

    terminated_reason = None
    for _ in range(len(pool) + 1):
        term = _check_termination(target_repo)
        if term["terminated"]:
            terminated_reason = term["reason"]
            break
        cand = json.loads(_sindri(target_repo, "pick-next").stdout)
        assert cand is not None, "pool drained before the revert halt fired"
        metric_before = _current_metric_before(target_repo)
        result = run_stub_experiment(
            target_repo, cand["name"], StubAction(force_error=True),
            current_best=metric_before,
        )
        _apply_result(target_repo, cand, result, metric_before)

    assert terminated_reason == "max_reverts_in_a_row", terminated_reason
    # Halt fired before exhaustion → pending candidates remain, no kept commits.
    state = json.loads(_sindri(target_repo, "read-state").stdout)
    assert any(c["status"] == "pending" for c in state["pool"]), \
        "revert halt should fire before the pool is exhausted"
    assert "kept:" not in _git(target_repo, "log", "--oneline")

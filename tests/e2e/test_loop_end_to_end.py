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
        if exp["status"] in ("regressed", "inconclusive", "errored", "timeout"):
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

        commit_sha: str | None = None
        if result["status"] == "improved":
            subprocess.run(["git", "add", "-A"], cwd=target_repo, check=True)
            subprocess.run(
                ["git", "commit", "-q", "-m",
                 f"kept: {cand['name']} (Δ{result['metric_value'] - metric_before})"],
                cwd=target_repo, check=True,
            )
            commit_sha = _git(target_repo, "rev-parse", "HEAD").strip()
        else:
            subprocess.run(["git", "reset", "--hard", "HEAD"], cwd=target_repo, check=True)

        payload = build_record_payload(
            candidate_id=cand["id"],
            metric_before=metric_before,
            subagent_result=result,
            commit_sha=commit_sha,
        )
        rec = _sindri(target_repo, "record-result", stdin=payload)
        assert rec.returncode == 0, rec.stderr

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
        # All regress → always reset.
        subprocess.run(["git", "reset", "--hard", "HEAD"], cwd=target_repo, check=True)
        payload = build_record_payload(
            candidate_id=cand["id"], metric_before=metric_before,
            subagent_result=result, commit_sha=None,
        )
        _sindri(target_repo, "record-result", stdin=payload)

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
    payload = build_record_payload(
        candidate_id=cand["id"], metric_before=metric_before,
        subagent_result=result, commit_sha=None,
    )
    rec = _sindri(target_repo, "record-result", stdin=payload)
    assert rec.returncode == 0, rec.stderr

    # After record-result, pick-next must return null (check_failed is terminal per-candidate).
    nxt = _sindri(target_repo, "pick-next").stdout.strip()
    assert nxt == "null", f"check_failed candidate was re-picked: {nxt!r}"

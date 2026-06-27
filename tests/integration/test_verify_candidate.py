"""Integration tests for `verify-candidate` and the commit-kept verification gate.

These prove the measurement seam is closed: the deterministic core re-runs the
benchmark itself, and a keep cannot be committed on a self-reported number.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# A real benchmark: counts non-blank lines in f.py, so the metric reflects the
# actual working tree (an honest improvement lowers it; a lie does not).
_BENCH = (
    "import pathlib\n"
    "n = len([l for l in pathlib.Path('f.py').read_text().splitlines() if l.strip()])\n"
    "print(f'METRIC lines={n}')\n"
)
_BENCH_PATH = ".claude/scripts/sindri/benchmark.py"


def _run_cli(*args: str, cwd: Path, input: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "sindri", *args],
        cwd=cwd, input=input, capture_output=True, text=True,
    )


def _setup(tmp_path: Path, *, baseline_value: float = 5.0) -> None:
    from sindri.core.state import write_state
    from sindri.core.validators import Baseline, Candidate, Goal, Guardrails, SindriState

    subprocess.run(["git", "init", "-b", "main"], check=True, cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], check=True, cwd=tmp_path)
    subprocess.run(["git", "config", "user.name", "t"], check=True, cwd=tmp_path)
    # f.py starts with 5 non-blank lines (== baseline).
    (tmp_path / "f.py").write_text("a = 1\nb = 2\nc = 3\nd = 4\ne = 5\n")
    bench = tmp_path / _BENCH_PATH
    bench.parent.mkdir(parents=True, exist_ok=True)
    bench.write_text(_BENCH)
    (tmp_path / ".gitignore").write_text(".sindri/\n")
    subprocess.run(["git", "add", "-A"], check=True, cwd=tmp_path)
    subprocess.run(["git", "commit", "-m", "base"], check=True, cwd=tmp_path, capture_output=True)
    state = SindriState(
        goal=Goal(metric_name="lines", direction="reduce", target_pct=10.0),
        baseline=Baseline(value=baseline_value, noise_floor=0.1, samples=[5.0, 5.0]),
        pool=[Candidate(id=1, name="a", expected_impact_pct=-40.0)],
        branch="sindri/test",
        started_at=datetime(2026, 6, 19, 10, 0, tzinfo=timezone.utc),
        guardrails=Guardrails(mode="local"),
        mode="local",
    )
    write_state(state, dir=tmp_path / ".sindri" / "current")


def _payload(metric_value: float, status: str = "improved", *, benchmark: bool = True) -> str:
    body = {
        "candidate_id": 1, "metric_before": 5.0,
        "subagent_result": {
            "metric_value": metric_value, "reps_used": 3, "confidence_ratio": 9.9,
            "status": status, "files_modified": ["f.py"],
        },
    }
    if benchmark:
        body["benchmark_cmd"] = _BENCH_PATH  # commit-kept re-measures with this
    return json.dumps(body)


def _append_jsonl_line(tmp_path: Path, obj: dict) -> None:
    """Append a raw JSONL line as the untrusted subagent could (it has Bash)."""
    path = tmp_path / ".sindri" / "current" / "sindri.jsonl"
    with path.open("a") as f:
        f.write(json.dumps(obj) + "\n")


def _head(tmp_path: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, capture_output=True, text=True
    ).stdout.strip()


def _verify_input() -> str:
    return json.dumps({"candidate_id": 1, "benchmark_cmd": _BENCH_PATH})


def _verify_events(tmp_path: Path) -> list[dict]:
    path = tmp_path / ".sindri" / "current" / "sindri.jsonl"
    out = []
    for ln in path.read_text().splitlines():
        rec = json.loads(ln)
        if rec.get("type") == "event" and rec.get("event") == "verify":
            out.append(rec)
    return out


def _kept_commits(tmp_path: Path) -> list[str]:
    out = subprocess.run(
        ["git", "log", "--format=%s"], cwd=tmp_path, capture_output=True, text=True,
    ).stdout
    return [ln for ln in out.splitlines() if ln.startswith("kept:")]


class TestVerifyCandidate:
    def test_confirmed_improvement_verifies(self, tmp_path: Path) -> None:
        _setup(tmp_path)
        (tmp_path / "f.py").write_text("a = 1\nb = 2\n")  # 5 -> 2 lines: a real win
        r = _run_cli("verify-candidate", cwd=tmp_path, input=_verify_input())
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        assert out["verified"] is True
        assert out["status"] == "improved"
        assert out["metric_value"] == 2.0
        ev = _verify_events(tmp_path)
        assert len(ev) == 1 and ev[0]["details"]["verified"] is True
        assert ev[0]["details"]["base_sha"]

    def test_false_improvement_claim_is_caught(self, tmp_path: Path) -> None:
        # The subagent could claim "improved", but the working tree is unchanged
        # (still 5 lines == baseline). Independent measurement says no improvement.
        _setup(tmp_path)
        r = _run_cli("verify-candidate", cwd=tmp_path, input=_verify_input())
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        assert out["verified"] is False
        assert out["status"] == "inconclusive"
        assert out["metric_value"] == 5.0

    def test_tampered_benchmark_is_refused(self, tmp_path: Path) -> None:
        # The subagent edits the measurement instrument to fake a win.
        _setup(tmp_path)
        (tmp_path / "f.py").write_text("a = 1\nb = 2\n")
        (tmp_path / _BENCH_PATH).write_text("print('METRIC lines=0')\n")  # rigged
        r = _run_cli("verify-candidate", cwd=tmp_path, input=_verify_input())
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        assert out["verified"] is False
        assert out["reason"] == "benchmark_tampered"

    def test_benchmark_crash_does_not_verify(self, tmp_path: Path) -> None:
        _setup(tmp_path)
        # Replace AND commit a crashing benchmark so it's the trusted (untampered) one.
        (tmp_path / _BENCH_PATH).write_text("import sys; sys.exit(3)\n")
        subprocess.run(["git", "commit", "-am", "bench"], check=True, cwd=tmp_path, capture_output=True)
        r = _run_cli("verify-candidate", cwd=tmp_path, input=_verify_input())
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout)
        assert out["verified"] is False
        assert out["status"] != "improved"

    def test_no_active_run_exits_nonzero(self, tmp_path: Path) -> None:
        subprocess.run(["git", "init", "-b", "main"], check=True, cwd=tmp_path, capture_output=True)
        r = _run_cli("verify-candidate", cwd=tmp_path, input=_verify_input())
        assert r.returncode != 0


class TestCommitKeptVerificationGate:
    def test_refuses_keep_without_benchmark_cmd(self, tmp_path: Path) -> None:
        # No benchmark_cmd ⇒ commit-kept can't independently measure ⇒ refuse,
        # even though the tree is a real improvement.
        _setup(tmp_path)
        (tmp_path / "f.py").write_text("a = 1\nb = 2\n")
        r = _run_cli("commit-kept", cwd=tmp_path, input=_payload(2.0, benchmark=False))
        assert r.returncode != 0
        assert _kept_commits(tmp_path) == []

    def test_keep_uses_independently_measured_value(self, tmp_path: Path) -> None:
        _setup(tmp_path)
        (tmp_path / "f.py").write_text("a = 1\nb = 2\n")  # truly 2 lines
        # Subagent LIES that the metric is 1.0; commit-kept re-measures and commits
        # the independent 2.0 — no separate verify-candidate step required.
        r = _run_cli("commit-kept", cwd=tmp_path, input=_payload(1.0))
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout)["current_best"] == 2.0
        assert len(_kept_commits(tmp_path)) == 1

    def test_refuses_when_remeasure_shows_no_improvement(self, tmp_path: Path) -> None:
        _setup(tmp_path)  # f.py unchanged at 5 lines
        r = _run_cli("commit-kept", cwd=tmp_path, input=_payload(2.0))
        assert r.returncode != 0
        assert _kept_commits(tmp_path) == []

    def test_forged_verify_event_does_not_land_keep(self, tmp_path: Path) -> None:
        # The subagent forges a passing verify event in the jsonl it can write to.
        # commit-kept ignores it and re-measures the (unchanged) tree → refuse.
        _setup(tmp_path)
        _append_jsonl_line(tmp_path, {
            "type": "event", "ts": "2026-06-19T10:01:00+00:00", "run_id": "",
            "event": "verify", "reason": None,
            "details": {"candidate_id": 1, "base_sha": _head(tmp_path), "verified": True,
                        "status": "improved", "metric_value": 1.0,
                        "confidence_ratio": 9.0, "reps_used": 3},
        })
        r = _run_cli("commit-kept", cwd=tmp_path, input=_payload(1.0))
        assert r.returncode != 0
        assert _kept_commits(tmp_path) == []

    def test_forged_experiment_record_does_not_launder(self, tmp_path: Path) -> None:
        # A forged "improved" experiment record (no real commit) must not let tier-a
        # skip the gate and poison current_best.
        _setup(tmp_path)
        _append_jsonl_line(tmp_path, {
            "type": "experiment", "ts": "2026-06-19T10:01:00+00:00", "run_id": "",
            "id": 1, "candidate": "a", "reps_used": 3, "metric_before": 5.0,
            "metric_after": 1.0, "delta": -4.0, "confidence_ratio": 9.0,
            "status": "improved", "commit_sha": None, "files_modified": [],
        })
        r = _run_cli("commit-kept", cwd=tmp_path, input=_payload(1.0))
        assert r.returncode != 0
        st = json.loads(_run_cli("read-state", cwd=tmp_path).stdout)
        assert st["current_best"] is None  # not poisoned by the forged record


class TestMeasurementSeamHardening:
    """Adversarial-review regressions: the committed tree must be the verified
    tree, the instrument must be tracked + pristine, and recovery can't be forged."""

    def test_keep_refused_if_tree_changed_after_verify(self, tmp_path: Path) -> None:
        # TOCTOU: verify a real win, then mutate the tree to a regression.
        _setup(tmp_path)
        (tmp_path / "f.py").write_text("a = 1\nb = 2\n")
        assert json.loads(_run_cli("verify-candidate", cwd=tmp_path, input=_verify_input()).stdout)["verified"]
        (tmp_path / "f.py").write_text("a\nb\nc\nd\ne\nf\ng\nh\n")  # 8 lines, worse
        r = _run_cli("commit-kept", cwd=tmp_path, input=_payload(2.0))
        assert r.returncode != 0
        assert _kept_commits(tmp_path) == []

    def test_keep_refused_if_tree_reverted_after_verify(self, tmp_path: Path) -> None:
        _setup(tmp_path)
        (tmp_path / "f.py").write_text("a = 1\nb = 2\n")
        assert json.loads(_run_cli("verify-candidate", cwd=tmp_path, input=_verify_input()).stdout)["verified"]
        (tmp_path / "f.py").write_text("a = 1\nb = 2\nc = 3\nd = 4\ne = 5\n")  # back to baseline
        (tmp_path / "unrelated.txt").write_text("x\n")  # keep the commit non-empty
        r = _run_cli("commit-kept", cwd=tmp_path, input=_payload(2.0))
        assert r.returncode != 0
        assert _kept_commits(tmp_path) == []

    def test_untracked_benchmark_is_refused(self, tmp_path: Path) -> None:
        _setup(tmp_path)
        subprocess.run(["git", "rm", "--cached", _BENCH_PATH], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-am", "untrack"], cwd=tmp_path, check=True, capture_output=True)
        (tmp_path / "f.py").write_text("a = 1\nb = 2\n")
        out = json.loads(_run_cli("verify-candidate", cwd=tmp_path, input=_verify_input()).stdout)
        assert out["verified"] is False
        assert out["reason"] == "benchmark_untracked"

    def test_checks_failure_blocks_verification(self, tmp_path: Path) -> None:
        _setup(tmp_path)
        checks = ".claude/scripts/sindri/checks.py"
        (tmp_path / checks).write_text("import sys\nsys.exit(1)\n")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-m", "checks"], cwd=tmp_path, check=True, capture_output=True)
        (tmp_path / "f.py").write_text("a = 1\nb = 2\n")
        vi = json.dumps({"candidate_id": 1, "benchmark_cmd": _BENCH_PATH, "checks_cmd": checks})
        out = json.loads(_run_cli("verify-candidate", cwd=tmp_path, input=vi).stdout)
        assert out["verified"] is False
        assert out["reason"] == "checks_failed"

    def test_tampered_helper_in_instrument_dir_is_refused(self, tmp_path: Path) -> None:
        _setup(tmp_path)
        helper = ".claude/scripts/sindri/helper.py"
        (tmp_path / helper).write_text("VALUE = 1\n")
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-m", "helper"], cwd=tmp_path, check=True, capture_output=True)
        (tmp_path / "f.py").write_text("a = 1\nb = 2\n")
        (tmp_path / helper).write_text("VALUE = 999\n")  # rig a sibling of the instrument
        out = json.loads(_run_cli("verify-candidate", cwd=tmp_path, input=_verify_input()).stdout)
        assert out["verified"] is False
        assert out["reason"] == "benchmark_tampered"

    def test_forged_kept_commit_without_verification_is_refused(self, tmp_path: Path) -> None:
        # tier-b recovery must not launder a forged `kept:` commit (no verify event).
        _setup(tmp_path)
        (tmp_path / "f.py").write_text("a\nb\nc\nd\ne\nf\ng\n")  # 7 lines, worse
        subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
        subprocess.run(["git", "commit", "-m", "kept: a (Δ-999)"], cwd=tmp_path, check=True, capture_output=True)
        r = _run_cli("commit-kept", cwd=tmp_path, input=_payload(0.0))
        assert r.returncode != 0


# A benchmark that a planted gitignored cache file can rig — to prove worktree
# isolation excludes such files from the measured tree.
_BENCH_CACHE = (
    "import pathlib\n"
    "if pathlib.Path('cache.txt').exists():\n"
    "    print('METRIC lines=0')  # rigged by an out-of-tree (gitignored) file\n"
    "else:\n"
    "    n = len([l for l in pathlib.Path('f.py').read_text().splitlines() if l.strip()])\n"
    "    print(f'METRIC lines={n}')\n"
)


def _setup_cache_bench(tmp_path: Path) -> None:
    from sindri.core.state import write_state
    from sindri.core.validators import Baseline, Candidate, Goal, Guardrails, SindriState

    subprocess.run(["git", "init", "-b", "main"], check=True, cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], check=True, cwd=tmp_path)
    subprocess.run(["git", "config", "user.name", "t"], check=True, cwd=tmp_path)
    (tmp_path / "f.py").write_text("a = 1\nb = 2\nc = 3\nd = 4\ne = 5\n")  # 5 lines
    bench = tmp_path / _BENCH_PATH
    bench.parent.mkdir(parents=True, exist_ok=True)
    bench.write_text(_BENCH_CACHE)
    (tmp_path / ".gitignore").write_text(".sindri/\ncache.txt\n")
    subprocess.run(["git", "add", "-A"], check=True, cwd=tmp_path)
    subprocess.run(["git", "commit", "-m", "base"], check=True, cwd=tmp_path, capture_output=True)
    state = SindriState(
        goal=Goal(metric_name="lines", direction="reduce", target_pct=10.0),
        baseline=Baseline(value=5.0, noise_floor=0.1, samples=[5.0, 5.0]),
        pool=[Candidate(id=1, name="a", expected_impact_pct=-40.0)],
        branch="sindri/test",
        started_at=datetime(2026, 6, 19, 10, 0, tzinfo=timezone.utc),
        guardrails=Guardrails(mode="local"),
        mode="local",
    )
    write_state(state, dir=tmp_path / ".sindri" / "current")


class TestWorktreeIsolation:
    def test_gitignored_cache_cannot_rig_the_measurement(self, tmp_path: Path) -> None:
        _setup_cache_bench(tmp_path)
        # No real improvement (f.py still 5 lines), but plant a gitignored cache
        # file that rigs the benchmark to report 0 in the LIVE tree.
        (tmp_path / "cache.txt").write_text("rig")
        live = subprocess.run(
            [sys.executable, _BENCH_PATH], cwd=tmp_path, capture_output=True, text=True
        ).stdout
        assert "lines=0" in live  # the attack works in the live working dir...
        # ...but commit-kept measures in an isolated worktree (no gitignored cache),
        # sees the true 5 lines, and refuses the keep.
        r = _run_cli("commit-kept", cwd=tmp_path, input=_payload(0.0))
        assert r.returncode != 0
        assert _kept_commits(tmp_path) == []

    def test_no_leftover_worktrees_after_measurement(self, tmp_path: Path) -> None:
        _setup(tmp_path)
        (tmp_path / "f.py").write_text("a = 1\n")  # real improvement
        assert _run_cli("commit-kept", cwd=tmp_path, input=_payload(1.0)).returncode == 0
        wts = subprocess.run(
            ["git", "worktree", "list"], cwd=tmp_path, capture_output=True, text=True
        ).stdout.strip().splitlines()
        assert len(wts) == 1, wts  # only the main worktree remains


class TestTierAReMeasure:
    def test_tier_a_uses_remeasured_value_not_forged_record(self, tmp_path: Path) -> None:
        # A real keep lands current_best=2.0; then the subagent FORGES the recorded
        # magnitude to a much-better 0.001. On a tier-a re-run, commit-kept must
        # re-measure the committed tree and keep current_best at the real 2.0.
        _setup(tmp_path)
        (tmp_path / "f.py").write_text("a = 1\nb = 2\n")  # real improvement (5 -> 2)
        assert _run_cli("commit-kept", cwd=tmp_path, input=_payload(2.0)).returncode == 0
        assert json.loads(_run_cli("read-state", cwd=tmp_path).stdout)["current_best"] == 2.0

        jpath = tmp_path / ".sindri" / "current" / "sindri.jsonl"
        forged = []
        for ln in jpath.read_text().splitlines():
            rec = json.loads(ln)
            if rec.get("type") == "experiment":
                rec["metric_after"] = 0.001  # forged "much better" magnitude
            forged.append(json.dumps(rec))
        jpath.write_text("\n".join(forged) + "\n")

        r = _run_cli("commit-kept", cwd=tmp_path, input=_payload(2.0))  # tier-a re-run
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout).get("skipped") is True
        st = json.loads(_run_cli("read-state", cwd=tmp_path).stdout)
        assert st["current_best"] == 2.0  # NOT the forged 0.001

"""Tests for the single-writer wakeup lock (RUNNING sentinel)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sindri.core.lock import LOCK_FILENAME, acquire_lock, release_lock

T0 = datetime(2026, 6, 19, 12, 0, 0, tzinfo=timezone.utc)
MAX_AGE = 100.0  # seconds, for deterministic age tests


class TestAcquire:
    def test_acquire_on_empty_dir(self, tmp_path: Path) -> None:
        r = acquire_lock(dir=tmp_path, max_age_seconds=MAX_AGE, now=T0, token="A")
        assert r.acquired is True
        assert r.took_over_stale is False
        assert (tmp_path / LOCK_FILENAME).exists()
        assert r.holder.token == "A"

    def test_live_holder_blocks(self, tmp_path: Path) -> None:
        acquire_lock(dir=tmp_path, max_age_seconds=MAX_AGE, now=T0, token="A")
        r = acquire_lock(
            dir=tmp_path, max_age_seconds=MAX_AGE, now=T0 + timedelta(seconds=5), token="B"
        )
        assert r.acquired is False
        assert r.holder.token == "A"  # the live holder, not us
        # The sentinel still belongs to A.
        assert "A" in (tmp_path / LOCK_FILENAME).read_text()

    def test_aged_out_holder_taken_over(self, tmp_path: Path) -> None:
        acquire_lock(dir=tmp_path, max_age_seconds=MAX_AGE, now=T0, token="A")
        r = acquire_lock(
            dir=tmp_path, max_age_seconds=MAX_AGE, now=T0 + timedelta(seconds=200), token="C"
        )
        assert r.acquired is True
        assert r.took_over_stale is True
        assert r.holder.token == "C"
        assert "C" in (tmp_path / LOCK_FILENAME).read_text()

    def test_at_exactly_max_age_is_stale(self, tmp_path: Path) -> None:
        # Age == max_age is NOT live (strict <), so it's reclaimable.
        acquire_lock(dir=tmp_path, max_age_seconds=MAX_AGE, now=T0, token="A")
        r = acquire_lock(
            dir=tmp_path, max_age_seconds=MAX_AGE, now=T0 + timedelta(seconds=MAX_AGE), token="C"
        )
        assert r.acquired is True
        assert r.took_over_stale is True

    def test_malformed_sentinel_taken_over(self, tmp_path: Path) -> None:
        (tmp_path / LOCK_FILENAME).write_text("not json at all")
        r = acquire_lock(dir=tmp_path, max_age_seconds=MAX_AGE, now=T0, token="C")
        assert r.acquired is True
        assert r.took_over_stale is True

    def test_sentinel_missing_field_taken_over(self, tmp_path: Path) -> None:
        # Valid JSON but no `token` field — treated as no valid holder.
        (tmp_path / LOCK_FILENAME).write_text(
            '{"pid": 1, "host": "h", "started_at": "2026-06-19T12:00:00+00:00"}'
        )
        r = acquire_lock(dir=tmp_path, max_age_seconds=MAX_AGE, now=T0, token="C")
        assert r.acquired is True
        assert r.took_over_stale is True

    def test_clock_stepped_back_keeps_holder_live(self, tmp_path: Path) -> None:
        # `now` earlier than started_at (NTP step-back) → negative age → the
        # holder is recent, so it stays live and is NOT reclaimed.
        acquire_lock(dir=tmp_path, max_age_seconds=MAX_AGE, now=T0, token="A")
        r = acquire_lock(
            dir=tmp_path, max_age_seconds=MAX_AGE, now=T0 - timedelta(seconds=30), token="B"
        )
        assert r.acquired is False
        assert r.holder.token == "A"

    def test_real_now_roundtrip_without_injection(self, tmp_path: Path) -> None:
        # Defaults (real now/pid/host/token) must produce a usable lock.
        r = acquire_lock(dir=tmp_path, max_age_seconds=MAX_AGE)
        assert r.acquired is True
        assert r.holder.token  # non-empty generated token
        assert r.holder.pid > 0


class TestRelease:
    def test_release_matching_token_removes(self, tmp_path: Path) -> None:
        acquire_lock(dir=tmp_path, max_age_seconds=MAX_AGE, now=T0, token="A")
        assert release_lock(dir=tmp_path, token="A") is True
        assert not (tmp_path / LOCK_FILENAME).exists()

    def test_release_wrong_token_is_noop(self, tmp_path: Path) -> None:
        acquire_lock(dir=tmp_path, max_age_seconds=MAX_AGE, now=T0, token="A")
        assert release_lock(dir=tmp_path, token="WRONG") is False
        assert (tmp_path / LOCK_FILENAME).exists()  # still A's

    def test_release_missing_file_is_false(self, tmp_path: Path) -> None:
        assert release_lock(dir=tmp_path, token="A") is False

    def test_acquire_after_release(self, tmp_path: Path) -> None:
        acquire_lock(dir=tmp_path, max_age_seconds=MAX_AGE, now=T0, token="A")
        release_lock(dir=tmp_path, token="A")
        # A fresh wakeup (even within max_age) acquires cleanly after release.
        r = acquire_lock(
            dir=tmp_path, max_age_seconds=MAX_AGE, now=T0 + timedelta(seconds=5), token="B"
        )
        assert r.acquired is True
        assert r.took_over_stale is False

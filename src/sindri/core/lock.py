"""Single-writer lock for the wakeup loop — a ``RUNNING`` sentinel file.

A wakeup spans several short-lived backend processes (every ``forge.sh`` call is
a fresh ``uvx python -m sindri`` process) plus a long ``Task`` dispatch, so a
held-fd ``flock`` cannot span the *wakeup*. The cross-process, wakeup-spanning
lock is therefore a sentinel FILE (``.sindri/current/RUNNING``) that outlives any
single process.

**Liveness is AGE-BASED, not PID-based.** The process that writes ``RUNNING``
(``acquire-lock``) exits immediately, so its pid is dead by the time the next
wakeup checks — an ``os.kill`` probe would mark every lock stale. A holder is
"live" while the sentinel is younger than ``max_age_seconds`` (a small multiple
of the per-experiment timeout — the longest a legitimate wakeup can hold it);
past that it is taken over. ``pid``/``host`` are forensic metadata only. (This
assumes a single host with a roughly stable wall clock; a large forward NTP jump
could prematurely age out a live holder — the 2x margin makes that unlikely.)

**The acquire/release *decision* is serialized by a short-lived ``flock``** on a
sidecar file (``.sindri/current/.RUNNING.acquire``). flock can't span the
wakeup, but it cleanly serializes the brief read-decide-write of a single
``acquire-lock`` process against another — so the sentinel write is a **true
single-winner**, not a racy claim-then-verify.

**Release is explicit and TOKEN-scoped.** ``acquire-lock`` returns a token; the
orchestrator threads it to ``release-lock``, which removes ``RUNNING`` only on a
token match — so a wakeup can never release another's lock. A crashed
orchestrator's lock is reclaimed by the age fallback.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import socket
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

LOCK_FILENAME = "RUNNING"
_ACQUIRE_LOCK_FILENAME = ".RUNNING.acquire"

# A legitimate wakeup holds the lock for at most one experiment; 2x the
# per-experiment timeout gives margin before a holder is treated as wedged.
STALE_AGE_MULTIPLIER = 2


@dataclass(frozen=True)
class LockHolder:
    pid: int
    host: str
    started_at: datetime
    token: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "pid": self.pid,
                "host": self.host,
                "started_at": self.started_at.isoformat(),
                "token": self.token,
            }
        )


@dataclass(frozen=True)
class LockResult:
    acquired: bool
    holder: LockHolder  # us if acquired; the blocking holder if not
    took_over_stale: bool


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


@contextlib.contextmanager
def _acquire_op_lock(dir: Path) -> Iterator[None]:
    """flock a sidecar file for the duration of one acquire/release decision.

    Serializes concurrent ``acquire-lock`` / ``release-lock`` processes on this
    host so the sentinel read-decide-write is atomic across them.
    """
    lock_path = dir / _ACQUIRE_LOCK_FILENAME
    f = lock_path.open("w")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        finally:
            f.close()


def _read_holder(path: Path) -> LockHolder | None:
    """Return the current holder, or None if absent/empty/malformed."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    try:
        d = json.loads(text)
        return LockHolder(
            pid=int(d["pid"]),
            host=str(d["host"]),
            started_at=datetime.fromisoformat(d["started_at"]),
            token=str(d["token"]),
        )
    except (ValueError, KeyError, TypeError):
        return None  # malformed / missing field → no valid holder → eligible for takeover


def _is_live(holder: LockHolder, *, now: datetime, max_age_seconds: float) -> bool:
    age = (now - holder.started_at).total_seconds()
    if age < 0:
        # Clock stepped back since acquire (NTP correction) → the holder is
        # actually recent; treat as live rather than reclaiming a fresh lock.
        return True
    return age < max_age_seconds


def _atomic_write(path: Path, content: str) -> None:
    tmp = path.with_name(f"{path.name}.tmp.{uuid.uuid4().hex}")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)  # no-op after a successful replace


def acquire_lock(
    *,
    dir: Path = Path(".sindri/current"),
    max_age_seconds: float,
    now: datetime | None = None,
    pid: int | None = None,
    host: str | None = None,
    token: str | None = None,
) -> LockResult:
    """Try to acquire the single-writer lock for this wakeup.

    Returns ``acquired=True`` if we now hold it (``took_over_stale`` when we
    reclaimed an aged-out/malformed sentinel), or ``acquired=False`` with the
    blocking holder when a live wakeup already holds it. The decision is
    serialized by ``flock``, so the outcome is a true single-winner.
    """
    dir.mkdir(parents=True, exist_ok=True)
    path = dir / LOCK_FILENAME
    now = _now() if now is None else now
    me = LockHolder(
        pid=os.getpid() if pid is None else pid,
        host=socket.gethostname() if host is None else host,
        started_at=now,
        token=token or uuid.uuid4().hex,
    )
    with _acquire_op_lock(dir):
        holder = _read_holder(path)
        if holder is not None and _is_live(holder, now=now, max_age_seconds=max_age_seconds):
            return LockResult(acquired=False, holder=holder, took_over_stale=False)
        # Any pre-existing sentinel here is stale (aged-out) or malformed — either
        # way we're reclaiming it. Key on file existence, not holder validity.
        took_over = path.exists()
        _atomic_write(path, me.to_json())
        return LockResult(acquired=True, holder=me, took_over_stale=took_over)


def release_lock(*, dir: Path = Path(".sindri/current"), token: str) -> bool:
    """Remove ``RUNNING`` iff its token matches ours. Returns True if removed."""
    path = dir / LOCK_FILENAME
    if not dir.exists():
        return False
    with _acquire_op_lock(dir):
        holder = _read_holder(path)
        if holder is None or holder.token != token:
            return False
        path.unlink(missing_ok=True)
        return True

"""State file I/O: sindri.md (frontmatter YAML + markdown body) and sindri.jsonl.

sindri.md is rendered with frontmatter containing the full SindriState as JSON
(serialized via pydantic), followed by a human-readable markdown body. On read,
we parse only the frontmatter — the body is for humans.

sindri.jsonl is append-only; each line is one JSON-serialized pydantic model.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from sindri.core.validators import JsonlRecord, SindriState


class StateIOError(Exception):
    """Raised when state files can't be read or are malformed."""


def state_digest(*, dir: Path = Path(".sindri/current")) -> str:
    """A sha256 fingerprint of the run's protected state (sindri.jsonl + sindri.md).

    The orchestrator snapshots this before dispatching the (untrusted) experiment
    subagent and re-checks it afterward — a change means the subagent wrote state it
    must not (forged jsonl records/events poisoning counters/termination/keeps). This
    is the .sindri twin of the step-6a git-tamper check; the expected value lives in
    the orchestrator's tick context, not on disk, so the subagent can't forge it.
    """
    import hashlib

    h = hashlib.sha256()
    for name in ("sindri.jsonl", "sindri.md"):
        p = dir / name
        h.update(name.encode())
        try:
            h.update(b"\x00" + p.read_bytes() + b"\x00")
        except OSError:
            h.update(b"\x00<absent>\x00")
    return h.hexdigest()


_FRONTMATTER_DELIM = "---\n"

# Type adapter for the JsonlRecord union — pydantic uses the discriminator `type`
# to pick the right subclass at parse time.
_jsonl_adapter: TypeAdapter[JsonlRecord] = TypeAdapter(JsonlRecord)


def write_state(state: SindriState, *, dir: Path = Path(".sindri/current")) -> None:
    """Atomically write state to `<dir>/sindri.md` (JSON frontmatter + body).

    The run's only source of truth must never be left half-written by a crash
    (OOM, laptop sleep, Ctrl-C) during an unattended run. We write to a temp
    file, ``fsync`` it, keep the prior good file as ``sindri.md.bak``, then
    ``os.replace`` — atomic on POSIX, so ``sindri.md`` is always either the old
    or the new content, never torn.
    """
    dir.mkdir(parents=True, exist_ok=True)
    path = dir / "sindri.md"
    tmp = path.with_name(path.name + ".tmp")
    content = (
        f"{_FRONTMATTER_DELIM}{state.model_dump_json(indent=2)}\n"
        f"{_FRONTMATTER_DELIM}\n{_render_human_body(state)}"
    )
    with tmp.open("w", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
    if path.exists():
        # Preserve the last good state so a corrupt write can be rolled back.
        shutil.copy2(path, path.with_name(path.name + ".bak"))
    os.replace(tmp, path)


def _parse_state_file(path: Path) -> SindriState:
    """Parse one sindri.md file's frontmatter; raise StateIOError on any problem."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith(_FRONTMATTER_DELIM):
        raise StateIOError(f"state file {path} missing frontmatter delimiter")
    try:
        body_start = text.index(_FRONTMATTER_DELIM, len(_FRONTMATTER_DELIM))
    except ValueError as e:
        # Truncated mid-frontmatter (the partial-write corruption case): no
        # closing delimiter. Surface as StateIOError, not a bare ValueError.
        raise StateIOError(f"state file {path} has no closing frontmatter delimiter") from e
    fm = text[len(_FRONTMATTER_DELIM):body_start]
    try:
        return SindriState.model_validate_json(fm)
    except ValidationError as e:
        raise StateIOError(f"invalid state in {path}: {e}") from e


def read_state(*, dir: Path = Path(".sindri/current")) -> SindriState:
    """Read and validate sindri.md's frontmatter into a SindriState.

    If the primary file exists but is corrupt (e.g. a partial write from a
    crash), fall back to the ``sindri.md.bak`` snapshot left by `write_state`.
    """
    path = dir / "sindri.md"
    if not path.exists():
        raise StateIOError(f"state file not found: {path}")
    try:
        return _parse_state_file(path)
    except StateIOError:
        bak = path.with_name(path.name + ".bak")
        if bak.exists():
            try:
                state = _parse_state_file(bak)
            except StateIOError:
                raise  # both corrupt — re-raise the primary error
            else:
                print(
                    f"sindri: warning: {path} was unreadable; recovered from {bak}",
                    file=sys.stderr,
                )
                return state
        raise


def append_jsonl(
    record: JsonlRecord,
    *,
    path: Path = Path(".sindri/current/sindri.jsonl"),
) -> None:
    """Append a single pydantic record as one line to the jsonl file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = record.model_dump_json()
    # Safe because sindri is a single-writer process per .sindri/current/.
    # The earlier comment cited POSIX PIPE_BUF atomicity, which only applies
    # to pipes — regular file writes of any size race across processes.
    # fsync so the record (esp. the terminated record that gates finalize)
    # survives a power loss; read_jsonl tolerates a torn tail regardless.
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())


def read_jsonl(path: Path) -> list[JsonlRecord]:
    """Read all records from a jsonl file.

    Skips malformed lines rather than refusing to read at all — a partial
    write after a crash shouldn't block access to valid records. Every skip
    is surfaced on stderr so a silently truncated PR body is never
    attributed to "no activity" by a human reviewer.
    """
    if not path.exists():
        return []
    out: list[JsonlRecord] = []
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
            rec = _jsonl_adapter.validate_python(raw)
            out.append(rec)
        except (json.JSONDecodeError, ValidationError) as e:
            print(
                f"sindri: warning: skipping malformed jsonl line {line_no} in {path}: {e}",
                file=sys.stderr,
            )
            continue
    return out


def _render_human_body(state: SindriState) -> str:
    """Render a human-readable markdown body below the frontmatter.

    The source of truth is the frontmatter; this body is for humans who open
    sindri.md in an editor.
    """
    lines: list[str] = []
    lines.append("# Goal\n")
    sign = "−" if state.goal.direction == "reduce" else "+"
    lines.append(
        f"{state.goal.direction.title()} `{state.goal.metric_name}` by {state.goal.target_pct}%. "
        f"Baseline {state.baseline.value:,.0f} → target {sign}{state.goal.target_pct}%.\n"
    )
    lines.append("## Pool\n")
    pending = [c for c in state.pool if c.status == "pending"]
    kept = [c for c in state.pool if c.status == "kept"]
    reverted = [c for c in state.pool if c.status == "reverted"]
    dead = [c for c in state.pool if c.status in {"errored", "check_failed"}]
    if pending:
        lines.append("### Pending\n")
        for c in pending:
            lines.append(f"- [ ] **{c.name}** *(expected: {c.expected_impact_pct:+.1f}%)*")
        lines.append("")
    if kept:
        lines.append("### Kept ✓\n")
        for c in kept:
            lines.append(f"- [x] **{c.name}** — Δ {c.expected_impact_pct:+.1f}%")
        lines.append("")
    if reverted:
        lines.append("### Reverted ✗\n")
        for c in reverted:
            lines.append(f"- [×] **{c.name}**")
        lines.append("")
    if dead:
        lines.append("### Dead ends\n")
        for c in dead:
            lines.append(f"- [⚠] **{c.name}** — {c.status}")
        lines.append("")
    return "\n".join(lines)

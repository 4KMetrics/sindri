"""State file I/O: sindri.md (frontmatter YAML + markdown body) and sindri.jsonl.

sindri.md is rendered with frontmatter containing the full SindriState as JSON
(serialized via pydantic), followed by a human-readable markdown body. On read,
we parse only the frontmatter — the body is for humans.

sindri.jsonl is append-only; each line is one JSON-serialized pydantic model.
"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from sindri.core.validators import JsonlRecord, SindriState


class StateIOError(Exception):
    """Raised when state files can't be read or are malformed."""


_FRONTMATTER_DELIM = "---\n"

# Type adapter for the JsonlRecord union — pydantic uses the discriminator `type`
# to pick the right subclass at parse time.
_jsonl_adapter: TypeAdapter[JsonlRecord] = TypeAdapter(JsonlRecord)


def write_state(state: SindriState, *, dir: Path = Path(".sindri/current")) -> None:
    """Write state to `<dir>/sindri.md` as JSON frontmatter + markdown body."""
    dir.mkdir(parents=True, exist_ok=True)
    path = dir / "sindri.md"
    frontmatter = state.model_dump_json(indent=2)
    body = _render_human_body(state)
    path.write_text(
        f"{_FRONTMATTER_DELIM}{frontmatter}\n{_FRONTMATTER_DELIM}\n{body}",
        encoding="utf-8",
    )


def read_state(*, dir: Path = Path(".sindri/current")) -> SindriState:
    """Read and validate sindri.md's frontmatter into a SindriState."""
    path = dir / "sindri.md"
    if not path.exists():
        raise StateIOError(f"state file not found: {path}")
    text = path.read_text(encoding="utf-8")
    if not text.startswith(_FRONTMATTER_DELIM):
        raise StateIOError(f"state file {path} missing frontmatter delimiter")
    body_start = text.index(_FRONTMATTER_DELIM, len(_FRONTMATTER_DELIM))
    fm = text[len(_FRONTMATTER_DELIM):body_start]
    try:
        return SindriState.model_validate_json(fm)
    except ValidationError as e:
        raise StateIOError(f"invalid state in {path}: {e}") from e


def append_jsonl(
    record: JsonlRecord,
    *,
    path: Path = Path(".sindri/current/sindri.jsonl"),
) -> None:
    """Append a single pydantic record as one line to the jsonl file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = record.model_dump_json()
    # Single write in append mode — on POSIX, a write() under PIPE_BUF is
    # atomic; sindri is a single-writer process so this is documentation
    # of intent more than a concurrency guarantee.
    with path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_jsonl(path: Path) -> list[JsonlRecord]:
    """Read all records from a jsonl file. Skips malformed lines (returns only valid)."""
    if not path.exists():
        return []
    out: list[JsonlRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
            rec = _jsonl_adapter.validate_python(raw)
            out.append(rec)
        except (json.JSONDecodeError, ValidationError):
            # Skip malformed lines — a partial-write after a crash is
            # recoverable and shouldn't block reading valid records.
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

"""Parse `METRIC <name>=<number>` lines from benchmark stdout."""
from __future__ import annotations

import re

_METRIC_RE = re.compile(
    r"""
    ^\s*METRIC\s+
    (?P<name>[a-z][a-z0-9_]*)
    \s*=\s*
    (?P<value>-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)
    \s*$
    """,
    re.VERBOSE,
)


class MetricParseError(ValueError):
    """Raised when stdout does not contain a parseable METRIC line."""


def parse_metric_line(output: str, *, expected_name: str | None = None) -> tuple[str, float]:
    """Parse the LAST `METRIC name=value` line from `output`.

    If `expected_name` is provided, the parsed name must match.
    Multiple METRIC lines are allowed; the last one wins (per the spec's
    "emit the final METRIC line" contract).

    Raises:
        MetricParseError: if no METRIC line is present, or if the parsed
            name doesn't match `expected_name`, or if the value isn't
            a valid number.
    """
    last_match: re.Match[str] | None = None
    for line in output.splitlines():
        m = _METRIC_RE.match(line)
        if m is not None:
            last_match = m

    if last_match is None:
        raise MetricParseError("no METRIC line in output")

    name = last_match.group("name")
    value_str = last_match.group("value")
    try:
        value = float(value_str)
    except ValueError as e:  # pragma: no cover — regex already constrains
        raise MetricParseError(f"failed to parse {value_str!r} as number") from e

    if expected_name is not None and name != expected_name:
        raise MetricParseError(f"metric name {name!r} but expected {expected_name!r}")

    return name, value

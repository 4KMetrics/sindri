"""Tests for METRIC line parsing."""
from __future__ import annotations

import pytest

from sindri.core.metric import MetricParseError, parse_metric_line


class TestParseMetricLine:
    def test_simple_integer(self) -> None:
        name, value = parse_metric_line("METRIC bundle_bytes=842000")
        assert name == "bundle_bytes"
        assert value == 842000.0

    def test_simple_float(self) -> None:
        _, value = parse_metric_line("METRIC test_duration_s=12.5")
        assert value == 12.5

    def test_scientific_notation(self) -> None:
        _, value = parse_metric_line("METRIC big=1.5e6")
        assert value == 1_500_000.0

    def test_negative_value(self) -> None:
        _, value = parse_metric_line("METRIC delta=-42.5")
        assert value == -42.5

    def test_takes_last_metric_line_when_multiple(self) -> None:
        output = """\
INFO: build starting
METRIC bundle_bytes=900000
METRIC bundle_bytes=842000
Build complete.
"""
        _, value = parse_metric_line(output)
        assert value == 842000.0  # last wins

    def test_ignores_surrounding_text(self) -> None:
        output = "prefix text\n  METRIC x=42  \ntrailing text\n"
        name, value = parse_metric_line(output)
        assert name == "x"
        assert value == 42.0

    def test_expected_name_validation(self) -> None:
        _, value = parse_metric_line("METRIC bundle_bytes=42", expected_name="bundle_bytes")
        assert value == 42.0

    def test_expected_name_mismatch_raises(self) -> None:
        with pytest.raises(MetricParseError, match="expected 'foo'"):
            parse_metric_line("METRIC bar=42", expected_name="foo")

    def test_missing_metric_raises(self) -> None:
        with pytest.raises(MetricParseError, match="no METRIC line"):
            parse_metric_line("just some build output\nwith no metric\n")

    def test_malformed_number_raises(self) -> None:
        with pytest.raises(MetricParseError, match="no METRIC line"):
            # Regex won't match "not-a-number" as a value, so this falls under "no METRIC line"
            parse_metric_line("METRIC x=not-a-number")

    def test_empty_output_raises(self) -> None:
        with pytest.raises(MetricParseError):
            parse_metric_line("")

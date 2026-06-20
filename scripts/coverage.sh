#!/usr/bin/env bash
# Accurate coverage, including cli.py — which the integration/e2e suites exercise
# via `python -m sindri` subprocesses (so a plain `coverage run` misses it and
# reports cli.py as ~untested, misleading reviewers).
#
# This sets COVERAGE_PROCESS_START + puts scripts/cov (a sitecustomize.py) on
# PYTHONPATH, so each subprocess records its own .coverage.* file; `coverage
# combine` then merges them with the in-process data.
#
# Usage: ./scripts/coverage.sh [extra pytest args]   e.g. ./scripts/coverage.sh -m "not e2e"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export COVERAGE_PROCESS_START="$ROOT/pyproject.toml"
export PYTHONPATH="$ROOT/scripts/cov${PYTHONPATH:+:$PYTHONPATH}"
# Subprocesses run with cwd=<test tmp dir>; pin the data file to the repo root
# (absolute) so their parallel .coverage.* files land here and combine finds them.
export COVERAGE_FILE="$ROOT/.coverage"

coverage erase
coverage run -m pytest -q "$@"
coverage combine
coverage report

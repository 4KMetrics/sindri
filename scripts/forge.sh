#!/usr/bin/env bash
# sindri forge — backend launcher.
#
# Resolves the pinned sindri-forge version from the plugin manifest and runs the
# Python backend in an isolated environment via uvx. Centralizes:
#   - version pinning (matched to .claude-plugin/plugin.json)
#   - uv presence check (friendly message, never a traceback)
#   - first-run fetch notice (stderr only; stdout stays clean for JSON parsers)
#   - local-dev source override via SINDRI_FORGE_SOURCE (a path or package spec)
#
# Usage: forge.sh <sindri-subcommand> [args...]
# All wrapper diagnostics go to stderr; the backend's stdout passes through clean.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MANIFEST="$PLUGIN_ROOT/.claude-plugin/plugin.json"

# Read version from the manifest WITHOUT python (uv may be bootstrapping python).
VERSION="$( { grep -m1 '"version"' "$MANIFEST" || true; } \
  | sed -E 's/.*"version"[[:space:]]*:[[:space:]]*"([^"]+)".*/\1/' )"
if [ -z "$VERSION" ]; then
  echo "sindri: could not read version from $MANIFEST" >&2
  exit 1
fi

# Default to the pinned PyPI package; allow a local path/spec override for dev.
SOURCE="${SINDRI_FORGE_SOURCE:-sindri-forge==$VERSION}"

# Debug hook (tests): print resolved source and exit before any uv use.
if [ "${SINDRI_FORGE_DEBUG:-}" = "1" ]; then
  echo "FORGE_SOURCE=$SOURCE" >&2
  exit 0
fi

# uv presence check — friendly, copy-pasteable, no traceback.
if ! command -v uv >/dev/null 2>&1; then
  cat >&2 <<'MSG'
sindri needs `uv` (it runs the backend in an isolated environment).
Install it, then re-run /sindri:
  curl -LsSf https://astral.sh/uv/install.sh | sh
MSG
  exit 1
fi

# First-run fetch notice (stderr), only for the pinned package and only once
# per version. Skipped when a source override is set (local dev doesn't fetch).
if [ -z "${SINDRI_FORGE_SOURCE:-}" ]; then
  CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/sindri"
  WARMED="$CACHE_DIR/warmed-$VERSION"
  if [ ! -e "$WARMED" ]; then
    echo "Fetching sindri backend (first run only)…" >&2
  fi
fi

set +e
uvx --from "$SOURCE" python -m sindri "$@"
status=$?
set -e

# Mark this version warmed so the notice only shows once.
if [ "$status" -eq 0 ] && [ -z "${SINDRI_FORGE_SOURCE:-}" ]; then
  mkdir -p "$CACHE_DIR" 2>/dev/null && : > "$WARMED" 2>/dev/null || true
fi
exit "$status"

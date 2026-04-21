#!/usr/bin/env bash
# sindri plugin installer — one-shot setup for local-dev installs.
#
# Does three things:
#   1. Installs the `sindri` Python package into the active environment.
#   2. Symlinks this plugin directory into ~/.claude/plugins/sindri so
#      Claude Code discovers it.
#   3. Prints next steps.
#
# Idempotent — rerunning after upstream changes just reinstalls the
# package and refreshes the symlink.
#
# Usage:
#   ./scripts/install-plugin.sh
#
# Exit 0 on success, non-zero on any failure.

set -euo pipefail

SINDRI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLAUDE_PLUGINS="${CLAUDE_PLUGINS_DIR:-$HOME/.claude/plugins}"
LINK="$CLAUDE_PLUGINS/sindri"

PYBIN="${SINDRI_PYTHON:-$(command -v python3 || command -v python)}"
if [[ -z "$PYBIN" ]]; then
  echo "error: no python3/python on PATH. Install Python 3.10+ and retry." >&2
  exit 1
fi

echo ">> Installing sindri into $PYBIN from $SINDRI_DIR"
if command -v uv >/dev/null 2>&1; then
  uv pip install --python "$PYBIN" -e "$SINDRI_DIR"
else
  "$PYBIN" -m pip install -e "$SINDRI_DIR"
fi

echo ">> Linking plugin into $CLAUDE_PLUGINS"
mkdir -p "$CLAUDE_PLUGINS"
ln -sfn "$SINDRI_DIR" "$LINK"

echo ">> Verifying CLI"
"$PYBIN" -m sindri --version

cat <<EOF

OK. Sindri is installed.

Next steps:
  1. Restart Claude Code so the plugin is picked up.
  2. In a repo you want to optimize, run:
       /sindri <goal>            e.g. /sindri reduce bundle_bytes by 15%
     or                          /sindri status / stop / clear
  3. See README.md + docs/DOGFOOD.md for a guided first-run walkthrough.

Plugin link: $LINK -> $SINDRI_DIR
EOF

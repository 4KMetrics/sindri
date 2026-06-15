#!/usr/bin/env bash
# sindri plugin installer — local-dev symlink helper.
#
# Symlinks this plugin directory into ~/.claude/plugins/sindri so Claude Code
# discovers it. The Python backend is NOT installed here — it is fetched on
# demand by uvx (see scripts/forge.sh). To test LOCAL Python edits, export
# SINDRI_FORGE_SOURCE pointing at this repo before running /sindri:forge:
#   export SINDRI_FORGE_SOURCE="$(pwd)"
#
# Idempotent. Usage: ./scripts/install-plugin.sh
# Exit 0 on success, non-zero on any failure.

set -euo pipefail

SINDRI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLAUDE_PLUGINS="${CLAUDE_PLUGINS_DIR:-$HOME/.claude/plugins}"
LINK="$CLAUDE_PLUGINS/sindri"

echo ">> Linking plugin into $CLAUDE_PLUGINS"
mkdir -p "$CLAUDE_PLUGINS"
ln -sfn "$SINDRI_DIR" "$LINK"

cat <<EOF

OK. Sindri plugin linked.

Next steps:
  1. Run /reload-plugins in Claude Code (or relaunch) so the plugin is picked up.
  2. In a repo you want to optimize, run:
       /sindri:forge <goal>      e.g. /sindri:forge reduce bundle_bytes by 15%
     or                          /sindri:status  /sindri:stop  /sindri:clear  /sindri:setup
  3. See README.md + docs/DOGFOOD.md for a guided first-run walkthrough.

The Python backend is fetched on demand by uvx — no pip install needed.
To test local backend edits: export SINDRI_FORGE_SOURCE="$SINDRI_DIR"

Plugin link: $LINK -> $SINDRI_DIR
EOF

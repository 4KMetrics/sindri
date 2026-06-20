#!/usr/bin/env bash
# sindri manual smoke test
# Runs the full backend lifecycle (through the forge.sh/uvx wrapper, against local
# source) in a disposable temp repo — no Claude, no PR.
# This is the "did I break the plumbing" check before pushing.
#
# Usage: ./scripts/smoke.sh
# Exit 0 on success, non-zero on any failure.

set -euo pipefail

SINDRI_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo ">> temp repo: $TMP"
cd "$TMP"
git init -q
git config user.email "smoke@example.com"
git config user.name "Smoke"
mkdir -p src .claude/scripts/sindri
for f in a b c; do printf 'x = 1\n%.0s' {1..10} > "src/${f}.py"; done
cat > .claude/scripts/sindri/benchmark.py <<'PY'
#!/usr/bin/env python3
from pathlib import Path
total = sum(1 for p in Path("src").rglob("*.py") for ln in p.read_text().splitlines() if ln.strip())
print(f"METRIC lines={total}")
PY
chmod +x .claude/scripts/sindri/benchmark.py
echo ".sindri/" > .gitignore
git add -A && git commit -q -m "seed"

# Exercise the real uvx launch path, but against THIS working tree (not PyPI).
export SINDRI_FORGE_SOURCE="$SINDRI_REPO"
FORGE="$SINDRI_REPO/scripts/forge.sh"

POOL_JSON='[{"id":1,"name":"dummy","expected_impact_pct":-10,"files":[]}]'

echo ">> sindri init"
"$FORGE" init \
  --goal "reduce lines by 10%" \
  --pool-json "$POOL_JSON" \
  --script .claude/scripts/sindri/benchmark.py

echo ">> validate-benchmark"
"$FORGE" validate-benchmark

echo ">> detect-mode"
echo '{"baseline_samples": [30.0, 30.0, 30.0]}' | "$FORGE" detect-mode --script .claude/scripts/sindri/benchmark.py

echo ">> read-state"
"$FORGE" read-state | python3 -c "import json, sys; print('  pool size:', len(json.load(sys.stdin).get('pool', [])))"

echo ">> pick-next"
"$FORGE" pick-next

echo ">> check-termination"
echo '{"experiments_run": 0, "consecutive_reverts": 0}' | "$FORGE" check-termination

# Exercise the MUTATION path — record-result is the one write that "must never
# silently fail", and generate-pr-body reads the audit log it produces. The
# read-only path above would pass even if these regressed.
echo ">> record-result (improved)"
RECORD_JSON='{"candidate_id":1,"metric_before":30.0,"subagent_result":{"metric_value":27.0,"reps_used":3,"confidence_ratio":5.0,"status":"improved","files_modified":["src/a.py"]}}'
echo "$RECORD_JSON" | "$FORGE" record-result | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['ok'] and d['new_status']=='kept', d; print('  ->', d['new_status'])"

echo ">> generate-pr-body (must be non-empty)"
BODY="$("$FORGE" generate-pr-body)"
[ -n "$BODY" ] || { echo "FAIL: generate-pr-body produced no output" >&2; exit 1; }
echo "  pr body: ${#BODY} chars"

echo ">> status"
"$FORGE" status

echo ">> OK — plumbing works."

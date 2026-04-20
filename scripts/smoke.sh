#!/usr/bin/env bash
# sindri manual smoke test
# Runs the full Python-level lifecycle in a disposable temp repo — no Claude, no PR.
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

export PYTHONPATH="$SINDRI_REPO/src:${PYTHONPATH:-}"

POOL_JSON='[{"id":1,"name":"dummy","expected_impact_pct":-10,"files":[]}]'

echo ">> sindri init"
python -m sindri init \
  --goal "reduce lines by 10%" \
  --pool-json "$POOL_JSON" \
  --script .claude/scripts/sindri/benchmark.py

echo ">> validate-benchmark"
python -m sindri validate-benchmark

echo ">> detect-mode"
echo '{"baseline_samples": [30.0, 30.0, 30.0]}' | python -m sindri detect-mode --script .claude/scripts/sindri/benchmark.py

echo ">> read-state"
python -m sindri read-state | python -c "import json, sys; print('  pool size:', len(json.load(sys.stdin).get('pool', [])))"

echo ">> pick-next"
python -m sindri pick-next

echo ">> check-termination"
echo '{"experiments_run": 0, "consecutive_reverts": 0}' | python -m sindri check-termination

echo ">> status"
python -m sindri status

echo ">> OK — plumbing works."

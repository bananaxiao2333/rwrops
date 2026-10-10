#!/usr/bin/env bash
# rwrops acceptance gate. Run after every change.
#
#   ./gate.sh                  # compare against the saved baselines in .gate/
#   ./gate.sh /path/to/basedir # compare against <basedir>/<package>.json
#
# Four checks, not a test framework. If one fails, stop and look.
#
# Every package under dist/packages/ gets a baseline in .gate/<package>.json,
# refreshed after a passing run, so the next ./gate.sh tells you how each
# package changed. Baselines live at the repo root rather than under dist/,
# because everything under dist/ is uploaded to the CDN.
set -uo pipefail
cd "$(dirname "$0")"

BASEDIR="${1:-.gate}"
FAIL=0

run() { uv run python main.py >"$1" 2>&1; }

# sha256 + path for every package result.json, in a fixed order. This is the
# whole-output fingerprint; LC_ALL=C sort makes the order a property of the
# path list, not of the locale.
manifest() {
  find dist/packages -name result.json 2>/dev/null | LC_ALL=C sort | while read -r f; do
    printf "%s  %s\n" "$(shasum -a 256 "$f" | cut -d' ' -f1)" "$f"
  done
}
digest() { manifest | shasum -a 256 | cut -d' ' -f1; }

echo "── gate 1/4: pipeline ──────────────────────────────"
if ! run /tmp/gate_a.log; then
  echo "FAIL: main.py exited non-zero"
  tail -30 /tmp/gate_a.log
  exit 1
fi
grep -E "Wrote result.json|Traceback|CRITICAL" /tmp/gate_a.log | tail -3
A=$(digest)
NPKG=$(manifest | wc -l | tr -d ' ')
echo "result.json sha256 ${A:0:16}…  (${NPKG} packages)"

echo "── gate 2/4: determinism (rerun, same bytes?) ──────"
BEFORE=$(manifest)
run /tmp/gate_b.log
AFTER=$(manifest)
if [ "$BEFORE" = "$AFTER" ]; then
  echo "OK: two runs produced identical output"
else
  echo "FAIL: non-deterministic — these packages differ between runs:"
  diff <(echo "$BEFORE") <(echo "$AFTER") | head -20
  echo "      (os.walk order / find_file_in_package_paths ties / layer order)"
  FAIL=1
fi

echo "── gate 3/4: drop counters ─────────────────────────"
if grep -q "\[gate\]" /tmp/gate_a.log; then
  grep -o "\[gate\].*" /tmp/gate_a.log | sed 's/^/  /'
else
  echo "  (none — nothing was dropped, or instrumentation is missing)"
fi

echo "── gate 4/4: diff vs baselines in ${BASEDIR}/ ──────"
shopt -s nullglob
LOST=0
for f in dist/packages/*/result.json; do
  pkg=$(basename "$(dirname "$f")")
  base="${BASEDIR}/${pkg}.json"
  if [ ! -f "$base" ]; then
    echo "  [${pkg}] no baseline yet — this run becomes it"
    continue
  fi
  out=$(uv run python -m util.diff "$base" "$f")
  rc=$?
  if [ $rc -ne 0 ]; then
    LOST=$((LOST + 1))
    echo "  [${pkg}] DATA LOST vs ${base}"
    echo "$out" | sed 's/^/    /'
  elif echo "$out" | grep -qE "CHANGED|APPEARED"; then
    echo "  [${pkg}] changed (no loss)"
  fi
done
[ $LOST -gt 0 ] && { echo "FAIL: data was lost in ${LOST} package(s)"; FAIL=1; }

if [ $FAIL -eq 0 ]; then
  mkdir -p "$BASEDIR"
  n=0
  for f in dist/packages/*/result.json; do
    pkg=$(basename "$(dirname "$f")")
    cp "$f" "${BASEDIR}/${pkg}.json"
    n=$((n + 1))
  done
  echo "  baselines refreshed (${n})"
fi

echo
[ $FAIL -eq 0 ] && echo "GATE PASS" || echo "GATE FAIL"
exit $FAIL

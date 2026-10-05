#!/usr/bin/env bash
# rwrops acceptance gate. Run after every change.
#
#   ./gate.sh                  # compare against the previous run (auto-saved)
#   ./gate.sh /tmp/golden.json # compare against a specific baseline
#
# Four checks, not a test framework. If one fails, stop and look.
#
# dist/result.prev.json is written at the start of every run, so the next
# ./gate.sh automatically tells you how this run differs from the last one.
set -uo pipefail
cd "$(dirname "$0")"

BASELINE="${1:-dist/result.prev.json}"
FAIL=0

run() { uv run python main.py >"$1" 2>&1; }

# Snapshot the previous output before overwriting it.
[ -f dist/result.json ] && cp dist/result.json dist/result.prev.json

echo "── gate 1/4: pipeline ──────────────────────────────"
if ! run /tmp/gate_a.log; then
  echo "FAIL: main.py exited non-zero"
  tail -30 /tmp/gate_a.log
  exit 1
fi
grep -E "Wrote result.json|Traceback|CRITICAL" /tmp/gate_a.log | tail -5
A=$(shasum -a 256 dist/result.json | cut -d' ' -f1)
echo "result.json sha256 ${A:0:16}…"

echo "── gate 2/4: determinism (rerun, same bytes?) ──────"
run /tmp/gate_b.log
B=$(shasum -a 256 dist/result.json | cut -d' ' -f1)
if [ "$A" = "$B" ]; then
  echo "OK: two runs produced identical output"
else
  echo "FAIL: non-deterministic — ${A:0:16}… != ${B:0:16}…"
  echo "      (os.walk order / rglob first-hit / clean_final keep-existing)"
  FAIL=1
fi

echo "── gate 3/4: drop counters ─────────────────────────"
if grep -q "\[gate\]" /tmp/gate_a.log; then
  grep -o "\[gate\].*" /tmp/gate_a.log | sed 's/^/  /'
else
  echo "  (none — nothing was dropped, or instrumentation is missing)"
fi

echo "── gate 4/4: diff vs baseline ──────────────────────"
if [ -f "$BASELINE" ]; then
  uv run python -m util.diff "$BASELINE" dist/result.json
  rc=$?
  [ $rc -eq 1 ] && { echo "FAIL: data was lost vs $BASELINE"; FAIL=1; }
else
  echo "  no baseline at $BASELINE — this run becomes the baseline"
fi

echo
[ $FAIL -eq 0 ] && echo "GATE PASS" || echo "GATE FAIL"
exit $FAIL

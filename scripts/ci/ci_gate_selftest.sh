#!/usr/bin/env bash
# Synthetic-status test of ci_gate.sh: only an all-"success" NEEDS may pass.
set -euo pipefail

GATE="$(dirname "$0")/ci_gate.sh"
fails=0

expect() { # expect <pass|fail> <label> <NEEDS json>
  local want="$1" label="$2" rc=0
  NEEDS="$3" GITHUB_STEP_SUMMARY=/dev/null bash "$GATE" > /dev/null 2>&1 || rc=$?
  local got=pass
  [ "$rc" -eq 0 ] || got=fail
  if [ "$got" = "$want" ]; then
    echo "ok   $label -> $got"
  else
    echo "::error title=CI_GATE_SELFTEST::$label: expected $want, got $got (exit $rc)"
    fails=$((fails + 1))
  fi
}

ok='{"result":"success"}'
expect pass "all success"          "{\"a\":$ok,\"b\":$ok}"
for r in failure skipped cancelled neutral action_required timed_out null '""'; do
  expect fail "one required job $r" "{\"a\":$ok,\"b\":{\"result\":$( [ "$r" = null ] || [ "$r" = '""' ] && echo "$r" || echo "\"$r\"" )}}"
done
expect fail "result key missing"   "{\"a\":$ok,\"b\":{}}"
expect fail "empty needs"          '{}'
expect fail "needs is an array"    "[$ok]"
expect fail "malformed json"       '{"a":'
expect fail "SUCCESS wrong case"   '{"a":{"result":"SUCCESS"}}'

if [ "$fails" -ne 0 ]; then
  echo "ci_gate self-test: FAIL ($fails case(s))"
  exit 1
fi
echo "ci_gate self-test: PASS"

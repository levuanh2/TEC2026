#!/usr/bin/env bash
# ci-gate: pass only when EVERY upstream job in $NEEDS (the workflow's
# toJSON(needs)) has result "success". skipped / cancelled / neutral / failure /
# anything else fails, and so does an empty or malformed $NEEDS.
# Behaviour is proven on synthetic statuses by ci_gate_selftest.sh (workflow-policy).
set -euo pipefail

: "${NEEDS:?NEEDS must hold toJSON(needs)}"
command -v jq > /dev/null || { echo "::error title=ci-gate::jq is not installed"; exit 1; }
if ! count="$(jq -e 'if type == "object" then length else error("not an object") end' <<<"$NEEDS" 2>/dev/null)"; then
  echo "::error title=ci-gate::NEEDS is not a JSON object"
  exit 1
fi
if [ "$count" -eq 0 ]; then
  echo "::error title=ci-gate::no required jobs in NEEDS"
  exit 1
fi

{
  echo "### CI gate"
  echo "| Layer | Job | Result |"
  echo "|---|---|---|"
  jq -r 'to_entries[] | "| \(.key | if test("backend|migration|rls") then "backend/DB" elif test("web|playwright|openapi") then "web/API" elif test("flutter") then "flutter" else "integrity/security" end) | \(.key) | \(if .value.result == "success" then "PASS" else "**" + ((.value.result // "missing") | ascii_upcase) + "**" end) |"' <<<"$NEEDS"
} >> "${GITHUB_STEP_SUMMARY:-/dev/null}"

bad="$(jq -r 'to_entries[] | select(.value.result != "success") | "\(.key)=\(.value.result // "missing")"' <<<"$NEEDS")"
if [ -n "$bad" ]; then
  echo "::error title=ci-gate::required jobs did not succeed: ${bad//$'\n'/ }"
  exit 1
fi
echo "all $count required jobs succeeded"

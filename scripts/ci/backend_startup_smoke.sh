#!/usr/bin/env bash
# Boot the backend the way Render does, from ONLY backend/requirements.txt.
#
#   bash scripts/ci/backend_startup_smoke.sh
#
# Fresh venv (no site packages), `pip install -r requirements.txt`, then the
# exact Render start command. Proves: every import the app needs is declared,
# uvicorn starts, GET /health and GET /docs answer 200, and the CV stack
# (torch/torchvision, deliberately NOT in requirements.txt) is absent
# while the API still boots -- CV routes degrade to 503 by design. (Pillow
# itself IS installed: reportlab, the MRV PDF renderer, depends on it.)
# No Supabase settings are given: startup must not need them.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV="${RUNNER_TEMP:-${TMPDIR:-/tmp}}/agricarbon-startup-venv"
PORT="${SMOKE_PORT:-8099}"
LOG="${SMOKE_LOG:-$ROOT/backend-startup.log}"

rm -rf "$VENV"
python -m venv "$VENV"
# Call the venv's interpreter directly -- never `activate`: under Git Bash a
# Windows venv's activate script can leave PATH pointing at the global Python,
# and every install below would then land there.
PY="$VENV/bin/python"
[ -x "$PY" ] || PY="$VENV/Scripts/python.exe"
"$PY" -c 'import sys; sys.exit(0 if sys.prefix != sys.base_prefix else "not a venv interpreter")'
"$PY" -m pip install --quiet --upgrade pip
"$PY" -m pip install --quiet -r "$ROOT/backend/requirements.txt"

cd "$ROOT/backend"
env -u SUPABASE_URL -u SUPABASE_SERVICE_ROLE_KEY -u SUPABASE_PUBLISHABLE_KEY -u SUPABASE_DB_URL \
  "$PY" - <<'PY'
import importlib.util, sys
for mod in ("torch", "torchvision"):
    if importlib.util.find_spec(mod) is not None:
        sys.exit(f"{mod} is installed from requirements.txt -- the CV stack must stay optional")
import main  # noqa: F401  -- import errors surface here with a clean traceback
print("import main: ok; torch/torchvision absent as designed (CV routes answer 503)")
PY

# Render: uvicorn main:app --host 0.0.0.0 --port $PORT (rootDir backend)
env -u SUPABASE_URL -u SUPABASE_SERVICE_ROLE_KEY -u SUPABASE_PUBLISHABLE_KEY -u SUPABASE_DB_URL \
  "$PY" -m uvicorn main:app --host 127.0.0.1 --port "$PORT" >"$LOG" 2>&1 &
PID=$!
trap 'kill "$PID" 2>/dev/null || true' EXIT

up=""
for _ in $(seq 1 60); do
  if ! kill -0 "$PID" 2>/dev/null; then
    echo "::error title=Backend startup::uvicorn exited during startup"; cat "$LOG"; exit 1
  fi
  if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then up=1; break; fi
  sleep 1
done
if [ -z "$up" ]; then
  echo "::error title=Backend startup::/health did not answer within 60s"; cat "$LOG"; exit 1
fi

for path in /health /docs /openapi.json; do
  code="$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT$path")"
  echo "GET $path -> $code"
  if [ "$code" != "200" ]; then
    echo "::error title=Backend startup::GET $path returned $code"; cat "$LOG"; exit 1
  fi
done
echo "backend clean startup: PASS"

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
# Guard: abort before any install unless the interpreter IS this venv.
# (cygpath turns Git Bash's /c/... into the C:\... form Python reports.)
VENV_NATIVE="$(cygpath -w "$VENV" 2>/dev/null || printf '%s' "$VENV")"
"$PY" - "$VENV_NATIVE" <<'GUARD'
import os, sys
norm = lambda p: os.path.normcase(os.path.realpath(p))
if sys.prefix == sys.base_prefix or norm(sys.prefix) != norm(sys.argv[1]):
    sys.exit(f"refusing to install: {sys.executable} is not the interpreter of the venv {sys.argv[1]}")
GUARD
"$PY" -m pip install --quiet --upgrade pip
"$PY" -m pip install --quiet -r "$ROOT/backend/requirements.txt"
# What requirements.txt resolved to today (dependency drift check, dep_audit.py --drift).
"$PY" -m pip freeze --exclude pip > "${FREEZE_OUT:-$ROOT/backend-resolved.txt}"

cd "$ROOT/backend"  # Render's rootDir: the production working directory

# Interpreter/pip isolation, every production module importable from
# requirements.txt alone, no undeclared third-party imports.
env -u SUPABASE_URL -u SUPABASE_SERVICE_ROLE_KEY -u SUPABASE_PUBLISHABLE_KEY -u SUPABASE_DB_URL \
  "$PY" "$ROOT/scripts/ci/python_deps_check.py"

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
# Always stop the server, however this script exits (no leaked process).
# `wait` returns 143 for the SIGTERM we send; inside `if !` that expected status
# neither trips set -e nor replaces the script's own exit code.
trap 'if kill -0 "$PID" 2>/dev/null; then kill "$PID"; if ! wait "$PID" 2>/dev/null; then echo "uvicorn stopped"; fi; fi' EXIT

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
# The production process (no pytest loaded) must enforce auth like the pytest
# sweep does: every protected /v1 operation in its own OpenAPI answers 401 with
# the error envelope. Catches app code that behaves only under the test runner.
PORT="$PORT" "$PY" - <<'PY'
import json, os, re, sys, urllib.error, urllib.request
base = f"http://127.0.0.1:{os.environ['PORT']}"
spec = json.load(urllib.request.urlopen(f"{base}/openapi.json", timeout=10))
public = {("GET", "/v1/carbon/scenarios")}  # EXC-API-01
# EXC-API-02: the Carbon routes keep `missing_authorization`; all others `unauthenticated`.
carbon = {("POST", "/v1/carbon/calculate"), ("GET", "/v1/crop-seasons/{crop_season_id}/carbon"),
          ("GET", "/v1/crop-seasons/{crop_season_id}/carbon/readiness")}
ops = [(m.upper(), p) for p, item in spec["paths"].items() if p.startswith("/v1")
       for m in item if m in {"get", "post", "put", "patch", "delete"}]
bad = []
for method, path in public:  # the documented public routes must stay public
    try:
        status = urllib.request.urlopen(urllib.request.Request(base + path, method=method), timeout=10).status
    except urllib.error.HTTPError as exc:
        status = exc.code
    if (method, path) not in set(ops) or status != 200:
        bad.append(f"public {method} {path} -> {status}")
for method, path in ops:
    if (method, path) in public:
        continue
    url = base + re.sub(r"\{[^}]+\}", "00000000-0000-4000-8000-000000000001", path)
    req = urllib.request.Request(url, data=b"{}", method=method, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
        status, body = 200, b""
    except urllib.error.HTTPError as exc:
        status, body = exc.code, exc.read()
    try:
        err = json.loads(body)["detail"]["error"]
        want = "missing_authorization" if (method, path) in carbon else "unauthenticated"
        envelope = err.get("code") == want and isinstance(err.get("message"), str)
    except (ValueError, KeyError, TypeError, AttributeError):
        envelope = False
    if status != 401 or not envelope:
        bad.append(f"{method} {path} -> {status} {body[:80]!r}")
if len(ops) < 50 or bad:
    print(f"::error title=Backend startup::live 401 sweep: {len(ops)} operations, failures: {bad[:10]}")
    sys.exit(1)
print(f"live production process: {len(ops) - len(public & set(ops))} protected /v1 operations answer 401 + envelope")
PY
echo "backend clean startup: PASS"

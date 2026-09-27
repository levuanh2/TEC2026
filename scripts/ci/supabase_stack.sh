#!/usr/bin/env bash
# Start an ISOLATED local Supabase stack for CI and export its settings.
#
#   bash scripts/ci/supabase_stack.sh            # needs Docker + the Supabase CLI
#
# `supabase start` creates an empty Postgres, then applies EVERY file in
# supabase/migrations in version order and stops at the first one that fails --
# that is the clean-apply check. Afterwards this script proves the applied set
# equals the files on disk (nothing skipped), and that PostgREST boots on the
# resulting schema.
#
# Only the services the tests exercise are started: Postgres, GoTrue (Auth
# admin + real JWTs), PostgREST, Storage (MRV exports) and Kong in front of
# them. Nothing here ever talks to the hosted project.
#
# Exports (to $GITHUB_ENV when set, else prints `export` lines):
#   SUPABASE_URL SUPABASE_DB_URL SUPABASE_SERVICE_ROLE_KEY SUPABASE_PUBLISHABLE_KEY
# The keys are the CLI's fixed, public local-development keys, not secrets.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

supabase start -x realtime,imgproxy,mailpit,postgres-meta,studio,edge-runtime,logflare,vector,supavisor

STATUS="$(supabase status -o json)"
ENV_LINES="$(python3 - "$STATUS" <<'PY'
import json, sys
s = json.loads(sys.argv[1])
pick = lambda *names: next(s[n] for n in names if s.get(n))
print(f"SUPABASE_URL={pick('API_URL')}")
print(f"SUPABASE_DB_URL={pick('DB_URL')}")
# Legacy JWT keys: accepted by every supabase-py/PostgREST/GoTrue path the
# backend and scripts use.
print(f"SUPABASE_SERVICE_ROLE_KEY={pick('SERVICE_ROLE_KEY')}")
print(f"SUPABASE_PUBLISHABLE_KEY={pick('ANON_KEY')}")
PY
)"
eval "$(printf '%s\n' "$ENV_LINES" | sed 's/^/export /')"

# Every migration file must be recorded as applied -- no silent skip.
expected="$(find supabase/migrations -maxdepth 1 -name '*.sql' -printf '%f\n' | cut -d_ -f1 | sort)"
applied="$(psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -At \
  -c 'select version from supabase_migrations.schema_migrations order by version')"
if [ "$expected" != "$applied" ]; then
  echo "::error title=Migrations::applied versions differ from supabase/migrations"
  echo "only in files:    $(comm -23 <(printf '%s\n' "$expected") <(printf '%s\n' "$applied") | tr '\n' ' ')"
  echo "only in database: $(comm -13 <(printf '%s\n' "$expected") <(printf '%s\n' "$applied") | tr '\n' ' ')"
  exit 1
fi
echo "all $(printf '%s\n' "$expected" | wc -l) migrations applied from an empty database"

# The schema must boot PostgREST (a broken grant/function breaks its schema cache).
code="$(curl -s -o /dev/null -w '%{http_code}' -H "apikey: $SUPABASE_PUBLISHABLE_KEY" "$SUPABASE_URL/rest/v1/")"
if [ "$code" != "200" ]; then
  echo "::error title=PostgREST::GET /rest/v1/ returned $code after migrations"
  exit 1
fi
echo "PostgREST serves the migrated schema"

if [ -n "${GITHUB_ENV:-}" ]; then
  printf '%s\n' "$ENV_LINES" >>"$GITHUB_ENV"
else
  printf '%s\n' "$ENV_LINES" | sed 's/^/export /'
fi

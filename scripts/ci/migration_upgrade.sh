#!/usr/bin/env bash
# Upgrade test: an EXISTING, seeded database at the base revision -> this
# change's migrations. Empty-database replay (supabase_stack.sh) cannot catch a
# migration that only fails on real data.
#
#   bash scripts/ci/migration_upgrade.sh origin/main
#
# 1. check out the base ref in a separate worktree; start the stack from ITS
#    migrations and seed it with ITS scripts/ci/seed_ci_db.py (realistic rows);
# 2. apply only the migrations this change adds (`supabase migration up`, which
#    stops at the first failure). If the change adds none, the newest base
#    migration is held back and replayed instead (N-1 -> N), so the upgrade
#    path is exercised on every run;
# 3. require: every migration recorded, core row counts unchanged (no data
#    lost), the upgraded catalog identical to the freshly-built one
#    (db_audit.py against the committed snapshot), and the PostgREST lifecycle
#    probe still 36/36.
# Local only; the stack and the worktree are removed on exit, whatever happens.
set -euo pipefail

BASE="${1:?usage: migration_upgrade.sh <base-ref>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK="${RUNNER_TEMP:-${TMPDIR:-/tmp}}/migration-upgrade"
BASE_TREE="$WORK/base"
PY="${PYTHON:-python}"
TABLES="organizations organization_memberships farms farm_members plots crop_seasons production_batches activities irrigation_events emission_factor_sets mrv_cases"

cleanup() {
  if [ -d "$BASE_TREE/supabase" ]; then
    supabase stop --no-backup --workdir "$BASE_TREE" >/dev/null
  fi
  if [ -d "$BASE_TREE" ]; then
    git -C "$ROOT" worktree remove --force "$BASE_TREE"
  fi
}
trap cleanup EXIT

rm -rf "$WORK" && mkdir -p "$WORK"
git -C "$ROOT" worktree add --detach "$BASE_TREE" "$BASE" >/dev/null
BASE_SHA="$(git -C "$BASE_TREE" rev-parse --short HEAD)"

head_files="$(cd "$ROOT/supabase/migrations" && ls -1 ./*.sql | sed 's#^\./##' | sort)"
base_files="$(cd "$BASE_TREE/supabase/migrations" && ls -1 ./*.sql | sed 's#^\./##' | sort)"
removed="$(comm -23 <(printf '%s\n' "$base_files") <(printf '%s\n' "$head_files"))"
if [ -n "$removed" ]; then
  echo "::error title=Migration upgrade::migrations present on $BASE were removed: $removed"
  exit 1
fi
new="$(comm -13 <(printf '%s\n' "$base_files") <(printf '%s\n' "$head_files"))"
if [ -z "$new" ]; then
  new="$(printf '%s\n' "$base_files" | tail -1)"
  rm "$BASE_TREE/supabase/migrations/$new"
  mode="no new migrations: replaying the newest one onto seeded data (N-1 -> N)"
else
  mode="applying $(printf '%s\n' "$new" | wc -l) new migration(s) onto $BASE ($BASE_SHA)"
fi
echo "$mode"
printf '  %s\n' $new

# Base stack + base seed. The base's own stack script checks ITS file set.
eval "$(cd "$BASE_TREE" && env -u GITHUB_ENV bash scripts/ci/supabase_stack.sh | grep '^export ')"
(cd "$BASE_TREE" && "$PY" scripts/ci/seed_ci_db.py >/dev/null)

count_rows() {
  for t in $TABLES; do
    printf '%s=%s ' "$t" "$(psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -At -c "select count(*) from public.$t")"
  done
}
before="$(count_rows)"
echo "seeded rows before upgrade: $before"

for f in $new; do
  cp "$ROOT/supabase/migrations/$f" "$BASE_TREE/supabase/migrations/$f"
done
supabase migration up --local --workdir "$BASE_TREE"

applied="$(psql "$SUPABASE_DB_URL" -v ON_ERROR_STOP=1 -At -c 'select version from supabase_migrations.schema_migrations order by version')"
expected="$(printf '%s\n' "$head_files" | cut -d_ -f1)"
if [ "$applied" != "$expected" ]; then
  echo "::error title=Migration upgrade::applied versions after upgrade differ from supabase/migrations"
  exit 1
fi
after="$(count_rows)"
echo "rows after upgrade:          $after"
if [ "$before" != "$after" ]; then
  echo "::error title=Migration upgrade::row counts changed during the upgrade (data lost or duplicated)"
  exit 1
fi

# The upgraded catalog must equal the one built from scratch (same snapshot).
"$PY" "$ROOT/scripts/ci/db_audit.py"
(cd "$ROOT/backend" && "$PY" scripts/hosted_lifecycle_rls_probe.py --enforce | tee "$WORK/upgrade-lifecycle.log")
"$PY" "$ROOT/scripts/ci/ci_report.py" --label "Lifecycle after upgrade" --probe-log "$WORK/upgrade-lifecycle.log" --probe lifecycle
echo "migration upgrade: PASS ($mode)"

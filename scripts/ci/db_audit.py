"""Database architecture audit against the migrated CI database.

    python scripts/ci/db_audit.py            # check (needs SUPABASE_DB_URL -> local stack)
    python scripts/ci/db_audit.py --write    # regenerate scripts/ci/policy/schema-audit.json

Two layers:

HARD RULES (fail regardless of the snapshot)
  SCHEMA_INVARIANT     hierarchy NOT NULLs, foreign keys, soft-delete columns,
                       idempotency/uniqueness indexes, lifecycle triggers
  RLS_DISABLED         a public table without row level security
  RLS_PERMISSIVE       a policy granted to anon/public, a write policy whose
                       USING/WITH CHECK is literally `true`, or a read policy with
                       USING `true` (every signed-in user of every tenant) outside
                       the exact open-read allowlist
  PRIVILEGE_BROADENED  anon holds INSERT/UPDATE/DELETE/TRUNCATE on a public TABLE,
                       or anon/authenticated/PUBLIC can EXECUTE a function, beyond
                       the documented exceptions below
  SECURITY_DEFINER     a SECURITY DEFINER function without a pinned search_path,
                       or one that builds dynamic SQL (EXECUTE ...)

SNAPSHOT (scripts/ci/policy/schema-audit.json)
  SCHEMA_AUDIT_DRIFT   RLS flags, every policy (cmd, roles, USING, WITH CHECK),
                       table grants to anon/authenticated/PUBLIC, function EXECUTE
                       grants, SECURITY DEFINER config, triggers and unique indexes
                       differ from the committed snapshot. A migration that changes
                       them intentionally regenerates the snapshot (--write) in the
                       same PR, so the change is reviewed as a readable diff.

Refuses a non-local SUPABASE_DB_URL.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import psycopg

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "scripts" / "ci" / "policy" / "schema-audit.json"
ROLES = ("anon", "authenticated", "PUBLIC")
DETAIL_TABLES = ("seeding_events", "fertilizer_applications", "irrigation_events", "pesticide_applications",
                 "straw_management_events", "harvest_events")

# Documented exceptions (docs/CI_PIPELINE.md, "CI exceptions") live in policy.json
# `db_exceptions`, so growing them is a policy relaxation (ci_policy.py).
_EXC = json.loads((ROOT / "scripts" / "ci" / "policy" / "policy.json").read_text(encoding="utf-8"))["db_exceptions"]
ANON_TABLE_WRITE_EXCEPTIONS = set(_EXC["anon_table_write"])                              # EXC-DB-01
FUNCTION_EXECUTE_EXCEPTIONS = {(e["function"], e["role"]) for e in _EXC["function_execute"]}  # EXC-DB-02
OPEN_READ_POLICIES = set(_EXC["open_read_policies"])                                      # EXC-DB-03

NOT_NULL = [("activities", "production_batch_id"), ("activities", "activity_type"), ("activities", "occurred_at"),
            ("production_batches", "crop_season_id"), ("crop_seasons", "plot_id"), ("plots", "farm_id"),
            ("farms", "cooperative_id")] + [(t, "activity_id") for t in DETAIL_TABLES]
FOREIGN_KEYS = [("activities", "production_batch_id", "production_batches"),
                ("production_batches", "crop_season_id", "crop_seasons"),
                ("crop_seasons", "plot_id", "plots"), ("plots", "farm_id", "farms"),
                ("farms", "cooperative_id", "organizations")] + [(t, "activity_id", "activities") for t in DETAIL_TABLES]
SOFT_DELETE = [("activities", "deleted_at"), ("production_batches", "deleted_at"), ("crop_seasons", "deleted_at")]
UNIQUE_INDEXES = ["activities_device_event_uidx", "activities_web_idempotency_uidx",
                  "crop_seasons_plot_id_season_code_key", "production_batches_crop_season_id_batch_code_key",
                  "carbon_calculations_season_input_uniq"]

# P1 lifecycle enforcement (20260926090000..120000): writes into a season that is
# not open are refused by the database for every client.
LIFECYCLE_TRIGGERS = (["activities.enforce_activity_season_open_trg", "production_batches.enforce_batch_season_open_trg"]
                      + [f"{t}.enforce_detail_season_open_trg" for t in DETAIL_TABLES + ("fuel_usages",)])

errors: list[str] = []


def fail(code: str, msg: str) -> None:
    errors.append(f"{code}: {msg}")
    print(f"::error title={code}::{msg}")


def rows(cur, sql, params=None):
    cur.execute(sql, params)  # None, not (): a literal % in LIKE must not be a placeholder
    return cur.fetchall()


def snapshot(cur) -> dict:
    snap: dict = {}
    snap["rls"] = {r[0]: {"enabled": r[1], "forced": r[2]} for r in rows(cur, """
        select c.relname, c.relrowsecurity, c.relforcerowsecurity from pg_class c
        where c.relnamespace = 'public'::regnamespace and c.relkind in ('r','p') order by 1""")}
    snap["policies"] = {f"{r[0]}.{r[1]}": {"cmd": r[2], "roles": sorted(r[3]), "permissive": r[4],
                                           "using": r[5], "with_check": r[6]} for r in rows(cur, """
        select tablename, policyname, cmd, roles, permissive, qual, with_check from pg_policies
        where schemaname = 'public' order by 1, 2""")}
    grants: dict = {role: {} for role in ROLES}
    for table, grantee, privs in rows(cur, """
            select table_name, grantee, string_agg(privilege_type, ',' order by privilege_type)
            from information_schema.role_table_grants
            where table_schema = 'public' and grantee in ('anon','authenticated','PUBLIC')
            group by 1, 2 order by 1, 2"""):
        grants[grantee][table] = privs
    snap["table_grants"] = grants
    funcs = {}
    for sig, schema, secdef, config in rows(cur, """
            select p.oid::regprocedure::text, n.nspname, p.prosecdef, p.proconfig
            from pg_proc p join pg_namespace n on n.oid = p.pronamespace
            where n.nspname in ('public','private') and p.prokind = 'f' order by 1"""):
        cur.execute("select has_function_privilege('anon', %s::regprocedure, 'EXECUTE'),"
                    " has_function_privilege('authenticated', %s::regprocedure, 'EXECUTE')", (sig, sig))
        anon, auth = cur.fetchone()
        funcs[sig] = {"security_definer": secdef, "config": sorted(config or []),
                      "execute": [r for r, ok in (("anon", anon), ("authenticated", auth)) if ok]}
    snap["functions"] = funcs
    snap["triggers"] = {f"{r[0]}.{r[1]}": r[2] for r in rows(cur, """
        select c.relname, t.tgname, p.oid::regprocedure::text from pg_trigger t
        join pg_class c on c.oid = t.tgrelid join pg_proc p on p.oid = t.tgfoid
        where c.relnamespace = 'public'::regnamespace and not t.tgisinternal order by 1, 2""")}
    snap["unique_indexes"] = {r[0]: r[1] for r in rows(cur, """
        select indexname, indexdef from pg_indexes
        where schemaname = 'public' and indexdef like 'CREATE UNIQUE%' order by 1""")}
    return snap


def hard_rules(cur, snap: dict) -> None:
    for table, col in NOT_NULL + SOFT_DELETE:
        r = rows(cur, "select is_nullable from information_schema.columns where table_schema='public' "
                      "and table_name=%s and column_name=%s", (table, col))
        if not r:
            fail("SCHEMA_INVARIANT", f"column public.{table}.{col} is missing")
        elif (table, col) in NOT_NULL and r[0][0] != "NO":
            fail("SCHEMA_INVARIANT", f"public.{table}.{col} must be NOT NULL")
    for table, col, target in FOREIGN_KEYS:
        ok = rows(cur, """
            select 1 from pg_constraint c
            join pg_attribute a on a.attrelid = c.conrelid and a.attnum = any(c.conkey)
            where c.contype = 'f' and c.conrelid = ('public.' || %s)::regclass
              and c.confrelid = ('public.' || %s)::regclass and a.attname = %s""", (table, target, col))
        if not ok:
            fail("SCHEMA_INVARIANT", f"foreign key public.{table}.{col} -> {target} is missing")
    for idx in UNIQUE_INDEXES:
        if idx not in snap["unique_indexes"]:
            fail("SCHEMA_INVARIANT", f"unique index {idx} is missing")
    for trig in LIFECYCLE_TRIGGERS:
        if trig not in snap["triggers"]:
            fail("SCHEMA_INVARIANT", f"season-lifecycle trigger {trig} is missing")
    for table, flags in snap["rls"].items():
        if not flags["enabled"]:
            fail("RLS_DISABLED", f"public.{table} has row level security disabled")
    for name, p in snap["policies"].items():
        if set(p["roles"]) & {"anon", "public"}:
            fail("RLS_PERMISSIVE", f"policy {name} applies to {p['roles']}")
        if p["cmd"] in ("INSERT", "UPDATE", "DELETE", "ALL") and "true" in (p["using"], p["with_check"]):
            fail("RLS_PERMISSIVE", f"write policy {name} is unconditional (true)")
        elif p["cmd"] == "SELECT" and p["using"] == "true" and name not in OPEN_READ_POLICIES:
            fail("RLS_PERMISSIVE", f"read policy {name} is USING (true): every tenant's users can read it")
    for table, privs in snap["table_grants"]["anon"].items():
        writes = set(privs.split(",")) & {"INSERT", "UPDATE", "DELETE", "TRUNCATE"}
        is_table = table in snap["rls"]
        if writes and is_table and table not in ANON_TABLE_WRITE_EXCEPTIONS:
            fail("PRIVILEGE_BROADENED", f"anon has {sorted(writes)} on table public.{table}")
    for sig, f in snap["functions"].items():
        for role in f["execute"]:
            if sig.startswith("public.") and (sig, role) not in FUNCTION_EXECUTE_EXCEPTIONS and f["security_definer"]:
                fail("PRIVILEGE_BROADENED", f"{role} can EXECUTE SECURITY DEFINER {sig}")
        if f["security_definer"]:
            if not any(c.startswith("search_path=") for c in f["config"]):
                fail("SECURITY_DEFINER", f"{sig} is SECURITY DEFINER without a pinned search_path")
            src = rows(cur, "select prosrc from pg_proc where oid = %s::regprocedure", (sig,))[0][0]
            if re.search(r"\bexecute\s+(?!function|procedure)", src, re.I):
                fail("SECURITY_DEFINER", f"{sig} is SECURITY DEFINER and builds dynamic SQL")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    url = os.environ.get("SUPABASE_DB_URL", "")
    if urlparse(url).hostname not in {"127.0.0.1", "localhost"}:
        sys.exit("refusing: SUPABASE_DB_URL must point at the local CI stack")
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        snap = snapshot(cur)
        hard_rules(cur, snap)
    text = json.dumps(snap, indent=1, sort_keys=True) + "\n"
    if args.write:
        SNAPSHOT.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {SNAPSHOT.relative_to(ROOT)}")
    elif not SNAPSHOT.is_file():
        fail("SCHEMA_AUDIT_DRIFT", f"{SNAPSHOT.relative_to(ROOT)} does not exist (run with --write)")
    else:
        committed = SNAPSHOT.read_text(encoding="utf-8").replace("\r\n", "\n")
        if committed != text:
            diff = list(difflib.unified_diff(committed.splitlines(), text.splitlines(), "committed", "migrated", lineterm="", n=2))
            print("\n".join(diff[:300]))
            fail("SCHEMA_AUDIT_DRIFT", f"catalog differs from {SNAPSHOT.relative_to(ROOT)} ({len(diff)} diff lines above); "
                                       "if intended, run scripts/ci/db_audit.py --write in the same PR")
    counts = {k: len(v) for k, v in snap.items() if k != "table_grants"}
    print(f"db_audit: {'FAIL' if errors else 'PASS'} -- {counts}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

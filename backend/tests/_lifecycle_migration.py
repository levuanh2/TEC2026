"""Apply the P1 lifecycle migrations inside a test's own (rolled-back)
transaction when the target database does not have them yet, so the real-DB
tests exercise the rules before deployment. A no-op once deployed."""
from __future__ import annotations

from pathlib import Path

_DIR = Path(__file__).resolve().parents[2] / "supabase" / "migrations"
_MIGRATIONS = [
    ("20260926090000_db_lifecycle_enforcement.sql",
     "select to_regprocedure('private.activity_batch_open(uuid)') is not null"),
    ("20260926100000_activity_update_denies_loudly.sql",
     "select coalesce((select qual like '%user_can_read_batch%' from pg_policies "
     "where schemaname = 'public' and tablename = 'activities' and policyname = 'activities_update'), false)"),
]


def ensure_lifecycle_migration(conn) -> None:
    with conn.cursor() as cur:
        for name, present_sql in _MIGRATIONS:
            cur.execute(present_sql)
            row = cur.fetchone()
            present = list(row.values())[0] if isinstance(row, dict) else row[0]
            if not present:
                cur.execute((_DIR / name).read_text(encoding="utf-8"))

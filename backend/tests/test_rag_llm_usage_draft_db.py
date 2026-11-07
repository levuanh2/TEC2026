"""The DRAFT durable quota schema (supabase/drafts/rag_llm_usage_daily.sql), applied INSIDE a
rolled-back transaction on a local stack: nothing persists, nothing reaches hosted (the
tests/_db_target guard refuses non-local databases)."""
from __future__ import annotations

from pathlib import Path

import pytest

from infrastructure.config import load_settings

_SETTINGS = load_settings()
DRAFT = Path(__file__).resolve().parents[2] / "supabase" / "drafts"
pytestmark = pytest.mark.skipif(not _SETTINGS.supabase_db_url, reason="SUPABASE_DB_URL is not configured.")


@pytest.fixture
def cur():
    import psycopg
    conn = psycopg.connect(_SETTINGS.supabase_db_url, autocommit=False)
    try:
        c = conn.cursor()
        c.execute((DRAFT / "rag_llm_usage_daily.sql").read_text(encoding="utf-8"))
        yield c
    finally:
        conn.rollback()
        conn.close()


def _reserve(cur, user, user_limit=2, project_limit=3, hard_stop=None):
    cur.execute("select private.rag_llm_usage_reserve(date '2026-11-07', %s, %s, %s, %s)",
                (user, user_limit, project_limit, hard_stop))
    return cur.fetchone()[0]


def test_reserve_enforces_user_and_project_limits(cur):
    a, b, c = "a" * 16, "b" * 16, "c" * 16
    assert [_reserve(cur, a), _reserve(cur, a), _reserve(cur, a)] == [True, True, False]
    assert _reserve(cur, b) is True                 # project now at 3
    assert _reserve(cur, c) is False                # project limit reached for everyone
    cur.execute("select user_key, requests from private.rag_llm_usage_daily order by user_key")
    assert cur.fetchall() == [("*project*", 3), (a, 2), (b, 1)]


def test_cost_hard_stop_refuses(cur):
    assert _reserve(cur, "d" * 16, hard_stop=1) is True
    cur.execute("update private.rag_llm_usage_daily set cost_usd = 1 where user_key = '*project*'")
    assert _reserve(cur, "d" * 16, hard_stop=1) is False


def test_only_pseudonymous_keys_are_accepted(cur):
    import psycopg
    with pytest.raises(psycopg.errors.CheckViolation):
        _reserve(cur, "88888888-8888-8888-8888-888888888888")


def test_clients_cannot_read_or_call_it(cur):
    for privilege, obj in (("select", "private.rag_llm_usage_daily"),):
        cur.execute(f"select has_table_privilege('authenticated', '{obj}', '{privilege}'),"
                    f" has_table_privilege('anon', '{obj}', '{privilege}')")
        assert cur.fetchone() == (False, False)
    cur.execute("select has_function_privilege('authenticated', 'private.rag_llm_usage_reserve(date,text,integer,"
                "integer,numeric)', 'execute')")
    assert cur.fetchone() == (False,)


def test_the_rollback_removes_everything(cur):
    cur.execute((DRAFT / "rag_llm_usage_daily.rollback.sql").read_text(encoding="utf-8"))
    cur.execute("select to_regclass('private.rag_llm_usage_daily'), to_regprocedure("
                "'private.rag_llm_usage_reserve(date,text,integer,integer,numeric)')")
    assert cur.fetchone() == (None, None)

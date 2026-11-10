"""RAG V1.5 M1 (migrations 20261110090000 + 20261110090100): controlled, audited knowledge status
transitions, at the DATABASE under the real roles (`authenticated` and `anon` as PostgREST runs
them, `service_role`, and the table owner the operator CLI connects as).

The lifecycle matrix, the retrieval matrix and the approval invariants are in
test_rag_knowledge_storage.py. This file covers the audit log and its authorization boundary. One
transaction per test, rolled back, except the concurrency test, which needs two committed sessions
(see its docstring). Synthetic TEST FIXTURE rows only. Skipped without SUPABASE_DB_URL.

dev3-01 stays OPEN: quarantine is now possible and every decision is auditable, but nothing here
judges content, and expert_review proves only that the stage was passed (M2: evidence, distinct
reviewer/approver).
"""

from __future__ import annotations

import json
import threading
import uuid

import pytest

from tests.test_rag_knowledge_storage import (CHECK_VIOLATION, PERMISSION_DENIED, TRANSITION, _DB_URL,  # noqa: E402
                                              pytestmark, psycopg, tx)

__all__ = ["pytestmark", "tx"]       # the storage module's environment gate and fixture, reused

EVENTS = "public.knowledge_status_events"


def _as_role(tx, role, sql, params=(), claims=None):
    """('ok', rows) or ('err', sqlstate) under `set local role <role>` in a savepoint."""
    tx.settle()
    tx.cur.execute("savepoint r")
    try:
        tx.cur.execute(f"set local role {role}")
        if claims is not None:
            tx.cur.execute("select set_config('request.jwt.claims', %s, true)", (json.dumps(claims),))
        tx.cur.execute(sql, params)
        rows = tx.cur.fetchall() if tx.cur.description else tx.cur.rowcount
        tx.cur.execute("reset role")
        tx.cur.execute("release savepoint r")
        return ("ok", rows)
    except psycopg.Error as exc:
        tx.cur.execute("rollback to savepoint r")
        return ("err", exc.sqlstate)


def _client(tx, user):
    return {"sub": str(user), "role": "authenticated"}


# ------------------------------------------------------------------ schema

def test_the_two_status_values_exist_and_are_never_retrievable_by_default(tx):
    tx.cur.execute("select array_agg(e.enumlabel::text order by e.enumsortorder) from pg_enum e"
                   " where e.enumtypid = 'public.knowledge_status'::regtype")
    assert tx.cur.fetchone()[0] == ["review_required", "expert_review", "approved", "quarantined", "rejected",
                                    "archived"]
    tx.cur.execute("select qual from pg_policies where schemaname = 'public'"
                   " and tablename in ('knowledge_sources', 'knowledge_documents')")
    assert all("status = 'approved'" in q for (q,) in tx.cur.fetchall())


def test_event_log_shape_and_privileges(tx):
    tx.cur.execute("select relrowsecurity from pg_class where oid = %s::regclass", (EVENTS,))
    assert tx.cur.fetchone()[0] is True
    tx.cur.execute("select count(*) from pg_policies where schemaname = 'public' and tablename = 'knowledge_status_events'")
    assert tx.cur.fetchone()[0] == 0                                     # clients read nothing
    tx.cur.execute("select grantee, privilege_type from information_schema.role_table_grants"
                   " where table_schema = 'public' and table_name = 'knowledge_status_events'"
                   " and grantee in ('anon', 'authenticated', 'service_role', 'PUBLIC') order by 1, 2")
    assert tx.cur.fetchall() == [("service_role", "SELECT")]
    for fn in ("private.knowledge_transition_source(text,knowledge_status,knowledge_status,text,uuid)",
               "private.knowledge_transition_document(uuid,knowledge_status,knowledge_status,text,uuid)"):
        tx.cur.execute("select has_function_privilege('anon', %s, 'execute'),"
                       " has_function_privilege('authenticated', %s, 'execute'),"
                       " has_function_privilege('service_role', %s, 'execute'), p.prosecdef"
                       " from pg_proc p where p.oid = %s::regprocedure", (fn, fn, fn, fn))
        assert tx.cur.fetchone() == (False, False, True, True), fn


# ------------------------------------------------------------------ one event per transition

def test_every_transition_writes_exactly_one_complete_event(tx):
    src = tx.source(status="review_required")
    doc = tx.document(tx.source(), status="review_required")
    tx.cur.execute("select pg_current_xact_id()::text")
    xid = tx.cur.fetchone()[0]
    steps = [("source", src, "review_required", "approved"), ("source", src, "approved", "quarantined"),
             ("source", src, "quarantined", "archived"),
             ("document", doc, "review_required", "expert_review"), ("document", doc, "expert_review", "approved"),
             ("document", doc, "approved", "quarantined"), ("document", doc, "quarantined", "archived")]
    for kind, key, frm, to in steps:
        result = tx.transit(kind, key, frm, to, reason=f"why {frm}->{to}")
        assert result[0] == "ok", (kind, frm, to, result)
    tx.cur.execute(f"select entity_type, source_id, document_pk, document_id, document_version, from_status::text,"
                   f" to_status::text, reason, stated_approver, actor_session_user, actor_role,"
                   f" transaction_id::text, occurred_at is not null from {EVENTS}"
                   f" where source_id = %s or document_pk = %s order by id", (src, doc))
    rows = tx.cur.fetchall()
    tx.cur.execute("select source_id, document_id, document_version from public.knowledge_documents where id = %s",
                   (doc,))
    d_src, d_id, d_ver = tx.cur.fetchone()
    tx.cur.execute("select session_user")
    login = tx.cur.fetchone()[0]
    expected = []
    for kind, key, frm, to in steps:
        identity = ("source", src, None, None, None) if kind == "source" else ("document", d_src, doc, d_id, d_ver)
        expected.append((*identity, frm, to, f"why {frm}->{to}", tx.approver if to == "approved" else None,
                         login, login, xid, True))
    # the document's own source was approved in fixture setup (1 earlier event): keep only ours
    assert [r for r in rows if r[1] == src or r[2] == doc] == expected


def test_an_unchanged_status_writes_no_event(tx):
    src = tx.source()
    before = tx.events("source", src)
    assert tx.transit("source", src, "approved", "approved") == ("err", CHECK_VIOLATION)
    assert tx.operator("update public.knowledge_sources set status = 'approved' where source_id = %s", (src,)) \
        == ("ok", None)                                                  # same status: not a transition
    assert tx.events("source", src) == before


def test_a_rolled_back_transition_leaves_no_event_and_no_status(tx):
    src = tx.source(status="review_required")
    tx.cur.execute("savepoint outer_work")
    assert tx.transit("source", src, "review_required", "approved")[0] == "ok"
    assert len(tx.events("source", src)) == 1
    tx.cur.execute("rollback to savepoint outer_work")                  # the caller's transaction fails later
    assert tx.events("source", src) == [] and tx.status_of("source", src) == "review_required"


def test_a_failed_transaction_commits_no_event():
    """Across sessions: a transition inside a transaction that rolls back is invisible to everyone."""
    source_id = f"kn-m1rb-{uuid.uuid4().hex[:10]}"
    with psycopg.connect(_DB_URL, autocommit=False) as a:
        a.execute("insert into public.knowledge_sources (source_id, title, owner, source_type, visibility)"
                  " values (%s, 'TEST FIXTURE', 'o', 'guideline', 'public')", (source_id,))
        a.execute("select private.knowledge_transition_source(%s, 'review_required', 'rejected', 'test', null)",
                  (source_id,))
        a.rollback()
    with psycopg.connect(_DB_URL, autocommit=True) as b:
        assert b.execute(f"select count(*) from {EVENTS} where source_id = %s", (source_id,)).fetchone()[0] == 0
        assert b.execute("select count(*) from public.knowledge_sources where source_id = %s",
                         (source_id,)).fetchone()[0] == 0


# ------------------------------------------------------------------ append-only

@pytest.mark.parametrize("statement", [f"update {EVENTS} set reason = 'rewritten'", f"delete from {EVENTS}",
                                       f"truncate {EVENTS}"])
def test_the_event_log_is_append_only_even_for_the_owner(tx, statement):
    src = tx.source()
    assert tx.events("source", src)
    assert tx.operator(statement) == ("err", PERMISSION_DENIED)
    assert tx.events("source", src)


@pytest.mark.parametrize("role", ["service_role", "authenticated", "anon"])
@pytest.mark.parametrize("statement", [f"update {EVENTS} set reason = 'x'", f"delete from {EVENTS}",
                                       f"truncate {EVENTS}",
                                       f"insert into {EVENTS} (entity_type, source_id, from_status, to_status, reason,"
                                       f" actor_session_user, actor_role) values ('source', 'kn-forged',"
                                       f" 'review_required', 'rejected', 'forged', 'postgres', 'postgres')"])
def test_no_role_can_write_the_event_log(tx, role, statement):
    tx.source()
    assert _as_role(tx, role, statement) == ("err", PERMISSION_DENIED)


# ------------------------------------------------------------------ authorization boundary

@pytest.mark.parametrize("role", ["authenticated", "anon"])
def test_clients_cannot_call_a_transition_or_read_events(tx, role):
    src = tx.source(status="review_required")
    claims = _client(tx, tx.manager) if role == "authenticated" else {"role": "anon"}
    assert _as_role(tx, role, TRANSITION["source"], (src, "review_required", "approved", "x", tx.approver),
                    claims) == ("err", PERMISSION_DENIED)
    assert _as_role(tx, role, f"select * from {EVENTS}", (), claims) == ("err", PERMISSION_DENIED)
    assert _as_role(tx, role, "update public.knowledge_sources set status = 'approved' where source_id = %s",
                    (src,), claims) == ("err", PERMISSION_DENIED)
    assert tx.status_of("source", src) == "review_required" and tx.events("source", src) == []


def test_a_tenant_member_sees_no_event_of_their_own_organizations_knowledge(tx):
    """Event privacy: the log is operator-only, so even an in-scope member reads nothing."""
    src = tx.source(visibility="tenant", org=tx.org_a)
    assert tx.events("source", src)
    for user in (tx.member, tx.manager, tx.outsider):
        assert _as_role(tx, "authenticated", f"select count(*) from {EVENTS} where source_id = %s", (src,),
                        _client(tx, user)) == ("err", PERMISSION_DENIED)


def test_service_role_transitions_are_attributed_to_service_role(tx):
    doc = tx.document(tx.source(), status="review_required")
    result = _as_role(tx, "service_role", TRANSITION["document"], (doc, "review_required", "expert_review",
                                                                   "service path", None))
    assert result[0] == "ok", result
    tx.cur.execute(f"select actor_role, reason from {EVENTS} where document_pk = %s", (doc,))
    assert tx.cur.fetchall() == [("service_role", "service path")]
    assert _as_role(tx, "service_role", f"select count(*) from {EVENTS} where document_pk = %s", (doc,)) \
        == ("ok", [(1,)])


def test_service_role_cannot_forge_the_transition_marker(tx):
    """A service_role session that sets the marker itself is still refused: it is not the owner."""
    doc = tx.document(tx.source(), status="review_required")
    forged = (f"select set_config('knowledge.status_transition', 'document|{doc}|expert_review', true);"
              f" update public.knowledge_documents set status = 'expert_review' where id = '{doc}'")
    assert _as_role(tx, "service_role", forged) == ("err", PERMISSION_DENIED)
    assert tx.status_of("document", doc) == "review_required" and tx.events("document", doc) == []


def test_owner_session_marker_forgery_is_the_documented_residual(tx):
    """RESIDUAL, documented in the migration header (M2 removes it with a non-owner operator role):
    a session that IS the owner can deliberately forge the marker, as it could DISABLE TRIGGER. Its
    ordinary direct UPDATE is refused (test_rag_knowledge_storage). If this ever starts failing
    because the bypass was closed, flip it to assert the refusal."""
    doc = tx.document(tx.source(), status="review_required")
    tx.settle()
    tx.cur.execute("select set_config('knowledge.status_transition', %s, true)", (f"document|{doc}|expert_review",))
    tx.cur.execute("update public.knowledge_documents set status = 'expert_review' where id = %s", (doc,))
    assert tx.status_of("document", doc) == "expert_review" and tx.events("document", doc) == []   # unaudited


def test_a_caller_named_approver_is_recorded_as_stated(tx):
    """Human identity is not verified in M1: the approver the caller names is stored as
    `stated_approver` (and approved_by). The verified fields are the database roles."""
    doc = tx.document(tx.source(), status="expert_review")
    assert tx.transit("document", doc, "expert_review", "approved", approver=tx.manager)[0] == "ok"
    tx.cur.execute(f"select stated_approver, actor_role from {EVENTS} where document_pk = %s and to_status = 'approved'",
                   (doc,))
    approver, role = tx.cur.fetchone()
    tx.cur.execute("select current_user")
    assert approver == tx.manager and role == tx.cur.fetchone()[0]


# ------------------------------------------------------------------ concurrency

def test_concurrent_transitions_serialize_and_the_loser_writes_nothing():
    """Two sessions race the same source: the first holds the row lock, the second waits and then
    fails on its stale `from` status. Exactly one transition and one event commit.

    This test COMMITS (a second session cannot see an uncommitted row): a never-approved, rejected
    synthetic source. The source is deleted afterwards (allowed while never approved). Its event
    stays, because the log is append-only by design (source id prefix kn-m1conc-, a CI/local DB
    only)."""
    source_id = f"kn-m1conc-{uuid.uuid4().hex[:10]}"
    with psycopg.connect(_DB_URL, autocommit=True) as setup:
        setup.execute("insert into public.knowledge_sources (source_id, title, owner, source_type, visibility)"
                      " values (%s, 'TEST FIXTURE concurrency', 'o', 'guideline', 'public')", (source_id,))
    outcome = {}
    try:
        with psycopg.connect(_DB_URL, autocommit=False) as first, psycopg.connect(_DB_URL, autocommit=False) as second:
            first.execute("select private.knowledge_transition_source(%s, 'review_required', 'rejected', 'first', null)",
                          (source_id,))

            def race():
                try:
                    second.execute("set lock_timeout = '20s'")
                    second.execute("select private.knowledge_transition_source(%s, 'review_required', 'approved',"
                                   " 'second', %s)", (source_id, _any_user(second)))
                    second.commit()
                    outcome["second"] = "ok"
                except psycopg.Error as exc:
                    second.rollback()
                    outcome["second"] = exc.sqlstate

            worker = threading.Thread(target=race)
            worker.start()
            worker.join(timeout=2)
            assert worker.is_alive(), "the second transition did not wait for the first one's row lock"
            first.commit()
            worker.join(timeout=30)
            assert not worker.is_alive()
        assert outcome["second"] == CHECK_VIOLATION                       # stale `from`: nothing written
        with psycopg.connect(_DB_URL, autocommit=True) as check:
            assert check.execute("select status::text from public.knowledge_sources where source_id = %s",
                                 (source_id,)).fetchone()[0] == "rejected"
            assert check.execute(f"select from_status::text, to_status::text, reason from {EVENTS}"
                                 f" where source_id = %s order by id", (source_id,)).fetchall() \
                == [("review_required", "rejected", "first")]
    finally:
        with psycopg.connect(_DB_URL, autocommit=True) as cleanup:
            cleanup.execute("delete from public.knowledge_sources where source_id = %s", (source_id,))


def _any_user(conn):
    row = conn.execute("select id from auth.users limit 1").fetchone()
    assert row, "the seeded database has users"
    return row[0]


# ------------------------------------------------------------------ rollback and replay

ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent.parent
MIGRATION_A = ROOT / "supabase/migrations/20261005090000_knowledge_retrieval_lexical_foundation.sql"
M1 = ROOT / "supabase/migrations/20261110090100_knowledge_status_lifecycle_m1.sql"
M1_ROLLBACK = ROOT / "supabase/rollbacks/20261110090100_knowledge_status_lifecycle_m1.down.sql"
TRIGGER_FUNCTIONS = ("enforce_knowledge_source_scope", "enforce_knowledge_document_immutability",
                     "enforce_knowledge_chunk_immutability")


def _without_tx_control(path):
    return "\n".join(line for line in path.read_text(encoding="utf-8").splitlines()
                     if line.strip().lower() not in ("begin;", "commit;"))


def _body_in(path, name):
    """The $$ body of `create function private.<name>()` in a migration file."""
    text = path.read_text(encoding="utf-8")
    start = text.index("$$", text.index(f"function private.{name}()")) + 2
    return text[start:text.index("$$", start)]


def _live_body(tx, name):
    tx.cur.execute("select prosrc from pg_proc where oid = %s::regprocedure", (f"private.{name}()",))
    return tx.cur.fetchone()[0]


def test_rollback_restores_migration_a_and_replay_restores_m1(tx):
    tx.settle()
    tx.cur.execute(_without_tx_control(M1_ROLLBACK))
    for name in TRIGGER_FUNCTIONS:                                   # verbatim Migration A bodies again
        assert _live_body(tx, name) == _body_in(MIGRATION_A, name), name
    tx.cur.execute("select to_regclass('public.knowledge_status_events'), to_regproc('private.knowledge_transition_document')")
    assert tx.cur.fetchone() == (None, None)
    tx.cur.execute(M1.read_text(encoding="utf-8"))                   # replay: M1 is back and works
    for name in TRIGGER_FUNCTIONS:
        assert _live_body(tx, name) == _body_in(M1, name), name
    doc = tx.document(tx.source(), status="review_required")
    assert tx.transit("document", doc, "review_required", "expert_review")[0] == "ok"
    assert [e[1] for e in tx.events("document", doc)] == ["expert_review"]


def test_rollback_refuses_while_a_row_is_quarantined(tx):
    tx.source(status="quarantined")
    tx.settle()
    tx.cur.execute("savepoint rb")
    with pytest.raises(psycopg.errors.RaiseException, match="M1 rollback refused"):
        tx.cur.execute(_without_tx_control(M1_ROLLBACK))
    tx.cur.execute("rollback to savepoint rb")
    tx.cur.execute("select to_regclass('public.knowledge_status_events') is not null")
    assert tx.cur.fetchone()[0] is True

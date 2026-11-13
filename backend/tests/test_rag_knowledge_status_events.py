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

from tests import knowledge_status_paths as paths  # noqa: E402
from tests.knowledge_status_paths import M2_OWNED  # noqa: E402
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
        # M2: a human decision runs as the verified person's `authenticated` role (session_user stays the
        # login); every other transition is the operator's. H-b: an archive is the archivist's (`authenticated`),
        # an emergency quarantine the operator's.
        actor = "authenticated" if (kind, frm, to) in M2_OWNED or to == "archived" else login
        expected.append((*identity, frm, to, paths.event_reason(frm, to, f"why {frm}->{to}"),
                         tx.approver if to == "approved" else None, login, actor, xid, True))
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
    # M2: service_role cannot start an expert review (a verified human decision) ...
    assert _as_role(tx, "service_role", TRANSITION["document"], (doc, "review_required", "expert_review",
                                                                 "service path", None)) == ("err", PERMISSION_DENIED)
    # ... but keeps the operator transitions, attributed to it
    result = _as_role(tx, "service_role", TRANSITION["document"], (doc, "review_required", "rejected",
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


def test_owner_marker_forgery_no_longer_reaches_a_human_decision(tx):
    """M2 closed the routine part of the M1 residual: a forged marker alone no longer starts an expert
    review or approves, because the row trigger also requires this transaction's verified evidence row
    (test_rag_knowledge_m2_approval.py covers forging that too). Flipped from the M1 residual test."""
    draft = tx.document(tx.source(), status="review_required")
    in_review = tx.document(tx.source(), status="expert_review")    # reached legally, via a verified reviewer
    tx.settle()
    for doc, target, approved_by in ((draft, "expert_review", None), (in_review, "approved", tx.approver)):
        before = tx.events("document", doc)
        tx.cur.execute("savepoint f")
        tx.cur.execute("select set_config('knowledge.status_transition', %s, true)", (f"document|{doc}|{target}",))
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            tx.cur.execute("update public.knowledge_documents set status = %s, approved_by = %s,"
                           " approved_at = case when %s::uuid is null then null else now() end,"
                           " review_note = 'forged' where id = %s", (target, approved_by, approved_by, doc))
        tx.cur.execute("rollback to savepoint f")
        assert tx.events("document", doc) == before
    assert (tx.status_of("document", draft), tx.status_of("document", in_review)) == ("review_required", "expert_review")


def test_owner_session_marker_forgery_of_an_operator_transition_is_the_documented_residual(tx):
    """RESIDUAL (documented in both migration headers): a session that IS the owner can still forge the
    marker for an operator transition (here a rejection, which fails closed), as it could DISABLE
    TRIGGER. Its ordinary direct UPDATE is refused (test_rag_knowledge_storage)."""
    doc = tx.document(tx.source(), status="review_required")
    tx.settle()
    tx.cur.execute("select set_config('knowledge.status_transition', %s, true)", (f"document|{doc}|rejected",))
    tx.cur.execute("update public.knowledge_documents set status = 'rejected' where id = %s", (doc,))
    assert tx.status_of("document", doc) == "rejected" and tx.events("document", doc) == []   # unaudited


def test_an_approval_event_names_the_verified_approver(tx):
    """M2: the approver is the authenticated aal2 caller of public.knowledge_decide_document, never a
    caller-named uuid; the event's `stated_approver` equals the approval record's verified approver."""
    doc = tx.document(tx.source(), status="expert_review")
    assert tx.transit("document", doc, "expert_review", "approved", approver=tx.manager)[0] == "ok"
    tx.cur.execute(f"select e.stated_approver, e.actor_role, a.approver_user_id from {EVENTS} e"
                   " join public.knowledge_approval_records a on a.status_event_id = e.id"
                   " where e.document_pk = %s and e.to_status = 'approved'", (doc,))
    assert tx.cur.fetchone() == (tx.manager, "authenticated", tx.manager)


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
                    second.execute("select private.knowledge_transition_source(%s, 'review_required', 'rejected',"
                                   " 'second', null)", (source_id,))
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


# ------------------------------------------------------------------ rollback and replay

ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent.parent
MIGRATION_A = ROOT / "supabase/migrations/20261005090000_knowledge_retrieval_lexical_foundation.sql"
M1 = ROOT / "supabase/migrations/20261110090100_knowledge_status_lifecycle_m1.sql"
M1_ROLLBACK = ROOT / "supabase/rollbacks/20261110090100_knowledge_status_lifecycle_m1.down.sql"
M2 = ROOT / "supabase/migrations/20261110120000_knowledge_verified_expert_approval_m2.sql"
M2_ROLLBACK = ROOT / "supabase/rollbacks/20261110120000_knowledge_verified_expert_approval_m2.down.sql"
M3 = ROOT / "supabase/migrations/20261111090000_knowledge_effective_dates_m3.sql"
M3_ROLLBACK = ROOT / "supabase/rollbacks/20261111090000_knowledge_effective_dates_m3.down.sql"
M4 = ROOT / "supabase/migrations/20261112090000_knowledge_claims_contradictions_m4.sql"
M4_ROLLBACK = ROOT / "supabase/rollbacks/20261112090000_knowledge_claims_contradictions_m4.down.sql"
M4_1_ROLLBACK = ROOT / "supabase/rollbacks/20261112120000_knowledge_review_read_m4_1.down.sql"
HA_ROLLBACK = ROOT / "supabase/rollbacks/20261113090000_knowledge_m2_hardening_assurance.down.sql"
HB_ROLLBACK = ROOT / "supabase/rollbacks/20261113120000_knowledge_m2_hardening_operator.down.sql"
HC_ROLLBACK = ROOT / "supabase/rollbacks/20261113150000_knowledge_m2_hardening_supersession.down.sql"
M6_1_ROLLBACK = ROOT / "supabase/rollbacks/20261113180000_knowledge_citation_events_m6_1.down.sql"
E2_ROLLBACK = ROOT / "supabase/rollbacks/20261113210000_knowledge_integrity_approval_gate_m7_e2.down.sql"
E7_ROLLBACK = ROOT / "supabase/rollbacks/20261113235900_knowledge_integrity_independent_verification_m7_e7.down.sql"
E7_1_ROLLBACK = ROOT / "supabase/rollbacks/20261114090000_knowledge_integrity_portable_attestation_m7_e7_1.down.sql"
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


def unwind_m6_1(tx):
    """M6.1 (citation events) unwinds first, when it is installed."""
    tx.cur.execute("select to_regclass('public.knowledge_citation_events') is not null")
    if tx.cur.fetchone()[0]:
        tx.cur.execute("set local knowledge.m6_1_rollback_evidence_exported = 'yes'")
        tx.cur.execute(_without_tx_control(M6_1_ROLLBACK))


def unwind_e7_1(tx):
    """M7 E7.1 (portable attestation) unwinds first, when it is installed."""
    tx.cur.execute("select to_regnamespace('knowledge_verifier') is not null")
    if tx.cur.fetchone()[0]:
        tx.cur.execute("set local knowledge.e7_1_rollback_confirmed = 'yes'")
        tx.cur.execute(_without_tx_control(E7_1_ROLLBACK))


def unwind_e7(tx):
    """E7.1 first, then M7 E7 (independent verification), when installed."""
    unwind_e7_1(tx)
    tx.cur.execute("select to_regclass('public.knowledge_integrity_verifications') is not null")
    if tx.cur.fetchone()[0]:
        tx.cur.execute("set local knowledge.e7_rollback_confirmed = 'yes'")
        tx.cur.execute(_without_tx_control(E7_ROLLBACK))


def unwind_e2(tx):
    """E7 first, then M7 E2 (integrity approval gate), when installed."""
    unwind_e7(tx)
    tx.cur.execute("select to_regclass('public.knowledge_integrity_reports') is not null")
    if tx.cur.fetchone()[0]:
        tx.cur.execute("set local knowledge.e2_rollback_confirmed = 'yes'")
        tx.cur.execute(_without_tx_control(E2_ROLLBACK))


def unwind_hc(tx):
    """E2 (and E7, E7.1) first, then M6.1 (citation events), then H-c (custodian countersignature), before
    H-b, when installed: the reverse of the migration versions."""
    unwind_e2(tx)
    unwind_m6_1(tx)
    tx.cur.execute("select to_regclass('public.knowledge_supersession_authorizations') is not null")
    if tx.cur.fetchone()[0]:
        tx.cur.execute("set local knowledge.hc_rollback_evidence_exported = 'yes'")
        tx.cur.execute(_without_tx_control(HC_ROLLBACK))


def unwind_hb(tx):
    """H-c first, then H-b (emergency quarantine, archivist archive), before H-a, when installed."""
    unwind_hc(tx)
    tx.cur.execute("select to_regclass('public.knowledge_emergency_actions') is not null")
    if tx.cur.fetchone()[0]:
        tx.cur.execute("set local knowledge.hb_rollback_evidence_exported = 'yes'")
        tx.cur.execute(_without_tx_control(HB_ROLLBACK))


def unwind_ha(tx):
    """H-b first, then H-a (demo assurance isolation), before M4.1. These rollback tests confirm both of
    H-a's re-exposure checks: they run on synthetic rows inside a rolled-back transaction."""
    unwind_hb(tx)
    tx.cur.execute("set local knowledge.ha_rollback_confirmed = 'yes'")
    tx.cur.execute("set local knowledge.ha_rollback_reserve_unrecorded = 'yes'")
    tx.cur.execute(_without_tx_control(HA_ROLLBACK))


def unwind_m4(tx):
    """H-a, then M4.1 (reviewer read) and M4 (claims and contradiction candidates), newest first:
    the M4.1 audit table references the M2 registry."""
    unwind_ha(tx)
    tx.cur.execute("set local knowledge.m4_1_rollback_evidence_exported = 'yes'")
    tx.cur.execute(_without_tx_control(M4_1_ROLLBACK))
    tx.cur.execute("set local knowledge.m4_rollback_evidence_exported = 'yes'")
    tx.cur.execute(_without_tx_control(M4_ROLLBACK))


def test_rollback_restores_migration_a_and_replay_restores_m1(tx):
    """Rollbacks unwind newest first (M4, M3, M2, then M1); replay applies M1, M2, M3, then M4."""
    tx.settle()
    tx.cur.execute("savepoint m4_order_check")
    tx.cur.execute("set local knowledge.m3_rollback_evidence_exported = 'yes'")
    with pytest.raises(psycopg.errors.RaiseException, match="M4 is installed"):
        tx.cur.execute(_without_tx_control(M3_ROLLBACK))             # M3 never unwinds under M4
    tx.cur.execute("rollback to savepoint m4_order_check")
    unwind_m4(tx)
    tx.cur.execute("savepoint order_check")
    tx.cur.execute("set local knowledge.m2_rollback_evidence_exported = 'yes'")
    with pytest.raises(psycopg.errors.RaiseException, match="M3 is installed"):
        tx.cur.execute(_without_tx_control(M2_ROLLBACK))             # M2 never unwinds under M3
    tx.cur.execute("rollback to savepoint order_check")
    tx.cur.execute("set local knowledge.m3_rollback_evidence_exported = 'yes'")
    tx.cur.execute(_without_tx_control(M3_ROLLBACK))
    assert _live_body(tx, TRIGGER_FUNCTIONS[1]) == _body_in(M2, TRIGGER_FUNCTIONS[1])   # M3 rollback restores M2 verbatim
    tx.cur.execute("set local knowledge.m2_rollback_evidence_exported = 'yes'")   # the explicit confirmation
    tx.cur.execute(_without_tx_control(M2_ROLLBACK))
    for name in TRIGGER_FUNCTIONS[:2]:                               # M2 rollback restores M1 verbatim
        assert _live_body(tx, name) == _body_in(M1, name), name
    tx.cur.execute(_without_tx_control(M1_ROLLBACK))
    for name in TRIGGER_FUNCTIONS:                                   # verbatim Migration A bodies again
        assert _live_body(tx, name) == _body_in(MIGRATION_A, name), name
    tx.cur.execute("select to_regclass('public.knowledge_status_events'), to_regproc('private.knowledge_transition_document')")
    assert tx.cur.fetchone() == (None, None)
    tx.cur.execute(M1.read_text(encoding="utf-8"))                   # replay: M1 is back
    for name in TRIGGER_FUNCTIONS:
        assert _live_body(tx, name) == _body_in(M1, name), name
    tx.cur.execute(M2.read_text(encoding="utf-8"))                   # ... and M2 on top, and it works
    for name in TRIGGER_FUNCTIONS[:2]:
        assert _live_body(tx, name) == _body_in(M2, name), name
    tx.cur.execute(M3.read_text(encoding="utf-8"))                   # ... and M3 on top
    assert _live_body(tx, TRIGGER_FUNCTIONS[1]) == _body_in(M3, TRIGGER_FUNCTIONS[1])
    tx.cur.execute(M4.read_text(encoding="utf-8"))                   # ... and M4 on top (it replaces nothing)
    assert _live_body(tx, TRIGGER_FUNCTIONS[1]) == _body_in(M3, TRIGGER_FUNCTIONS[1])
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

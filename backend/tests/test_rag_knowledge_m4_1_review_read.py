"""RAG V1.5 M4.1 (migration 20261112120000): the read-only reviewer interface to the M4 claims and
contradiction candidates, at the DATABASE under the real roles.

Every text is a SYNTHETIC TEST FIXTURE; the numbers are not agronomic reference values. Identities
are synthetic fixtures (tests/knowledge_status_paths.py). One transaction per test, rolled back.
Skipped without SUPABASE_DB_URL.

dev3-01 stays OPEN: what the interface returns is unverified analysis for a human reviewer. It
changes no status and no review or approval depends on it.
"""

from __future__ import annotations

import time
import uuid

import pytest

from infrastructure.knowledge_claims_repo import analyze_document
from tests.test_rag_knowledge_m2_approval import as_role, code, m2, owner  # noqa: F401
from tests.test_rag_knowledge_m3_validity import approve
from tests.test_rag_knowledge_m4_claims import DRY_15, DRY_30, active, draft, store
from tests.test_rag_knowledge_status_events import ROOT, _without_tx_control
from tests.test_rag_knowledge_storage import (INVALID_PARAMETER, PERMISSION_DENIED, _DB_URL, pytestmark,  # noqa: E402
                                              psycopg, tx)

__all__ = ["pytestmark", "tx", "m2"]

M4_1 = ROOT / "supabase/migrations/20261112120000_knowledge_review_read_m4_1.sql"
M4_1_ROLLBACK = ROOT / "supabase/rollbacks/20261112120000_knowledge_review_read_m4_1.down.sql"
READ = "select public.knowledge_review_claims(%s)"
DENIED = {"access": "denied", "notice": "not available for your knowledge role"}
STATE = ("select (select count(*) from public.knowledge_status_events), (select count(*) from public.knowledge_claims),"
         " (select count(*) from public.knowledge_contradiction_candidates),"
         " (select count(*) from public.knowledge_expert_reviews), (select count(*) from public.knowledge_approval_records),"
         " (select md5(string_agg(id::text || status::text, ',' order by id)) from public.knowledge_documents),"
         " (select md5(string_agg(source_id || status::text, ',' order by source_id)) from public.knowledge_sources)")


def read(m2, uid, doc):
    return m2.call(uid, READ, (doc,))[0][0]


def person(m2, role, visibility="public", org=None):
    """A fresh verified user holding `role` in that scope."""
    uid = uuid.uuid4()
    m2.role(uid, role, visibility, org)
    return uid


def audit(tx, uid):
    tx.cur.execute("select outcome, role, personnel_id is not null, role_id is not null, requested_document_pk,"
                   " claims_returned, candidates_returned from public.knowledge_review_read_events"
                   " where caller_user_id = %s order by id", (uid,))
    return tx.cur.fetchall()


def state(tx):
    tx.cur.execute(STATE)
    return tx.cur.fetchone()


def pair(tx, m2, *, public_active=True):
    """A public version and a tenant (org A) draft whose dry-down depths disagree, with one stored
    candidate between them: (public_doc, tenant_doc)."""
    if public_active:
        _, public_doc, _ = active(tx, m2, DRY_15)
    else:
        public_doc, _ = draft(tx, m2, DRY_15)
    tenant_doc, _ = draft(tx, m2, DRY_30, src=tx.source(visibility="tenant", org=tx.org_a))
    assert analyze_document(store(tx), str(tenant_doc)).inserted == 1
    return public_doc, tenant_doc


# ================================================================== schema and privileges

def test_the_audit_table_is_rls_locked_append_only_and_pins_no_account(tx, m2):
    tx.cur.execute("select relrowsecurity, (select count(*) from pg_policies where tablename = 'knowledge_review_read_events')"
                   " from pg_class where oid = 'public.knowledge_review_read_events'::regclass")
    assert tx.cur.fetchone() == (True, 0)
    for role, expected in (("anon", False), ("authenticated", False), ("service_role", True)):
        tx.cur.execute("select has_table_privilege(%s, 'public.knowledge_review_read_events', 'select'),"
                       " has_table_privilege(%s, 'public.knowledge_review_read_events', 'insert, update, delete, truncate')",
                       (role, role))
        assert tx.cur.fetchone() == (expected, False), role
    # no foreign key to auth.users: a (denied) call must not make an account undeletable
    tx.cur.execute("select count(*) from pg_constraint where conrelid = 'public.knowledge_review_read_events'::regclass"
                   " and contype = 'f' and confrelid = 'auth.users'::regclass")
    assert tx.cur.fetchone()[0] == 0
    tx.cur.execute("select column_name from information_schema.columns where table_name = 'knowledge_review_read_events'")
    assert not {r[0] for r in tx.cur.fetchall()} & {"raw_text", "content", "snapshot", "claims", "candidates"}
    _, doc, _ = active(tx, m2, DRY_15)
    reviewer = person(m2, "expert_reviewer")
    read(m2, reviewer, doc)
    assert owner(tx, "insert into public.knowledge_review_read_events (caller_user_id, caller_session_id,"
                     " requested_document_pk, outcome) values (%s, %s, %s, 'denied')",
                 (reviewer, uuid.uuid4(), doc)) == ("err", PERMISSION_DENIED)
    assert owner(tx, "update public.knowledge_review_read_events set outcome = 'denied' where caller_user_id = %s",
                 (reviewer,)) == ("err", PERMISSION_DENIED)
    assert owner(tx, "delete from public.knowledge_review_read_events where caller_user_id = %s",
                 (reviewer,)) == ("err", PERMISSION_DENIED)
    assert owner(tx, "truncate public.knowledge_review_read_events") == ("err", PERMISSION_DENIED)


def test_the_read_function_is_definer_pinned_and_executable_only_by_authenticated(tx):
    tx.cur.execute("select prosecdef, proconfig from pg_proc where oid = 'public.knowledge_review_claims(uuid)'::regprocedure")
    assert tx.cur.fetchone() == (True, ['search_path=""'])
    for role, expected in (("anon", False), ("authenticated", True), ("service_role", False)):
        tx.cur.execute("select has_function_privilege(%s, 'public.knowledge_review_claims(uuid)', 'execute')", (role,))
        assert tx.cur.fetchone()[0] is expected, role
    for role in ("anon", "authenticated", "service_role"):
        tx.cur.execute("select has_function_privilege(%s, 'private.knowledge_review_claim_json(bigint)', 'execute')",
                       (role,))
        assert tx.cur.fetchone()[0] is False, role


# ================================================================== who may read

def test_only_a_verified_personal_aal2_session_reaches_the_function(tx, m2):
    _, doc, _ = active(tx, m2, DRY_15)
    reviewer = person(m2, "expert_reviewer")
    _, sid = m2.user(reviewer)
    assert as_role(tx, "anon", READ, (doc,)) == ("err", PERMISSION_DENIED)
    assert as_role(tx, "service_role", READ, (doc,)) == ("err", PERMISSION_DENIED)
    assert owner(tx, READ, (doc,)) == ("err", PERMISSION_DENIED)                     # owner / operator login
    good = m2.claims(reviewer, sid)
    for claims in ({**good, "aal": "aal1"}, {**good, "session_id": str(uuid.uuid4())},
                   {**good, "exp": int(time.time()) - 5}, {k: v for k, v in good.items() if k != "session_id"}):
        assert code(m2.call, reviewer, READ, (doc,), claims=claims) == PERMISSION_DENIED
    assert tx.as_user(tx.member, READ, (doc,)) == ("err", PERMISSION_DENIED)        # signed in, no aal2 session
    assert audit(tx, reviewer) == []                                                # an unverified call records nothing
    assert code(m2.call, reviewer, READ, (None,)) == INVALID_PARAMETER              # no id is a usage error, not a denial
    assert audit(tx, reviewer) == []
    assert read(m2, reviewer, doc)["access"] == "granted"


@pytest.mark.parametrize("role", ["expert_reviewer", "approver"])
def test_a_reviewer_or_approver_in_scope_reads_the_claims_labelled_unverified(tx, m2, role):
    _, doc, _ = active(tx, m2, DRY_15)
    caller = person(m2, role)
    before = state(tx)
    out = read(m2, caller, doc)
    assert out["access"] == "granted" and out["role"] == role and out["assurance"] == "unverified_analysis"
    assert out["notice"].startswith("UNVERIFIED ANALYSIS")
    tx.cur.execute("select file_sha256, source_id, document_id, document_version from public.knowledge_documents"
                   " where id = %s", (doc,))
    file_sha, source_id, document_id, document_version = tx.cur.fetchone()
    assert {"document_pk": str(doc), "file_sha256": file_sha, "source_id": source_id, "document_id": document_id,
            "document_version": document_version, "evidence_state": "active"}.items() <= out["document"].items()
    tx.cur.execute("select id, claim_id, chunk_content_sha256, span_start, span_end, raw_text, extractor_version"
                   " from public.knowledge_claims where document_pk = %s order by id", (doc,))
    rows = tx.cur.fetchall()
    assert len(rows) >= 1 and len(out["claims"]) == len(rows)
    for claim, row in zip(out["claims"], rows):
        assert claim["assurance"] == "unverified_analysis" and claim["file_sha256"] == file_sha
        assert (claim["id"], claim["claim_id"], claim["chunk_content_sha256"], claim["span_start"], claim["span_end"],
                claim["raw_text"], claim["extractor_version"]) == row
    assert out["candidates"] == []
    assert audit(tx, caller) == [("granted", role, True, True, doc, len(rows), 0)]
    assert state(tx) == before                                                      # nothing else was written


def test_everyone_else_gets_one_denial_whatever_the_reason(tx, m2):
    _, public_doc, _ = active(tx, m2, DRY_15)
    tenant_doc, _ = draft(tx, m2, DRY_30, src=tx.source(visibility="tenant", org=tx.org_a))
    missing = uuid.uuid4()
    uploader = person(m2, "uploader")
    nobody, _ = m2.user(label="norole")
    public_reviewer = person(m2, "expert_reviewer")
    org_b_reviewer = person(m2, "expert_reviewer", "tenant", tx.org_b)
    m2.ensure_admin()
    cases = [(uploader, public_doc), (nobody, public_doc), (m2.admin, public_doc), (public_reviewer, tenant_doc),
             (org_b_reviewer, tenant_doc), (org_b_reviewer, public_doc), (public_reviewer, missing), (nobody, missing)]
    before = state(tx)
    for caller, doc in cases:
        assert read(m2, caller, doc) == DENIED, (caller, doc)
    assert state(tx) == before
    # the audit row has one shape: the id as requested, no personnel, no counts
    for caller in {c for c, _ in cases}:
        asked = [d for c, d in cases if c == caller]
        assert audit(tx, caller) == [("denied", None, False, False, d, None, None) for d in asked]


def test_denied_calls_are_recorded_up_to_a_cap_per_caller_and_hour(tx, m2):
    """An account with no role cannot grow the append-only audit without bound."""
    _, doc, _ = active(tx, m2, DRY_15)
    tx.cur.execute("select private.knowledge_review_read_denied_cap()")
    cap = tx.cur.fetchone()[0]
    assert cap == 20
    nobody, _ = m2.user(label="flood")
    other, _ = m2.user(label="other")
    for _ in range(cap + 5):
        assert read(m2, nobody, doc) == DENIED                                      # the answer never changes
    assert len(audit(tx, nobody)) == cap
    assert read(m2, other, uuid.uuid4()) == DENIED and len(audit(tx, other)) == 1   # the cap is per caller
    reviewer = person(m2, "expert_reviewer")
    for _ in range(3):                                                              # granted reads are always recorded
        assert read(m2, reviewer, doc)["access"] == "granted"
    assert len(audit(tx, reviewer)) == 3
    # the window is rolling: once the recorded denials are older than an hour, recording resumes
    tx.cur.execute("alter table public.knowledge_review_read_events disable trigger knowledge_review_read_events_guard")
    tx.cur.execute("update public.knowledge_review_read_events set recorded_at = recorded_at - interval '61 minutes'"
                   " where caller_user_id = %s", (nobody,))
    tx.cur.execute("alter table public.knowledge_review_read_events enable trigger knowledge_review_read_events_guard")
    assert read(m2, nobody, doc) == DENIED and len(audit(tx, nobody)) == cap + 1


@pytest.mark.parametrize("change", ["role_suspended", "person_suspended", "role_revoked"])
def test_a_role_that_is_no_longer_active_reads_nothing(tx, m2, change):
    _, doc, _ = active(tx, m2, DRY_15)
    reviewer = person(m2, "expert_reviewer")
    assert read(m2, reviewer, doc)["access"] == "granted"
    role_id = m2.role(reviewer, "expert_reviewer")
    if change == "person_suspended":
        m2.call(m2.admin, "select public.knowledge_set_personnel_status(%s, 'suspended', 'test')", (m2.person(reviewer),))
    else:
        m2.call(m2.admin, "select public.knowledge_set_personnel_role_status(%s, %s, 'test')",
                (role_id, "suspended" if change == "role_suspended" else "revoked"))
    assert read(m2, reviewer, doc) == DENIED


# ================================================================== disclosure of the other side

def test_a_tenant_reviewer_sees_a_candidate_against_public_knowledge_everyone_can_retrieve(tx, m2):
    public_doc, tenant_doc = pair(tx, m2)
    org_a_reviewer = person(m2, "expert_reviewer", "tenant", tx.org_a)
    out = read(m2, org_a_reviewer, tenant_doc)
    assert len(out["candidates"]) == 1
    candidate = out["candidates"][0]
    assert candidate["assurance"] == "unverified_analysis"
    assert {candidate["claim_a"]["document_pk"], candidate["claim_b"]["document_pk"]} == {str(public_doc), str(tenant_doc)}
    assert audit(tx, org_a_reviewer)[-1][-1] == 1


def test_a_public_reviewer_learns_nothing_about_a_tenant_version_that_disagrees(tx, m2):
    """The candidate is withheld entirely: no row, no placeholder, no count, in the response or the audit."""
    public_doc, tenant_doc = pair(tx, m2)
    _, lone_doc, _ = active(tx, m2, DRY_15.replace("15", "16"))                     # a public version with no candidate
    public_reviewer = person(m2, "expert_reviewer")
    with_hidden, without = read(m2, public_reviewer, public_doc), read(m2, public_reviewer, lone_doc)
    assert with_hidden["candidates"] == [] and without["candidates"] == []
    assert set(with_hidden) == set(without)                                         # same shape, no extra key
    assert str(tenant_doc) not in str(with_hidden)
    assert [row[-1] for row in audit(tx, public_reviewer)] == [0, 0]
    m2.role(public_reviewer, "approver", "tenant", tx.org_a)                        # once they may read it themselves
    assert len(read(m2, public_reviewer, public_doc)["candidates"]) == 1


def test_a_tenant_reviewer_does_not_see_public_material_that_is_not_served(tx, m2):
    """A public draft is not something every user can read: only a public reviewer or approver sees it."""
    public_doc, tenant_doc = pair(tx, m2, public_active=False)
    org_a_reviewer = person(m2, "expert_reviewer", "tenant", tx.org_a)
    out = read(m2, org_a_reviewer, tenant_doc)
    assert out["candidates"] == [] and str(public_doc) not in str(out)
    assert audit(tx, org_a_reviewer)[-1][-1] == 0
    m2.role(org_a_reviewer, "expert_reviewer", "public")
    assert len(read(m2, org_a_reviewer, tenant_doc)["candidates"]) == 1


def test_candidates_are_filtered_one_by_one(tx, m2):
    """One version in two candidates, one readable and one not: exactly the readable one is returned and counted."""
    _, served, _ = active(tx, m2, DRY_15)
    hidden, _ = draft(tx, m2, DRY_15.replace("15", "16"))                           # a public draft: not served
    tenant_doc, _ = draft(tx, m2, DRY_30, src=tx.source(visibility="tenant", org=tx.org_a))
    assert analyze_document(store(tx), str(tenant_doc)).inserted == 2
    org_a_reviewer = person(m2, "expert_reviewer", "tenant", tx.org_a)
    out = read(m2, org_a_reviewer, tenant_doc)
    assert len(out["candidates"]) == 1 and str(hidden) not in str(out)
    assert {out["candidates"][0]["claim_a"]["document_pk"], out["candidates"][0]["claim_b"]["document_pk"]} \
        == {str(served), str(tenant_doc)}
    assert audit(tx, org_a_reviewer)[-1][-2:] == (len(out["claims"]), 1)


# ================================================================== non-blocking

def test_a_stored_candidate_blocks_no_approval_and_reading_changes_no_status(tx, m2):
    _, old, _ = active(tx, m2, DRY_15)
    new, _ = draft(tx, m2, DRY_30)
    assert analyze_document(store(tx), str(new)).inserted == 1
    reviewer = person(m2, "expert_reviewer")
    before = state(tx)
    assert len(read(m2, reviewer, new)["candidates"]) == 1
    assert state(tx) == before
    approve(tx, m2, new)                                                            # the candidate is only an aid
    assert (tx.status_of("document", old), tx.status_of("document", new)) == ("approved", "approved")
    assert len(read(m2, reviewer, new)["candidates"]) == 1                          # still there, still unverified


# ================================================================== rollback

def test_m4_1_rollback_needs_a_confirmation_drops_only_its_own_objects_and_replays(tx, m2):
    _, doc, _ = active(tx, m2, DRY_15)
    reviewer = person(m2, "expert_reviewer")
    read(m2, reviewer, doc)
    tx.settle()
    tx.cur.execute("savepoint rb")
    with pytest.raises(psycopg.errors.RaiseException, match="DROPS the reviewer read audit"):
        tx.cur.execute(_without_tx_control(M4_1_ROLLBACK))
    tx.cur.execute("rollback to savepoint rb")
    tx.cur.execute("set local knowledge.m4_1_rollback_evidence_exported = 'yes'")
    tx.cur.execute(_without_tx_control(M4_1_ROLLBACK))
    tx.cur.execute("select to_regclass('public.knowledge_review_read_events'), to_regproc('public.knowledge_review_claims'),"
                   " to_regproc('private.knowledge_review_claim_json'), to_regproc('private.knowledge_review_read_denied_cap'),"
                   " to_regclass('public.knowledge_claims') is not null")
    assert tx.cur.fetchone() == (None, None, None, None, True)
    tx.cur.execute(M4_1.read_text(encoding="utf-8"))                                # replay
    assert read(m2, reviewer, doc)["access"] == "granted"

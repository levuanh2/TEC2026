"""RAG V1.5 M2 (migration 20261110120000): verified expert approval, at the DATABASE under the real
roles. Identities are SYNTHETIC TEST FIXTURES (auth users inserted by the test owner with a verified
TOTP factor and a live aal2 session, called as `authenticated` with the claims PostgREST would set);
none is a real person and no real document is approved. One transaction per test, rolled back,
except the concurrency test (it commits synthetic rows and removes them). Skipped without
SUPABASE_DB_URL.

dev3-01 stays OPEN: M2 makes each decision attributable to verified, distinct, registered humans and
binds it to the exact reviewed content. It does not judge whether the content is correct.
"""

from __future__ import annotations

import json
import threading
import time
import uuid

import pytest

from tests import knowledge_status_paths as paths
from tests.test_rag_knowledge_storage import (CHECK_VIOLATION, INVALID_PARAMETER, PERMISSION_DENIED, TRANSITION,  # noqa: E402
                                              _DB_URL, pytestmark, psycopg, tx)

__all__ = ["pytestmark", "tx"]

M2_TABLES = ("knowledge_registry_admins", "knowledge_personnel", "knowledge_personnel_roles",
             "knowledge_upload_attestations", "knowledge_expert_reviews", "knowledge_approval_records")
RPCS = {
    "knowledge_register_personnel": "(uuid, text, text, text, text, uuid)",
    "knowledge_grant_personnel_role": "(uuid, text, text, uuid, text, text, text, timestamptz)",
    "knowledge_set_personnel_status": "(uuid, text, text)",
    "knowledge_set_personnel_role_status": "(uuid, text, text)",
    "knowledge_attest_document_upload": "(uuid, text, text, text)",
    "knowledge_attest_source_upload": "(text, text)",
    "knowledge_start_expert_review": "(uuid, text, text)",
    "knowledge_submit_expert_review": "(uuid, text, text, jsonb, jsonb, jsonb, text)",
    "knowledge_decide_document": "(uuid, text, text, text)",
    "knowledge_approve_source": "(text, text, text)",
    "knowledge_review_snapshot": "(uuid, text)",
    "knowledge_cancel_expert_review": "(uuid, text)",
}
START = "select public.knowledge_start_expert_review(%s, %s, %s)"
DECIDE = "select public.knowledge_decide_document(%s, %s, %s, %s)"
SUBMIT = "select public.knowledge_submit_expert_review(%s, %s, %s, %s, %s, %s, %s)"


def code(fn, *args, **kwargs):
    """'ok' or the SQLSTATE of the psycopg error `fn` raised (the helpers isolate each RPC in a savepoint)."""
    try:
        fn(*args, **kwargs)
        return "ok"
    except psycopg.Error as exc:
        return exc.sqlstate


def as_role(tx, role, sql, params=(), claims=None):
    """('ok', rows) or ('err', sqlstate) as a database role, savepoint-isolated."""
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


def owner(tx, sql, params=()):
    return tx.operator(sql, params)


@pytest.fixture
def m2(tx):
    return paths.M2.of(tx.cur)


def draft(tx, m2, *, visibility="public", org=None, content="awd guidance m2", attest=True):
    """An approved source and a review_required version with one chunk, attested by the uploader."""
    src = tx.source(visibility=visibility, org=org)
    doc = tx.document(src, status="review_required")
    tx.chunk(doc, content)
    if attest:
        m2.attest("document", doc)
    return src, doc


def sha_of(tx, doc):
    tx.cur.execute("select file_sha256 from public.knowledge_documents where id = %s", (doc,))
    return tx.cur.fetchone()[0]


def recommended(tx, m2, **kw):
    """A version under expert review whose review recommends approval: (doc, review)."""
    _, doc = draft(tx, m2, **kw)
    review = m2.start(doc)
    m2.submit(review)
    return doc, review


# ================================================================== schema and privileges

def test_m2_tables_are_rls_locked_and_readable_only_by_service_role(tx):
    for table in M2_TABLES:
        tx.cur.execute("select relrowsecurity from pg_class where oid = %s::regclass", (f"public.{table}",))
        assert tx.cur.fetchone()[0] is True, table
        tx.cur.execute("select count(*) from pg_policies where schemaname = 'public' and tablename = %s", (table,))
        assert tx.cur.fetchone()[0] == 0, table                                  # no client policy at all
        tx.cur.execute("select grantee, privilege_type from information_schema.role_table_grants"
                       " where table_schema = 'public' and table_name = %s"
                       " and grantee in ('anon', 'authenticated', 'service_role', 'PUBLIC') order by 1, 2", (table,))
        assert tx.cur.fetchall() == [("service_role", "SELECT")], table
    tx.cur.execute("select has_table_privilege('service_role', 'private.knowledge_demo_mode', 'select, update'),"
                   " has_table_privilege('authenticated', 'private.knowledge_demo_mode', 'select')")
    assert tx.cur.fetchone() == (False, False)


def test_rpcs_are_definer_pinned_and_executable_by_authenticated_only(tx):
    for name, args in RPCS.items():
        fn = f"public.{name}{args}"
        tx.cur.execute("select p.prosecdef, p.proconfig, has_function_privilege('anon', p.oid, 'execute'),"
                       " has_function_privilege('authenticated', p.oid, 'execute'),"
                       " has_function_privilege('service_role', p.oid, 'execute'),"
                       " exists (select 1 from aclexplode(coalesce(p.proacl, acldefault('f', p.proowner))) a"
                       "         where a.grantee = 0 and a.privilege_type = 'EXECUTE')"
                       " from pg_proc p where p.oid = %s::regprocedure", (fn,))
        assert tx.cur.fetchone() == (True, ['search_path=""'], False, True, False, False), fn


def test_internal_helpers_are_not_executable_by_any_client_or_service(tx):
    tx.cur.execute("select p.oid::regprocedure::text from pg_proc p join pg_namespace n on n.oid = p.pronamespace"
                   " where n.nspname = 'private' and (p.proname like 'knowledge_m2%%' or p.proname in ("
                   " 'knowledge_verified_actor', 'knowledge_actor_role', 'knowledge_person_identity', 'knowledge_identity_key',"
                   " 'knowledge_registry_admin_actor', 'knowledge_document_snapshot', 'knowledge_source_snapshot',"
                   " 'knowledge_snapshot_sha256', 'knowledge_apply_source_transition',"
                   " 'knowledge_apply_document_transition', 'knowledge_check_review_evidence',"
                   " 'knowledge_demo_reason', 'knowledge_demo_require_enabled'))")
    helpers = [r[0] for r in tx.cur.fetchall()]
    assert len(helpers) == 16, helpers
    for fn in helpers:
        tx.cur.execute("select has_function_privilege('anon', %s, 'execute'), has_function_privilege('authenticated',"
                       " %s, 'execute'), has_function_privilege('service_role', %s, 'execute')", (fn, fn, fn))
        assert tx.cur.fetchone() == (False, False, False), fn
    for fn in ("private.knowledge_demo_approve_document(uuid,uuid,text)",
               "private.knowledge_demo_approve_source(text,uuid,text)", "private.knowledge_demo_quarantine_all(text)"):
        tx.cur.execute("select has_function_privilege('authenticated', %s, 'execute'),"
                       " has_function_privilege('service_role', %s, 'execute')", (fn, fn))
        assert tx.cur.fetchone() == (False, True), fn


def test_service_role_is_not_a_member_of_authenticated(tx):
    """service_role is not a member of `authenticated` and cannot log in, so the service-role path (the
    backend's key through PostgREST, which runs fixed queries) never reaches the human RPCs. SET ROLE
    is checked against the SESSION user: the owner and PostgREST's `authenticator` login can assume
    `authenticated` -- the documented infrastructure trust boundary."""
    tx.cur.execute("select pg_has_role('service_role', 'authenticated', 'member'), rolcanlogin from pg_roles"
                   " where rolname = 'service_role'")
    assert tx.cur.fetchone() == (False, False)
    doc = tx.document(tx.source(), status="review_required")
    assert as_role(tx, "service_role", START, (doc, "0" * 64, "x")) == ("err", PERMISSION_DENIED)


# ================================================================== the verified flow

def test_full_flow_binds_every_decision_to_verified_distinct_people_and_the_reviewed_content(tx, m2):
    src, doc = draft(tx, m2)
    review = m2.start(doc, reason="starting review")
    m2.submit(review, findings=[{"kind": "contradiction", "severity": "blocking", "status": "resolved",
                                 "description": "dose differs from registry", "resolution": "erratum checked"}])
    record = m2.decide(review, tx.approver, rationale="approved after review")
    assert tx.status_of("document", doc) == "approved"
    tx.cur.execute("select d.approved_by, d.review_note, a.assurance, a.approver_user_id, a.snapshot_sha256,"
                   " r.snapshot_sha256, r.reviewer_user_id, u.uploader_user_id, a.status_event_id, r.start_event_id,"
                   " r.decision, r.qualification_category"
                   " from public.knowledge_documents d"
                   " join public.knowledge_approval_records a on a.document_pk = d.id"
                   " join public.knowledge_expert_reviews r on r.id = a.review_id"
                   " join public.knowledge_upload_attestations u on u.id = a.upload_attestation_id"
                   " where a.id = %s", (record,))
    (approved_by, note, assurance, approver, a_sha, r_sha, reviewer, uploader, approve_event, start_event, decision,
     qualification) = tx.cur.fetchone()
    assert (approved_by, approver, note, assurance) == (tx.approver, tx.approver, "approved after review", "verified")
    assert a_sha == r_sha == m2.snapshot_sha("document", doc)
    assert len({approver, reviewer, uploader}) == 3 and (reviewer, uploader) == (m2.reviewer, m2.uploader)
    assert (decision, qualification) == ("recommend_approval", "test_fixture_domain")
    tx.cur.execute("select id, from_status::text, to_status::text, stated_approver, actor_role"
                   " from public.knowledge_status_events where document_pk = %s order by id", (doc,))
    assert tx.cur.fetchall() == [(start_event, "review_required", "expert_review", None, "authenticated"),
                                 (approve_event, "expert_review", "approved", tx.approver, "authenticated")]


def test_reviewer_reject_and_return_and_approver_reject(tx, m2):
    _, doc = draft(tx, m2)
    m2.submit(m2.start(doc), "return", rationale="needs the annex")
    assert tx.status_of("document", doc) == "review_required"
    second = m2.start(doc)                                         # a new review, a new snapshot
    m2.submit(second, "reject", checklist={**paths.CHECKLIST, "claims_checked": False}, sources=[],
              rationale="wrong rates")
    assert tx.status_of("document", doc) == "rejected"
    doc2, review = recommended(tx, m2, content="awd second")
    m2.decide(review, tx.approver, "reject", rationale="not now")
    assert tx.status_of("document", doc2) == "rejected"
    tx.cur.execute("select decision, assurance from public.knowledge_approval_records where review_id = %s", (review,))
    assert tx.cur.fetchone() == ("reject", "verified")


# ================================================================== refusals: missing or wrong people

def test_the_operator_path_cannot_start_a_review_or_approve(tx, m2):
    _, doc = draft(tx, m2)
    params = (doc, "review_required", "expert_review", "operator", None)
    assert as_role(tx, "service_role", TRANSITION["document"], params) == ("err", PERMISSION_DENIED)
    assert owner(tx, TRANSITION["document"], params) == ("err", PERMISSION_DENIED)    # the owner login too
    review = m2.start(doc)
    m2.submit(review)
    assert as_role(tx, "service_role", TRANSITION["document"], (doc, "expert_review", "approved", "op", tx.approver)) \
        == ("err", PERMISSION_DENIED)
    assert as_role(tx, "service_role", TRANSITION["document"], (doc, "expert_review", "review_required", "op", None)) \
        == ("err", PERMISSION_DENIED)
    src = tx.source(status="review_required")
    assert as_role(tx, "service_role", TRANSITION["source"], (src, "review_required", "approved", "op", tx.approver)) \
        == ("err", PERMISSION_DENIED)
    # a fail-closed operator rejection of a version under review stays possible
    assert as_role(tx, "service_role", TRANSITION["document"], (doc, "expert_review", "rejected", "op", None))[0] == "ok"


def test_approval_without_a_review_or_recommendation_is_refused(tx, m2):
    _, doc = draft(tx, m2)
    assert code(m2.call, tx.approver, DECIDE, (uuid.uuid4(), "approve", "0" * 64, "x")) in (PERMISSION_DENIED,)
    m2.role(tx.approver, "approver")
    review = m2.start(doc)                                          # started, not yet recommended
    assert code(m2.decide, review, tx.approver) == CHECK_VIOLATION
    assert tx.status_of("document", doc) == "expert_review"


def test_missing_reviewer_role_or_qualification_scope_is_refused(tx, m2):
    _, doc = draft(tx, m2)
    stranger = uuid.uuid4()
    m2.person(stranger)                                             # registered, but no reviewer role
    assert code(m2.call, stranger, START, (doc, sha_of(tx, doc), "x")) == PERMISSION_DENIED
    m2.role(stranger, "expert_reviewer", "tenant", tx.org_a)       # qualified for org A only
    assert code(m2.call, stranger, START, (doc, sha_of(tx, doc), "x")) == PERMISSION_DENIED
    unregistered = m2.user(label="nobody")[0]                       # MFA but not in the registry
    assert code(m2.call, unregistered, START, (doc, sha_of(tx, doc), "x")) == PERMISSION_DENIED
    assert tx.status_of("document", doc) == "review_required"


def test_inactive_reviewer_cannot_start_and_a_later_suspension_blocks_approval(tx, m2):
    _, doc = draft(tx, m2)
    role = m2.role(m2.reviewer, "expert_reviewer")
    m2.ensure_admin()
    m2.call(m2.admin, "select public.knowledge_set_personnel_role_status(%s, 'suspended', 'leave')", (role,))
    assert code(m2.call, m2.reviewer, START, (doc, sha_of(tx, doc), "x")) == PERMISSION_DENIED
    m2.call(m2.admin, "select public.knowledge_set_personnel_role_status(%s, 'active', 'back')", (role,))
    review = m2.start(doc)
    m2.submit(review)
    person = m2.person(m2.reviewer)
    m2.call(m2.admin, "select public.knowledge_set_personnel_status(%s, 'suspended', 'credential under review')",
            (person,))
    assert code(m2.decide, review, tx.approver) == PERMISSION_DENIED
    m2.call(m2.admin, "select public.knowledge_set_personnel_status(%s, 'revoked', 'credential withdrawn')", (person,))
    assert code(m2.decide, review, tx.approver) == PERMISSION_DENIED
    assert tx.status_of("document", doc) == "expert_review"


def test_separation_of_duties_uploader_reviewer_approver(tx, m2):
    _, doc = draft(tx, m2)
    m2.role(m2.uploader, "expert_reviewer")                         # the uploader also holds a reviewer role
    assert code(m2.call, m2.uploader, START, (doc, sha_of(tx, doc), "self review")) == PERMISSION_DENIED
    review = m2.start(doc)
    m2.submit(review)
    m2.role(m2.reviewer, "approver")                                # the reviewer also holds an approver role
    assert code(m2.decide, review, m2.reviewer) == PERMISSION_DENIED
    m2.role(m2.uploader, "approver")                                # the uploader also holds an approver role
    assert code(m2.decide, review, m2.uploader) == PERMISSION_DENIED
    assert tx.status_of("document", doc) == "expert_review"
    assert m2.decide(review, tx.approver)                           # a third, distinct person can


def test_one_human_with_a_second_account_is_still_one_human(tx, m2):
    """The registry's identity_reference ties accounts to humans: the uploader's revoked record and a
    new account of the same human (same identity_reference) cannot approve that upload."""
    _, doc = draft(tx, m2)
    review = m2.start(doc)
    m2.submit(review)
    m2.ensure_admin()
    tx.cur.execute("select id, identity_reference from public.knowledge_personnel where auth_user_id = %s",
                   (m2.uploader,))
    uploader_person, identity = tx.cur.fetchone()
    m2.call(m2.admin, "select public.knowledge_set_personnel_status(%s, 'revoked', 'moved to a new account')",
            (uploader_person,))
    second_account = m2.user(label="same-human")[0]
    person = m2.call(m2.admin, "select public.knowledge_register_personnel(%s, 'TEST FIXTURE same human', %s,"
                     " 'in_person', 'TEST FIXTURE evidence', null)", (second_account, identity.upper()))[0][0]
    m2.call(m2.admin, "select public.knowledge_grant_personnel_role(%s, 'approver', 'public', null, 'test_fixture_domain',"
            " 'owner_assessment', 'TEST FIXTURE evidence', null)", (person,))
    assert code(m2.decide, review, second_account) == PERMISSION_DENIED


def test_a_reviewer_cannot_sign_another_reviewers_review(tx, m2):
    _, doc = draft(tx, m2)
    review = m2.start(doc)
    other = uuid.uuid4()
    m2.role(other, "expert_reviewer")
    assert code(m2.submit, review, reviewer=other) == PERMISSION_DENIED
    tx.cur.execute("select decision from public.knowledge_expert_reviews where id = %s", (review,))
    assert tx.cur.fetchone()[0] is None


# ================================================================== refusals: authentication

def _claims_case(tx, m2, uid, sid, case):
    good = m2.claims(uid, sid)
    if case == "aal1":
        return {**good, "aal": "aal1"}
    if case == "no_session_id":
        return {k: v for k, v in good.items() if k != "session_id"}
    if case == "foreign_session":
        return {**good, "session_id": str(m2.user(label="other")[1])}
    if case == "unknown_session":
        return {**good, "session_id": str(uuid.uuid4())}
    if case == "aal1_session":
        return {**good, "session_id": str(m2.user(uid, aal="aal1")[1])}
    if case == "expired_session":
        sid2 = uuid.uuid4()
        tx.cur.execute("insert into auth.sessions (id, user_id, aal, created_at, updated_at, not_after, tag)"
                       " values (%s, %s, 'aal2', now(), now(), now() - interval '1 minute', %s)",
                       (sid2, uid, paths.FIXTURE_TAG))
        return {**good, "session_id": str(sid2)}
    if case == "expired_token":
        return {**good, "exp": int(time.time()) - 5}
    if case == "no_exp":
        return {k: v for k, v in good.items() if k != "exp"}
    if case == "service_role_claim":
        return {**good, "role": "service_role"}
    if case == "no_sub":
        return {k: v for k, v in good.items() if k != "sub"}
    if case == "no_factor":
        tx.cur.execute("update auth.mfa_factors set status = 'unverified' where user_id = %s", (uid,))
        return good
    if case == "banned":
        tx.cur.execute("update auth.users set banned_until = now() + interval '1 day' where id = %s", (uid,))
        return good
    if case == "password_change_pending":
        tx.cur.execute("update auth.users set raw_app_meta_data = '{\"must_change_password\": true}' where id = %s",
                       (uid,))
        return good
    raise AssertionError(case)


@pytest.mark.parametrize("case", ["aal1", "no_session_id", "foreign_session", "unknown_session", "aal1_session",
                                  "expired_session", "expired_token", "no_exp", "service_role_claim", "no_sub",
                                  "no_factor", "banned", "password_change_pending"])
def test_review_needs_a_live_mfa_session_of_an_active_user(tx, m2, case):
    _, doc = draft(tx, m2)
    m2.role(m2.reviewer, "expert_reviewer")
    uid, sid = m2.user(m2.reviewer)
    claims = _claims_case(tx, m2, uid, sid, case)
    assert code(m2.call, uid, START, (doc, sha_of(tx, doc), "x"), claims=claims) == PERMISSION_DENIED, case
    assert tx.status_of("document", doc) == "review_required"


def test_owner_session_without_set_role_is_refused(tx, m2):
    """The database owner calling the RPC directly is not a person (no `authenticated` role)."""
    _, doc = draft(tx, m2)
    m2.role(m2.reviewer, "expert_reviewer")
    uid, sid = m2.user(m2.reviewer)
    tx.cur.execute("savepoint o")
    tx.cur.execute("select set_config('request.jwt.claims', %s, true)", (json.dumps(m2.claims(uid, sid)),))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        tx.cur.execute(START, (doc, sha_of(tx, doc), "owner"))
    tx.cur.execute("rollback to savepoint o")


# ================================================================== refusals: evidence

@pytest.mark.parametrize(("change", "expected"), [
    ({"checklist": {**paths.CHECKLIST, "license_verified": False}}, INVALID_PARAMETER),
    ({"checklist": {k: v for k, v in paths.CHECKLIST.items() if k != "claims_checked"}}, INVALID_PARAMETER),
    ({"checklist": {**paths.CHECKLIST, "llm_says_ok": True}}, INVALID_PARAMETER),
    ({"checklist": {**paths.CHECKLIST, "scope_checked": "yes"}}, INVALID_PARAMETER),
    ({"sources": []}, INVALID_PARAMETER),
    ({"sources": [{"reference": "  "}]}, INVALID_PARAMETER),
    ({"findings": [{"kind": "contradiction", "severity": "blocking", "status": "open", "description": "AWD depth"}]},
     CHECK_VIOLATION),
    ({"findings": [{"kind": "exception", "severity": "non_blocking", "status": "resolved", "description": "d"}]},
     INVALID_PARAMETER),
    ({"findings": [{"kind": "rumour", "severity": "blocking", "status": "resolved", "description": "d",
                    "resolution": "r"}]}, INVALID_PARAMETER),
    ({"rationale": "  "}, INVALID_PARAMETER),
    ({"findings": [{"kind": "contradiction", "severity": "blocking", "status": "accepted_exception",
                    "description": "AWD depth differs", "resolution": "we accept it"}]}, INVALID_PARAMETER),
])
def test_incomplete_or_blocking_evidence_cannot_recommend_approval(tx, m2, change, expected):
    _, doc = draft(tx, m2)
    review = m2.start(doc)
    assert code(m2.submit, review, **change) == expected, change
    tx.cur.execute("select decision from public.knowledge_expert_reviews where id = %s", (review,))
    assert tx.cur.fetchone()[0] is None
    assert code(m2.decide, review, tx.approver) == CHECK_VIOLATION          # nothing to approve


def test_an_open_non_blocking_finding_and_resolved_exceptions_are_allowed(tx, m2):
    _, doc = draft(tx, m2)
    review = m2.start(doc)
    m2.submit(review, findings=[
        {"kind": "other", "severity": "non_blocking", "status": "open", "description": "typo in title"},
        {"kind": "exception", "severity": "blocking", "status": "accepted_exception", "description": "older edition",
         "resolution": "the ministry confirmed it is still in force"}])
    assert m2.decide(review, tx.approver)


def test_evidence_rows_are_immutable_even_for_the_owner(tx, m2):
    doc, review = recommended(tx, m2)
    record = m2.decide(review, tx.approver)
    for table, key in (("knowledge_expert_reviews", review), ("knowledge_approval_records", record)):
        assert owner(tx, f"update public.{table} set snapshot_sha256 = %s where id = %s", ("0" * 64, key)) \
            == ("err", PERMISSION_DENIED), table
        assert owner(tx, f"delete from public.{table} where id = %s", (key,)) == ("err", PERMISSION_DENIED), table
    for table in paths.M2_EVIDENCE_TRIGGERS:
        assert owner(tx, f"truncate public.{table} cascade") == ("err", PERMISSION_DENIED), table
    assert owner(tx, "update public.knowledge_upload_attestations set statement = 'x' where document_pk = %s",
                 (doc,)) == ("err", PERMISSION_DENIED)


@pytest.mark.parametrize("role", ["owner", "service_role", "authenticated", "anon"])
def test_no_direct_evidence_or_registry_write_path(tx, m2, role):
    doc, review = recommended(tx, m2)
    forged = ("insert into public.knowledge_approval_records (entity_type, source_id, document_pk, review_id,"
              " upload_attestation_id, decision, approver_personnel_id, approver_role_id, approver_user_id,"
              " approver_session_id, snapshot, snapshot_sha256, rationale, status_event_id)"
              " select 'document', r.source_id, r.document_pk, r.id, r.upload_attestation_id, 'approve',"
              " r.reviewer_personnel_id, r.reviewer_role_id, r.reviewer_user_id, r.reviewer_session_id, r.snapshot,"
              " r.snapshot_sha256, 'forged', 1 from public.knowledge_expert_reviews r where r.id = %s")
    person = ("insert into public.knowledge_personnel (auth_user_id, display_name, identity_reference,"
              " identity_verification_method, identity_evidence_ref, verified_by) values (%s, 'x', %s, 'in_person',"
              " 'x', %s)")
    claims = m2.claims(tx.approver, m2.user(tx.approver)[1]) if role == "authenticated" else (
        {"role": "anon"} if role == "anon" else None)
    for sql, params in ((forged, (review,)), (person, (tx.approver, f"forged-{uuid.uuid4()}", m2.reviewer)),
                        ("insert into public.knowledge_registry_admins (auth_user_id, note) values (%s, 'me')",
                         (tx.approver,))):
        got = owner(tx, sql, params) if role == "owner" else as_role(tx, role, sql, params, claims)
        if role == "owner" and "registry_admins" in sql:
            assert got == ("ok", None)                  # the documented trust root: the owner adds admins
        else:
            assert got == ("err", PERMISSION_DENIED), (role, sql[:40])
    assert tx.status_of("document", doc) == "expert_review"


def test_a_registry_admin_never_registers_or_promotes_themselves(tx, m2):
    m2.ensure_admin()
    register = "select public.knowledge_register_personnel(%s, 'me', %s, 'in_person', 'x', null)"
    assert code(m2.call, m2.admin, register, (m2.admin, f"self-{uuid.uuid4()}")) == PERMISSION_DENIED
    outsider = m2.user(label="outsider")[0]
    m2.person(outsider)
    assert code(m2.call, outsider, register, (uuid.uuid4(), "x")) == PERMISSION_DENIED   # not an admin
    # an admin who is also personnel cannot grant or change their own record
    second_admin = m2.user(label="admin2")[0]
    tx.cur.execute("insert into public.knowledge_registry_admins (auth_user_id, note) values (%s, 'TEST FIXTURE')",
                   (second_admin,))
    person = m2.person(second_admin)
    grant = ("select public.knowledge_grant_personnel_role(%s, 'approver', 'public', null, 'test_fixture_domain',"
             " 'owner_assessment', 'x', null)")
    assert code(m2.call, second_admin, grant, (person,)) == PERMISSION_DENIED
    assert code(m2.call, second_admin, "select public.knowledge_set_personnel_status(%s, 'active', 'x')",
                (person,)) == PERMISSION_DENIED


def test_registry_records_change_only_status_and_revocation_is_terminal(tx, m2):
    person = m2.person(m2.reviewer)
    m2.ensure_admin()
    assert owner(tx, "update public.knowledge_personnel set display_name = 'renamed' where id = %s", (person,)) \
        == ("err", PERMISSION_DENIED)
    m2.call(m2.admin, "select public.knowledge_set_personnel_status(%s, 'revoked', 'left')", (person,))
    assert code(m2.call, m2.admin, "select public.knowledge_set_personnel_status(%s, 'active', 'back')",
                (person,)) == CHECK_VIOLATION
    tx.cur.execute("select status, status_changed_by, verified_by from public.knowledge_personnel where id = %s",
                   (person,))
    assert tx.cur.fetchone() == ("revoked", m2.admin, m2.admin)


# ================================================================== refusals: content changed

@pytest.mark.parametrize(("column", "value"), [
    ("artifact_ref", "knowledge-artifacts/" + "0" * 64 + "/swapped.md"), ("license_basis", "open_license"),
    ("license_reference", "CC BY 4.0"), ("official_url", "https://example.invalid/swapped"), ("title", "swapped")])
def test_decision_metadata_is_frozen_under_expert_review(tx, m2, column, value):
    _, doc = draft(tx, m2)
    m2.start(doc)
    assert owner(tx, f"update public.knowledge_documents set {column} = %s where id = %s", (value, doc)) \
        == ("err", CHECK_VIOLATION)
    assert as_role(tx, "service_role", f"update public.knowledge_documents set {column} = %s where id = %s",
                   (value, doc))[1] in (CHECK_VIOLATION, PERMISSION_DENIED)


def test_a_source_change_after_the_review_started_invalidates_the_evidence(tx, m2):
    src = tx.source(status="review_required")
    doc = tx.document(src, status="review_required")
    tx.chunk(doc, "awd source change")
    m2.attest("document", doc)
    review = m2.start(doc)
    tx.cur.execute("select title from public.knowledge_sources where source_id = %s", (src,))
    title = tx.cur.fetchone()[0]
    tx.cur.execute("update public.knowledge_sources set title = 'swapped title' where source_id = %s", (src,))
    assert code(m2.submit, review) == CHECK_VIOLATION                  # the reviewer sees the change
    tx.cur.execute("update public.knowledge_sources set title = %s where source_id = %s", (title, src))
    m2.submit(review)                                                  # back to the reviewed metadata
    tx.cur.execute("update public.knowledge_sources set owner = 'another publisher' where source_id = %s", (src,))
    assert code(m2.decide, review, tx.approver) == CHECK_VIOLATION    # the approver sees it too
    assert m2.decide(review, tx.approver, "reject", rationale="metadata changed after review")
    assert tx.status_of("document", doc) == "rejected"


def test_the_approver_must_confirm_the_reviewed_snapshot(tx, m2):
    doc, review = recommended(tx, m2)
    assert code(m2.decide, review, tx.approver, snapshot_sha256="f" * 64) == CHECK_VIOLATION
    assert code(m2.call, m2.reviewer, START, (doc, "0" * 64, "x")) == CHECK_VIOLATION   # wrong artifact hash too


def test_evidence_is_not_reused_across_reviews_or_versions(tx, m2):
    src, doc = draft(tx, m2)
    first = m2.start(doc)
    m2.submit(first, "return", rationale="fix")
    second = m2.start(doc)
    assert code(m2.submit, first) == CHECK_VIOLATION                   # a returned review is closed
    m2.submit(second)
    v2 = tx.document(src, status="review_required", version="v2")
    tx.chunk(v2, "awd v2", ordinal=0)
    m2.attest("document", v2)
    m2.start(v2)
    v1_snapshot = m2.snapshot_sha("document", doc)
    review_v2 = m2.current_review(v2)[0]
    assert code(m2.decide, review_v2, tx.approver, snapshot_sha256=v1_snapshot) == CHECK_VIOLATION
    record = m2.decide(second, tx.approver)
    assert code(m2.decide, second, tx.approver) == CHECK_VIOLATION    # one decision per review
    tx.cur.execute("select document_pk from public.knowledge_approval_records where id = %s", (record,))
    assert tx.cur.fetchone()[0] == doc and tx.status_of("document", v2) == "expert_review"


def test_a_second_attestation_or_an_attestation_of_other_hashes_is_refused(tx, m2):
    _, doc = draft(tx, m2, attest=False)
    m2.role(m2.uploader, "uploader")
    attest = "select public.knowledge_attest_document_upload(%s, %s, %s, 'x')"
    assert code(m2.call, m2.uploader, attest, (doc, "0" * 64, "0" * 64)) == CHECK_VIOLATION
    m2.attest("document", doc)
    tx.cur.execute("select file_sha256, normalized_sha256 from public.knowledge_documents where id = %s", (doc,))
    assert code(m2.call, m2.uploader, attest, (doc, *tx.cur.fetchone())) == "23505"     # unique per version
    assert code(m2.call, m2.reviewer, START, (uuid.uuid4(), "0" * 64, "x")) == PERMISSION_DENIED


# ================================================================== tenant scope

def test_tenant_scope_is_enforced_for_every_role_and_hides_existence(tx, m2):
    src_b = tx.source(visibility="tenant", org=tx.org_b)
    doc_b = tx.document(src_b, status="review_required")
    tx.chunk(doc_b, "org b awd")
    org_a_uploader = uuid.uuid4()
    m2.role(org_a_uploader, "uploader", "tenant", tx.org_a)            # uploader for org A only
    attest = "select public.knowledge_attest_document_upload(%s, %s, %s, 'x')"
    tx.cur.execute("select file_sha256, normalized_sha256 from public.knowledge_documents where id = %s", (doc_b,))
    assert code(m2.call, org_a_uploader, attest, (doc_b, *tx.cur.fetchone())) == PERMISSION_DENIED
    m2.role(m2.reviewer, "expert_reviewer")                            # public reviewer only
    snap = "select * from public.knowledge_review_snapshot(%s, null)"
    assert code(m2.call, m2.reviewer, snap, (doc_b,)) == PERMISSION_DENIED   # same error as a missing row
    assert code(m2.call, m2.reviewer, snap, (uuid.uuid4(),)) == PERMISSION_DENIED
    # the tenant's own personnel can run the whole flow
    _, doc_a = draft(tx, m2, visibility="tenant", org=tx.org_a, content="org a awd")
    m2.role(m2.reviewer, "expert_reviewer", "tenant", tx.org_a)
    review = m2.start(doc_a)
    m2.submit(review)
    public_approver = uuid.uuid4()                                     # (tx.approver approved org A's source)
    m2.role(public_approver, "approver")                               # public approver: not org A's
    assert code(m2.call, public_approver, DECIDE, (review, "approve", m2.current_review(doc_a)[3], "x")) \
        == PERMISSION_DENIED
    m2.role(public_approver, "approver", "tenant", tx.org_a)
    assert m2.decide(review, public_approver)


def test_tenant_members_read_no_personnel_or_evidence(tx, m2):
    recommended(tx, m2, visibility="tenant", org=tx.org_a)
    for user in (tx.member, tx.manager, tx.outsider):
        for table in M2_TABLES:
            assert tx.as_user(user, f"select count(*) from public.{table}") == ("err", PERMISSION_DENIED), table


# ================================================================== concurrency

def test_concurrent_approvals_serialize_and_the_loser_writes_nothing():
    """Two approvers decide the same recommended review: the first holds the version's row lock, the
    second waits, then fails on the changed status. Exactly one approval record and one event commit.
    COMMITS synthetic rows (source prefix kn-m2conc-) and removes them afterwards; the audit events
    stay (append-only by design, local/CI DB only)."""
    source_id = f"kn-m2conc-{uuid.uuid4().hex[:10]}"
    approvers = [uuid.uuid4(), uuid.uuid4()]
    outcome: dict = {}
    with psycopg.connect(_DB_URL) as setup:
        for uid in approvers:
            setup.execute("insert into auth.users (id, email, aud, role, created_at) values (%s, %s, 'authenticated',"
                          " 'authenticated', now())", (uid, f"kn-m2conc-{uid.hex[:8]}@agricarbon-test.invalid"))
        setup.execute("insert into public.knowledge_sources (source_id, title, owner, source_type, visibility)"
                      " values (%s, 'TEST FIXTURE m2 concurrency', 'o', 'guideline', 'public')", (source_id,))
        doc = setup.execute(
            "insert into public.knowledge_documents (source_id, document_id, document_version, title, language,"
            " artifact_ref, file_sha256, normalized_sha256, parser_version, normalizer_version, chunker_version,"
            " license_basis) values (%s, 'doc', 'v1', 'TEST FIXTURE', 'vi', %s, %s, %s, 'p', 'n', 'c',"
            " 'official_publication') returning id",
            (source_id, f"knowledge-artifacts/{'a' * 64}/d.md", "a" * 64, "b" * 64)).fetchone()[0]
        m2 = paths.M2.of(setup)
        m2.attest("document", doc)
        review = m2.start(doc)
        m2.submit(review)
        for uid in approvers:
            m2.role(uid, "approver")
        snapshot = m2.current_review(doc)[3]
        setup.commit()
    try:
        with psycopg.connect(_DB_URL) as first, psycopg.connect(_DB_URL) as second:
            paths.M2.of(first).call(approvers[0], DECIDE, (review, "approve", snapshot, "first"))

            def race():
                try:
                    second.execute("set lock_timeout = '20s'")
                    paths.M2.of(second).call(approvers[1], DECIDE, (review, "approve", snapshot, "second"))
                    second.commit()
                    outcome["second"] = "ok"
                except psycopg.Error as exc:
                    second.rollback()
                    outcome["second"] = exc.sqlstate

            worker = threading.Thread(target=race)
            worker.start()
            worker.join(timeout=2)
            assert worker.is_alive(), "the second approval did not wait for the first one's row lock"
            first.commit()
            worker.join(timeout=30)
            assert not worker.is_alive()
        assert outcome["second"] == CHECK_VIOLATION
        with psycopg.connect(_DB_URL, autocommit=True) as check:
            assert check.execute("select status::text, approved_by from public.knowledge_documents where id = %s",
                                 (doc,)).fetchone() == ("approved", approvers[0])
            assert check.execute("select approver_user_id, rationale from public.knowledge_approval_records"
                                 " where review_id = %s", (review,)).fetchall() == [(approvers[0], "first")]
            assert check.execute("select count(*) from public.knowledge_status_events where document_pk = %s"
                                 " and to_status = 'approved'", (doc,)).fetchone()[0] == 1
    finally:
        with psycopg.connect(_DB_URL, autocommit=True) as cleanup:
            paths.m2_cleanup(cleanup, [source_id])
            cleanup.execute("alter table public.knowledge_documents disable trigger knowledge_documents_immutable")
            cleanup.execute("alter table public.knowledge_sources disable trigger knowledge_sources_scope")
            try:
                cleanup.execute("delete from public.knowledge_documents where source_id = %s", (source_id,))
                cleanup.execute("delete from public.knowledge_sources where source_id = %s", (source_id,))
            finally:
                cleanup.execute("alter table public.knowledge_sources enable trigger knowledge_sources_scope")
                cleanup.execute("alter table public.knowledge_documents enable trigger knowledge_documents_immutable")
            cleanup.execute("delete from auth.users where id = any(%s)", (approvers,))


# ================================================================== M1 regressions and retrieval

def test_m1_quarantine_rules_hold_for_verified_approvals(tx, m2):
    doc, review = recommended(tx, m2, content="awd quarantine m2")
    m2.decide(review, tx.approver)
    assert tx.transit("document", doc, "approved", "quarantined", reason="dispute")[0] == "ok"
    assert tx.transit("document", doc, "quarantined", "approved") == ("err", CHECK_VIOLATION)
    assert tx.transit("document", doc, "quarantined", "archived", reason="withdrawn")[0] == "ok"
    assert tx.transit("document", doc, "archived", "review_required") == ("err", CHECK_VIOLATION)


def test_only_approved_content_is_retrievable_at_each_m2_stage(tx, m2):
    src = tx.source()
    doc = tx.document(src, status="review_required")
    chunk = tx.chunk(doc, "awd retrieval stage")
    m2.attest("document", doc)
    assert chunk not in tx.rpc_ids(tx.member, tx.season_a, "awd retrieval stage")
    review = m2.start(doc)
    m2.submit(review)
    assert chunk not in tx.rpc_ids(tx.member, tx.season_a, "awd retrieval stage")   # expert_review: invisible
    m2.decide(review, tx.approver)
    assert chunk in tx.rpc_ids(tx.member, tx.season_a, "awd retrieval stage")


def test_source_approval_keeps_its_own_flow_with_verified_identity(tx, m2):
    src = tx.source(status="review_required")
    assert code(m2.call, tx.approver, "select public.knowledge_approve_source(%s, %s, 'x')",
                (src, m2.snapshot_sha("source", src))) == PERMISSION_DENIED      # no approver role yet
    m2.role(tx.approver, "approver")
    assert code(m2.call, tx.approver, "select public.knowledge_approve_source(%s, %s, 'x')",
                (src, m2.snapshot_sha("source", src))) == CHECK_VIOLATION         # nobody attested it
    m2.attest("source", src)
    m2.role(m2.uploader, "approver")
    assert code(m2.call, m2.uploader, "select public.knowledge_approve_source(%s, %s, 'x')",
                (src, m2.snapshot_sha("source", src))) == PERMISSION_DENIED       # uploader cannot approve
    assert code(m2.call, tx.approver, "select public.knowledge_approve_source(%s, %s, 'x')",
                (src, "0" * 64)) == CHECK_VIOLATION                              # must confirm the metadata
    m2.approve_source(src, tx.approver, "publisher verified")
    tx.cur.execute("select status::text, approved_by from public.knowledge_sources where source_id = %s", (src,))
    assert tx.cur.fetchone() == ("approved", tx.approver)
    tx.cur.execute("select count(*) from public.knowledge_expert_reviews where source_id = %s", (src,))
    assert tx.cur.fetchone()[0] == 0                                             # no expert_review for sources


# ================================================================== demo approvals (owner switch)

DEMO_DOC = "select private.knowledge_demo_approve_document(%s, %s, %s)"
DEMO_SRC = "select private.knowledge_demo_approve_source(%s, %s, %s)"


def _demo(tx, enabled, label="ci"):
    tx.cur.execute("update private.knowledge_demo_mode set enabled = %s, environment_label = %s, note = %s",
                   (enabled, label if enabled else None, "TEST FIXTURE demo switch" if enabled else None))


def test_demo_approval_is_off_by_default_and_only_the_owner_switches_it(tx):
    tx.cur.execute("select enabled from private.knowledge_demo_mode")
    assert tx.cur.fetchall() == [(False,)]
    src = tx.source(status="review_required")
    assert as_role(tx, "service_role", DEMO_SRC, (src, tx.approver, "demo")) == ("err", PERMISSION_DENIED)
    assert as_role(tx, "service_role", "update private.knowledge_demo_mode set enabled = true") \
        == ("err", PERMISSION_DENIED)
    assert owner(tx, "update private.knowledge_demo_mode set enabled = true") == ("err", CHECK_VIOLATION)   # no label/note
    assert owner(tx, "update private.knowledge_demo_mode set enabled = true, environment_label = 'production',"
                     " note = 'x'") == ("err", CHECK_VIOLATION)
    assert owner(tx, "insert into private.knowledge_demo_mode (singleton) values (true)")[0] == "err"
    assert owner(tx, "delete from private.knowledge_demo_mode") == ("err", PERMISSION_DENIED)


def test_demo_approval_is_labelled_audited_retrievable_and_quarantined_for_go_live(tx, m2):
    _demo(tx, True)
    src = tx.source(status="review_required")
    doc = tx.document(src, status="review_required")
    chunk = tx.chunk(doc, "awd demo document")
    for role, sql, params in (("authenticated", DEMO_DOC, (doc, tx.approver, "x")), ("anon", DEMO_DOC,
                                                                                   (doc, tx.approver, "x"))):
        claims = m2.claims(tx.approver, m2.user(tx.approver)[1]) if role == "authenticated" else {"role": "anon"}
        assert as_role(tx, role, sql, params, claims) == ("err", PERMISSION_DENIED), role
    assert as_role(tx, "service_role", DEMO_SRC, (src, tx.approver, "demo source"))[0] == "ok"
    assert as_role(tx, "service_role", DEMO_DOC, (doc, tx.approver, "  "))[1] == INVALID_PARAMETER
    assert as_role(tx, "service_role", DEMO_DOC, (doc, tx.approver, "demo for the cooperative meeting"))[0] == "ok"
    tx.cur.execute("select d.status::text, d.review_note, a.assurance, a.review_id, a.approver_personnel_id"
                   " from public.knowledge_documents d join public.knowledge_approval_records a on a.document_pk = d.id"
                   " where d.id = %s", (doc,))
    assert tx.cur.fetchone() == ("approved", "DEMO - NOT EXPERT-REVIEWED: demo for the cooperative meeting",
                                 "demo_unverified", None, None)
    tx.cur.execute("select to_status::text, reason, actor_role from public.knowledge_status_events"
                   " where document_pk = %s order by id", (doc,))
    assert [(t, r.startswith("DEMO - NOT EXPERT-REVIEWED"), a) for t, r, a in tx.cur.fetchall()] == [
        ("expert_review", True, "service_role"), ("approved", True, "service_role")]
    assert chunk in tx.rpc_ids(tx.member, tx.season_a, "awd demo document")
    # a verified approval is untouched by the go-live quarantine; demo ones are quarantined
    verified_doc, review = recommended(tx, m2, content="awd verified keeps")
    m2.decide(review, tx.approver)
    _demo(tx, False)                                              # works with the switch off too
    tx.cur.execute("savepoint q")
    tx.cur.execute("set local role service_role")
    tx.cur.execute("select private.knowledge_demo_quarantine_all('go-live')")
    assert tx.cur.fetchone()[0] >= 2
    tx.cur.execute("reset role")
    tx.cur.execute("release savepoint q")
    assert (tx.status_of("document", doc), tx.status_of("source", src)) == ("quarantined", "quarantined")
    assert tx.status_of("document", verified_doc) == "approved"
    assert chunk not in tx.rpc_ids(tx.member, tx.season_a, "awd demo document")


def test_a_demo_record_cannot_be_forged_into_a_verified_one(tx, m2):
    _demo(tx, True)
    doc = tx.document(tx.source(), status="review_required")
    assert as_role(tx, "service_role", DEMO_DOC, (doc, tx.approver, "demo"))[0] == "ok"
    assert owner(tx, "update public.knowledge_approval_records set assurance = 'verified' where document_pk = %s",
                 (doc,)) == ("err", PERMISSION_DENIED)


# ================================================================== rollback

def test_m2_rollback_refuses_while_a_version_is_under_expert_review(tx, m2):
    from tests.test_rag_knowledge_status_events import M2_ROLLBACK, _without_tx_control
    _, doc = draft(tx, m2)
    m2.start(doc)
    tx.cur.execute("savepoint rb")
    with pytest.raises(psycopg.errors.RaiseException, match="DROPS the review/approval evidence"):
        tx.cur.execute(_without_tx_control(M2_ROLLBACK))                  # no explicit confirmation
    tx.cur.execute("rollback to savepoint rb")
    tx.cur.execute("set local knowledge.m2_rollback_evidence_exported = 'yes'")
    with pytest.raises(psycopg.errors.RaiseException, match="versions are in expert_review"):
        tx.cur.execute(_without_tx_control(M2_ROLLBACK))
    tx.cur.execute("rollback to savepoint rb")
    tx.cur.execute("select to_regclass('public.knowledge_approval_records') is not null")
    assert tx.cur.fetchone()[0] is True


# ================================================================== review follow-ups (agy, 2026-11-10)

@pytest.mark.parametrize("zone", ["UTC", "Asia/Ho_Chi_Minh", "America/Los_Angeles"])
def test_the_snapshot_hash_does_not_depend_on_the_session_timezone(tx, m2, zone):
    """A reviewer and an approver on sessions with different TimeZone settings see one hash."""
    _, doc = draft(tx, m2)
    tx.cur.execute("set local timezone = 'UTC'")
    review = m2.start(doc)
    tx.cur.execute(f"set local timezone = '{zone}'")
    assert m2.snapshot_sha("document", doc) == m2.current_review(doc)[3]
    m2.submit(review)
    assert m2.decide(review, tx.approver)


@pytest.mark.parametrize("variant", ["TEST-FIXTURE-SAME-9999", "test fixture same 9999 ", " Test_Fixture.Same/9999",
                                     "ＴＥＳＴ－ＦＩＸＴＵＲＥ－ＳＡＭＥ－９９９９"])
def test_identity_reference_variants_are_one_human(tx, m2, variant):
    m2.ensure_admin()
    register = "select public.knowledge_register_personnel(%s, 'TEST FIXTURE', %s, 'in_person', 'x', null)"
    m2.call(m2.admin, register, (m2.user(label="first")[0], "TEST-FIXTURE-SAME-9999"))
    assert code(m2.call, m2.admin, register, (m2.user(label="second")[0], variant)) == "23505", variant
    assert code(m2.call, m2.admin, register, (m2.user(label="blank")[0], " -/. ")) == CHECK_VIOLATION


def test_a_registry_admin_can_cancel_a_stuck_review_and_it_cannot_be_reused(tx, m2):
    _, doc = draft(tx, m2)
    review = m2.start(doc)
    person = m2.person(m2.reviewer)
    m2.ensure_admin()
    m2.call(m2.admin, "select public.knowledge_set_personnel_status(%s, 'suspended', 'lost MFA device')", (person,))
    cancel = "select public.knowledge_cancel_expert_review(%s, %s)"
    assert code(m2.call, m2.reviewer, cancel, (review, "x")) == PERMISSION_DENIED        # not an admin
    m2.call(m2.admin, cancel, (review, "reviewer unavailable"))
    assert tx.status_of("document", doc) == "review_required"
    tx.cur.execute("select decision, cancelled_by, decision_event_id is not null from public.knowledge_expert_reviews"
                   " where id = %s", (review,))
    assert tx.cur.fetchone() == ("cancelled", m2.admin, True)
    assert code(m2.call, m2.admin, cancel, (review, "again")) == CHECK_VIOLATION
    m2.call(m2.admin, "select public.knowledge_set_personnel_status(%s, 'active', 'new device enrolled')", (person,))
    assert code(m2.submit, review) == CHECK_VIOLATION                                      # closed for good
    fresh = m2.start(doc)
    m2.submit(fresh)
    assert code(m2.call, m2.admin, cancel, (fresh, "x")) == CHECK_VIOLATION   # a recommended review goes to the approver
    assert m2.decide(fresh, tx.approver)


def test_a_rejected_source_is_approved_through_the_verified_rpc(tx, m2):
    src = tx.source(status="rejected")
    m2.approve_source(src, tx.approver, "re-verified")
    tx.cur.execute("select from_status::text, to_status::text, actor_role from public.knowledge_status_events"
                   " where source_id = %s and entity_type = 'source' order by id", (src,))
    assert tx.cur.fetchall()[-1] == ("rejected", "approved", "authenticated")


def test_an_expired_or_not_yet_valid_role_does_not_count(tx, m2):
    _, doc = draft(tx, m2)
    reviewer = uuid.uuid4()
    person = m2.person(reviewer)
    m2.ensure_admin()
    for valid_from, valid_until in (("now() - interval '2 days'", "now() - interval '1 day'"),
                                    ("now() + interval '1 day'", "now() + interval '2 days'")):
        tx.cur.execute("savepoint v")
        # the validity window is normally set by the grant RPC; the owner inserts it directly here (test only)
        tx.cur.execute("select set_config('knowledge.m2_write', 'knowledge_personnel_roles', true)")
        tx.cur.execute("insert into public.knowledge_personnel_roles (personnel_id, role, scope_visibility,"
                       " qualification_category, qualification_method, qualification_evidence_ref, valid_from,"
                       f" valid_until, verified_by) values (%s, 'expert_reviewer', 'public', 'test_fixture_domain',"
                       f" 'owner_assessment', 'x', {valid_from}, {valid_until}, %s)", (person, m2.admin))
        tx.cur.execute("select set_config('knowledge.m2_write', '', true)")
        assert code(m2.call, reviewer, START, (doc, sha_of(tx, doc), "x")) == PERMISSION_DENIED
        tx.cur.execute("rollback to savepoint v")


@pytest.mark.parametrize("rpc", sorted(RPCS))
def test_a_farmer_session_without_aal2_reaches_no_m2_rpc(tx, m2, rpc):
    """An ordinary signed-in user (aal1, as PostgREST would run them) is refused by every RPC before any
    argument is looked at."""
    args = RPCS[rpc].strip("()").split(", ")
    nulls = ", ".join(f"null::{a}" for a in args)
    claims = {"sub": str(tx.member), "role": "authenticated", "aal": "aal1", "exp": int(time.time()) + 600}
    got = as_role(tx, "authenticated", f"select public.{rpc}({nulls})" if "snapshot" not in rpc
                  else f"select * from public.{rpc}({nulls})", (), claims)
    assert got == ("err", PERMISSION_DENIED), rpc
    assert as_role(tx, "anon", f"select public.{rpc}({nulls})", (), {"role": "anon"}) == ("err", PERMISSION_DENIED)

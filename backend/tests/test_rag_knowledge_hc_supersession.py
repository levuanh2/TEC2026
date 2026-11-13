"""RAG V1.5 hardening H-c (migration 20261113150000): cross-source supersession needs a countersignature
by an independent, active custodian of the TARGET source (owner decision D-H4, option C).

Every text is a SYNTHETIC TEST FIXTURE; publishers, custodians and every identity are synthetic fixtures on
reserved test domains, never real organizations or people. One transaction per test, rolled back.
Skipped without SUPABASE_DB_URL. dev3-01 stays OPEN.
"""

from __future__ import annotations

import uuid

import pytest

from tests import knowledge_status_paths as paths
from tests.test_rag_knowledge_m2_approval import as_role, code, m2, owner  # noqa: F401
from tests.test_rag_knowledge_m3_validity import approve, approved, authority, cross_source, version
from tests.test_rag_knowledge_status_events import HC_ROLLBACK, M3, _without_tx_control
from tests.test_rag_knowledge_storage import (CHECK_VIOLATION, PERMISSION_DENIED, _DB_URL, pytestmark,  # noqa: E402
                                              psycopg, tx)

__all__ = ["pytestmark", "tx", "m2"]

SERIALIZATION = "40001"
COUNTERSIGN = "select public.knowledge_countersign_supersession(%s, %s, %s, %s)"
STATEMENT = "TEST FIXTURE countersignature statement (synthetic)"


def submit_ok(m2, new, old):
    review = m2.start(new)
    m2.submit(review, sources=authority(old))
    return review


def target_source(tx, doc):
    tx.cur.execute("select source_id from public.knowledge_documents where id = %s", (doc,))
    return tx.cur.fetchone()[0]


# ================================================================== the rule

def test_without_a_countersignature_the_old_guidance_is_not_superseded_but_can_be_quarantined(tx, m2):
    old, old_chunk, new, _, _ = cross_source(tx, m2, countersign=False)
    review = m2.start(new)
    assert code(m2.submit, review, sources=authority(old)) == CHECK_VIOLATION      # a reference alone is not authority
    assert (tx.status_of("document", old), tx.status_of("document", new)) == ("approved", "expert_review")
    assert old_chunk in tx.rpc_ids(tx.member, tx.season_a, "awd cross source")
    tx.transition("document", old, "approved", "quarantined", "custodian unreachable")  # H-b emergency path
    assert old_chunk not in tx.rpc_ids(tx.member, tx.season_a, "awd cross source")


def test_a_valid_countersignature_lets_the_verified_flow_supersede(tx, m2):
    old, old_chunk, new, new_chunk, _ = cross_source(tx, m2)
    m2.decide(submit_ok(m2, new, old), tx.approver)
    assert (tx.status_of("document", old), tx.status_of("document", new)) == ("archived", "approved")
    tx.cur.execute("select a.target_document_pk, a.custodian_user_id, p.auth_user_id"
                   " from public.knowledge_supersession_authorizations a"
                   " join public.knowledge_personnel p on p.id = a.custodian_personnel_id where a.successor_document_pk = %s",
                   (new,))
    assert tx.cur.fetchall() == [(old, m2.custodian, m2.custodian)]


def test_same_source_supersession_needs_no_countersignature(tx, m2):
    src, old, _ = approved(tx, m2, content="awd hc same source old")
    new, _ = version(tx, m2, src, version="v2", content="awd hc same source new", supersedes_document_pk=old)
    approve(tx, m2, new)
    assert (tx.status_of("document", old), tx.status_of("document", new)) == ("archived", "approved")


# ================================================================== role spoofing and scope

def test_only_an_active_custodian_of_the_target_source_countersigns(tx, m2):
    old, _, new, _, other = cross_source(tx, m2, countersign=False)
    params = (new, m2.snapshot_sha("document", new), m2.snapshot_sha("document", old), STATEMENT)
    # an approver, an archivist and an expert reviewer of the same scope are not custodians
    for role in ("approver", "archivist", "expert_reviewer"):
        who = uuid.uuid4()
        m2.role(who, role)
        assert code(m2.call, who, COUNTERSIGN, params) == PERMISSION_DENIED, role
    # a custodian of the REPLACING source (or of any other source) is not a custodian of the target
    for src in (other, tx.source()):
        who = uuid.uuid4()
        m2.custody(who, src)
        assert code(m2.call, who, COUNTERSIGN, params) == PERMISSION_DENIED
    # shared credentials and owner sessions are not a person
    assert as_role(tx, "service_role", COUNTERSIGN, params) == ("err", PERMISSION_DENIED)
    assert owner(tx, COUNTERSIGN, params) == ("err", PERMISSION_DENIED)
    tx.cur.execute("select count(*) from public.knowledge_supersession_authorizations where successor_document_pk = %s",
                   (new,))
    assert tx.cur.fetchone()[0] == 0


def test_a_custodian_of_another_tenants_source_cannot_countersign(tx, m2):
    """Custody is per source: an assignment for org B's tenant source gives no authority over a public
    source or over org A's tenant source."""
    old, _, new, _, _ = cross_source(tx, m2, countersign=False)
    tenant_b = tx.source(visibility="tenant", org=tx.org_b)
    who = uuid.uuid4()
    m2.custody(who, tenant_b)
    assert code(m2.call, who, COUNTERSIGN, (new, m2.snapshot_sha("document", new), m2.snapshot_sha("document", old),
                                            STATEMENT)) == PERMISSION_DENIED


def test_registry_rows_need_a_registry_admin_and_custody_needs_a_bound_active_publisher(tx, m2):
    src = tx.source()
    person = m2.person(m2.custodian, label="custodian")
    m2.ensure_admin()
    # no publisher binding yet: no custodian
    assert code(m2.call, m2.admin, "select public.knowledge_grant_source_custodian(%s, %s, %s)",
                (person, src, "TEST FIXTURE evidence")) == CHECK_VIOLATION
    # only a registry admin registers publishers
    nobody = uuid.uuid4()
    m2.role(nobody, "approver")
    assert code(m2.call, nobody, "select public.knowledge_register_publisher('test-fixture-x1', 'TEST FIXTURE', %s)",
                ("TEST FIXTURE identity evidence",)) == PERMISSION_DENIED
    m2.publisher_for(src)
    # a binding is immutable: no rebinding to another publisher
    other = m2.call(m2.admin, "select public.knowledge_register_publisher(%s, 'TEST FIXTURE other', %s)",
                    (f"test-fixture-{uuid.uuid4().hex[:8]}", "TEST FIXTURE identity evidence"))[0][0]
    assert code(m2.call, m2.admin, "select public.knowledge_bind_source_publisher(%s, %s, %s)",
                (src, other, "TEST FIXTURE rebinding evidence")) == CHECK_VIOLATION
    # a registry admin never makes themselves a custodian
    second_admin = m2.user(label="admin2")[0]
    tx.cur.execute("insert into public.knowledge_registry_admins (auth_user_id, note) values (%s, %s)",
                   (second_admin, f"TEST FIXTURE registry admin TEST-FIXTURE-M2-{m2.tag}"))
    admin_person = m2.call(second_admin, "select public.knowledge_register_personnel(%s, 'TEST FIXTURE admin', %s,"
                           " 'in_person', 'TEST FIXTURE evidence', null)",
                           (m2.admin, f"TEST-FIXTURE-M2-{m2.tag}-admin-person"))[0][0]
    assert code(m2.call, m2.admin, "select public.knowledge_grant_source_custodian(%s, %s, %s)",
                (admin_person, src, "TEST FIXTURE evidence")) == PERMISSION_DENIED


# ================================================================== stale evidence and identity changes

def test_a_stale_hash_is_refused_at_countersigning(tx, m2):
    old, _, new, _, _ = cross_source(tx, m2, countersign=False)
    assert code(m2.countersign, new, successor_sha="0" * 64) == SERIALIZATION
    assert code(m2.countersign, new, target_sha="0" * 64) == SERIALIZATION


def test_a_countersignature_of_other_content_does_not_count(tx, m2):
    """The successor changes after the countersignature (a chunk added while still review_required)."""
    old, _, new, _, _ = cross_source(tx, m2)
    tx.chunk(new, "awd cross source added after the countersignature", ordinal=1)
    review = m2.start(new)
    assert code(m2.submit, review, sources=authority(old)) == CHECK_VIOLATION
    m2.countersign(new)                                                           # a fresh one for the new content
    m2.submit(review, sources=authority(old))
    m2.decide(review, tx.approver)
    assert tx.status_of("document", old) == "archived"


def test_a_countersignature_for_another_pair_does_not_count(tx, m2):
    old, _, new, _, other = cross_source(tx, m2, countersign=False)
    # the same custodian countersigns a different successor of the same target: not this one
    sibling, _ = version(tx, m2, other, document_id="doc-sibling", content="awd cross source sibling",
                         supersedes_document_pk=old)
    m2.countersign(sibling)
    assert code(m2.submit, m2.start(new), sources=authority(old)) == CHECK_VIOLATION


@pytest.mark.parametrize("change", ["custodian_suspended", "custodian_revoked", "person_revoked",
                                    "publisher_suspended", "publisher_revoked"])
def test_a_change_of_custody_or_publisher_after_the_countersignature_refuses_the_approval(tx, m2, change):
    old, old_chunk, new, _, _ = cross_source(tx, m2)
    review = submit_ok(m2, new, old)                                              # valid at submission
    src = target_source(tx, old)
    tx.cur.execute("select c.id, c.personnel_id, c.publisher_id from public.knowledge_source_custodians c"
                   " where c.source_id = %s", (src,))
    custodian_id, person, publisher = tx.cur.fetchone()
    status = change.split("_")[1]
    sql = {"custodian": "select public.knowledge_set_source_custodian_status(%s, %s, 'TEST FIXTURE change')",
           "person": "select public.knowledge_set_personnel_status(%s, %s, 'TEST FIXTURE change')",
           "publisher": "select public.knowledge_set_publisher_status(%s, %s, 'TEST FIXTURE change')"}[change.split("_")[0]]
    key = {"custodian": custodian_id, "person": person, "publisher": publisher}[change.split("_")[0]]
    m2.call(m2.admin, sql, (key, status))
    assert code(m2.decide, review, tx.approver) == CHECK_VIOLATION               # re-validated at the approval
    assert (tx.status_of("document", old), tx.status_of("document", new)) == ("approved", "expert_review")
    assert old_chunk in tx.rpc_ids(tx.member, tx.season_a, "awd cross source")


# ================================================================== independence

def test_the_custodian_is_independent_of_the_uploader_reviewer_and_approver(tx, m2):
    old, _, new, _, _ = cross_source(tx, m2, countersign=False)
    assert code(m2.countersign, new, m2.uploader) == PERMISSION_DENIED           # the successor's uploader
    review = m2.start(new)
    assert code(m2.countersign, new, m2.reviewer) == PERMISSION_DENIED           # its reviewer
    # a custodian who is also the approver: the countersignature is valid at submission, not at approval
    m2.countersign(new, tx.approver)
    m2.submit(review, sources=authority(old))
    assert code(m2.decide, review, tx.approver) == CHECK_VIOLATION
    other_approver = uuid.uuid4()
    m2.decide(review, other_approver)
    assert tx.status_of("document", old) == "archived"


def test_a_custodian_who_becomes_the_reviewer_voids_their_countersignature(tx, m2):
    old, _, new, _, _ = cross_source(tx, m2, countersign=False)
    m2.countersign(new, m2.reviewer)
    review = m2.start(new)                                                        # the same human now reviews
    assert code(m2.submit, review, sources=authority(old)) == CHECK_VIOLATION


# ================================================================== forged and demo

def test_countersignatures_cannot_be_forged_or_changed(tx, m2):
    old, _, new, _, _ = cross_source(tx, m2)
    for sql in ("update public.knowledge_supersession_authorizations set statement = 'TEST FIXTURE forged statement x'",
                "delete from public.knowledge_supersession_authorizations",
                "truncate public.knowledge_supersession_authorizations",
                "update public.knowledge_source_publishers set ownership_evidence = 'TEST FIXTURE forged'",
                "delete from public.knowledge_source_custodians"):
        assert owner(tx, sql) == ("err", PERMISSION_DENIED), sql
    tx.cur.execute("select row_to_json(a)::jsonb from public.knowledge_supersession_authorizations a"
                   " where successor_document_pk = %s", (new,))
    row = tx.cur.fetchone()[0]
    assert owner(tx, "insert into public.knowledge_supersession_authorizations (target_document_pk, target_source_id,"
                     " target_snapshot_sha256, successor_document_pk, successor_source_id, successor_snapshot_sha256,"
                     " publisher_id, custodian_id, custodian_personnel_id, custodian_user_id, custodian_session_id,"
                     " statement) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                 (row["target_document_pk"], row["target_source_id"], row["target_snapshot_sha256"],
                  row["successor_document_pk"], row["successor_source_id"], row["successor_snapshot_sha256"],
                  row["publisher_id"], row["custodian_id"], row["custodian_personnel_id"], row["custodian_user_id"],
                  row["custodian_session_id"], STATEMENT)) == ("err", PERMISSION_DENIED)
    for role in ("authenticated", "anon"):
        assert as_role(tx, role, "select count(*) from public.knowledge_supersession_authorizations") \
            == ("err", PERMISSION_DENIED), role


def test_grants(tx):
    for fn in ("public.knowledge_register_publisher(text,text,text)", "public.knowledge_set_publisher_status(uuid,text,text)",
               "public.knowledge_bind_source_publisher(text,uuid,text)",
               "public.knowledge_grant_source_custodian(uuid,text,text)",
               "public.knowledge_set_source_custodian_status(uuid,text,text)",
               "public.knowledge_countersign_supersession(uuid,text,text,text)",
               "public.knowledge_custodian_snapshot(uuid)"):
        for role, expected in (("authenticated", True), ("service_role", False), ("anon", False)):
            tx.cur.execute("select has_function_privilege(%s, %s, 'execute')", (role, fn))
            assert tx.cur.fetchone()[0] is expected, (fn, role)


def test_a_custodian_reads_the_hash_of_the_target(tx, m2):
    old, _, new, _, _ = cross_source(tx, m2, countersign=False)
    m2.custody(m2.custodian, target_source(tx, old))
    rows = m2.call(m2.custodian, "select snapshot_sha256 from public.knowledge_custodian_snapshot(%s)", (old,))
    assert rows == [(m2.snapshot_sha("document", old),)]
    stranger = uuid.uuid4()
    m2.person(stranger)
    assert code(m2.call, stranger, "select * from public.knowledge_custodian_snapshot(%s)", (old,)) == PERMISSION_DENIED


# ================================================================== rollback

def test_rollback_refuses_without_the_export_and_restores_the_m3_check_verbatim(tx):
    tx.settle()
    tx.cur.execute("savepoint rb")
    with pytest.raises(psycopg.errors.RaiseException, match="hc_rollback_evidence_exported"):
        tx.cur.execute(_without_tx_control(HC_ROLLBACK))
    tx.cur.execute("rollback to savepoint rb")
    tx.cur.execute("set local knowledge.hc_rollback_evidence_exported = 'yes'")
    tx.cur.execute(_without_tx_control(HC_ROLLBACK))
    tx.cur.execute("select to_regclass('public.knowledge_supersession_authorizations'),"
                   " to_regclass('public.knowledge_publishers')")
    assert tx.cur.fetchone() == (None, None)
    tx.cur.execute("select prosrc from pg_proc where oid ="
                   " 'private.knowledge_check_cross_source_supersession(uuid,jsonb)'::regprocedure")
    body = tx.cur.fetchone()[0].replace("\r\n", "\n").strip()
    m3 = M3.read_text(encoding="utf-8").replace("\r\n", "\n")
    start = m3.index("create function private.knowledge_check_cross_source_supersession(")
    assert body == m3[m3.index("as $$", start) + 5:m3.index("$$;", start)].strip()


def test_no_hosted_target():
    assert _DB_URL

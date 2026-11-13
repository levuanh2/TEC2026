"""RAG V1.5 hardening H-b (migration 20261113120000): emergency quarantine with typed, immutable
evidence, and permanent archive by an authenticated archivist.

Owner decisions (2026-11-12): D-H2a a separate `archivist` role; D-H2b the original approver does not
archive their own approved version directly.

Every text is a SYNTHETIC TEST FIXTURE; identities are synthetic fixtures on reserved test domains and
the operator references are synthetic, not real tickets. One transaction per test, rolled back.
Skipped without SUPABASE_DB_URL. dev3-01 stays OPEN.
"""

from __future__ import annotations

import uuid

import pytest

from tests import knowledge_status_paths as paths
from tests.test_rag_knowledge_m2_approval import as_role, code, m2, owner, recommended  # noqa: F401
from tests.test_rag_knowledge_m3_validity import approve, version
from tests.test_rag_knowledge_status_events import HB_ROLLBACK, _without_tx_control
from tests.test_rag_knowledge_storage import (CHECK_VIOLATION, INVALID_PARAMETER, PERMISSION_DENIED,  # noqa: E402
                                              _DB_URL, pytestmark, psycopg, tx)

__all__ = ["pytestmark", "tx", "m2"]

SERIALIZATION = "40001"
EQ_DOC = "select private.knowledge_emergency_quarantine_document(%s, %s, %s, %s)"
EQ_SRC = "select private.knowledge_emergency_quarantine_source(%s, %s, %s, %s)"
ARCHIVE_DOC = "select public.knowledge_archive_document(%s, %s, %s, %s)"
ARCHIVE_SRC = "select public.knowledge_archive_source(%s, %s, %s, %s)"
DETAIL = "TEST FIXTURE: synthetic integrity incident detail"
TICKET = "TEST-FIXTURE-INC-1"
RATIONALE = "TEST FIXTURE: synthetic archive rationale text"
REASON_CODES = ("integrity_mismatch", "provenance_withdrawn", "rights_withdrawn", "harmful_content_report",
                "superseding_law", "demo_go_live", "operator_error_containment")


def approved_doc(tx, m2, content="awd hb guidance"):
    doc, review = recommended(tx, m2, content=content)
    m2.decide(review, tx.approver)
    tx.cur.execute("select chunk_id from public.knowledge_chunks where document_pk = %s", (doc,))
    return doc, tx.cur.fetchone()[0]


def events(tx, doc):
    tx.cur.execute("select id, from_status::text, to_status::text from public.knowledge_status_events"
                   " where document_pk = %s order by id", (doc,))
    return tx.cur.fetchall()


def archive_doc(m2, doc, who, *, sha=None, reason_code="retention_policy", rationale=RATIONALE, claims=None):
    m2.role(who, "archivist", *m2.scope("document", doc))
    return m2.call(who, ARCHIVE_DOC, (doc, sha or m2.snapshot_sha("document", doc), reason_code, rationale),
                   claims=claims)[0][0]


# ================================================================== emergency quarantine

@pytest.mark.parametrize("reason_code", REASON_CODES)
def test_emergency_quarantine_writes_the_transition_and_its_evidence_together(tx, m2, reason_code):
    doc, chunk = approved_doc(tx, m2)
    sha = m2.snapshot_sha("document", doc)
    status, rows = as_role(tx, "service_role", EQ_DOC, (doc, reason_code, DETAIL, TICKET))
    assert status == "ok"
    evidence = rows[0][0]
    assert tx.status_of("document", doc) == "quarantined"
    tx.cur.execute("select e.entity_type, e.reason_code, e.reason_detail, e.operator_reference, e.snapshot_sha256,"
                   " e.db_role, s.to_status::text, s.from_status::text, s.transaction_id = e.recorded_xact,"
                   " s.reason like 'EMERGENCY %%'"
                   " from public.knowledge_emergency_actions e join public.knowledge_status_events s on s.id = e.status_event_id"
                   " where e.id = %s", (evidence,))
    assert tx.cur.fetchone() == ("document", reason_code, DETAIL, TICKET, sha, "service_role", "quarantined",
                                 "approved", True, True)
    assert chunk not in tx.rpc_ids(tx.member, tx.season_a, "awd hb guidance")


@pytest.mark.parametrize("args", [("not_a_code", DETAIL, TICKET), (None, DETAIL, TICKET), ("integrity_mismatch", "short", TICKET),
                                  ("integrity_mismatch", " " * 30, TICKET), ("integrity_mismatch", DETAIL, ""),
                                  ("integrity_mismatch", DETAIL, None), ("integrity_mismatch", DETAIL, "  ")])
def test_emergency_quarantine_needs_a_closed_reason_a_detail_and_an_operator_reference(tx, m2, args):
    doc, _ = approved_doc(tx, m2)
    before = events(tx, doc)
    assert as_role(tx, "service_role", EQ_DOC, (doc, *args)) == ("err", INVALID_PARAMETER)
    assert tx.status_of("document", doc) == "approved" and events(tx, doc) == before


def test_a_failed_emergency_quarantine_writes_nothing(tx, m2):
    doc, review = recommended(tx, m2)                         # under expert review, not approved
    before = events(tx, doc)
    assert as_role(tx, "service_role", EQ_DOC, (doc, "integrity_mismatch", DETAIL, TICKET)) == ("err", CHECK_VIOLATION)
    assert as_role(tx, "service_role", EQ_DOC, (uuid.uuid4(), "integrity_mismatch", DETAIL, TICKET))[0] == "err"
    tx.cur.execute("select count(*) from public.knowledge_emergency_actions where document_pk = %s", (doc,))
    assert tx.cur.fetchone()[0] == 0 and events(tx, doc) == before


def test_the_generic_operator_path_refuses_quarantine_and_archive_for_everyone(tx, m2):
    doc, _ = approved_doc(tx, m2)
    src = tx.source()
    for role in ("service_role", None):
        for kind, key, to in (("document", doc, "quarantined"), ("document", doc, "archived"),
                              ("source", src, "quarantined"), ("source", src, "archived")):
            sql = paths.TRANSITION[kind]
            params = (key, "approved", to, "operator shortcut", None)
            result = as_role(tx, role, sql, params) if role else owner(tx, sql, params)
            assert result == ("err", PERMISSION_DENIED), (role, kind, to)
    assert (tx.status_of("document", doc), tx.status_of("source", src)) == ("approved", "approved")
    # a stale request is still reported as such first (M1 contract)
    assert as_role(tx, "service_role", paths.TRANSITION["document"],
                   (doc, "quarantined", "archived", "stale", None)) == ("err", CHECK_VIOLATION)


def test_only_service_role_and_the_owner_reach_emergency_quarantine(tx):
    for fn in ("private.knowledge_emergency_quarantine_document(uuid,text,text,text)",
               "private.knowledge_emergency_quarantine_source(text,text,text,text)"):
        for role, expected in (("service_role", True), ("authenticated", False), ("anon", False)):
            tx.cur.execute("select has_function_privilege(%s, %s, 'execute')", (role, fn))
            assert tx.cur.fetchone()[0] is expected, (fn, role)


def test_emergency_quarantine_of_a_source(tx):
    src = tx.source()
    status, rows = as_role(tx, "service_role", EQ_SRC, (src, "rights_withdrawn", DETAIL, TICKET))
    assert status == "ok" and tx.status_of("source", src) == "quarantined"
    tx.cur.execute("select entity_type, document_pk, reason_code from public.knowledge_emergency_actions where id = %s",
                   (rows[0][0],))
    assert tx.cur.fetchone() == ("source", None, "rights_withdrawn")


def test_emergency_and_archive_evidence_is_immutable_even_for_the_owner(tx, m2):
    doc, _ = approved_doc(tx, m2)
    assert as_role(tx, "service_role", EQ_DOC, (doc, "integrity_mismatch", DETAIL, TICKET))[0] == "ok"
    archive_doc(m2, doc, m2.archivist)
    for table in ("knowledge_emergency_actions", "knowledge_archive_records"):
        for sql in (f"update public.{table} set snapshot_sha256 = repeat('0', 64)", f"delete from public.{table}",
                    f"truncate public.{table}"):
            assert owner(tx, sql) == ("err", PERMISSION_DENIED), sql
        assert owner(tx, f"insert into public.{table} (entity_type) values ('document')")[0] == "err"
        for role in ("authenticated", "anon"):
            assert as_role(tx, role, f"select count(*) from public.{table}") == ("err", PERMISSION_DENIED), (table, role)


# ================================================================== archive

def test_an_archivist_archives_a_quarantined_version_with_an_archive_record(tx, m2):
    doc, chunk = approved_doc(tx, m2)
    tx.transition("document", doc, "approved", "quarantined")
    sha = m2.snapshot_sha("document", doc)
    record = archive_doc(m2, doc, m2.archivist, reason_code="quarantine_concluded")
    assert tx.status_of("document", doc) == "archived"
    tx.cur.execute("select r.from_status::text, r.reason_code, r.snapshot_sha256, r.archivist_user_id, p.auth_user_id,"
                   " s.to_status::text, s.actor_role from public.knowledge_archive_records r"
                   " join public.knowledge_personnel p on p.id = r.archivist_personnel_id"
                   " join public.knowledge_status_events s on s.id = r.status_event_id where r.id = %s", (record,))
    assert tx.cur.fetchone() == ("quarantined", "quarantine_concluded", sha, m2.archivist, m2.archivist,
                                 "archived", "authenticated")
    assert code(archive_doc, m2, doc, m2.archivist) == CHECK_VIOLATION            # archived is terminal
    assert chunk not in tx.rpc_ids(tx.member, tx.season_a, "awd hb guidance")


def test_an_archivist_archives_an_approved_version_directly(tx, m2):
    doc, _ = approved_doc(tx, m2)
    archive_doc(m2, doc, m2.archivist, reason_code="withdrawn_by_publisher")
    tx.cur.execute("select from_status::text from public.knowledge_archive_records where document_pk = %s", (doc,))
    assert tx.cur.fetchall() == [("approved",)]


def test_shared_service_credentials_and_owner_sessions_cannot_archive(tx, m2):
    doc, _ = approved_doc(tx, m2)
    sha = m2.snapshot_sha("document", doc)
    params = (doc, sha, "retention_policy", RATIONALE)
    assert as_role(tx, "service_role", ARCHIVE_DOC, params) == ("err", PERMISSION_DENIED)
    assert owner(tx, ARCHIVE_DOC, params) == ("err", PERMISSION_DENIED)       # not an authenticated person
    m2.role(m2.archivist, "archivist")
    # an archivist's own claims under the service role are still not a person's session
    claims = m2.claims(m2.archivist, m2.user(m2.archivist)[1])
    assert as_role(tx, "service_role", ARCHIVE_DOC, params, claims=claims) == ("err", PERMISSION_DENIED)
    for role, expected in (("authenticated", True), ("service_role", False), ("anon", False)):
        tx.cur.execute("select has_function_privilege(%s, 'public.knowledge_archive_document(uuid,text,text,text)',"
                       " 'execute')", (role,))
        assert tx.cur.fetchone()[0] is expected, role
    assert tx.status_of("document", doc) == "approved"


def test_archive_needs_aal2(tx, m2):
    doc, _ = approved_doc(tx, m2)
    m2.role(m2.archivist, "archivist")
    claims = {**m2.claims(m2.archivist, m2.user(m2.archivist)[1]), "aal": "aal1"}
    assert code(archive_doc, m2, doc, m2.archivist, claims=claims) == PERMISSION_DENIED
    assert tx.status_of("document", doc) == "approved"


def test_archive_needs_an_active_archivist_role_in_the_right_scope(tx, m2):
    doc, _ = approved_doc(tx, m2)
    nobody = uuid.uuid4()
    m2.role(nobody, "approver")                                  # a knowledge role, but not archivist
    assert code(m2.call, nobody, ARCHIVE_DOC, (doc, m2.snapshot_sha("document", doc), "retention_policy",
                                               RATIONALE)) == PERMISSION_DENIED
    # an archivist for another organization's tenant scope cannot archive public guidance
    elsewhere = uuid.uuid4()
    m2.role(elsewhere, "archivist", "tenant", tx.org_b)
    assert code(m2.call, elsewhere, ARCHIVE_DOC, (doc, m2.snapshot_sha("document", doc), "retention_policy",
                                                  RATIONALE)) == PERMISSION_DENIED
    # a suspended archivist role no longer counts
    role = m2.role(m2.archivist, "archivist")
    m2.ensure_admin()
    m2.call(m2.admin, "select public.knowledge_set_personnel_role_status(%s, 'suspended', 'TEST FIXTURE pause')", (role,))
    assert code(m2.call, m2.archivist, ARCHIVE_DOC, (doc, m2.snapshot_sha("document", doc), "retention_policy",
                                                     RATIONALE)) == PERMISSION_DENIED
    assert tx.status_of("document", doc) == "approved"


def test_archive_needs_the_exact_current_snapshot_hash_and_a_closed_reason(tx, m2):
    doc, _ = approved_doc(tx, m2)
    assert code(archive_doc, m2, doc, m2.archivist, sha="0" * 64) == SERIALIZATION
    assert code(archive_doc, m2, doc, m2.archivist, sha="not-a-hash") == INVALID_PARAMETER
    assert code(archive_doc, m2, doc, m2.archivist, reason_code="because") == INVALID_PARAMETER
    assert code(archive_doc, m2, doc, m2.archivist, rationale="too short") == INVALID_PARAMETER
    assert tx.status_of("document", doc) == "approved"


def test_the_uploader_never_archives_their_version(tx, m2):
    doc, _ = approved_doc(tx, m2)
    assert code(archive_doc, m2, doc, m2.uploader) == PERMISSION_DENIED
    tx.transition("document", doc, "approved", "quarantined")
    assert code(archive_doc, m2, doc, m2.uploader) == PERMISSION_DENIED       # not from quarantine either
    assert tx.status_of("document", doc) == "quarantined"


def test_the_approver_archives_only_through_quarantine(tx, m2):
    """D-H2b: no direct approved -> archived by the approver; quarantined -> archived is a separate act."""
    doc, _ = approved_doc(tx, m2)
    assert code(archive_doc, m2, doc, tx.approver) == PERMISSION_DENIED
    assert tx.status_of("document", doc) == "approved"
    tx.transition("document", doc, "approved", "quarantined")
    archive_doc(m2, doc, tx.approver, reason_code="quarantine_concluded")
    assert tx.status_of("document", doc) == "archived"


def test_the_same_human_with_a_second_account_is_still_the_uploader(tx, m2):
    doc, _ = approved_doc(tx, m2)
    m2.ensure_admin()
    tx.cur.execute("select id, identity_reference from public.knowledge_personnel where auth_user_id = %s", (m2.uploader,))
    person, identity = tx.cur.fetchone()
    m2.call(m2.admin, "select public.knowledge_set_personnel_status(%s, 'revoked', 'TEST FIXTURE moved account')", (person,))
    second = m2.user(label="same-human")[0]
    again = m2.call(m2.admin, "select public.knowledge_register_personnel(%s, 'TEST FIXTURE same human', %s,"
                    " 'in_person', 'TEST FIXTURE evidence', null)", (second, identity.upper()))[0][0]
    m2.call(m2.admin, "select public.knowledge_grant_personnel_role(%s, 'archivist', 'public', null,"
            " 'test_fixture_domain', 'owner_assessment', 'TEST FIXTURE evidence', null)", (again,))
    assert code(m2.call, second, ARCHIVE_DOC, (doc, m2.snapshot_sha("document", doc), "retention_policy",
                                               RATIONALE)) == PERMISSION_DENIED


def test_an_archivist_reads_the_snapshot_hash_they_confirm(tx, m2):
    doc, _ = approved_doc(tx, m2)
    m2.role(m2.archivist, "archivist")
    rows = m2.call(m2.archivist, "select snapshot_sha256 from public.knowledge_review_snapshot(%s, null)", (doc,))
    assert rows == [(m2.snapshot_sha("document", doc),)]


def test_source_archive_by_an_archivist_and_never_by_its_uploader_or_direct_approver(tx, m2):
    src = tx.source()
    for who in (m2.uploader, tx.approver):
        m2.role(who, "archivist")
        assert code(m2.call, who, ARCHIVE_SRC, (src, m2.snapshot_sha("source", src), "rights_ended",
                                                RATIONALE)) == PERMISSION_DENIED, who
    m2.archive("source", src, reason="publisher withdrew the series")
    assert tx.status_of("source", src) == "archived"


def test_supersession_still_archives_inside_the_approval(tx, m2):
    """M3: a verified approval of a successor archives the version it supersedes, atomically, with no
    archivist: the approval is the independent authorization."""
    old, _ = approved_doc(tx, m2, content="awd hb superseded")
    tx.cur.execute("select source_id from public.knowledge_documents where id = %s", (old,))
    src = tx.cur.fetchone()[0]
    new, _ = version(tx, m2, src, version="v2", content="awd hb successor", supersedes_document_pk=old)
    approve(tx, m2, new)
    assert (tx.status_of("document", old), tx.status_of("document", new)) == ("archived", "approved")
    tx.cur.execute("select count(*) from public.knowledge_archive_records where document_pk = %s", (old,))
    assert tx.cur.fetchone()[0] == 0


def test_without_an_archivist_nothing_is_archived_and_quarantine_still_works(tx, m2):
    """No break-glass: the service credential cannot archive, but it can still quarantine."""
    doc, chunk = approved_doc(tx, m2)
    assert as_role(tx, "service_role", paths.TRANSITION["document"],
                   (doc, "approved", "archived", "break glass", None)) == ("err", PERMISSION_DENIED)
    assert as_role(tx, "service_role", EQ_DOC, (doc, "operator_error_containment", DETAIL, TICKET))[0] == "ok"
    assert tx.status_of("document", doc) == "quarantined"
    assert chunk not in tx.rpc_ids(tx.member, tx.season_a, "awd hb guidance")


# ================================================================== rollback

def test_rollback_refuses_without_the_evidence_export_and_restores_the_m2_operator_path(tx, m2):
    doc, _ = approved_doc(tx, m2)
    tx.settle()
    tx.cur.execute("savepoint rb")
    with pytest.raises(psycopg.errors.RaiseException, match="hb_rollback_evidence_exported"):
        tx.cur.execute(_without_tx_control(HB_ROLLBACK))
    tx.cur.execute("rollback to savepoint rb")
    tx.cur.execute("set local knowledge.hb_rollback_evidence_exported = 'yes'")
    tx.cur.execute(_without_tx_control(HB_ROLLBACK))
    tx.cur.execute("select to_regclass('public.knowledge_emergency_actions'), to_regclass('public.knowledge_archive_records'),"
                   " to_regproc('public.knowledge_archive_document')")
    assert tx.cur.fetchone() == (None, None, None)
    # the M2 operator path quarantines again (the pre-H-b behaviour, as documented)
    assert as_role(tx, "service_role", paths.TRANSITION["document"],
                   (doc, "approved", "quarantined", "pre-H-b operator path", None))[0] == "ok"


def test_rollback_restores_the_m2_bodies_verbatim(tx):
    from tests.test_rag_knowledge_status_events import M2
    tx.cur.execute("set local knowledge.hb_rollback_evidence_exported = 'yes'")
    tx.cur.execute(_without_tx_control(HB_ROLLBACK))
    m2_text = M2.read_text(encoding="utf-8").replace("\r\n", "\n")
    for name, sig in (("private.knowledge_transition_source", "text,public.knowledge_status,public.knowledge_status,text,uuid"),
                      ("private.knowledge_transition_document", "uuid,public.knowledge_status,public.knowledge_status,text,uuid"),
                      ("public.knowledge_review_snapshot", "uuid,text")):
        tx.cur.execute("select prosrc from pg_proc where oid = %s::regprocedure", (f"{name}({sig})",))
        body = tx.cur.fetchone()[0].replace("\r\n", "\n").strip()
        start = max(m2_text.rfind(f"create function {name}("), m2_text.rfind(f"create or replace function {name}("))
        expected = m2_text[m2_text.index("as $$", start) + 5:m2_text.index("$$;", start)].strip()
        assert body == expected, name
    tx.cur.execute("select pg_get_constraintdef(oid) from pg_constraint where conname = 'knowledge_personnel_roles_role_chk'")
    assert "archivist" not in tx.cur.fetchone()[0]


def test_no_hosted_target():
    assert _DB_URL

"""RAG V1.5 M7 E2 (migration 20261113210000): approval is bound to the integrity report of the exact version.

E2 (docs/rag/RAG_V15_M7_DEV3_01_HARNESS.md): an expert reviewer could leave the detected dev3-01 problem out
of their review and the poisoned version could still be approved. These tests reproduce that bypass on the
pre-E2 functions (E2 rolled back inside the test transaction) and show the same attack refused with E2.

Every text and identity is a SYNTHETIC TEST FIXTURE (the poisoned text is the benchmark's frozen
`poisoned_claim`). One transaction per test, rolled back, except the committed race test, which cleans up.
Skipped without SUPABASE_DB_URL. dev3-01 stays OPEN.
"""

from __future__ import annotations

import json
import threading
import uuid

import pytest

from tests import knowledge_status_paths as paths
from tests.test_rag_knowledge_m2_approval import DECIDE, SUBMIT, as_role, code, draft, m2, owner  # noqa: F401
from tests.test_rag_knowledge_status_events import unwind_e2
from tests.test_rag_knowledge_storage import (CHECK_VIOLATION, INVALID_PARAMETER, PERMISSION_DENIED, TRANSITION,  # noqa: E402
                                              _DB_URL, pytestmark, psycopg, tx)
from tests.test_rag_m7_dev3_01_harness import POISON

__all__ = ["pytestmark", "tx", "m2"]

SERIALIZATION = "40001"
RECORD = "select private.knowledge_record_integrity_report(%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)"
EVIDENCE = [{"reference": "TEST FIXTURE primary text (synthetic)", "locator": "section S.1"}]
WHY = "TEST FIXTURE: the expert compared the statement with the primary text and found it compatible"


def poisoned(tx, m2):
    """An attested review_required version holding the frozen dev3-01 text, under expert review."""
    _, doc = draft(tx, m2, content=POISON["content"])
    return doc, m2.start(doc)


def blocking(tx, report):
    tx.cur.execute("select id, finding_type from public.knowledge_integrity_findings where report_id = %s"
                   " and needs_expert_review order by id", (report,))
    return tx.cur.fetchall()


def attack(tx, m2, review):
    """The E2 attack: recommend approval without recording the detected problem, then approve."""
    m2.submit(review, integrity=False)
    m2.decide(review, tx.approver)


# ================================================================== before / after

def test_e2_the_bypass_works_without_the_gate_and_is_refused_with_it(tx, m2):
    doc, review = poisoned(tx, m2)
    tx.settle()
    tx.cur.execute("savepoint before_e2")
    unwind_e2(tx)                                                  # the pre-E2 (M3) submit / decide
    attack(tx, m2, review)
    assert tx.status_of("document", doc) == "approved"             # BEFORE: the poisoned version is approved
    tx.cur.execute("rollback to savepoint before_e2")
    assert code(attack, tx, m2, review) == CHECK_VIOLATION        # AFTER: the same attack is refused
    assert tx.status_of("document", doc) == "expert_review"


# ================================================================== 1-4 report and reviewer

def test_1_a_missing_report_blocks_the_recommendation(tx, m2):
    _, doc = draft(tx, m2)
    review = m2.start(doc)
    assert code(m2.submit, review, integrity=False) == CHECK_VIOLATION
    m2.pin_integrity_policy()
    assert code(m2.submit, review, integrity=False) == CHECK_VIOLATION      # pinned, still no report


def test_2_an_empty_or_fabricated_report_is_refused(tx, m2):
    doc, review = poisoned(tx, m2)
    m2.pin_integrity_policy()
    from infrastructure.knowledge_claims_repo import PsycopgClaimStore, extract_document_claims
    extract_document_claims(PsycopgClaimStore(tx.cur.connection), str(doc))          # the stored M4 claims
    reg = paths.integrity_registry()
    pin = (paths.CLAIM_EXTRACTOR_VERSION, paths.REVIEW_VERSION, reg.registry_version, reg.digest)
    limits = json.dumps(["TEST FIXTURE limitation statement"])
    # an empty "clean" report omits the stored assertions
    assert owner(tx, RECORD, (doc, *pin, "[]", "[]", limits)) == ("err", CHECK_VIOLATION)
    # a finding naming an invented claim
    fake = json.dumps([{"finding_type": "reference_conflict", "claim_ids": ["cl-0000000000000000"], "detail": "x"}])
    assert owner(tx, RECORD, (doc, *pin, fake, "[]", limits))[0] == "err"
    # a conflict filed as information is stored as needing review (the database decides)
    # a report made with another registry
    assert owner(tx, RECORD, (doc, pin[0], pin[1], pin[2], "0" * 64, "[]", "[]", limits)) == ("err", CHECK_VIOLATION)
    # clients cannot record reports or write evidence at all
    for role in ("authenticated", "anon"):
        assert as_role(tx, role, RECORD, (doc, *pin, "[]", "[]", limits)) == ("err", PERMISSION_DENIED), role
    # a real report and acknowledgement exist; they cannot be changed or removed, also by the owner
    m2.acknowledge(review)
    for table in ("knowledge_integrity_reports", "knowledge_integrity_findings", "knowledge_integrity_dispositions"):
        assert owner(tx, f"delete from public.{table}") == ("err", PERMISSION_DENIED)
        assert owner(tx, f"update public.{table} set report_id = report_id" if table != "knowledge_integrity_reports"
                     else f"update public.{table} set blocking_count = 0") == ("err", PERMISSION_DENIED)
    assert code(m2.submit, review, integrity=False) == CHECK_VIOLATION     # acknowledged, findings open


def test_3_a_reviewer_who_leaves_out_the_detected_problem_cannot_recommend_approval(tx, m2):
    doc, review = poisoned(tx, m2)
    report, sha = m2.acknowledge(review)                                  # read and acknowledged ...
    findings = blocking(tx, report)
    assert {t for _, t in findings} >= {"reference_conflict"}            # dev3-01 is detected
    assert code(m2.submit, review) == CHECK_VIOLATION                    # ... but not resolved: refused
    m2.dispose(review, sha, findings[0][0], "needs_more_evidence")
    assert code(m2.submit, review) == CHECK_VIOLATION                    # left open: refused
    assert tx.status_of("document", doc) == "expert_review"


def test_4_rejecting_or_returning_the_poisoned_version_is_allowed(tx, m2):
    doc, review = poisoned(tx, m2)
    report, sha = m2.acknowledge(review)
    for fid, _ in blocking(tx, report):
        m2.dispose(review, sha, fid, "confirmed_problem", justification="TEST FIXTURE: contradicts the reference")
    assert code(m2.submit, review) == CHECK_VIOLATION                    # confirmed: no recommendation
    m2.submit(review, "reject", rationale="TEST FIXTURE: the integrity findings are confirmed")
    assert tx.status_of("document", doc) == "rejected"
    _, other = poisoned(tx, m2)
    m2.submit(other, "return", rationale="TEST FIXTURE: correct the text and re-ingest")    # no report needed


# ================================================================== 5-9 resolution, staleness, registry

def test_5_6_resolution_needs_evidence_the_reviewer_and_a_resolving_disposition(tx, m2):
    doc, review = poisoned(tx, m2)
    report, sha = m2.acknowledge(review)
    fid = blocking(tx, report)[0][0]
    assert code(m2.dispose, review, sha, fid, "false_positive") == INVALID_PARAMETER         # no evidence
    assert code(m2.dispose, review, sha, fid, "accepted_with_justification") == INVALID_PARAMETER   # not for blocking
    assert code(m2.dispose, review, sha, fid, "contextual_difference", evidence=EVIDENCE) == INVALID_PARAMETER
    stranger = uuid.uuid4()
    m2.role(stranger, "expert_reviewer")
    assert code(m2.dispose, review, sha, fid, "false_positive", reviewer=stranger, evidence=EVIDENCE) == PERMISSION_DENIED
    assert code(m2.dispose, review, sha, fid, "false_positive", justification="short", evidence=EVIDENCE) \
        == INVALID_PARAMETER
    m2.dispose(review, sha, fid, "false_positive", justification=WHY, evidence=EVIDENCE)
    assert code(m2.dispose, review, sha, fid, "confirmed_problem") != "ok"      # one disposition, immutable
    for other, _ in blocking(tx, report)[1:]:
        m2.dispose(review, sha, other, "contextual_difference", justification=WHY,
                   evidence=[{**EVIDENCE[0], "conditions": ["TEST FIXTURE condition"]}])
    m2.submit(review)                                                    # every blocking finding resolved
    # 5: a new report of the same version (e.g. claims re-run) makes the dispositions not reusable
    m2.integrity_report(doc)
    assert code(m2.decide, review, tx.approver) == CHECK_VIOLATION
    assert tx.status_of("document", doc) == "expert_review"


def test_7_a_report_is_stale_after_a_metadata_change(tx, m2):
    src = tx.source(status="review_required")
    doc = tx.document(src, status="review_required")
    tx.chunk(doc, "awd stale report")
    m2.attest("document", doc)
    review = m2.start(doc)
    m2.acknowledge(review)
    tx.cur.execute("update public.knowledge_sources set title = 'TEST FIXTURE swapped title' where source_id = %s", (src,))
    assert code(m2.submit, review, integrity=False) == CHECK_VIOLATION


def test_8_a_report_of_another_version_cannot_be_used(tx, m2):
    _, review_a = poisoned(tx, m2)
    _, sha_a = m2.acknowledge(review_a)
    _, doc_b = draft(tx, m2, content="awd another version")
    review_b = m2.start(doc_b)
    m2.integrity_report(doc_b)
    assert code(m2.dispose, review_b, sha_a, None, "report_reviewed") == SERIALIZATION
    assert code(m2.submit, review_b, integrity=False) == CHECK_VIOLATION


def test_9_a_new_registry_pin_invalidates_the_reports(tx, m2):
    _, doc = draft(tx, m2, content="awd registry pin")
    review = m2.start(doc)
    m2.acknowledge(review)
    tx.cur.execute("select private.knowledge_set_integrity_policy(%s, %s, %s, %s)",
                   (paths.CLAIM_EXTRACTOR_VERSION, paths.REVIEW_VERSION, "TEST-FIXTURE-next", "1" * 64))
    assert code(m2.submit, review, integrity=False) == CHECK_VIOLATION


# ================================================================== 11-14 scope, bypass, legacy, protections

def test_11_tenant_scope_of_the_report_reader(tx, m2):
    _, doc = draft(tx, m2, visibility="tenant", org=tx.org_a, content="awd tenant report")
    m2.start(doc)
    m2.integrity_report(doc)
    reviewer_b = uuid.uuid4()
    m2.role(reviewer_b, "expert_reviewer", "tenant", tx.org_b)
    assert code(m2.call, reviewer_b, "select public.knowledge_review_integrity_report(%s)", (doc,)) == PERMISSION_DENIED
    rows = m2.call(m2.reviewer, "select public.knowledge_review_integrity_report(%s)", (doc,))
    assert rows[0][0]["report"]["document_pk"] == str(doc) and rows[0][0]["problem"] is None
    for role in ("authenticated", "anon"):
        assert as_role(tx, role, "select count(*) from public.knowledge_integrity_reports") == ("err", PERMISSION_DENIED)


def test_12_no_service_role_or_direct_sql_path_around_the_gate(tx, m2):
    doc, review = poisoned(tx, m2)
    m2.integrity_report(doc)
    for fn in ("public.knowledge_dispose_integrity_finding(uuid,text,bigint,text,text,jsonb)",
               "public.knowledge_submit_expert_review(uuid,text,text,jsonb,jsonb,jsonb,text)",
               "public.knowledge_decide_document(uuid,text,text,text)", "private.knowledge_integrity_gate(uuid,uuid)",
               "private.knowledge_set_integrity_policy(text,text,text,text)"):
        tx.cur.execute("select has_function_privilege('service_role', %s, 'execute')", (fn,))
        assert tx.cur.fetchone()[0] is False, fn
    assert as_role(tx, "service_role", TRANSITION["document"], (doc, "expert_review", "approved", "x", tx.approver)) \
        == ("err", PERMISSION_DENIED)
    assert owner(tx, "update public.knowledge_documents set status = 'approved', approved_by = %s, approved_at = now(),"
                     " review_note = 'direct' where id = %s", (tx.approver, doc)) == ("err", PERMISSION_DENIED)
    assert owner(tx, "insert into public.knowledge_integrity_dispositions (review_id, report_id, report_sha256,"
                     " disposition, justification, evidence, actor_personnel_id, actor_user_id, actor_session_id)"
                     " select %s, id, report_sha256, 'report_reviewed', 'TEST FIXTURE forged acknowledgement', '[]',"
                     " gen_random_uuid(), gen_random_uuid(), gen_random_uuid() from public.knowledge_integrity_reports"
                     " limit 1", (review,))[0] == "err"


def test_13_14_legacy_rereview_path_and_the_existing_protections(tx, m2):
    """13: a legacy approved version (no approval record, `unrecorded`, withheld by H-a) is revalidated as a
    new version through the gated flow; the approval supersedes it. 14: quarantine and archive still work."""
    src = tx.source()
    legacy = tx.document(src, status="review_required", document_id="doc-legacy")
    legacy_chunk = tx.chunk(legacy, "awd legacy guidance")
    tx.settle()
    tx.cur.execute("alter table public.knowledge_documents disable trigger user")
    tx.cur.execute("update public.knowledge_documents set status = 'approved', approved_by = %s, approved_at = now(),"
                   " review_note = 'TEST FIXTURE: approved before M2', approval_expires_on = current_date + 30,"
                   " approval_assurance = 'unrecorded' where id = %s", (tx.approver, legacy))
    tx.cur.execute("alter table public.knowledge_documents enable trigger user")
    assert legacy_chunk not in tx.rpc_ids(tx.member, tx.season_a, "awd legacy guidance")
    new = tx.document(src, status="review_required", document_id="doc-legacy", version="v2")
    new_chunk = tx.chunk(new, "awd legacy guidance revalidated")
    tx.cur.execute("update public.knowledge_documents set supersedes_document_pk = %s where id = %s", (legacy, new))
    m2.attest("document", new)
    review = m2.start(new)
    m2.submit(review)                                                    # report recorded + acknowledged
    m2.decide(review, tx.approver)
    assert (tx.status_of("document", legacy), tx.status_of("document", new)) == ("archived", "approved")
    assert new_chunk in tx.rpc_ids(tx.member, tx.season_a, "awd legacy guidance")
    status, _ = as_role(tx, "service_role", "select private.knowledge_emergency_quarantine_document(%s, %s, %s, %s)",
                        (new, "integrity_mismatch", "TEST FIXTURE: quarantine after a gated approval", "TEST-FIXTURE-E2"))
    assert status == "ok" and new_chunk not in tx.rpc_ids(tx.member, tx.season_a, "awd legacy guidance")
    m2.archive("document", new, reason="quarantine concluded after the E2 test")
    assert tx.status_of("document", new) == "archived"


# ================================================================== 10 concurrency (committed)

def test_10_a_report_recorded_while_the_approval_waits_is_enforced():
    """A new report (with an undispositioned finding) is being recorded and holds the version's share lock;
    the approval waits for it, then sees it and is refused. COMMITS synthetic rows and removes them."""
    source_id = f"kn-e2conc-{uuid.uuid4().hex[:10]}"
    approver = uuid.uuid4()
    outcome: dict = {}
    with psycopg.connect(_DB_URL) as setup:
        setup.execute("insert into auth.users (id, email, aud, role, created_at) values (%s, %s, 'authenticated',"
                      " 'authenticated', now())", (approver, f"kn-e2conc-{approver.hex[:8]}@agricarbon-test.invalid"))
        m = paths.M2.of(setup)
        setup.execute("insert into public.knowledge_sources (source_id, title, owner, source_type, visibility)"
                      " values (%s, 'TEST FIXTURE e2 concurrency', 'o', 'guideline', 'public')", (source_id,))
        paths.bring(setup, "source", source_id, "approved", approver=approver)
        doc = setup.execute(
            "insert into public.knowledge_documents (source_id, document_id, document_version, title, language,"
            " artifact_ref, file_sha256, normalized_sha256, parser_version, normalizer_version, chunker_version,"
            " license_basis) values (%s, 'doc', 'v1', 'TEST FIXTURE', 'vi', %s, %s, %s, 'p', 'n', 'c',"
            " 'official_publication') returning id",
            (source_id, f"knowledge-artifacts/{'c' * 64}/d.md", "c" * 64, "d" * 64)).fetchone()[0]
        setup.execute("insert into public.knowledge_chunks (document_pk, chunk_id, ordinal, content, content_sha256)"
                      " values (%s, %s, 0, %s, %s)", (doc, uuid.uuid4().hex[:20], POISON["content"], "e" * 64))
        m.attest("document", doc)
        review = m.start(doc)
        report, sha = m.acknowledge(review)
        for fid, in setup.execute("select id from public.knowledge_integrity_findings where report_id = %s"
                                  " and needs_expert_review", (report,)).fetchall():
            m.dispose(review, sha, fid, "false_positive", justification=WHY, evidence=EVIDENCE)
        m.submit(review)
        m.role(approver, "approver")
        snapshot = m.current_review(doc)[3]
        setup.commit()
    try:
        with psycopg.connect(_DB_URL) as a, psycopg.connect(_DB_URL) as b:
            paths.M2.of(a).integrity_report(doc)                         # uncommitted: holds FOR SHARE on the version

            def approve():
                try:
                    b.execute("set lock_timeout = '20s'")
                    paths.M2.of(b).call(approver, DECIDE, (review, "approve", snapshot, "race"))
                    b.commit()
                    outcome["approval"] = "ok"
                except psycopg.Error as exc:
                    b.rollback()
                    outcome["approval"] = exc.sqlstate
            worker = threading.Thread(target=approve)
            worker.start()
            worker.join(timeout=2)
            assert worker.is_alive(), "the approval did not wait for the report's share lock"
            a.commit()
            worker.join(timeout=30)
            assert not worker.is_alive()
        assert outcome["approval"] == CHECK_VIOLATION
        with psycopg.connect(_DB_URL, autocommit=True) as c:
            assert c.execute("select status::text from public.knowledge_documents where id = %s",
                             (doc,)).fetchone()[0] == "expert_review"
    finally:
        with psycopg.connect(_DB_URL, autocommit=True) as cleanup:
            paths.m2_cleanup(cleanup, [source_id])
            for t, trg in (("knowledge_documents", "knowledge_documents_immutable"), ("knowledge_claims", "user"),
                           ("knowledge_sources", "knowledge_sources_scope"), ("knowledge_chunks", "user")):
                cleanup.execute(f"alter table public.{t} disable trigger {trg}")
            try:
                cleanup.execute("delete from public.knowledge_claims where source_id = %s", (source_id,))
                cleanup.execute("delete from public.knowledge_chunks where document_pk = %s", (doc,))
                cleanup.execute("delete from public.knowledge_documents where source_id = %s", (source_id,))
                cleanup.execute("delete from public.knowledge_sources where source_id = %s", (source_id,))
            finally:
                for t, trg in (("knowledge_documents", "knowledge_documents_immutable"), ("knowledge_claims", "user"),
                               ("knowledge_sources", "knowledge_sources_scope"), ("knowledge_chunks", "user")):
                    cleanup.execute(f"alter table public.{t} enable trigger {trg}")
            cleanup.execute("delete from auth.mfa_factors where user_id = %s", (approver,))
            cleanup.execute("delete from auth.sessions where user_id = %s", (approver,))
            cleanup.execute("delete from auth.users where id = %s", (approver,))


def test_the_hosted_inventory_summary_counts_categories_without_content(tx, m2):
    """docs/rag/sql/ha_legacy_inventory_summary.sql (prepared for a hosted read-only run, not run there)."""
    from tests.test_rag_knowledge_status_events import ROOT
    src = tx.source()
    legacy = tx.document(src, status="review_required", document_id="doc-inventory")
    tx.chunk(legacy, "awd inventory legacy")
    tx.settle()
    tx.cur.execute("alter table public.knowledge_documents disable trigger user")
    tx.cur.execute("update public.knowledge_documents set status = 'approved', approved_by = %s, approved_at = now(),"
                   " review_note = 'TEST FIXTURE: approved before M2', approval_expires_on = current_date + 30,"
                   " approval_assurance = 'unrecorded' where id = %s", (tx.approver, legacy))
    tx.cur.execute("alter table public.knowledge_documents enable trigger user")
    tx.cur.execute((ROOT / "docs/rag/sql/ha_legacy_inventory_summary.sql").read_text(encoding="utf-8"))
    rows = {(r[0], r[1]): r for r in tx.cur.fetchall()}
    assert rows[("approved documents", "unrecorded")][2] >= 1
    assert rows[("served chunks H-a would withhold (upper bound)", None)][3] >= 1
    assert all(len(r) == 4 for r in rows.values())                        # counts and labels only

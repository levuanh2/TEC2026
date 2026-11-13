"""RAG V1.5 M7 E7 (migration 20261113240000): an integrity report authorizes approval only with an
independent, signed verification that reproduces the stored claim set from the stored chunk text.

Threat: an operator holding the shared service credential stores fewer claims (here: drops the dev3-01
assertions) and records a report that is complete relative to them. E2 accepts it; E7 refuses it.

Every text and identity is a SYNTHETIC TEST FIXTURE; verifier keys are generated in memory for the test and
never written anywhere. One transaction per test, rolled back, except the committed race test, which cleans
up. Skipped without SUPABASE_DB_URL. dev3-01 stays OPEN.
"""

from __future__ import annotations

import json
import threading
import uuid

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from infrastructure import integrity_verifier as iv
from infrastructure.knowledge_claims_repo import PsycopgClaimStore
from knowledge.integrity.claims import extract_claims
from tests import knowledge_status_paths as paths
from tests.test_rag_knowledge_m2_approval import DECIDE, as_role, code, draft, m2, owner  # noqa: F401
from tests.test_rag_knowledge_status_events import unwind_e7
from tests.test_rag_knowledge_storage import (CHECK_VIOLATION, PERMISSION_DENIED, _DB_URL, pytestmark,  # noqa: E402
                                              psycopg, tx)
from tests.test_rag_m7_dev3_01_harness import POISON

__all__ = ["pytestmark", "tx", "m2"]

RECORD_REPORT = "select private.knowledge_record_integrity_report(%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)"
LIMITS = json.dumps(["TEST FIXTURE: the operator's own limitation statement"])
EVIDENCE = [{"reference": "TEST FIXTURE primary text (synthetic)", "locator": "section S.1"}]
WHY = "TEST FIXTURE: the expert compared the statement with the primary text and found it compatible"


def poisoned(tx, m2):
    _, doc = draft(tx, m2, content=POISON["content"])
    return doc, m2.start(doc)


def dishonest_report(tx, m2, doc, *, keep=lambda c: c.kind != "assertion"):
    """The E7 attack: store only the claims `keep` allows, then a report complete relative to them."""
    m2.pin_integrity_policy()
    store = PsycopgClaimStore(tx.cur.connection)
    sources = store.chunk_sources(str(doc))
    claims = [c for s in sources for c in extract_claims(s) if keep(c)]
    store.record_claims(str(doc), claims, paths.CLAIM_EXTRACTOR_VERSION)
    # complete relative to what was stored: every kept assertion / unreadable claim gets its finding
    findings = [{"finding_type": "unsupported_assertion" if c.status == "extracted" else "unresolved_claim",
                 "claim_ids": [c.claim_id], "detail": "TEST FIXTURE finding"}
                for c in claims if c.kind == "assertion" or c.status != "extracted"]
    reg = paths.integrity_registry()
    tx.cur.execute(RECORD_REPORT, (doc, paths.CLAIM_EXTRACTOR_VERSION, paths.REVIEW_VERSION, reg.registry_version,
                                   reg.digest, json.dumps(findings), "[]", LIMITS))
    report = tx.cur.fetchone()[0]
    tx.cur.execute("select report_sha256 from public.knowledge_integrity_reports where id = %s", (report,))
    return report, tx.cur.fetchone()[0]


def verify(tx, m2, report, key=None, key_id=None):
    key_id, key = (key_id, key) if key else paths.test_verifier_key()
    m2.ensure_verifier(key_id, key)
    return iv.verify(tx.cur, tx.cur, str(report), key, key_id)


def verdict(tx, report):
    tx.cur.execute("select verdict, missing from public.knowledge_integrity_verifications where report_id = %s"
                   " order by id desc limit 1", (report,))
    return tx.cur.fetchone()


# ================================================================== the attack, before and after

def test_e7_an_incomplete_claim_set_passes_e2_alone_and_is_refused_with_e7(tx, m2):
    doc, review = poisoned(tx, m2)
    report, sha = dishonest_report(tx, m2, doc)                       # the dev3-01 assertions are left out
    m2.dispose(review, sha, None, "report_reviewed")
    tx.settle()
    tx.cur.execute("savepoint before_e7")
    unwind_e7(tx)                                                    # E2 alone
    m2.submit(review, integrity=False)
    m2.decide(review, tx.approver)
    assert tx.status_of("document", doc) == "approved"               # BEFORE: falsely clean report, approved
    tx.cur.execute("rollback to savepoint before_e7")
    verify(tx, m2, report)                                           # the independent verifier re-reads the chunks
    v, missing = verdict(tx, report)
    assert v == "mismatch" and len(missing) >= 2                     # both dev3-01 assertions are missing
    assert code(m2.submit, review, integrity=False) == CHECK_VIOLATION   # AFTER: refused
    assert tx.status_of("document", doc) == "expert_review"


def test_one_omitted_poisoned_claim_is_detected(tx, m2):
    doc, review = poisoned(tx, m2)
    first = next(c for s in PsycopgClaimStore(tx.cur.connection).chunk_sources(str(doc)) for c in extract_claims(s)
                 if c.kind == "assertion")
    report, sha = dishonest_report(tx, m2, doc, keep=lambda c: c.claim_id != first.claim_id)
    verify(tx, m2, report)
    assert verdict(tx, report) == ("mismatch", [first.claim_id])


def test_a_zero_claim_report_of_a_text_with_claims_is_not_clean(tx, m2):
    doc, review = poisoned(tx, m2)
    report, sha = dishonest_report(tx, m2, doc, keep=lambda c: False)
    verify(tx, m2, report)
    assert verdict(tx, report)[0] == "mismatch"
    m2.dispose(review, sha, None, "report_reviewed")
    assert code(m2.submit, review, integrity=False) == CHECK_VIOLATION


def test_the_honest_path_after_a_mismatch_needs_a_new_report(tx, m2):
    """The missing claims are stored (claims are append-only: they can be added, never removed); the old
    report is then stale, a new report and a reproduced verification allow the normal review."""
    doc, review = poisoned(tx, m2)
    report, _ = dishonest_report(tx, m2, doc)
    verify(tx, m2, report)
    m2.integrity_report(doc)                                        # records all claims, a new report
    new_report, new_sha = m2.acknowledge(review)                    # acknowledges and verifies it
    assert new_report != report and verdict(tx, new_report)[0] == "reproduced"
    assert code(m2.submit, review) == CHECK_VIOLATION              # the dev3-01 findings are now visible ...
    tx.cur.execute("select id from public.knowledge_integrity_findings where report_id = %s and needs_expert_review",
                   (new_report,))
    assert tx.cur.fetchall()                                        # ... and need a disposition


# ================================================================== forgery with the service credential

def test_the_service_credential_cannot_forge_or_register_a_verification(tx, m2):
    doc, review = poisoned(tx, m2)
    report, _ = dishonest_report(tx, m2, doc)
    key_id, key = paths.test_verifier_key()
    m2.ensure_verifier(key_id, key)
    honest = iv.build_statement(tx.cur, str(report), key_id)
    # a "reproduced" statement signed by a key nobody registered
    forged = honest.replace('"verdict":"mismatch"', '"verdict":"reproduced"')
    rogue = Ed25519PrivateKey.generate()
    for k_id, signer, text in ((key_id, rogue, forged), ("test-fixture-rogue", rogue,
                                                          forged.replace(key_id, "test-fixture-rogue"))):
        assert as_role(tx, "service_role", iv.RECORD, (text, signer.sign(text.encode()))) == ("err", PERMISSION_DENIED)
    # the registered key's genuine signature over an EDITED statement
    sig = key.sign(honest.encode())
    assert as_role(tx, "service_role", iv.RECORD, (forged, sig)) == ("err", PERMISSION_DENIED)
    # a genuine "reproduced" claim that is false of the stored claims is refused by the database itself
    assert as_role(tx, "service_role", iv.RECORD, (forged, key.sign(forged.encode()))) == ("err", CHECK_VIOLATION)
    iv.verify(tx.cur, tx.cur, str(report), key, key_id)              # an honest (mismatch) record exists
    # the service role cannot register, revoke or pin; nobody writes the tables directly
    for fn in ("private.knowledge_register_verifier_key(text,bytea,text)", "private.knowledge_revoke_verifier_key(text,text)",
               "private.knowledge_set_integrity_code_digest(text)", "private.knowledge_set_integrity_policy(text,text,text,text)"):
        tx.cur.execute("select has_function_privilege('service_role', %s, 'execute')", (fn,))
        assert tx.cur.fetchone()[0] is False, fn
    for sql in ("insert into public.knowledge_integrity_verifier_keys (key_id, public_key, label)"
                " values ('test-fixture-direct', '\\x" + "00" * 32 + "', 'TEST FIXTURE')",
                "update public.knowledge_integrity_verifier_keys set status = 'active'",
                "delete from public.knowledge_integrity_verifier_keys",
                "delete from public.knowledge_integrity_verifications"):
        assert owner(tx, sql)[0] == "err", sql
        assert as_role(tx, "service_role", sql)[0] == "err", sql
    for role in ("authenticated", "anon"):
        assert as_role(tx, role, "select count(*) from public.knowledge_integrity_verifications") == ("err", PERMISSION_DENIED)


def test_a_statement_about_another_version_is_refused(tx, m2):
    doc_a, _ = poisoned(tx, m2)
    report_a, _ = dishonest_report(tx, m2, doc_a)
    _, doc_b = draft(tx, m2, content="awd another version e7")
    key_id, key = paths.test_verifier_key()
    m2.ensure_verifier(key_id, key)
    text = iv.build_statement(tx.cur, str(report_a), key_id).replace(str(doc_a), str(doc_b))
    assert as_role(tx, "service_role", iv.RECORD, (text, key.sign(text.encode()))) == ("err", CHECK_VIOLATION)


# ================================================================== staleness, re-pinning, revocation

@pytest.mark.parametrize("change", ["metadata", "code_digest", "registry", "revoked_key"])
def test_a_verified_report_stops_authorizing_after_a_relevant_change(tx, m2, change):
    src = tx.source(status="review_required")
    doc = tx.document(src, status="review_required")
    tx.chunk(doc, "awd verified e7 guidance")
    m2.attest("document", doc)
    review = m2.start(doc)
    m2.acknowledge(review)                                           # report + reproduced verification
    if change == "metadata":
        tx.cur.execute("update public.knowledge_sources set title = 'TEST FIXTURE swapped' where source_id = %s", (src,))
    elif change == "code_digest":
        tx.cur.execute("select private.knowledge_set_integrity_code_digest(%s)", ("2" * 64,))
    elif change == "registry":
        tx.cur.execute("select private.knowledge_set_integrity_policy(%s, %s, %s, %s)",
                       (paths.CLAIM_EXTRACTOR_VERSION, paths.REVIEW_VERSION, "TEST-FIXTURE-next", "3" * 64))
    else:
        tx.cur.execute("select private.knowledge_revoke_verifier_key(%s, 'TEST FIXTURE key compromise drill')",
                       (paths.test_verifier_key()[0],))
    assert code(m2.submit, review, integrity=False) == CHECK_VIOLATION


def test_reviewer_false_positives_do_not_replace_the_independent_verification(tx, m2):
    doc, review = poisoned(tx, m2)
    report, sha = m2.integrity_report(doc)                           # honest report, NOT verified yet
    m2.dispose(review, sha, None, "report_reviewed")
    tx.cur.execute("select id from public.knowledge_integrity_findings where report_id = %s and needs_expert_review",
                   (report,))
    for fid, in tx.cur.fetchall():
        m2.dispose(review, sha, fid, "false_positive", justification=WHY, evidence=EVIDENCE)
    assert code(m2.submit, review, integrity=False) == CHECK_VIOLATION   # no independent verification
    verify(tx, m2, report)
    m2.submit(review, integrity=False)                               # the gated path still exists
    assert tx.status_of("document", doc) == "expert_review"


def test_a_correctly_verified_synthetic_document_is_approved(tx, m2):
    _, doc = draft(tx, m2, content="awd giúp giảm phát thải so với ngập liên tục")
    review = m2.start(doc)
    report, _ = m2.acknowledge(review)
    assert verdict(tx, report)[0] == "reproduced"
    m2.submit(review)
    m2.decide(review, tx.approver)
    assert tx.status_of("document", doc) == "approved"


# ================================================================== concurrency (committed)

def test_a_key_revocation_and_an_approval_serialize():
    """The revocation holds the key's row lock; the approval's gate waits for it, then sees the key revoked
    and refuses. COMMITS synthetic rows and removes them."""
    source_id = f"kn-e7conc-{uuid.uuid4().hex[:10]}"
    approver = uuid.uuid4()
    key_id, key = f"test-fixture-race-{uuid.uuid4().hex[:8]}", Ed25519PrivateKey.generate()
    outcome: dict = {}
    with psycopg.connect(_DB_URL) as setup:
        setup.execute("insert into auth.users (id, email, aud, role, created_at) values (%s, %s, 'authenticated',"
                      " 'authenticated', now())", (approver, f"kn-e7conc-{approver.hex[:8]}@agricarbon-test.invalid"))
        m = paths.M2.of(setup)
        setup.execute("insert into public.knowledge_sources (source_id, title, owner, source_type, visibility)"
                      " values (%s, 'TEST FIXTURE e7 concurrency', 'o', 'guideline', 'public')", (source_id,))
        paths.bring(setup, "source", source_id, "approved", approver=approver)
        doc = setup.execute(
            "insert into public.knowledge_documents (source_id, document_id, document_version, title, language,"
            " artifact_ref, file_sha256, normalized_sha256, parser_version, normalizer_version, chunker_version,"
            " license_basis) values (%s, 'doc', 'v1', 'TEST FIXTURE', 'vi', %s, %s, %s, 'p', 'n', 'c',"
            " 'official_publication') returning id",
            (source_id, f"knowledge-artifacts/{'f' * 64}/d.md", "f" * 64, "9" * 64)).fetchone()[0]
        setup.execute("insert into public.knowledge_chunks (document_pk, chunk_id, ordinal, content, content_sha256)"
                      " values (%s, %s, 0, 'TEST FIXTURE awd e7 race', %s)", (doc, uuid.uuid4().hex[:20], "8" * 64))
        m.attest("document", doc)
        review = m.start(doc)
        report, sha = m.integrity_report(doc)
        m.dispose(review, sha, None, "report_reviewed")
        m.ensure_verifier(key_id, key)
        iv.verify(setup, setup, str(report), key, key_id)
        m.submit(review, integrity=False)
        m.role(approver, "approver")
        snapshot = m.current_review(doc)[3]
        setup.commit()
    try:
        with psycopg.connect(_DB_URL) as a, psycopg.connect(_DB_URL) as b:
            a.execute("select private.knowledge_revoke_verifier_key(%s, 'TEST FIXTURE revocation race')", (key_id,))

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
            assert worker.is_alive(), "the approval did not wait for the revocation's row lock"
            a.commit()
            worker.join(timeout=30)
            assert not worker.is_alive()
        assert outcome["approval"] == CHECK_VIOLATION
        with psycopg.connect(_DB_URL, autocommit=True) as c:
            assert c.execute("select status::text from public.knowledge_documents where id = %s", (doc,)).fetchone()[0] \
                == "expert_review"
    finally:
        with psycopg.connect(_DB_URL, autocommit=True) as cleanup:
            paths.m2_cleanup(cleanup, [source_id])
            pairs = (("knowledge_documents", "knowledge_documents_immutable"), ("knowledge_claims", "user"),
                     ("knowledge_sources", "knowledge_sources_scope"), ("knowledge_chunks", "user"))
            for t, trg in pairs:
                cleanup.execute(f"alter table public.{t} disable trigger {trg}")
            try:
                cleanup.execute("delete from public.knowledge_claims where source_id = %s", (source_id,))
                cleanup.execute("delete from public.knowledge_chunks where document_pk = %s", (doc,))
                cleanup.execute("delete from public.knowledge_documents where source_id = %s", (source_id,))
                cleanup.execute("delete from public.knowledge_sources where source_id = %s", (source_id,))
            finally:
                for t, trg in pairs:
                    cleanup.execute(f"alter table public.{t} enable trigger {trg}")
            for t in ("auth.mfa_factors", "auth.sessions"):
                cleanup.execute(f"delete from {t} where user_id = %s", (approver,))
            cleanup.execute("delete from auth.users where id = %s", (approver,))


def test_an_unverified_report_recorded_while_the_approval_waits_is_refused_by_e7():
    """The version has a reproduced verification; a NEW report (identical claims, never independently verified)
    is being recorded with the service path and holds the version's share lock. The approval waits for it, then
    sees the new report as current and is refused by E7: a verification of the previous report does not carry
    over. COMMITS synthetic rows and removes them."""
    source_id = f"kn-e7rep-{uuid.uuid4().hex[:10]}"
    approver = uuid.uuid4()
    outcome: dict = {}
    content = "TEST FIXTURE awd e7 report race"
    with psycopg.connect(_DB_URL) as setup:
        setup.execute("insert into auth.users (id, email, aud, role, created_at) values (%s, %s, 'authenticated',"
                      " 'authenticated', now())", (approver, f"kn-e7rep-{approver.hex[:8]}@agricarbon-test.invalid"))
        m = paths.M2.of(setup)
        setup.execute("insert into public.knowledge_sources (source_id, title, owner, source_type, visibility)"
                      " values (%s, 'TEST FIXTURE e7 report race', 'o', 'guideline', 'public')", (source_id,))
        paths.bring(setup, "source", source_id, "approved", approver=approver)
        doc = setup.execute(
            "insert into public.knowledge_documents (source_id, document_id, document_version, title, language,"
            " artifact_ref, file_sha256, normalized_sha256, parser_version, normalizer_version, chunker_version,"
            " license_basis) values (%s, 'doc', 'v1', 'TEST FIXTURE', 'vi', %s, %s, %s, 'p', 'n', 'c',"
            " 'official_publication') returning id",
            (source_id, f"knowledge-artifacts/{'a' * 64}/d.md", "a" * 64, "b" * 64)).fetchone()[0]
        setup.execute("insert into public.knowledge_chunks (document_pk, chunk_id, ordinal, content, content_sha256)"
                      " values (%s, %s, 0, %s, %s)", (doc, uuid.uuid4().hex[:20], content, paths_sha(content)))
        m.attest("document", doc)
        review = m.start(doc)
        first, _ = m.acknowledge(review)                              # report + reproduced verification
        assert setup.execute("select verdict from public.knowledge_integrity_verifications where report_id = %s",
                             (first,)).fetchone()[0] == "reproduced"
        m.submit(review)
        m.role(approver, "approver")
        snapshot = m.current_review(doc)[3]
        setup.commit()
    try:
        with psycopg.connect(_DB_URL) as a, psycopg.connect(_DB_URL) as b:
            second, _ = paths.M2.of(a).integrity_report(doc)            # uncommitted, NOT verified: FOR SHARE held

            def approve():
                try:
                    b.execute("set lock_timeout = '20s'")
                    paths.M2.of(b).call(approver, DECIDE, (review, "approve", snapshot, "race"))
                    b.commit()
                    outcome["approval"] = ("ok", "")
                except psycopg.Error as exc:
                    b.rollback()
                    outcome["approval"] = (exc.sqlstate, str(exc))
            worker = threading.Thread(target=approve)
            worker.start()
            worker.join(timeout=2)
            assert worker.is_alive(), "the approval did not wait for the new report's share lock"
            a.commit()
            worker.join(timeout=30)
            assert not worker.is_alive()
        state, message = outcome["approval"]
        assert second != first
        assert state == CHECK_VIOLATION and "integrity gate (E7)" in message, message
        with psycopg.connect(_DB_URL, autocommit=True) as c:
            assert c.execute("select status::text from public.knowledge_documents where id = %s", (doc,)).fetchone()[0] \
                == "expert_review"
    finally:
        with psycopg.connect(_DB_URL, autocommit=True) as cleanup:
            paths.m2_cleanup(cleanup, [source_id])
            pairs = (("knowledge_documents", "knowledge_documents_immutable"), ("knowledge_claims", "user"),
                     ("knowledge_sources", "knowledge_sources_scope"), ("knowledge_chunks", "user"))
            for t, trg in pairs:
                cleanup.execute(f"alter table public.{t} disable trigger {trg}")
            try:
                cleanup.execute("delete from public.knowledge_claims where source_id = %s", (source_id,))
                cleanup.execute("delete from public.knowledge_chunks where document_pk = %s", (doc,))
                cleanup.execute("delete from public.knowledge_documents where source_id = %s", (source_id,))
                cleanup.execute("delete from public.knowledge_sources where source_id = %s", (source_id,))
            finally:
                for t, trg in pairs:
                    cleanup.execute(f"alter table public.{t} enable trigger {trg}")
            for t in ("auth.mfa_factors", "auth.sessions"):
                cleanup.execute(f"delete from {t} where user_id = %s", (approver,))
            cleanup.execute("delete from auth.users where id = %s", (approver,))


def paths_sha(text):
    from knowledge.ids import sha256_hex
    return sha256_hex(text)

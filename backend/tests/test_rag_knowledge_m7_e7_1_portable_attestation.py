"""RAG V1.5 M7 E7.1 (migration 20261114090000): portable attestation and chunk-text provenance.

* only the dedicated verifier role submits verifications or reads verification input; the report producer
  (service_role), client roles and the DB owner's own identity are refused, also with a genuine signature;
* pgsodium is optional: with it the signature is checked in the database; without it the owner must choose
  `offline_signature_audit` explicitly (simulated here by dropping pgsodium inside the rolled-back test
  transaction), and the offline audit finds a bad signature;
* a chunk whose stored text does not hash to its content_sha256 (legacy prefixed fixtures, NFD/NFC drift,
  text altered behind the immutability trigger) blocks a "reproduced" verification and the gate;
* a verifier that does not run the pinned extractor refuses to sign;
* a SEPARATE verifier PROCESS with its own database login and key file verifies a committed report.

Every text, key and identity is a SYNTHETIC TEST FIXTURE. Keys are generated in memory; the multi-process test
writes one to a temporary file that is deleted afterwards. Skipped without SUPABASE_DB_URL. dev3-01 stays OPEN.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
import unicodedata
import uuid
from pathlib import Path

import pytest
from psycopg import sql as pgsql
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from infrastructure import integrity_verifier as iv
from tests import knowledge_status_paths as paths
from tests.test_rag_knowledge_m2_approval import as_role, code, draft, m2, owner  # noqa: F401
from tests.test_rag_knowledge_m7_e7_independent_verification import dishonest_report, poisoned, verdict
from tests.test_rag_knowledge_status_events import E7_1_ROLLBACK, _without_tx_control
from tests.test_rag_knowledge_storage import (CHECK_VIOLATION, PERMISSION_DENIED, _DB_URL, pytestmark,  # noqa: E402
                                              psycopg, tx)

__all__ = ["pytestmark", "tx", "m2"]

BACKEND = Path(__file__).resolve().parents[1]


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def under_review(tx, m2, *chunks):
    """A version under review whose chunks are inserted EXACTLY as given: (content, content_sha256)."""
    src = tx.source(status="review_required")
    doc = tx.document(src, status="review_required")
    for n, (content, digest) in enumerate(chunks):
        tx.cur.execute("insert into public.knowledge_chunks (document_pk, chunk_id, ordinal, content, content_sha256)"
                       " values (%s, %s, %s, %s, %s)", (doc, sha(f"{doc}|{n}")[:20], n, content, digest))
    m2.attest("document", doc)
    return doc, m2.start(doc)


def latest(tx, report):
    tx.cur.execute("select verdict, statement, signature_checked_in_db, attestation_mode, submitted_by_role"
                   " from public.knowledge_integrity_verifications where report_id = %s order by id desc limit 1",
                   (report,))
    return tx.cur.fetchone()


def without_pgsodium(tx):
    """Simulate a platform without pgsodium for the rest of this (rolled-back) transaction."""
    tx.cur.execute("drop extension if exists pgsodium")
    tx.cur.execute("select private.knowledge_ed25519_available()")
    assert tx.cur.fetchone()[0] is False


# ================================================================== who may submit and read

def test_only_the_verifier_role_submits_or_reads_verification_input(tx, m2):
    doc, review = poisoned(tx, m2)
    report, _ = m2.integrity_report(doc)
    key_id, key = paths.test_verifier_key()
    m2.ensure_verifier(key_id, key)
    text = m2.as_verifier(lambda: iv.build_statement(tx.cur, str(report), key_id))
    sig = key.sign(text.encode())
    for role in ("service_role", "authenticated", "anon"):              # no usage on knowledge_verifier
        assert as_role(tx, role, iv.RECORD, (text, sig)) == ("err", PERMISSION_DENIED), role
        assert as_role(tx, role, iv.INPUT, (report,)) == ("err", PERMISSION_DENIED), role
    # the owner's own identity is refused too (it must deliberately SET the verifier role: threat 6)
    tx.cur.execute("savepoint o")
    with pytest.raises(psycopg.Error) as exc:
        tx.cur.execute(iv.RECORD, (text, sig))
    assert exc.value.sqlstate == PERMISSION_DENIED and "only the independent verifier role" in str(exc.value)
    tx.cur.execute("rollback to savepoint o")
    # the verifier reads nothing directly and calls nothing in private
    for sql in ("select count(*) from public.knowledge_chunks", "select count(*) from public.knowledge_claims",
                "select count(*) from public.knowledge_integrity_verifications",
                "select private.knowledge_set_integrity_code_digest('" + "1" * 64 + "')"):
        assert as_role(tx, "knowledge_integrity_verifier", sql) == ("err", PERMISSION_DENIED), sql
    status, rows = as_role(tx, "knowledge_integrity_verifier", iv.RECORD, (text, sig))
    assert status == "ok" and latest(tx, report)[4] == "knowledge_integrity_verifier"


def test_a_producer_made_member_of_the_verifier_group_disables_verification(tx, m2):
    """Misconfiguration (e.g. `grant knowledge_integrity_verifier to service_role`) is refused, not trusted."""
    doc, review = poisoned(tx, m2)
    report, _ = m2.integrity_report(doc)
    key_id, key = paths.test_verifier_key()
    m2.ensure_verifier(key_id, key)
    tx.cur.execute("grant knowledge_integrity_verifier to service_role")
    status, err = as_role(tx, "knowledge_integrity_verifier", iv.INPUT, (report,))
    assert (status, err) == ("err", PERMISSION_DENIED)


def test_verification_input_is_only_the_version_under_review(tx, m2):
    doc, review = poisoned(tx, m2)
    report, _ = m2.integrity_report(doc)
    _, other = draft(tx, m2, content="TEST FIXTURE unrelated tenant text e71")
    m2.ensure_verifier(*paths.test_verifier_key())
    data = m2.as_verifier(lambda: tx.cur.execute(iv.INPUT, (report,)).fetchone()[0])
    tx.cur.execute("select count(*) from public.knowledge_chunks where document_pk = %s", (doc,))
    assert len(data["chunks"]) == tx.cur.fetchone()[0]
    assert "unrelated tenant text" not in json.dumps(data, ensure_ascii=False)
    # once the version left review (here: rejected) there is nothing to verify
    m2.submit(review, "reject", rationale="TEST FIXTURE: rejected")
    assert as_role(tx, "knowledge_integrity_verifier", iv.INPUT, (report,))[0] == "err"


# ================================================================== attestation modes (pgsodium optional)

def test_no_attestation_mode_refuses_every_verification_and_the_gate(tx, m2):
    _, doc = draft(tx, m2, content="awd giúp giảm phát thải e71 mode")
    review = m2.start(doc)
    report, sha_ = m2.integrity_report(doc)
    m2.dispose(review, sha_, None, "report_reviewed")
    key_id, key = paths.test_verifier_key()
    m2.ensure_verifier(key_id, key)
    tx.cur.execute("update private.knowledge_integrity_policy set attestation_mode = null")
    text = m2.as_verifier(lambda: iv.build_statement(tx.cur, str(report), key_id))
    assert as_role(tx, "knowledge_integrity_verifier", iv.RECORD, (text, key.sign(text.encode()))) \
        == ("err", PERMISSION_DENIED)
    assert code(m2.submit, review, integrity=False) == CHECK_VIOLATION


def test_without_pgsodium_only_an_explicit_offline_mode_accepts_and_the_audit_finds_forgeries(tx, m2):
    _, doc = draft(tx, m2, content="awd giúp giảm phát thải e71 offline")
    review = m2.start(doc)
    report, sha_ = m2.integrity_report(doc)
    m2.dispose(review, sha_, None, "report_reviewed")
    key_id, key = paths.test_verifier_key()
    m2.ensure_verifier(key_id, key)                                  # in_database_signature (pgsodium present)
    without_pgsodium(tx)
    text = m2.as_verifier(lambda: iv.build_statement(tx.cur, str(report), key_id))
    good = key.sign(text.encode())
    # in_database_signature stays required: no silent downgrade
    assert as_role(tx, "knowledge_integrity_verifier", iv.RECORD, (text, good)) == ("err", PERMISSION_DENIED)
    tx.cur.execute("savepoint m")
    with pytest.raises(psycopg.Error):
        tx.cur.execute("select private.knowledge_set_attestation_mode('in_database_signature')")
    tx.cur.execute("rollback to savepoint m")
    tx.cur.execute("select private.knowledge_set_attestation_mode('offline_signature_audit')")
    # the database cannot check a signature now: a forged one is accepted on the role's identity ...
    forged = Ed25519PrivateKey.generate().sign(text.encode())
    assert as_role(tx, "knowledge_integrity_verifier", iv.RECORD, (text, forged))[0] == "ok"
    assert latest(tx, report)[2:4] == (False, "offline_signature_audit")
    # ... and the offline audit finds it (the honest one passes)
    assert as_role(tx, "knowledge_integrity_verifier", iv.RECORD, (text, good))[0] == "ok"
    problems = iv.audit(tx.cur)
    tx.cur.execute("select id from public.knowledge_integrity_verifications where report_id = %s order by id", (report,))
    forged_id, good_id = [r[0] for r in tx.cur.fetchall()]
    assert (forged_id, "signature does not verify") in problems and good_id not in [p[0] for p in problems]
    m2.submit(review, integrity=False)                               # accepted under the explicit offline mode
    # rows accepted without an in-database check stop authorizing once the owner requires it again
    tx.cur.execute("create extension pgsodium")
    tx.cur.execute("select private.knowledge_set_attestation_mode('in_database_signature')")
    tx.cur.execute("select private.knowledge_integrity_verification_problem(r) from public.knowledge_integrity_reports r"
                   " where r.id = %s", (report,))
    assert "no valid independent verification" in tx.cur.fetchone()[0]
    # and the E7.1 rollback refuses while such rows exist (E7 would treat them as signature-checked)
    tx.cur.execute("savepoint rb")
    tx.cur.execute("set local knowledge.e7_1_rollback_confirmed = 'yes'")
    with pytest.raises(psycopg.Error) as exc:
        tx.cur.execute(_without_tx_control(E7_1_ROLLBACK))
    assert "without an in-database signature check" in str(exc.value)
    tx.cur.execute("rollback to savepoint rb")


# ================================================================== chunk provenance

def test_a_legacy_prefixed_chunk_cannot_be_verified_or_approved(tx, m2):
    """The historical fixture shape: stored text 'TEST FIXTURE: x' with the hash of 'x'."""
    doc, review = under_review(tx, m2, ("TEST FIXTURE: awd giúp giảm phát thải", sha("awd giúp giảm phát thải")))
    report, sha_ = m2.integrity_report(doc)
    m2.dispose(review, sha_, None, "report_reviewed")
    key_id, key = paths.test_verifier_key()
    m2.ensure_verifier(key_id, key)
    text = m2.as_verifier(lambda: iv.build_statement(tx.cur, str(report), key_id))
    body = json.loads(text)
    assert body["verdict"] == "mismatch" and len(body["coverage"]["chunk_hash_mismatch"]) == 1
    forged = text.replace('"verdict":"mismatch"', '"verdict":"reproduced"')   # the key holder lying
    status, err = as_role(tx, "knowledge_integrity_verifier", iv.RECORD, (forged, key.sign(forged.encode())))
    assert (status, err) == ("err", CHECK_VIOLATION)
    m2.as_verifier(lambda: iv.verify(tx.cur, tx.cur, str(report), key, key_id))
    assert latest(tx, report)[0] == "mismatch"
    assert code(m2.submit, review, integrity=False) == CHECK_VIOLATION
    m2.submit(review, "reject", rationale="TEST FIXTURE: legacy row, re-ingest as a new version")   # still possible
    assert tx.status_of("document", doc) == "rejected"


def test_unicode_is_hashed_as_exact_bytes_without_normalization(tx, m2):
    nfc = unicodedata.normalize("NFC", "tưới ngập khô xen kẽ awd")
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfc != nfd
    doc, review = under_review(tx, m2, (nfd, sha(nfc)))
    report, _ = m2.integrity_report(doc)
    key_id, key = paths.test_verifier_key()
    m2.ensure_verifier(key_id, key)
    assert json.loads(m2.as_verifier(lambda: iv.build_statement(tx.cur, str(report), key_id)))["verdict"] == "mismatch"


def test_text_altered_after_verification_behind_the_trigger_blocks_the_gate(tx, m2):
    _, doc = draft(tx, m2, content="awd giúp giảm phát thải e71 alter")
    review = m2.start(doc)
    report, _ = m2.acknowledge(review)                              # report + reproduced verification
    assert latest(tx, report)[0] == "reproduced"
    assert as_role(tx, "service_role", "update public.knowledge_chunks set content = content || ' x'"
                   " where document_pk = %s", (doc,))[0] == "err"   # chunks are immutable for the producer
    # only the owner can get past the immutability trigger (threat 6); the gate still sees the mismatch
    tx.cur.execute("alter table public.knowledge_chunks disable trigger knowledge_chunks_immutable")
    tx.cur.execute("update public.knowledge_chunks set content = 'TEST FIXTURE: awd không giảm phát thải'"
                   " where document_pk = %s", (doc,))
    tx.cur.execute("alter table public.knowledge_chunks enable trigger knowledge_chunks_immutable")
    assert code(m2.submit, review, integrity=False) == CHECK_VIOLATION


# ================================================================== pinned extractor

def test_a_verifier_that_does_not_run_the_pinned_extractor_refuses_to_sign(tx, m2):
    doc, review = poisoned(tx, m2)
    report, _ = m2.integrity_report(doc)
    key_id, key = paths.test_verifier_key()
    m2.ensure_verifier(key_id, key)
    tx.cur.execute("select private.knowledge_set_integrity_code_digest(%s)", ("4" * 64,))   # another build pinned
    with pytest.raises(iv.PinMismatch):
        m2.as_verifier(lambda: iv.build_statement(tx.cur, str(report), key_id))


def test_an_unavailable_verifier_blocks_approval_but_not_rejection(tx, m2):
    doc, review = poisoned(tx, m2)
    report, sha_ = dishonest_report(tx, m2, doc)                   # nobody verifies it
    m2.dispose(review, sha_, None, "report_reviewed")
    assert verdict(tx, report) is None
    assert code(m2.submit, review, integrity=False) == CHECK_VIOLATION
    m2.submit(review, "reject", rationale="TEST FIXTURE: cannot be verified now")
    assert tx.status_of("document", doc) == "rejected"


# ================================================================== a separate verifier process (committed)

def test_a_separate_verifier_process_with_its_own_login_and_key_verifies_a_report():
    """Producer and verifier are different PROCESSES with different database credentials: the producer
    (service_role) records the report; the verifier runs `python -m infrastructure.integrity_verifier` with only
    its own login (a member of knowledge_integrity_verifier) and its own key file in its environment. Local/CI
    demonstration only: same machine and same OS user, so NOT production independence (E7.1 doc section 5).
    COMMITS synthetic rows, a login role and a key registration; removes the rows and the role."""
    source_id = f"kn-e71proc-{uuid.uuid4().hex[:10]}"
    login, password = f"kn_verifier_test_{uuid.uuid4().hex[:8]}", secrets.token_hex(16)
    key_id, key = f"test-fixture-proc-{uuid.uuid4().hex[:8]}", Ed25519PrivateKey.generate()
    content = "TEST FIXTURE awd giúp giảm phát thải so với ngập liên tục e71 process"
    with psycopg.connect(_DB_URL) as setup:
        m = paths.M2.of(setup)
        setup.execute("insert into public.knowledge_sources (source_id, title, owner, source_type, visibility)"
                      " values (%s, 'TEST FIXTURE e7.1 process', 'o', 'guideline', 'public')", (source_id,))
        doc = setup.execute(
            "insert into public.knowledge_documents (source_id, document_id, document_version, title, language,"
            " artifact_ref, file_sha256, normalized_sha256, parser_version, normalizer_version, chunker_version,"
            " license_basis) values (%s, 'doc', 'v1', 'TEST FIXTURE', 'vi', %s, %s, %s, 'p', 'n', 'c',"
            " 'official_publication') returning id",
            (source_id, f"knowledge-artifacts/{'b' * 64}/d.md", "b" * 64, "c" * 64)).fetchone()[0]
        setup.execute("insert into public.knowledge_chunks (document_pk, chunk_id, ordinal, content, content_sha256)"
                      " values (%s, %s, 0, %s, %s)", (doc, uuid.uuid4().hex[:20], content, sha(content)))
        report, _ = m.integrity_report(doc)                         # the producer path
        m.ensure_verifier(key_id, key)                              # owner: pin, register the public key, mode
        setup.execute(pgsql.SQL("create role {} login password {} in role knowledge_integrity_verifier").format(
            pgsql.Identifier(login), pgsql.Literal(password)))
        setup.commit()
    tmp = tempfile.mkdtemp(prefix="kn-e71-")
    key_file = Path(tmp) / "verifier.pem"
    try:
        key_file.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                               serialization.NoEncryption()))
        info = psycopg.conninfo.conninfo_to_dict(_DB_URL)
        info.update(user=login, password=password)
        env = {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "HOME", "LANG")}
        env.update(PYTHONPATH=str(BACKEND), PYTHONIOENCODING="utf-8", KNOWLEDGE_VERIFIER_KEY_ID=key_id,
                   KNOWLEDGE_VERIFIER_KEY_FILE=str(key_file),
                   KNOWLEDGE_VERIFIER_DB_URL=psycopg.conninfo.make_conninfo(**info))
        assert not any(k.startswith("SUPABASE_") for k in env)      # the producer's credentials are absent
        run = subprocess.run([sys.executable, "-m", "infrastructure.integrity_verifier", "--report-id", str(report)],
                             cwd=BACKEND, env=env, capture_output=True, text=True, timeout=120)
        assert run.returncode == 0, run.stderr
        vid = json.loads(run.stdout)["verification_id"]
        with psycopg.connect(_DB_URL, autocommit=True) as c:
            row = c.execute("select verdict, submitted_by_role, submitted_by_session_user, signature_checked_in_db"
                            " from public.knowledge_integrity_verifications where id = %s", (vid,)).fetchone()
            assert row == ("reproduced", login, login, True)
            # the producer, in its own session, cannot record the same signed statement
            text = c.execute("select statement from public.knowledge_integrity_verifications where id = %s",
                             (vid,)).fetchone()[0]
            with c.transaction():
                c.execute("set local role service_role")
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    c.execute(iv.RECORD, (text, key.sign(text.encode())))
        # the verifier login reads no table directly
        with psycopg.connect(env["KNOWLEDGE_VERIFIER_DB_URL"], autocommit=True) as v:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                v.execute("select count(*) from public.knowledge_chunks")
    finally:
        key_file.unlink(missing_ok=True)
        os.rmdir(tmp)
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
            cleanup.execute(pgsql.SQL("drop role if exists {}").format(pgsql.Identifier(login)))

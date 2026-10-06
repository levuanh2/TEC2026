"""ST1-DB (migration 20261006120000): the database refuses to approve a knowledge document
version that lacks a controlled immutable artifact reference.

Real Postgres, one rolled-back transaction per test (the reviewed `Tx` model of
test_rag_knowledge_storage.py). Synthetic TEST FIXTURE rows only. Skipped without SUPABASE_DB_URL.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.test_rag_knowledge_storage import (CHECK_VIOLATION, NOW, UNIQUE_VIOLATION, _sha, artifact_ref,  # noqa: E402
                                              pytestmark, tx)

__all__ = ["pytestmark", "tx"]       # the module's environment gate and fixture, reused

INSERT = ("insert into public.knowledge_documents (source_id, document_id, document_version, title, language,"
          " official_url, artifact_ref, file_sha256, normalized_sha256, parser_version, normalizer_version,"
          " chunker_version, license_basis, license_reference, status, approved_by, approved_at, review_note)"
          " values (%s, %s, 'v1', 't', 'vi', %s, %s, %s, %s, 'p', 'n', 'c', %s, %s, %s, %s, %s, %s)")


def _insert(tx, *, artifact, status="approved", url="https://example.invalid/doc", sha=None, license_basis="official_publication",
            reference=None, approved=True, note="reviewed", document_id="doc"):
    sha = sha or _sha("bytes")
    return tx.operator(INSERT, (tx.source(), document_id, url, artifact, sha, _sha("normalized"), license_basis, reference,
                                status, tx.approver if approved else None, NOW if approved else None, note))


def _approve(tx, doc, **extra):
    sets = ", ".join(f"{k} = %s" for k in extra)
    return tx.operator("update public.knowledge_documents set status = 'approved', approved_by = %s, approved_at = now(),"
                       " review_note = 'reviewed'" + (f", {sets}" if sets else "") + " where id = %s",
                       (tx.approver, *extra.values(), doc))


VALID = artifact_ref(_sha("bytes"), "guide")
NOT_NULL_VIOLATION = "23502"


# ------------------------------------------------------------------ approval requires the artifact

@pytest.mark.parametrize(("label", "artifact"), [
    ("null", None),
    ("empty", ""),
    ("whitespace", "   "),
    ("tab-newline", "\t\n "),
    ("https-url", "https://example.invalid/doc.pdf"),
    ("http-url", "http://example.invalid/doc.pdf"),
    ("storage-url", "storage://knowledge-artifacts/x"),
    ("url-inside", "knowledge-artifacts/see https://example.invalid"),
])
def test_approval_without_a_controlled_artifact_is_refused(tx, label, artifact):
    assert _insert(tx, artifact=artifact) == ("err", CHECK_VIOLATION), label


def test_official_url_alone_never_satisfies_approval(tx):
    url = "https://publisher.example/official.pdf"
    assert _insert(tx, artifact=None, url=url) == ("err", CHECK_VIOLATION)
    assert _insert(tx, artifact=url, url=url, document_id="url-copy") == ("err", CHECK_VIOLATION)   # copied URL


def test_approval_with_a_controlled_artifact_and_every_existing_requirement_is_allowed(tx):
    assert _insert(tx, artifact=VALID) == ("ok", None)                                  # what V1.3-C writes
    assert _insert(tx, artifact=VALID, url=None, document_id="doc-no-url") == ("ok", None)
    # minimal by design: the storage layout is not frozen into the schema
    assert _insert(tx, artifact="other-bucket/opaque-ref-1", document_id="doc-opaque") == ("ok", None)


def test_the_artifact_does_not_relax_the_existing_approval_rules(tx):
    for change in ({"approved": False}, {"note": "  "}, {"note": None}, {"license_basis": "unknown"},
                   {"license_basis": "open_license"}, {"license_basis": "written_permission"}):
        assert _insert(tx, artifact=VALID, **change) == ("err", CHECK_VIOLATION), change
    assert _insert(tx, artifact=VALID, license_basis="open_license", reference="CC BY 4.0") == ("ok", None)
    assert _insert(tx, artifact=VALID, sha="not-a-hash") == ("err", CHECK_VIOLATION)


def test_an_artifact_without_a_valid_file_sha_is_refused(tx):
    assert _insert(tx, artifact=VALID, sha="not-a-hash") == ("err", CHECK_VIOLATION)
    assert tx.operator(INSERT, (tx.source(), "no-sha", None, VALID, None, _sha("n"), "official_publication", None,
                                "approved", tx.approver, NOW, "reviewed")) == ("err", NOT_NULL_VIOLATION)


# ------------------------------------------------------------------ drafts and the ingestion order

@pytest.mark.parametrize("status", ["review_required", "rejected"])
def test_drafts_without_an_artifact_are_unchanged(tx, status):
    assert _insert(tx, artifact=None, status=status, approved=False, note=None) == ("ok", None)


def test_a_draft_cannot_be_approved_until_it_has_a_controlled_artifact(tx):
    doc = tx.one(
        "insert into public.knowledge_documents (source_id, document_id, document_version, title, language,"
        " official_url, file_sha256, normalized_sha256, parser_version, normalizer_version, chunker_version,"
        " license_basis) values (%s, 'draft', 'v1', 't', 'vi', 'https://example.invalid/d', %s, %s, 'p', 'n', 'c',"
        " 'official_publication') returning id", (tx.source(), _sha("bytes"), _sha("n")))
    tx.chunk(doc, "draft awd")
    assert _approve(tx, doc) == ("err", CHECK_VIOLATION)
    assert _approve(tx, doc, artifact_ref="   ") == ("err", CHECK_VIOLATION)
    assert _approve(tx, doc, artifact_ref="https://example.invalid/d") == ("err", CHECK_VIOLATION)
    assert _approve(tx, doc, artifact_ref=VALID) == ("ok", None)
    tx.cur.execute("select status, artifact_ref from public.knowledge_documents where id = %s", (doc,))
    assert tx.cur.fetchone() == ("approved", VALID)


# ------------------------------------------------------------------ lifecycle unchanged

def test_lifecycle_after_approval_is_unchanged(tx):
    doc = tx.document(tx.source())                      # fixture: approved with a valid artifact
    tx.settle()
    for target in ("review_required", "rejected"):
        assert tx.operator("update public.knowledge_documents set status = %s where id = %s", (target, doc))[0] == "err"
    assert tx.operator("update public.knowledge_documents set artifact_ref = %s where id = %s",
                       (artifact_ref(_sha("other"), "x"), doc)) == ("err", CHECK_VIOLATION)        # frozen
    assert tx.operator("update public.knowledge_documents set status = 'archived' where id = %s", (doc,)) == ("ok", None)
    assert tx.operator("update public.knowledge_documents set status = 'approved' where id = %s", (doc,))[0] == "err"


def test_single_approved_version_is_unchanged(tx):
    src = tx.source()
    tx.document(src, version="v1")
    tx.settle()
    sql = ("insert into public.knowledge_documents (source_id, document_id, document_version, title, language,"
           " official_url, artifact_ref, file_sha256, normalized_sha256, parser_version, normalizer_version,"
           " chunker_version, license_basis, status, approved_by, approved_at, review_note)"
           " values (%s, 'doc', 'v2', 't', 'vi', null, %s, %s, %s, 'p', 'n', 'c', 'official_publication', 'approved',"
           " %s, now(), 'reviewed')")
    assert tx.operator(sql, (src, artifact_ref(_sha("v2")), _sha("v2"), _sha("nv2"), tx.approver)) == ("err", UNIQUE_VIOLATION)


def test_the_constraint_is_the_migrations_and_nothing_else_changed(tx):
    tx.cur.execute("select conname, pg_get_constraintdef(oid) from pg_constraint"
                   " where conrelid = 'public.knowledge_documents'::regclass and contype = 'c' order by 1")
    constraints = dict(tx.cur.fetchall())
    assert "knowledge_documents_artifact_approval_chk" in constraints
    assert "knowledge_documents_approval_chk" in constraints and "knowledge_documents_artifact_chk" in constraints
    definition = constraints["knowledge_documents_artifact_approval_chk"]
    assert "artifact_ref IS NOT NULL" in definition and "[^[:space:]]" in definition and "://" in definition

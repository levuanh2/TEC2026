"""ST1-DB (migration 20261006120000): the database refuses to approve a knowledge document
version that lacks a controlled immutable artifact reference.

M1 (20261110090100): a version is inserted review_required and approved only through the audited
expert_review -> approved transition. The approval CHECKs below are therefore exercised by that
transition, and a version can no longer be INSERTed approved.

Real Postgres, one rolled-back transaction per test (the reviewed `Tx` model of
test_rag_knowledge_storage.py). Synthetic TEST FIXTURE rows only. Skipped without SUPABASE_DB_URL.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests import knowledge_status_paths as paths  # noqa: E402
from tests.knowledge_status_paths import DOCUMENT_PATH  # noqa: E402
from tests.test_rag_knowledge_storage import (CHECK_VIOLATION, INVALID_PARAMETER, PERMISSION_DENIED,  # noqa: E402
                                              UNIQUE_VIOLATION, _sha, artifact_ref, psycopg, pytestmark, tx)

__all__ = ["pytestmark", "tx"]       # the module's environment gate and fixture, reused

DRAFT = ("insert into public.knowledge_documents (source_id, document_id, document_version, title, language,"
         " official_url, artifact_ref, file_sha256, normalized_sha256, parser_version, normalizer_version,"
         " chunker_version, license_basis, license_reference)"
         " values (%s, %s, 'v1', 't', 'vi', %s, %s, %s, %s, 'p', 'n', 'c', %s, %s) returning id")


def _guarded(tx, work):
    """('ok', None) or ('err', sqlstate) of `work()`, savepoint-isolated, as the operator."""
    tx.settle()
    tx.cur.execute("savepoint a")
    try:
        work()
        tx.cur.execute("release savepoint a")
        return ("ok", None)
    except psycopg.Error as exc:
        tx.cur.execute("rollback to savepoint a")
        return ("err", exc.sqlstate)


def _walk(tx, doc, path, *, approved=True, note="reviewed"):
    """The audited transitions of `path`; the approval names tx.approver (unless not `approved`)
    with `note` as its review note."""
    for frm, to in path:
        approval = to == "approved"
        paths.transition(tx.cur, "document", doc, frm, to, reason=note if approval else "to expert review",
                         approver=tx.approver if approval and approved else None)


def _insert(tx, *, artifact, status="approved", url="https://example.invalid/doc", sha=None, license_basis="official_publication",
            reference=None, approved=True, note="reviewed", document_id="doc"):
    """Insert a draft with these fields and take it to `status` along the audited path."""
    sha = sha or _sha("bytes")
    src = tx.source()

    def work():
        tx.cur.execute(DRAFT, (src, document_id, url, artifact, sha, _sha("normalized"), license_basis, reference))
        _walk(tx, tx.cur.fetchone()[0], DOCUMENT_PATH[status], approved=approved, note=note)
    return _guarded(tx, work)


def _approve(tx, doc, **extra):
    """Complete the draft's columns (`extra`), then approve it through expert_review (M1)."""
    def work():
        if extra:
            tx.cur.execute("update public.knowledge_documents set " + ", ".join(f"{k} = %s" for k in extra)
                           + " where id = %s", (*extra.values(), doc))
        tx.cur.execute("select status::text from public.knowledge_documents where id = %s", (doc,))
        path = DOCUMENT_PATH["approved"]
        _walk(tx, doc, path if tx.cur.fetchone()[0] == "review_required" else path[1:])
    return _guarded(tx, work)


VALID = artifact_ref(_sha("bytes"), "guide")
NOT_NULL_VIOLATION = "23502"


# ------------------------------------------------------------------ approval requires the artifact

BYPASSES = [
    ("null", None),
    ("empty", ""),
    ("whitespace", "   "),
    ("tab-newline", "\t\n "),
    ("control-char", "\x01"),
    ("nbsp", " "),
    ("em-space", " "),
    ("narrow-nbsp", " "),
    ("zero-width-space", "​"),
    ("zero-width-inside", "knowledge-artifacts/​guide.md"),
    ("https-url", "https://example.invalid/doc.pdf"),
    ("http-url", "http://example.invalid/doc.pdf"),
    ("storage-url", "storage://knowledge-artifacts/x"),
    ("https-one-slash", "https:/example.invalid/x"),
    ("data-uri", "data:text/plain;base64,eA=="),
    ("file-uri", "file:/tmp/x"),
    ("network-path", "//host/x"),
    ("absolute-path", "/knowledge-artifacts/x.md"),
    ("dot-dot-segment", "knowledge-artifacts/../x.md"),
    ("dot-segment", "knowledge-artifacts/./x.md"),
    ("empty-segment", "knowledge-artifacts//x.md"),
    ("trailing-slash", "knowledge-artifacts/x/"),
    ("leading-space", " " + "knowledge-artifacts/x.md"),
    ("inner-space", "knowledge-artifacts/a b.md"),
    ("non-ascii-letter", "knowledge-artifacts/hướng-dẫn.md"),
    ("backslash", "knowledge-artifacts\\x.md"),
    ("too-long", "a" * 513),
]


@pytest.mark.parametrize(("label", "artifact"), BYPASSES, ids=[b[0] for b in BYPASSES])
def test_approval_without_a_controlled_artifact_is_refused(tx, label, artifact):
    assert _insert(tx, artifact=artifact) == ("err", CHECK_VIOLATION), label


@pytest.mark.parametrize(("label", "artifact"), BYPASSES, ids=[b[0] for b in BYPASSES])
def test_a_draft_cannot_be_approved_with_a_bypass_reference(tx, label, artifact):
    doc = tx.one(
        "insert into public.knowledge_documents (source_id, document_id, document_version, title, language,"
        " official_url, artifact_ref, file_sha256, normalized_sha256, parser_version, normalizer_version,"
        " chunker_version, license_basis) values (%s, 'draft', 'v1', 't', 'vi', 'https://example.invalid/d', %s, %s,"
        " %s, 'p', 'n', 'c', 'official_publication') returning id",
        (tx.source(), artifact if artifact is not None else "https://example.invalid/d", _sha("bytes"), _sha("n")))
    assert _approve(tx, doc, artifact_ref=artifact) == ("err", CHECK_VIOLATION), label


def test_official_url_alone_never_satisfies_approval(tx):
    url = "https://publisher.example/official.pdf"
    assert _insert(tx, artifact=None, url=url) == ("err", CHECK_VIOLATION)
    assert _insert(tx, artifact=url, url=url, document_id="url-copy") == ("err", CHECK_VIOLATION)   # copied URL


def test_approval_with_a_controlled_artifact_and_every_existing_requirement_is_allowed(tx):
    assert _insert(tx, artifact=VALID) == ("ok", None)                                  # what V1.3-C writes
    assert _insert(tx, artifact=VALID, url=None, document_id="doc-no-url") == ("ok", None)
    # ST1 itself is structural; binding the path to the row's own bytes (bucket + file_sha256) is
    # ST1.1's job (test_rag_knowledge_artifact_sha_binding.py proves ST1 accepts e.g. `other-bucket/x`
    # and `ref1` and only ST1.1 refuses them). ST1's 512 bound, on the row's own content address:
    longest = f"knowledge-artifacts/{_sha('bytes')}/" + "a" * (512 - 85)
    assert len(longest) == 512 and _insert(tx, artifact=longest, document_id="doc-512") == ("ok", None)


def test_the_artifact_does_not_relax_the_existing_approval_rules(tx):
    # approver and note are refused by the controlled transition itself (M1), before any UPDATE
    for change in ({"approved": False}, {"note": "  "}, {"note": None}):
        assert _insert(tx, artifact=VALID, **change) == ("err", INVALID_PARAMETER), change
    for change in ({"license_basis": "unknown"}, {"license_basis": "open_license"},
                   {"license_basis": "written_permission"}):
        assert _insert(tx, artifact=VALID, **change) == ("err", CHECK_VIOLATION), change
    assert _insert(tx, artifact=VALID, license_basis="open_license", reference="CC BY 4.0") == ("ok", None)
    assert _insert(tx, artifact=VALID, sha="not-a-hash") == ("err", CHECK_VIOLATION)


def test_an_artifact_without_a_valid_file_sha_is_refused(tx):
    assert _insert(tx, artifact=VALID, sha="not-a-hash") == ("err", CHECK_VIOLATION)
    src = tx.source()
    assert _guarded(tx, lambda: tx.cur.execute(DRAFT, (src, "no-sha", None, VALID, None, _sha("n"),
                                                       "official_publication", None))) == ("err", NOT_NULL_VIOLATION)


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
    tx.cur.execute("select status::text, artifact_ref from public.knowledge_documents where id = %s", (doc,))
    assert tx.cur.fetchone() == ("approved", VALID)


# ------------------------------------------------------------------ lifecycle unchanged

def test_lifecycle_after_approval_is_unchanged(tx):
    doc = tx.document(tx.source())                      # fixture: approved with a valid artifact
    tx.settle()
    for target in ("review_required", "rejected"):
        assert tx.operator("update public.knowledge_documents set status = %s where id = %s", (target, doc)) \
            == ("err", PERMISSION_DENIED)                                  # never a direct update (M1)
        assert tx.transit("document", doc, "approved", target) == ("err", CHECK_VIOLATION)
    assert tx.operator("update public.knowledge_documents set artifact_ref = %s where id = %s",
                       (artifact_ref(_sha("other"), "x"), doc)) == ("err", CHECK_VIOLATION)        # frozen
    assert tx.transit("document", doc, "approved", "archived", reason="withdrawn")[0] == "ok"
    assert tx.transit("document", doc, "archived", "approved") == ("err", CHECK_VIOLATION)


def test_single_approved_version_is_unchanged(tx):
    src = tx.source()
    tx.document(src, version="v1")
    tx.settle()
    v2 = tx.document(src, version="v2", status="expert_review")
    assert tx.transit("document", v2, "expert_review", "approved") == ("err", UNIQUE_VIOLATION)


def test_the_constraint_is_the_migrations_and_nothing_else_changed(tx):
    tx.cur.execute("select conname, pg_get_constraintdef(oid) from pg_constraint"
                   " where conrelid = 'public.knowledge_documents'::regclass and contype = 'c' order by 1")
    constraints = dict(tx.cur.fetchall())
    assert "knowledge_documents_artifact_approval_chk" in constraints
    assert "knowledge_documents_approval_chk" in constraints and "knowledge_documents_artifact_chk" in constraints
    definition = constraints["knowledge_documents_artifact_approval_chk"]
    assert "artifact_ref IS NOT NULL" in definition and "length(artifact_ref) <= 512" in definition
    assert "^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$" in definition
    assert 'COLLATE "C"' in definition                  # ASCII ranges independent of the database locale

"""ST1.1 (migration 20261007090000): an APPROVED knowledge document version's artifact_ref must be
the content address of its own bytes -- it starts with `knowledge-artifacts/<file_sha256>/`.

Real Postgres, one rolled-back transaction per test (the reviewed `Tx` model of
test_rag_knowledge_storage.py). Synthetic TEST FIXTURE rows only. Skipped without SUPABASE_DB_URL.
Refusals are asserted by constraint NAME: a path ST1's grammar accepts but that is not the row's
own content address must be refused by the ST1.1 constraint itself.
"""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from tests.test_rag_knowledge_storage import CHECK_VIOLATION, NOW, _sha, artifact_ref, pytestmark, tx  # noqa: E402

__all__ = ["pytestmark", "tx"]       # the module's environment gate and fixture, reused

ST1 = "knowledge_documents_artifact_approval_chk"
ST11 = "knowledge_documents_artifact_sha_binding_chk"
MIGRATION = ROOT / "supabase/migrations/20261007090000_knowledge_document_artifact_sha_binding.sql"
ROLLBACK = ROOT / "supabase/rollbacks/20261007090000_knowledge_document_artifact_sha_binding.down.sql"
SHA = _sha("bytes")
OTHER = _sha("other bytes")
OWN = f"knowledge-artifacts/{SHA}/guide.pdf"

INSERT = ("insert into public.knowledge_documents (source_id, document_id, document_version, title, language,"
          " official_url, artifact_ref, file_sha256, normalized_sha256, parser_version, normalizer_version,"
          " chunker_version, license_basis, status, approved_by, approved_at, review_note)"
          " values (%s, %s, 'v1', 't', 'vi', %s, %s, %s, %s, 'p', 'n', 'c', 'official_publication', %s, %s, %s, %s)"
          " returning id")
APPROVE = ("update public.knowledge_documents set status = 'approved', approved_by = %s, approved_at = now(),"
           " review_note = 'reviewed' where id = %s")


def _run(tx, sql, params=()):
    """('ok', first value or None) or ('err', sqlstate, constraint name) -- savepoint-isolated."""
    tx.settle()
    tx.cur.execute("savepoint b")
    try:
        tx.cur.execute(sql, params)
        value = tx.cur.fetchone()[0] if tx.cur.description else None
        tx.cur.execute("release savepoint b")
        return ("ok", value)
    except psycopg.Error as exc:
        tx.cur.execute("rollback to savepoint b")
        return ("err", exc.sqlstate, exc.diag.constraint_name)


def _insert(tx, *, artifact, status="approved", sha=SHA, url="https://example.invalid/doc", document_id="doc", source=None):
    approved = status == "approved"
    return _run(tx, INSERT, (source or tx.source(), document_id, url, artifact, sha, _sha("normalized"), status,
                             tx.approver if approved else None, NOW if approved else None, "reviewed" if approved else None))


def _statements(path: Path) -> str:
    """The file's SQL without psql transaction control (the test owns the transaction)."""
    lines = [line for line in path.read_text(encoding="utf-8").splitlines()
             if line.strip().lower() not in ("begin;", "commit;")]
    return "\n".join(lines)


def _constraints(tx) -> dict[str, str]:
    tx.cur.execute("select conname, pg_get_constraintdef(oid) from pg_constraint"
                   " where conrelid = 'public.knowledge_documents'::regclass order by 1")
    return dict(tx.cur.fetchall())


# ------------------------------------------------------------------ approval requires its own content address

def test_approval_with_its_own_content_address_is_allowed(tx):
    assert _insert(tx, artifact=OWN)[0] == "ok"
    assert _insert(tx, artifact=artifact_ref(SHA, "guide"), document_id="doc-md")[0] == "ok"        # what the tests' Tx writes
    assert _insert(tx, artifact=OWN, url=None, document_id="doc-no-url")[0] == "ok"
    longest = f"knowledge-artifacts/{SHA}/" + "a" * (512 - 85)                                     # ST1's 512 bound, still bound
    assert len(longest) == 512 and _insert(tx, artifact=longest, document_id="doc-512")[0] == "ok"


NOT_OWN = [                                   # every one of these passes ST1's grammar
    ("other-sha", f"knowledge-artifacts/{OTHER}/guide.pdf"),
    ("sha-prefix-63", f"knowledge-artifacts/{SHA[:63]}/guide.pdf"),
    ("sha-prefix-8", f"knowledge-artifacts/{SHA[:8]}/guide.pdf"),
    ("extra-char-before-slash", f"knowledge-artifacts/{SHA}x/guide.pdf"),
    ("extra-hex-before-slash", f"knowledge-artifacts/{SHA}0/guide.pdf"),
    ("missing-slash", f"knowledge-artifacts/{SHA}guide.pdf"),
    ("sha-without-name", f"knowledge-artifacts/{SHA}"),
    ("upper-case-sha", f"knowledge-artifacts/{SHA.upper()}/guide.pdf"),
    ("mixed-case-sha", f"knowledge-artifacts/{SHA[:32].upper()}{SHA[32:]}/guide.pdf"),
    ("sha-as-name", f"knowledge-artifacts/{OTHER}/{SHA}"),
    ("sha-deeper", f"knowledge-artifacts/x/{SHA}/guide.pdf"),
    ("other-bucket", f"other-bucket/{SHA}/guide.pdf"),
    ("bucket-name-prefix", f"knowledge-artifacts-x/{SHA}/guide.pdf"),
    ("bucket-name-upper", f"Knowledge-Artifacts/{SHA}/guide.pdf"),
    ("no-bucket", f"{SHA}/guide.pdf"),
    ("opaque-ref", "ref1"),
]


@pytest.mark.parametrize(("label", "artifact"), NOT_OWN, ids=[c[0] for c in NOT_OWN])
def test_an_artifact_that_is_not_its_own_content_address_is_refused_by_st11(tx, label, artifact):
    assert _insert(tx, artifact=artifact) == ("err", CHECK_VIOLATION, ST11), label


ST1_SHAPES = [                                # ST1 still refuses these first (constraints fire in name order)
    ("null", None),
    ("blank", ""),
    ("url", f"https://example.invalid/knowledge-artifacts/{SHA}/guide.pdf"),
    ("dot-dot-after-sha", f"knowledge-artifacts/{SHA}/../guide.pdf"),
    ("trailing-slash", f"knowledge-artifacts/{SHA}/"),
    ("empty-segment", f"knowledge-artifacts/{SHA}//guide.pdf"),
    ("too-long", f"knowledge-artifacts/{SHA}/" + "a" * (513 - 85)),
]


@pytest.mark.parametrize(("label", "artifact"), ST1_SHAPES, ids=[c[0] for c in ST1_SHAPES])
def test_st1_shapes_are_still_refused(tx, label, artifact):
    assert _insert(tx, artifact=artifact)[:2] == ("err", CHECK_VIOLATION), label


def test_st11_refuses_a_null_artifact_on_its_own(tx):
    """NULL-safe: even without ST1, a NULL artifact_ref never satisfies the binding."""
    tx.cur.execute(f"alter table public.knowledge_documents drop constraint {ST1}")
    assert _insert(tx, artifact=None) == ("err", CHECK_VIOLATION, ST11)
    assert _insert(tx, artifact=OWN, document_id="ok")[0] == "ok"


def test_another_files_valid_path_is_refused(tx):
    source = tx.source()
    assert _insert(tx, artifact=OWN, source=source, document_id="first")[0] == "ok"          # its own copy
    other_path = f"knowledge-artifacts/{OTHER}/other.pdf"
    assert _insert(tx, artifact=other_path, sha=OTHER, source=source, document_id="second")[0] == "ok"
    # a third version whose bytes are SHA, pointing at the second file's (valid, approved) copy
    assert _insert(tx, artifact=other_path, source=source, document_id="third") == ("err", CHECK_VIOLATION, ST11)


# ------------------------------------------------------------------ drafts: approval-time only

@pytest.mark.parametrize("status", ["review_required", "rejected"])
def test_drafts_are_unchanged(tx, status):
    assert _insert(tx, artifact=None, status=status)[0] == "ok"                               # official_url only
    assert _insert(tx, artifact=OWN, status=status, document_id="own")[0] == "ok"
    assert _insert(tx, artifact=f"knowledge-artifacts/{OTHER}/x.pdf", status=status, document_id="mismatch")[0] == "ok"


def test_a_mismatched_draft_cannot_be_approved_until_corrected(tx):
    ok, doc = _insert(tx, artifact=f"knowledge-artifacts/{OTHER}/guide.pdf", status="review_required")
    assert ok == "ok"
    assert _run(tx, APPROVE, (tx.approver, doc)) == ("err", CHECK_VIOLATION, ST11)
    # artifact_ref is mutable until the first approval (file_sha256 never is)
    assert _run(tx, "update public.knowledge_documents set artifact_ref = %s where id = %s", (OWN, doc)) == ("ok", None)
    assert _run(tx, APPROVE, (tx.approver, doc)) == ("ok", None)
    tx.cur.execute("select status, artifact_ref from public.knowledge_documents where id = %s", (doc,))
    assert tx.cur.fetchone() == ("approved", OWN)


def test_correcting_and_approving_in_one_update_is_allowed(tx):
    ok, doc = _insert(tx, artifact=None, status="review_required")
    assert ok == "ok"
    assert _run(tx, APPROVE.replace(" where", ", artifact_ref = %s where"), (tx.approver, f"knowledge-artifacts/{OTHER}/g.pdf", doc)) \
        == ("err", CHECK_VIOLATION, ST11)
    assert _run(tx, APPROVE.replace(" where", ", artifact_ref = %s where"), (tx.approver, OWN, doc)) == ("ok", None)


def test_lifecycle_after_approval_is_unchanged(tx):
    ok, doc = _insert(tx, artifact=OWN)
    assert ok == "ok"
    assert _run(tx, "update public.knowledge_documents set artifact_ref = %s where id = %s",
                (f"knowledge-artifacts/{SHA}/renamed.pdf", doc))[:2] == ("err", CHECK_VIOLATION)   # frozen by the trigger
    for target in ("review_required", "rejected"):
        assert _run(tx, "update public.knowledge_documents set status = %s where id = %s", (target, doc))[0] == "err"
    assert _run(tx, "update public.knowledge_documents set status = 'archived' where id = %s", (doc,)) == ("ok", None)
    assert _run(tx, "update public.knowledge_documents set status = 'approved' where id = %s", (doc,))[0] == "err"


# ------------------------------------------------------------------ the migration and its rollback

def test_the_constraint_is_the_migrations_and_st1_is_untouched(tx):
    constraints = _constraints(tx)
    definition = constraints[ST11]
    assert "starts_with((artifact_ref COLLATE \"C\")" in definition and "COALESCE(" in definition
    assert "'knowledge-artifacts/'::text || file_sha256" in definition and "'/'::text" in definition
    assert "status <> 'approved'" in definition
    assert ST1 in constraints and "knowledge_documents_approval_chk" in constraints
    assert "knowledge_documents_hash_chk" in constraints and "^[0-9a-f]{64}$" in constraints["knowledge_documents_hash_chk"]
    tx.cur.execute("select obj_description(oid, 'pg_constraint') from pg_constraint where conname = %s", (ST11,))
    assert tx.cur.fetchone()[0].startswith("ST1.1:")


def test_the_migration_accepts_existing_drafts_and_refuses_an_existing_bad_approval(tx):
    tx.cur.execute(f"alter table public.knowledge_documents drop constraint {ST11}")             # the pre-ST1.1 state
    source = tx.source()
    assert _insert(tx, artifact=None, status="review_required", source=source, document_id="d1")[0] == "ok"
    assert _insert(tx, artifact=f"knowledge-artifacts/{OTHER}/x.pdf", status="review_required", source=source,
                   document_id="d2")[0] == "ok"
    assert _insert(tx, artifact=OWN, source=source, document_id="d3")[0] == "ok"
    assert _run(tx, MIGRATION.read_text(encoding="utf-8")) == ("ok", None)                     # drafts never block it
    tx.cur.execute(f"alter table public.knowledge_documents drop constraint {ST11}")
    assert _insert(tx, artifact=f"knowledge-artifacts/{OTHER}/x.pdf", source=source, document_id="bad")[0] == "ok"
    assert _run(tx, MIGRATION.read_text(encoding="utf-8")) == ("err", CHECK_VIOLATION, ST11)   # stop, never repaired


def test_rollback_removes_only_st11_and_replay_restores_it(tx):
    before = _constraints(tx)
    assert _run(tx, _statements(ROLLBACK)) == ("ok", None)
    after = _constraints(tx)
    assert set(before) - set(after) == {ST11} and all(after[k] == before[k] for k in after)    # ST1 / Migration A intact
    tx.cur.execute("savepoint gap")                   # an approved row cannot be deleted: undo it instead
    assert _insert(tx, artifact=f"knowledge-artifacts/{OTHER}/x.pdf")[0] == "ok"                # the gap is back
    tx.cur.execute("rollback to savepoint gap")
    assert _run(tx, MIGRATION.read_text(encoding="utf-8")) == ("ok", None)                     # replay
    assert _constraints(tx) == before

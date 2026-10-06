"""RAG V1.3-C ingestion against the REAL local Supabase stack (Migration A + Storage).

Database: one outer transaction per test, ALWAYS rolled back. PsycopgKnowledgeStore's own
`conn.transaction()` becomes a SAVEPOINT inside it, so the adapter's real all-or-nothing
write runs while nothing ever commits. Users/orgs/farms/seasons come from the reviewed `Tx`
model of test_rag_knowledge_storage.py (also in-transaction).
Storage: real objects in the private `knowledge-artifacts` bucket of the LOCAL stack; every
object a test creates is removed afterwards. Content is synthetic (TEST FIXTURE).

Skipped without SUPABASE_DB_URL; refuses anything but a local stack.
"""

from __future__ import annotations

import dataclasses
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from infrastructure.config import load_settings  # noqa: E402

_SETTINGS = load_settings()
_DB_URL = _SETTINGS.supabase_db_url
_LOCAL = {"127.0.0.1", "localhost"}
_REMOTE = bool(_DB_URL) and not (urlparse(_DB_URL).hostname in _LOCAL
                                 and urlparse(_SETTINGS.supabase_url or "").hostname in _LOCAL)
pytestmark = [
    pytest.mark.skipif(not _DB_URL, reason="SUPABASE_DB_URL is not configured."),
    pytest.mark.skipif(_REMOTE, reason="refusing: writes Storage objects; only runs against a LOCAL Supabase stack"),
]

from knowledge.ingest import ingest, plan  # noqa: E402
from knowledge.models import ArtifactIntegrityError, DocumentSpec, IngestionConflict, SourceSpec  # noqa: E402
from tests.fixtures.knowledge import FIXTURE, make_pdf, read  # noqa: E402

RPC = "select * from public.match_knowledge_chunks_lexical(%s, %s, %s)"


@pytest.fixture
def env():
    import psycopg
    from supabase import create_client

    from infrastructure.knowledge_repo import ARTIFACT_BUCKET, PsycopgKnowledgeStore, SupabaseArtifactStore
    from tests.test_rag_knowledge_storage import Tx

    url, service = _SETTINGS.require_supabase()
    client = create_client(url, service)
    if ARTIFACT_BUCKET not in {b.id for b in client.storage.list_buckets()}:     # local stack only (guarded above)
        client.storage.create_bucket(ARTIFACT_BUCKET, options={"public": False})
    conn = psycopg.connect(_DB_URL, autocommit=False)
    tx = Tx(conn)                                   # opens the outer transaction
    created: list[str] = []
    artifacts = SupabaseArtifactStore(client)
    put = artifacts.put

    def tracking_put(*args):
        ref, new = put(*args)
        if new:
            created.append(ref)
        return ref, new

    artifacts.put = tracking_put
    run = uuid.uuid4().hex[:8]
    try:
        yield {"tx": tx, "store": PsycopgKnowledgeStore(conn), "artifacts": artifacts, "client": client,
               "run": run, "conn": conn}
    finally:
        conn.rollback()
        conn.close()
        bucket = client.storage.from_(ARTIFACT_BUCKET)
        for ref in created:
            try:
                bucket.remove([ref.split("/", 1)[1]])
            except Exception:  # noqa: BLE001 -- already discarded by the code under test
                pass


def _data(env, extra=""):
    """Synthetic Markdown, unique per test run so its artifact address is fresh."""
    return (read("awd_guide.md").decode() + f"\n\nRun {env['run']}{extra} — {FIXTURE}\n").encode()


def _source(env, **kw):
    return SourceSpec(f"kn-ingest-{env['run']}", "TEST FIXTURE source", "Test publisher", "guideline", "official", **kw)


def _plan(env, data, version="v1", source=None, **kw):
    s = source or _source(env)
    d = DocumentSpec(s.source_id, "awd-guide", version, "TEST FIXTURE doc", "vi", **kw)
    return plan(data=data, filename="awd_guide.md", source=s, document=d)


def _ingest(env, p, data):
    return ingest(p, data=data, store=env["store"], artifacts=env["artifacts"])


def _rows(env, p):
    cur = env["tx"].cur
    cur.execute("select count(*) from public.knowledge_documents where source_id = %s", (p.source.source_id,))
    docs = cur.fetchone()[0]
    cur.execute("select count(*) from public.knowledge_chunks c join public.knowledge_documents d on d.id = c.document_pk"
                " where d.source_id = %s", (p.source.source_id,))
    return docs, cur.fetchone()[0]


def _approve(env, p, version="v1"):
    tx = env["tx"]
    tx.cur.execute("update public.knowledge_sources set status = 'approved', approved_by = %s, approved_at = now(),"
                   " review_note = 'fixture: publisher verified' where source_id = %s and status <> 'approved'",
                   (tx.approver, p.source.source_id))
    tx.cur.execute("update public.knowledge_documents set status = 'approved', approved_by = %s, approved_at = now(),"
                   " review_note = 'fixture', license_basis = 'official_publication'"
                   " where source_id = %s and document_version = %s", (tx.approver, p.source.source_id, version))


# ------------------------------------------------------------------ write path

def test_ingestion_writes_review_required_rows_and_a_verified_artifact(env):
    data = _data(env)
    p = _plan(env, data)
    result = _ingest(env, p, data)
    assert (result.outcome, result.status, result.artifact_created) == ("created", "review_required", True)
    stored = env["store"].find_document(p.source.source_id, "awd-guide", "v1")       # privileged operator read
    assert stored.status == "review_required" and stored.artifact_ref == result.artifact_ref
    assert (stored.file_sha256, stored.normalized_sha256) == (p.file_sha256, p.normalized_sha256)
    assert stored.chunks == tuple((c.chunk_id, c.content_sha256) for c in p.chunks)
    assert env["store"].find_source(p.source.source_id).status == "review_required"
    key = result.artifact_ref.split("/", 1)[1]
    assert env["client"].storage.from_("knowledge-artifacts").download(key) == data
    cur = env["tx"].cur
    cur.execute("select section_path, page_from, metadata, search_text <> '' from public.knowledge_chunks c"
                " join public.knowledge_documents d on d.id = c.document_pk where d.source_id = %s order by ordinal",
                (p.source.source_id,))
    rows = cur.fetchall()
    assert [r[0] for r in rows] == [c.section_path for c in p.chunks] and all(r[3] for r in rows)
    assert rows[2][2]["table"] is True


def test_review_required_chunks_are_not_retrievable_until_an_operator_approves(env):
    tx = env["tx"]
    data = _data(env)
    p = _plan(env, data)
    _ingest(env, p, data)
    ids = [c.chunk_id for c in p.chunks]
    assert tx.rpc_ids(tx.member, tx.season_a, "tưới ướt khô", 50) == []
    assert tx.as_user(tx.member, "select chunk_id from public.knowledge_chunks where chunk_id = any(%s)", (ids,)) == ("ok", [])
    _approve(env, p)                                 # the separate, explicit operator step (not ingestion)
    found = tx.rpc_ids(tx.member, tx.season_a, "tuoi uot kho", 50)
    assert found and set(found) <= set(ids)
    assert set(tx.rpc_ids(tx.member, tx.season_a, "1P5G", 50)) & set(ids)


def test_tenant_ingestion_respects_the_farm_scope(env):
    tx = env["tx"]
    data = _data(env, " tenant")
    source = _source(env, visibility="tenant", organization_id=str(tx.org_a), farm_id=str(tx.farm_a))
    p = _plan(env, data, source=dataclasses.replace(source, source_type="tenant_document"))
    _ingest(env, p, data)
    _approve(env, p)
    ids = set(c.chunk_id for c in p.chunks)
    assert set(tx.rpc_ids(tx.member, tx.season_a, "tưới", 50)) & ids
    assert not set(tx.rpc_ids(tx.member2, tx.season_a2, "tưới", 50)) & ids
    assert not set(tx.rpc_ids(tx.outsider, tx.season_b, "tưới", 50)) & ids


def test_tenant_source_with_a_farm_of_another_organization_is_refused_atomically(env):
    import psycopg

    tx = env["tx"]
    data = _data(env, " wrong farm")
    source = _source(env, visibility="tenant", organization_id=str(tx.org_a), farm_id=str(tx.farm_b))
    p = _plan(env, data, source=dataclasses.replace(source, source_type="tenant_document"))
    with pytest.raises(psycopg.Error):
        _ingest(env, p, data)
    assert env["store"].find_source(p.source.source_id) is None
    assert not env["store"].artifact_in_use(f"knowledge-artifacts/{p.file_sha256}/awd_guide.md")


# ------------------------------------------------------------------ idempotency + fail closed

def test_repeat_ingestion_creates_no_duplicates(env):
    data = _data(env)
    p = _plan(env, data)
    _ingest(env, p, data)
    before = _rows(env, p)
    again = _ingest(env, _plan(env, data), data)
    assert (again.outcome, again.artifact_created) == ("unchanged", False)
    assert _rows(env, p) == before == (1, len(p.chunks))


def test_conflicting_bytes_under_the_same_version_fail_closed(env):
    data = _data(env)
    p = _plan(env, data)
    _ingest(env, p, data)
    changed = data.replace(b"15 cm", b"25 cm")
    with pytest.raises(IngestionConflict) as err:
        _ingest(env, _plan(env, changed), changed)
    assert err.value.code == "content_changed"
    assert env["store"].find_document(p.source.source_id, "awd-guide", "v1").file_sha256 == p.file_sha256
    assert _rows(env, p) == (1, len(p.chunks))


def test_new_document_version_coexists(env):
    data = _data(env)
    p1 = _plan(env, data)
    _ingest(env, p1, data)
    changed = data.replace(b"15 cm", b"25 cm")
    p2 = _plan(env, changed, version="v2")
    assert _ingest(env, p2, changed).outcome == "created"
    assert _rows(env, p1) == (2, len(p1.chunks) + len(p2.chunks))
    assert not {c.chunk_id for c in p1.chunks} & {c.chunk_id for c in p2.chunks}


def test_an_approved_version_is_never_mutated_by_ingestion(env):
    data = _data(env)
    p = _plan(env, data)
    _ingest(env, p, data)
    _approve(env, p)
    cur = env["tx"].cur
    snapshot = "select d.*, (select array_agg(c.chunk_id order by ordinal) from public.knowledge_chunks c where c.document_pk = d.id)" \
               " from public.knowledge_documents d where source_id = %s"
    cur.execute(snapshot, (p.source.source_id,))
    before = cur.fetchall()
    with pytest.raises(IngestionConflict):          # stored license_basis differs from the plan's
        _ingest(env, _plan(env, data), data)
    same = _ingest(env, _plan(env, data, license_basis="official_publication"), data)
    assert (same.outcome, same.status) == ("unchanged", "approved")
    cur.execute(snapshot, (p.source.source_id,))
    assert cur.fetchall() == before


def test_archived_version_cannot_be_reopened(env):
    tx = env["tx"]
    data = _data(env)
    p = _plan(env, data, license_basis="official_publication")
    _ingest(env, p, data)
    _approve(env, p)
    tx.cur.execute("update public.knowledge_documents set status = 'archived' where source_id = %s", (p.source.source_id,))
    result = _ingest(env, _plan(env, data, license_basis="official_publication"), data)
    assert (result.outcome, result.status) == ("unchanged", "archived")
    for target in ("approved", "review_required"):
        assert tx.operator("update public.knowledge_documents set status = %s where source_id = %s",
                           (target, p.source.source_id))[0] == "err"


# ------------------------------------------------------------------ atomicity + artifacts

def test_failed_write_rolls_back_every_row_and_removes_the_new_artifact(env):
    data = _data(env, " rollback")
    p = _plan(env, data)
    broken = dataclasses.replace(p, chunks=p.chunks[:-1] + (dataclasses.replace(p.chunks[-1], chunk_id="NOT-HEX"),))
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation):
        _ingest(env, broken, data)
    assert env["store"].find_source(p.source.source_id) is None
    assert env["store"].find_document(p.source.source_id, "awd-guide", "v1") is None
    bucket = env["client"].storage.from_("knowledge-artifacts")
    assert bucket.list(p.file_sha256) == []


def test_same_bytes_reuse_one_verified_artifact_and_tampering_is_detected(env):
    data = _data(env, " reuse")
    p = _plan(env, data)
    first = _ingest(env, p, data)
    other = _plan(env, data, source=dataclasses.replace(_source(env), source_id=f"kn-ingest-{env['run']}-b"))
    second = _ingest(env, other, data)
    assert second.artifact_ref == first.artifact_ref and second.artifact_created is False
    bucket = env["client"].storage.from_("knowledge-artifacts")
    key = first.artifact_ref.split("/", 1)[1]
    bucket.update(key, b"tampered bytes", {"content-type": "text/markdown", "upsert": "true"})
    with pytest.raises(ArtifactIntegrityError):
        env["artifacts"].put(p.file_sha256, "awd_guide.md", data, "text/markdown")


def test_pdf_ingestion_records_pages(env):
    data = make_pdf([[FIXTURE, f"1.1 Mực nước {env['run']}", "Tưới ướt khô xen kẽ giúp giảm phát thải.",
                      "Thêm một dòng nội dung kiểm thử.", f"Trang {i}"] for i in range(1, 4)])
    s = _source(env)
    p = plan(data=data, filename="awd.pdf", source=s,
             document=DocumentSpec(s.source_id, "awd-pdf", "v1", "TEST FIXTURE pdf", "vi"))
    assert _ingest(env, p, data).outcome == "created"
    cur = env["tx"].cur
    cur.execute("select min(page_from), max(page_to) from public.knowledge_chunks c join public.knowledge_documents d"
                " on d.id = c.document_pk where d.document_id = 'awd-pdf' and d.source_id = %s", (s.source_id,))
    assert cur.fetchone() == (1, 3)

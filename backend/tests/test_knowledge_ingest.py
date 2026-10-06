"""RAG V1.3-C ingestion orchestration with in-memory ports, and the operator CLI.

The fakes mirror the contract of infrastructure/knowledge_repo.py (and Migration A): one
atomic write per version, identity (source_id, document_id, document_version), rows never
mutated, content-addressed artifacts. The same scenarios run against the real local Supabase
stack in test_knowledge_ingest_db.py. No network, no database.
"""

from __future__ import annotations

import contextlib
import dataclasses
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from knowledge.ids import sha256_hex  # noqa: E402
from knowledge.ingest import document_differences, ingest, plan  # noqa: E402
from knowledge.models import (ArtifactIntegrityError, DocumentSpec, IngestionConflict,  # noqa: E402
                              KnowledgeIngestionError, SourceSpec, StoredDocument, StoredSource)
from knowledge.ports import IdentityExists  # noqa: E402
from scripts import ingest_knowledge as cli  # noqa: E402
from tests.fixtures.knowledge import HERE, read  # noqa: E402

SOURCE = SourceSpec("test-fixture-src", "TEST FIXTURE source", "Test publisher", "guideline", "official")
DATA = read("awd_guide.md")


def doc(version="v1", **kw) -> DocumentSpec:
    return DocumentSpec("test-fixture-src", "awd-guide", version, "TEST FIXTURE doc", "vi", **kw)


def plan_of(data=DATA, version="v1", source=SOURCE, **kw):
    return plan(data=data, filename="awd_guide.md", source=source, document=doc(version, **kw))


class FakeStore:
    def __init__(self, fail_on_chunks=False):
        self.sources: dict[str, StoredSource] = {}
        self.docs: dict[tuple, StoredDocument] = {}
        self.fail_on_chunks = fail_on_chunks
        self.race: StoredDocument | None = None
        self.writes = 0
        self.locked: list[str] = []

    def find_source(self, source_id):
        return self.sources.get(source_id)

    def find_document(self, *identity):
        return self.docs.get(identity)

    def artifact_in_use(self, ref):
        return any(d.artifact_ref == ref for d in self.docs.values())

    def artifact_lock(self, sha):
        self.locked.append(sha)
        return contextlib.nullcontext()

    def create_version(self, p, artifact_ref):
        if self.race is not None:
            self.docs[(self.race.source_id, self.race.document_id, self.race.document_version)] = self.race
            raise IdentityExists("knowledge_documents_identity_key")
        staged_sources = dict(self.sources)
        s = p.source
        staged_sources.setdefault(s.source_id, StoredSource(*dataclasses.astuple(s), status="review_required"))
        if self.fail_on_chunks:
            raise RuntimeError("chunk insert failed")         # nothing below is applied: atomic
        d = p.document
        self.sources = staged_sources
        self.docs[(d.source_id, d.document_id, d.document_version)] = StoredDocument(
            d.source_id, d.document_id, d.document_version, d.title, d.language, d.official_url, artifact_ref,
            p.file_sha256, p.normalized_sha256, d.published_at, p.parser_version, p.normalizer_version,
            p.chunker_version, d.license_basis, d.license_reference, "review_required",
            tuple((c.chunk_id, c.content_sha256) for c in p.chunks))
        self.writes += 1
        return self.sources[s.source_id]


class FakeArtifacts:
    def __init__(self):
        self.objects: dict[str, bytes] = {}
        self.uploads = 0
        self.discarded: list[str] = []

    def put(self, sha, name, data, content_type):
        assert sha256_hex(data) == sha
        existing = [k for k in self.objects if k.startswith(f"knowledge-artifacts/{sha}/")]
        if existing:
            return existing[0], False
        ref = f"knowledge-artifacts/{sha}/{name}"
        self.objects[ref] = data
        self.uploads += 1
        return ref, True

    def verify(self, ref, sha):
        if not ref.startswith(f"knowledge-artifacts/{sha}/"):
            raise ArtifactIntegrityError("not the content address")
        if ref not in self.objects:
            raise ArtifactIntegrityError("missing", code="artifact_missing")
        if sha256_hex(self.objects[ref]) != sha:
            raise ArtifactIntegrityError("tampered")

    def discard(self, ref):
        self.discarded.append(ref)
        self.objects.pop(ref)


@pytest.fixture
def ports():
    return FakeStore(), FakeArtifacts()


def run(p, ports, data=DATA):
    store, artifacts = ports
    return ingest(p, data=data, store=store, artifacts=artifacts)


def _set_status(store, status, source_status=None):
    (key, d), = store.docs.items()
    store.docs[key] = dataclasses.replace(d, status=status)
    if source_status:
        sid = d.source_id
        store.sources[sid] = dataclasses.replace(store.sources[sid], status=source_status)


# ------------------------------------------------------------------ create / idempotency

def test_first_ingestion_creates_review_required_rows_with_a_verified_artifact(ports):
    p = plan_of()
    result = run(p, ports)
    store, artifacts = ports
    assert (result.outcome, result.status, result.artifact_created) == ("created", "review_required", True)
    assert result.artifact_ref == f"knowledge-artifacts/{p.file_sha256}/awd_guide.md"
    assert artifacts.objects[result.artifact_ref] == DATA
    stored = store.find_document("test-fixture-src", "awd-guide", "v1")
    assert stored.status == "review_required" and stored.artifact_ref == result.artifact_ref
    assert stored.file_sha256 == sha256_hex(DATA) and len(stored.chunks) == len(p.chunks)


def test_repeating_the_same_ingestion_is_a_no_op(ports):
    run(plan_of(), ports)
    store, artifacts = ports
    result = run(plan_of(), ports)
    assert (result.outcome, result.artifact_created) == ("unchanged", False)
    assert store.writes == 1 and artifacts.uploads == 1 and len(store.docs) == 1


@pytest.mark.parametrize("status", ["approved", "archived", "rejected"])
def test_existing_version_in_any_status_is_never_touched_or_reactivated(ports, status):
    run(plan_of(), ports)
    store, _ = ports
    _set_status(store, status)
    before = dict(store.docs)
    result = run(plan_of(), ports)
    assert (result.outcome, result.status) == ("unchanged", status)
    assert store.docs == before and store.writes == 1


def test_new_document_version_coexists_with_new_chunk_ids(ports):
    run(plan_of(), ports)
    result = run(plan_of(version="v2"), ports)
    store, artifacts = ports
    v1 = store.find_document("test-fixture-src", "awd-guide", "v1")
    v2 = store.find_document("test-fixture-src", "awd-guide", "v2")
    assert result.outcome == "created" and not {c for c, _ in v1.chunks} & {c for c, _ in v2.chunks}
    assert artifacts.uploads == 1 and v1.artifact_ref == v2.artifact_ref     # same bytes: one artifact


def test_every_run_holds_the_content_address_lock(ports):
    run(plan_of(), ports)
    run(plan_of(), ports)
    assert ports[0].locked == [sha256_hex(DATA)] * 2


@pytest.mark.parametrize(("damage", "code"), [("delete", "artifact_missing"), ("tamper", "artifact_integrity"),
                                              ("null_ref", "artifact_missing")])
def test_unchanged_requires_a_verified_stored_artifact(ports, damage, code):
    result = run(plan_of(), ports)
    store, artifacts = ports
    if damage == "delete":
        artifacts.objects.clear()
    elif damage == "tamper":
        artifacts.objects[result.artifact_ref] = b"tampered"
    else:
        (key, d), = store.docs.items()
        store.docs[key] = dataclasses.replace(d, artifact_ref=None)
    with pytest.raises(ArtifactIntegrityError) as err:
        run(plan_of(), ports)
    assert err.value.code == code


def test_same_version_with_a_conflicting_source_is_refused(ports):
    run(plan_of(), ports)
    with pytest.raises(IngestionConflict) as err:
        run(plan_of(source=dataclasses.replace(SOURCE, owner="Someone else")), ports)
    assert err.value.code == "source_mismatch"


# ------------------------------------------------------------------ fail closed

def test_changed_bytes_under_the_same_version_are_refused(ports):
    run(plan_of(), ports)
    changed = DATA.replace(b"15 cm", b"20 cm")
    with pytest.raises(IngestionConflict) as err:
        run(plan_of(changed), ports, data=changed)
    assert err.value.code == "content_changed" and "NEW document_version" in str(err.value)
    store, artifacts = ports
    assert store.writes == 1 and artifacts.uploads == 1


def test_another_pipeline_version_under_the_same_version_is_refused(ports):
    run(plan_of(), ports)
    store, _ = ports
    (key, d), = store.docs.items()
    store.docs[key] = dataclasses.replace(d, chunker_version="kn-chunk-0")
    with pytest.raises(IngestionConflict) as err:
        run(plan_of(), ports)
    assert err.value.code == "pipeline_changed"


@pytest.mark.parametrize("change", [{"title": "Another title"}, {"official_url": "https://example.invalid/new"},
                                    {"license_basis": "official_publication"}])
def test_changed_document_metadata_is_refused(ports, change):
    run(plan_of(), ports)
    p = plan_of()
    p = dataclasses.replace(p, document=dataclasses.replace(p.document, **change))
    with pytest.raises(IngestionConflict) as err:
        run(p, ports)
    assert err.value.code == "metadata_changed"


def test_tampered_stored_chunk_set_is_refused(ports):
    run(plan_of(), ports)
    store, _ = ports
    (key, d), = store.docs.items()
    store.docs[key] = dataclasses.replace(d, chunks=d.chunks[:-1])
    with pytest.raises(IngestionConflict):
        run(plan_of(), ports)


def test_source_metadata_is_never_changed_by_ingestion(ports):
    run(plan_of(), ports)
    other = dataclasses.replace(SOURCE, owner="Someone else")
    with pytest.raises(IngestionConflict) as err:
        run(plan_of(version="v2", source=other), ports)
    assert err.value.code == "source_mismatch"
    store, artifacts = ports
    assert store.writes == 1 and artifacts.uploads == 1


def test_bytes_must_match_the_plan(ports):
    with pytest.raises(KnowledgeIngestionError) as err:
        run(plan_of(), ports, data=DATA + b" ")
    assert err.value.code == "artifact_integrity"


def test_document_differences_ordering():
    p = plan_of()
    stored = StoredDocument("test-fixture-src", "awd-guide", "v1", p.document.title, "vi", None, "ref", "0" * 64,
                            p.normalized_sha256, None, p.parser_version, "other", p.chunker_version, "unknown", None,
                            "review_required", ())
    assert document_differences(stored, p) == ["file_sha256"]
    assert document_differences(dataclasses.replace(stored, file_sha256=p.file_sha256), p) == ["normalizer_version"]


# ------------------------------------------------------------------ atomicity + artifact compensation

def test_failed_transaction_leaves_no_rows_and_removes_the_new_artifact():
    store, artifacts = FakeStore(fail_on_chunks=True), FakeArtifacts()
    with pytest.raises(RuntimeError):
        ingest(plan_of(), data=DATA, store=store, artifacts=artifacts)
    assert store.docs == {} and store.sources == {}
    assert artifacts.objects == {} and len(artifacts.discarded) == 1


def test_failed_transaction_keeps_an_artifact_another_version_references():
    store, artifacts = FakeStore(), FakeArtifacts()
    ingest(plan_of(), data=DATA, store=store, artifacts=artifacts)
    store.fail_on_chunks = True
    with pytest.raises(RuntimeError):
        ingest(plan_of(version="v2"), data=DATA, store=store, artifacts=artifacts)
    assert artifacts.discarded == [] and len(artifacts.objects) == 1


def test_compensation_failure_is_attached_not_masking():
    class Broken(FakeArtifacts):
        def discard(self, ref):
            raise OSError("storage down")

    store = FakeStore(fail_on_chunks=True)
    with pytest.raises(RuntimeError) as err:
        ingest(plan_of(), data=DATA, store=store, artifacts=Broken())
    assert any("orphaned object: knowledge-artifacts/" in n for n in err.value.__notes__)


def test_concurrent_creation_of_the_same_version_resolves_to_unchanged_or_conflict():
    p = plan_of()
    template = FakeStore()
    ingest(p, data=DATA, store=template, artifacts=FakeArtifacts())
    (_, winner), = template.docs.items()

    store, artifacts = FakeStore(), FakeArtifacts()
    store.race = winner                                    # identical row appears concurrently
    result = ingest(p, data=DATA, store=store, artifacts=artifacts)
    assert result.outcome == "unchanged"
    store2 = FakeStore()
    store2.race = dataclasses.replace(winner, file_sha256="1" * 64)
    with pytest.raises(IngestionConflict):
        ingest(p, data=DATA, store=store2, artifacts=FakeArtifacts())


def test_artifact_integrity_error_stops_before_any_row():
    class Corrupt(FakeArtifacts):
        def put(self, *a):
            raise ArtifactIntegrityError("stored object does not hash")

    store = FakeStore()
    with pytest.raises(ArtifactIntegrityError):
        ingest(plan_of(), data=DATA, store=store, artifacts=Corrupt())
    assert store.docs == {}


# ------------------------------------------------------------------ operator CLI

ARGS = ["--source-id", "test-fixture-src", "--source-title", "TEST FIXTURE source", "--source-owner", "Test publisher",
        "--source-type", "guideline", "--document-id", "awd-guide", "--document-version", "v1",
        "--title", "TEST FIXTURE doc", "--language", "vi"]


def test_cli_dry_run_prints_the_plan_and_touches_nothing(capsys, monkeypatch):
    monkeypatch.setattr("psycopg.connect", lambda *a, **k: pytest.fail("dry run opened a database connection"))
    assert cli.main(["--file", str(HERE / "awd_guide.md"), "--dry-run", *ARGS]) == 0
    out = capsys.readouterr().out
    p = plan_of()
    for expected in (p.file_sha256, p.normalized_sha256, p.parser_version, p.normalizer_version, p.chunker_version,
                     *(c.chunk_id for c in p.chunks), f"chunks             {len(p.chunks)}", "NOT approved",
                     "front_matter_ignored"):
        assert expected in out


def test_cli_refuses_bad_input_with_exit_1(capsys, tmp_path):
    bad = tmp_path / "x.docx"
    bad.write_bytes(b"PK\x03\x04")
    assert cli.main(["--file", str(bad), "--dry-run", *ARGS]) == 1
    assert "refused [unsupported_format]" in capsys.readouterr().err


def test_cli_refuses_directories(tmp_path):
    with pytest.raises(SystemExit):
        cli.main(["--file", str(tmp_path), "--dry-run", *ARGS])


def test_cli_has_no_approval_switch():
    options = {o for action in cli.build_parser()._actions for o in action.option_strings}
    switches = {o for o in options if re.search(r"approv|trust|force|status|^--publish$|republish|restore|reactivat", o)}
    assert not switches and "--published-at" in options      # a provenance date, not a lifecycle switch
    with pytest.raises(SystemExit):
        cli.main(["--file", "x.md", "--dry-run", "--approve", *ARGS])


def test_cli_write_mode_requires_an_explicit_target():
    with pytest.raises(SystemExit):
        cli.main(["--file", str(HERE / "awd_guide.md"), *ARGS])


@pytest.mark.parametrize(("api", "db", "expected"), [
    ("http://127.0.0.1:54321", "postgresql://postgres:x@127.0.0.1:54322/postgres", "local"),
    ("https://abcdefgh.supabase.co", "postgresql://postgres.abcdefgh:x@pooler.supabase.com:6543/postgres", "abcdefgh"),
    ("https://abcdefgh.supabase.co", "postgresql://postgres.other:x@pooler.supabase.com:6543/postgres", None),
    ("http://127.0.0.1:54321", "postgresql://postgres.abcdefgh:x@pooler.supabase.com:6543/postgres", None),
    ("https://abcdefgh.supabase.co", "postgresql://postgres:x@db.abcdefgh.supabase.co:5432/postgres", "abcdefgh"),
    # the ref only inside the password / query / an unrelated host: another project
    ("https://abcdefgh.supabase.co", "postgresql://postgres.other:abcdefgh@pooler.supabase.com:6543/postgres", None),
    ("https://abcdefgh.supabase.co", "postgresql://postgres.other:x@pooler.supabase.com:6543/postgres?app=abcdefgh", None),
    ("https://abcdefgh.supabase.co", "postgresql://postgres:x@db.abcdefgh.evil.example:5432/postgres", None),
    ("https://abcdefgh.supabase.co.evil.example", "postgresql://postgres.abcdefgh:x@pooler.supabase.com/postgres", None),
    # a pooler user on a host that is not a Supabase pooler; a direct host with another user
    ("https://abcdefgh.supabase.co", "postgresql://postgres.abcdefgh:x@evil.example:6543/postgres", None),
    ("https://abcdefgh.supabase.co", "postgresql://postgres.abcdefgh:x@pooler.supabase.com.evil.example/postgres", None),
    ("https://abcdefgh.supabase.co",
     "postgresql://postgres.abcdefgh:x@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres", "abcdefgh"),
    ("https://abcdefgh.supabase.co", "postgresql://someone:x@db.abcdefgh.supabase.co:5432/postgres", None),
])
def test_cli_target_resolution(api, db, expected):
    assert cli.target_of(api, db) == expected


def test_cli_wrong_target_is_refused_before_any_write(monkeypatch, capsys):
    from infrastructure import config

    settings = config.Settings(supabase_url="http://127.0.0.1:54321", supabase_service_role_key="local-dev-key",
                               supabase_publishable_key=None, ef_config_path=Path("unused.yaml"),
                               require_factor_set_in_db=False, cors_origins=[],
                               supabase_db_url="postgresql://postgres:pw-not-printed@127.0.0.1:54322/postgres")
    monkeypatch.setattr(config, "load_settings", lambda: settings)
    monkeypatch.setattr("psycopg.connect", lambda *a, **k: pytest.fail("connected despite a wrong target"))
    assert cli.main(["--file", str(HERE / "awd_guide.md"), "--target", "abcdefgh", *ARGS]) == 2
    err = capsys.readouterr().err
    assert "refused" in err and "pw-not-printed" not in err and "local-dev-key" not in err


# ------------------------------------------------------------------ Storage adapter (in-memory client)

from storage3.exceptions import StorageApiError  # noqa: E402 -- the real error shape (message, code, status)

OBJECT_MISSING = StorageApiError("Object not found", "not_found", "404")


class _Bucket:
    def __init__(self, corrupt_download=False, fail_list=False, download_error=None, fail_after_upload=False):
        self.objects: dict[str, bytes] = {}
        self.corrupt_download = corrupt_download
        self.fail_list, self.download_error, self.fail_after_upload = fail_list, download_error, fail_after_upload
        self.removed: list[str] = []
        self.uploaded = False

    def list(self, folder):
        if self.fail_list:
            raise StorageApiError("Invalid Compact JWS", "Unauthorized", "403")
        return [{"name": k.split("/", 1)[1], "id": "x"} for k in sorted(self.objects) if k.startswith(f"{folder}/")]

    def download(self, key):
        if self.download_error is not None:
            raise self.download_error
        if self.fail_after_upload and self.uploaded:
            raise StorageApiError("timeout", "Gateway Timeout", "504")
        if key not in self.objects:
            raise OBJECT_MISSING
        return b"corrupted" if self.corrupt_download else self.objects[key]

    def upload(self, key, data, options):
        assert options["upsert"] == "false"
        if key in self.objects:
            raise RuntimeError("Duplicate")
        self.objects[key] = data
        self.uploaded = True

    def remove(self, keys):
        for k in keys:
            self.removed.append(k)
            self.objects.pop(k, None)


class _Client:
    def __init__(self, bucket):
        self.storage = type("S", (), {"from_": lambda _self, name: bucket})()


def _adapter(**kw):
    from infrastructure.knowledge_repo import SupabaseArtifactStore

    bucket = _Bucket(**kw)
    return SupabaseArtifactStore(_Client(bucket)), bucket


def test_storage_adapter_stores_reuses_and_verifies():
    store, bucket = _adapter()
    sha = sha256_hex(DATA)
    assert store.put(sha, "a.md", DATA, "text/markdown") == (f"knowledge-artifacts/{sha}/a.md", True)
    assert store.put(sha, "other-name.md", DATA, "text/markdown") == (f"knowledge-artifacts/{sha}/a.md", False)
    store.verify(f"knowledge-artifacts/{sha}/a.md", sha)
    with pytest.raises(ArtifactIntegrityError):
        store.verify(f"knowledge-artifacts/{'0' * 64}/a.md", sha)
    bucket.objects[f"{sha}/a.md"] = b"tampered"
    with pytest.raises(ArtifactIntegrityError):
        store.put(sha, "a.md", DATA, "text/markdown")
    with pytest.raises(ArtifactIntegrityError):
        store.verify(f"knowledge-artifacts/{sha}/a.md", sha)
    with pytest.raises(ArtifactIntegrityError):
        store.put(sha, "a.md", DATA + b"x", "text/markdown")


def test_storage_adapter_removes_an_object_it_could_not_verify():
    store, bucket = _adapter(corrupt_download=True)
    sha = sha256_hex(DATA)
    with pytest.raises(ArtifactIntegrityError):
        store.put(sha, "a.md", DATA, "text/markdown")
    assert bucket.objects == {} and bucket.removed == [f"{sha}/a.md"]


def test_storage_adapter_discard_only_takes_its_own_references():
    store, bucket = _adapter()
    sha = sha256_hex(DATA)
    ref, _ = store.put(sha, "a.md", DATA, "text/markdown")
    with pytest.raises(ValueError):
        store.discard("mrv-exports/" + ref.split("/", 1)[1])
    store.discard(ref)
    assert bucket.objects == {}


def test_storage_errors_are_never_read_as_absence():
    from knowledge.models import StorageError

    sha = sha256_hex(DATA)
    store, bucket = _adapter(fail_list=True)
    with pytest.raises(StorageError):
        store.put(sha, "a.md", DATA, "text/markdown")
    assert bucket.objects == {}                        # no second object uploaded after a failed lookup
    for error in (StorageApiError("Bucket not found", "Bucket not found", "404"),    # wrong key / missing bucket
                  StorageApiError("Bucket not found", "not_found", "404"),           # same code, bucket-level
                  StorageApiError("Invalid Compact JWS", "Unauthorized", "403")):
        store, bucket = _adapter(download_error=error)
        bucket.objects[f"{sha}/a.md"] = DATA
        with pytest.raises(StorageError):
            store.verify(f"knowledge-artifacts/{sha}/a.md", sha)
        with pytest.raises(StorageError):
            store.put(sha, "b.md", DATA, "text/markdown")
        assert list(bucket.objects) == [f"{sha}/a.md"]
    store, bucket = _adapter(download_error=OBJECT_MISSING)
    with pytest.raises(ArtifactIntegrityError) as err:            # the one true "absent"
        store.verify(f"knowledge-artifacts/{sha}/a.md", sha)
    assert err.value.code == "artifact_missing"


def test_a_storage_error_on_read_back_removes_the_new_object():
    from knowledge.models import StorageError

    store, bucket = _adapter(fail_after_upload=True)
    with pytest.raises(StorageError):
        store.put(sha256_hex(DATA), "a.md", DATA, "text/markdown")
    assert bucket.objects == {} and bucket.removed == [f"{sha256_hex(DATA)}/a.md"]


def test_orphan_note_survives_the_identity_race_path():
    class Broken(FakeArtifacts):
        def discard(self, ref):
            raise OSError("storage down")

    p = plan_of()
    template = FakeStore()
    ingest(p, data=DATA, store=template, artifacts=FakeArtifacts())
    (_, winner), = template.docs.items()
    store = FakeStore()
    store.race = dataclasses.replace(winner, file_sha256="1" * 64,          # other bytes won the identity
                                     artifact_ref=f"knowledge-artifacts/{'1' * 64}/other.md")
    with pytest.raises(IngestionConflict) as err:
        ingest(p, data=DATA, store=store, artifacts=Broken())
    assert any("orphaned object: knowledge-artifacts/" in n for n in err.value.__notes__)


class _Cursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        self.conn.calls.append(sql.split("(")[0])
        if "unlock" in sql and self.conn.unlock_fails:
            raise ConnectionError("connection lost")


class _Conn:
    def __init__(self, unlock_fails):
        self.calls: list[str] = []
        self.unlock_fails = unlock_fails

    def cursor(self):
        return _Cursor(self)


def test_a_failing_unlock_never_masks_the_original_error():
    from infrastructure.knowledge_repo import PsycopgKnowledgeStore

    store = PsycopgKnowledgeStore(_Conn(unlock_fails=True))
    with pytest.raises(RuntimeError) as err:
        with store.artifact_lock("a" * 64):
            boom = RuntimeError("write failed")
            boom.add_note("artifact compensation failed; orphaned object: knowledge-artifacts/x")
            raise boom
    assert str(err.value) == "write failed"
    assert [n.split(" (")[0] for n in err.value.__notes__] == [
        "artifact compensation failed; orphaned object: knowledge-artifacts/x", "advisory unlock failed"]
    with pytest.raises(ConnectionError):               # without an earlier error the unlock failure surfaces
        with PsycopgKnowledgeStore(_Conn(unlock_fails=True)).artifact_lock("a" * 64):
            pass
    ok = _Conn(unlock_fails=False)
    with PsycopgKnowledgeStore(ok).artifact_lock("a" * 64):
        pass
    assert ok.calls == ["select pg_advisory_lock", "select pg_advisory_unlock"]


# ------------------------------------------------------------------ third-party parser build suffix

_PDF: dict[str, bytes] = {}


def _pdf_plan():
    from tests.fixtures.knowledge import make_pdf

    if "data" not in _PDF:
        _PDF["data"] = make_pdf([["Tưới ướt khô xen kẽ (AWD) kiểm thử.", "Dòng hai của trang kiểm thử.", f"Trang {i}"]
                                 for i in range(1, 4)])
    return plan(data=_PDF["data"], filename="awd.pdf", source=SOURCE,
                document=DocumentSpec("test-fixture-src", "awd-pdf", "v1", "TEST FIXTURE pdf", "vi"))


def _restamp(store, **change):
    (key, d), = store.docs.items()
    store.docs[key] = dataclasses.replace(d, **change)


def test_a_pypdf_patch_with_identical_output_is_unchanged_with_a_note(ports):
    store, artifacts = ports
    p = _pdf_plan()
    ingest(p, data=_PDF["data"], store=store, artifacts=artifacts)
    _restamp(store, parser_version="kn-pdf-1+pypdf-0.0.1")
    result = ingest(_pdf_plan(), data=_PDF["data"], store=store, artifacts=artifacts)
    assert result.outcome == "unchanged" and "identical output" in result.notes[0]
    assert store.find_document("test-fixture-src", "awd-pdf", "v1").parser_version == "kn-pdf-1+pypdf-0.0.1"


@pytest.mark.parametrize("change", [
    {"parser_version": "kn-pdf-1+pypdf-0.0.1", "normalized_sha256": "0" * 64},   # the patch changed the output
    {"parser_version": "kn-pdf-2+pypdf-0.0.1"},                                  # another parser
    {"parser_version": "kn-pdf-1+pdfium-1.0"},                                   # another extraction engine
    {"parser_version": "kn-pdf-1"},                                              # no build suffix
])
def test_a_parser_change_with_different_output_or_family_is_refused(ports, change):
    store, artifacts = ports
    ingest(_pdf_plan(), data=_PDF["data"], store=store, artifacts=artifacts)
    _restamp(store, **change)
    with pytest.raises(IngestionConflict) as err:
        ingest(_pdf_plan(), data=_PDF["data"], store=store, artifacts=artifacts)
    assert err.value.code == "pipeline_changed"


def test_cli_warns_when_pypdf_is_not_the_pinned_version(monkeypatch):
    p = _pdf_plan()
    monkeypatch.setattr(cli, "pinned_pypdf", lambda: "0.0.0")
    assert "is not the pinned 0.0.0" in cli.summary(p, mode="dry-run")
    monkeypatch.setattr(cli, "pinned_pypdf", lambda: p.parser_version.rsplit("pypdf-", 1)[-1])
    assert "is not the pinned" not in cli.summary(p, mode="dry-run")
    assert cli.environment_warnings(plan_of()) == []
    monkeypatch.undo()
    assert cli.pinned_pypdf() is not None             # backend/constraints.txt pins pypdf

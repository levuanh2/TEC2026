"""Ingestion of ONE document version: plan (pure; also the dry run) then ingest (ports).

Idempotency (ADR §4.5): the identity is (source_id, document_id, document_version).
- Absent: store the artifact, then source + version + chunks in one transaction, `review_required`.
- Present with the same file SHA-256, pipeline versions, normalized SHA-256, metadata and chunk ids:
  a no-op (`unchanged`) whatever its status -- an approved/archived version is never touched and an
  archived one is never reactivated.
- Present with anything different: IngestionConflict (fail closed). New bytes or a new pipeline
  need a new document_version; immutable provenance is never replaced.
There is no approval and no republish path here (docs/rag/RAG_V1_INGESTION.md §6).

Artifact compensation: the artifact is stored BEFORE the transaction (its reference must resolve
when the row commits). If the transaction fails and this run created the object and no document
references it, it is removed; otherwise it is left (content-addressed, private, harmless).
"""

from __future__ import annotations

from dataclasses import asdict

from knowledge.chunking import CHUNKER_VERSION, chunk
from knowledge.ids import safe_artifact_name, sha256_hex
from knowledge.models import (DocumentSpec, IngestionConflict, IngestionPlan, IngestionResult, KnowledgeIngestionError,
                              MetadataError, ParseError, SourceSpec, StoredDocument, StoredSource, validate_document, validate_source)
from knowledge.normalize import normalize
from knowledge.parsers import detect, parser_for
from knowledge.ports import ArtifactStore, IdentityExists, KnowledgeStore

MAX_FILE_BYTES = 50 * 1024 * 1024   # the Storage bucket limit
_SOURCE_FIELDS = ("title", "owner", "source_type", "authority", "visibility", "organization_id", "farm_id")
_DOCUMENT_FIELDS = ("title", "language", "official_url", "published_at", "license_basis", "license_reference")


def plan(*, data: bytes, filename: str, source: SourceSpec, document: DocumentSpec) -> IngestionPlan:
    validate_source(source)
    warnings = validate_document(document)
    if document.source_id != source.source_id:
        raise MetadataError("document.source_id must equal source.source_id")
    if not data:
        raise ParseError("the file is empty", code="empty")
    if len(data) > MAX_FILE_BYTES:
        raise ParseError(f"the file is {len(data)} bytes (limit {MAX_FILE_BYTES})", code="too_large")
    fmt = detect(filename, data)
    parsed = parser_for(fmt)(data)
    normalized = normalize(parsed)
    chunks = chunk(normalized, source_id=source.source_id, document_id=document.document_id,
                   document_version=document.document_version)
    if not chunks:
        raise ParseError("no indexable text after normalization", code="no_content")
    return IngestionPlan(
        source=source, document=document, format=fmt.name, size_bytes=len(data), file_sha256=sha256_hex(data),
        normalized_sha256=normalized.sha256, parser_version=parsed.parser_version,
        normalizer_version=normalized.normalizer_version, chunker_version=CHUNKER_VERSION,
        artifact_name=safe_artifact_name(filename, fmt.extension), content_type=fmt.content_type, chunks=chunks,
        warnings=tuple(warnings) + parsed.warnings + normalized.warnings)


def source_differences(stored: StoredSource, spec: SourceSpec) -> list[str]:
    return [f for f in _SOURCE_FIELDS if getattr(stored, f) != getattr(spec, f)]


def document_differences(stored: StoredDocument, p: IngestionPlan) -> list[str]:
    """Why `stored` is not this plan, most fundamental first; [] means identical."""
    if stored.file_sha256 != p.file_sha256:
        return ["file_sha256"]
    diffs = [f for f in ("parser_version", "normalizer_version", "chunker_version") if getattr(stored, f) != getattr(p, f)]
    if diffs:
        return diffs
    if stored.normalized_sha256 != p.normalized_sha256:
        return ["normalized_sha256"]
    doc = asdict(p.document)
    diffs = [f for f in _DOCUMENT_FIELDS if getattr(stored, f) != doc[f]]
    if stored.chunks != tuple((c.chunk_id, c.content_sha256) for c in p.chunks):
        diffs.append("chunks")
    return diffs


def _conflict(stored: StoredDocument, p: IngestionPlan) -> IngestionConflict | None:
    diffs = document_differences(stored, p)
    if not diffs:
        return None
    ident = f"{p.document.source_id}/{p.document.document_id}@{p.document.document_version}"
    if diffs == ["file_sha256"]:
        return IngestionConflict(f"{ident} already exists with different bytes (stored {stored.file_sha256[:12]}…, "
                                 f"new {p.file_sha256[:12]}…): ingest the new bytes as a NEW document_version",
                                 code="content_changed")
    if set(diffs) & {"parser_version", "normalizer_version", "chunker_version"}:
        return IngestionConflict(f"{ident} was ingested with another pipeline ({', '.join(diffs)}): "
                                 "re-ingest as a NEW document_version", code="pipeline_changed")
    return IngestionConflict(f"{ident} already exists with different {', '.join(diffs)}: fail closed",
                             code="metadata_changed")


def _unchanged(stored: StoredDocument, p: IngestionPlan, store: KnowledgeStore) -> IngestionResult:
    conflict = _conflict(stored, p)
    if conflict:
        raise conflict
    src = store.find_source(p.source.source_id)
    return IngestionResult(outcome="unchanged", status=stored.status, artifact_ref=stored.artifact_ref,
                           artifact_created=False, source_status=src.status if src else None)


def ingest(p: IngestionPlan, *, data: bytes, store: KnowledgeStore, artifacts: ArtifactStore) -> IngestionResult:
    if sha256_hex(data) != p.file_sha256:
        raise KnowledgeIngestionError("the bytes changed after planning", code="artifact_integrity")
    doc = p.document
    stored = store.find_document(doc.source_id, doc.document_id, doc.document_version)
    if stored is not None:
        return _unchanged(stored, p, store)
    src = store.find_source(p.source.source_id)
    if src is not None and source_differences(src, p.source):
        raise IngestionConflict(f"source {src.source_id} exists with different {', '.join(source_differences(src, p.source))}"
                                " (source metadata is not changed by ingestion)", code="source_mismatch")
    ref, created = artifacts.put(p.file_sha256, p.artifact_name, data, p.content_type)
    try:
        written = store.create_version(p, ref)
    except IdentityExists as exc:
        stored = store.find_document(doc.source_id, doc.document_id, doc.document_version)
        _compensate(ref, created, store, artifacts, exc)
        if stored is None:
            raise
        return _unchanged(stored, p, store)
    except BaseException as exc:
        _compensate(ref, created, store, artifacts, exc)
        raise
    return IngestionResult(outcome="created", status="review_required", artifact_ref=ref,
                           artifact_created=created, source_status=written.status)


def _compensate(ref: str, created: bool, store: KnowledgeStore, artifacts: ArtifactStore, exc: BaseException) -> None:
    """Best effort; a failure here never hides the original error -- it is attached to it."""
    if not created:
        return
    try:
        if not store.artifact_in_use(ref):
            artifacts.discard(ref)
    except Exception as cleanup:  # noqa: BLE001
        exc.add_note(f"artifact compensation failed ({type(cleanup).__name__}); orphaned object: {ref}")

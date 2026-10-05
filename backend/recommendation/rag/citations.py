"""Citation validation: a generated `(source_id, chunk_id)` must be one of the
chunks retrieved for this request. Display metadata is resolved from those
trusted chunks, never taken from generated text."""

from __future__ import annotations

from collections.abc import Sequence

from .errors import CitationMismatch
from .models import CitedEvidence, EvidenceChunk, EvidenceRef


def validate_citations(refs: Sequence[EvidenceRef], evidence: Sequence[EvidenceChunk]) -> None:
    """One citation list (an answer's, or one recommendation's)."""
    sources = {chunk.source_id for chunk in evidence}
    chunks = {chunk.ref for chunk in evidence}
    seen: set[EvidenceRef] = set()
    for ref in refs:
        if ref in seen:
            raise CitationMismatch(f"duplicate citation source={ref.source_id} chunk={ref.chunk_id}")
        if ref.source_id not in sources:
            raise CitationMismatch(f"unknown source: {ref.source_id}")
        if ref not in chunks:
            raise CitationMismatch(f"unknown chunk {ref.chunk_id} for source {ref.source_id}")
        seen.add(ref)


def resolve_citations(refs: Sequence[EvidenceRef], evidence: Sequence[EvidenceChunk]) -> tuple[CitedEvidence, ...]:
    """Validated refs -> display citations, first-cited order, each once."""
    by_ref = {chunk.ref: chunk for chunk in evidence}
    out: dict[EvidenceRef, CitedEvidence] = {}
    for ref in refs:
        if ref in out:
            continue
        chunk = by_ref.get(ref)
        if chunk is None:
            raise CitationMismatch(f"unknown chunk {ref.chunk_id} for source {ref.source_id}")
        out[ref] = CitedEvidence(
            source_id=chunk.source_id, chunk_id=chunk.chunk_id, document_id=chunk.document_id,
            document_version=chunk.document_version, title=chunk.title, section=chunk.section,
            source_type=chunk.source_type, url=chunk.url, published_at=chunk.published_at,
        )
    return tuple(out.values())

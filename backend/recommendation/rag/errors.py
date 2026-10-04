"""Typed RAG failures. Flat on purpose; each carries the stable `code` a future
route puts in the Core V1 error envelope (`infrastructure/api_errors.error_detail`).

Insufficient evidence is NOT an error: it is a valid `RagAnswerResult` status.
"""

from __future__ import annotations


class RagError(Exception):
    code = "rag_error"


class RagAccessDenied(RagError):
    """Season unknown or outside the caller's scope — normalized to 404 like
    Recommendation/CV, so scope cannot be enumerated."""

    code = "not_found"


class UnsupportedHypothetical(RagError):
    code = "unsupported_hypothetical"


class RetrievalUnavailable(RagError):
    code = "retrieval_unavailable"


class GenerationUnavailable(RagError):
    code = "generation_unavailable"


class InvalidGeneratedSchema(RagError):
    code = "invalid_generated_schema"


class GroundingFailed(RagError):
    code = "grounding_failed"


class CitationMismatch(GroundingFailed):
    code = "citation_mismatch"


class TenantIsolationViolation(RagError):
    """A retriever returned another tenant's private evidence: a security
    failure, never shown and never passed to generation."""

    code = "tenant_isolation_violation"

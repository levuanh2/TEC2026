"""Typed RAG failures. Flat on purpose; each carries the stable `code` a future
route puts in the Core V1 error envelope (`infrastructure/api_errors.error_detail`).

Insufficient evidence and an unclear question are NOT errors: they are valid
`RagAnswerResult` states.
"""

from __future__ import annotations


class RagError(Exception):
    code = "rag_error"


class RagAccessDenied(RagError):
    """Season unknown or outside the caller's scope, or the caller lacks the
    access level the intent needs — normalized to 404 like Recommendation/CV,
    so neither scope nor the refusing rule can be probed."""

    code = "not_found"


class UnsupportedWhatIfDimension(RagError):
    """A what-if over something `CarbonService` cannot simulate (V1: anything
    but the water regime). Never guessed, never computed, never ignored."""

    code = "unsupported_what_if_dimension"


class RetrievalUnavailable(RagError):
    code = "retrieval_unavailable"


class GenerationUnavailable(RagError):
    code = "generation_unavailable"


class InvalidGeneratedSchema(RagError):
    code = "invalid_generated_schema"


class GroundingFailed(RagError):
    code = "grounding_failed"


class CitationMismatch(GroundingFailed):
    """A document citation that is not one of this request's retrieved chunks."""

    code = "citation_mismatch"


class FactReferenceMismatch(GroundingFailed):
    """A system-fact reference that is not in this request's fact catalog."""

    code = "fact_reference_mismatch"


class TenantIsolationViolation(RagError):
    """Evidence or facts outside the caller's scope reached the RAG core: a
    security failure, never shown and never passed to generation."""

    code = "tenant_isolation_violation"

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


class ActionTierDisabled(RagError):
    """The server runs READ-only (`RAG_QA_ACTION_TIER_ENABLED` is not "true"): recommend,
    what_if and non-ASK modes are refused before any read. Not a GenerationUnavailable
    subclass, so no handler can mistake it for a transient provider failure."""

    code = "action_tier_disabled"


class QuestionRateLimited(RagError):
    """The verified caller asked more questions than the server-side per-user limit allows.
    Raised after JWT verification and before any season read, so it is the same for every
    season id. `retry_after_seconds` becomes the Retry-After header."""

    code = "question_rate_limited"

    def __init__(self, message: str = "question rate limit reached", *, retry_after_seconds: int = 60) -> None:
        super().__init__(message)
        self.retry_after_seconds = max(1, int(retry_after_seconds))


class QuestionRateLimitUnavailable(RagError):
    """The rate-limit store could not answer: the question is refused, never let through."""

    code = "question_rate_limit_unavailable"


class QuestionNotEnabledForAccount(RagError):
    """Pilot cohort gate (`RAG_QA_ALLOWED_USER_IDS`): the verified caller is not in the approved
    QA cohort. Raised after JWT verification and before the rate limit and any season read, so
    it costs no quota and is the same for every season id."""

    code = "question_not_enabled"


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

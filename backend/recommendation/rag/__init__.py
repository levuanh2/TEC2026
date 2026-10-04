"""RAG V1 core for Recommendation Q&A — provider-neutral contracts only.

No model provider, no vector store, no route, no persistence
(docs/rag/RAG_V1_ARCHITECTURE.md). Depends on pydantic, the stdlib, `carbon`'s
scenario vocabulary/error type and `recommendation.rules.CarbonCalculator`;
Core V1 `recommendation` never imports this package.
"""

from .answers import AnswerBasis, GenerationInput, RagAnswerResult
from .citations import resolve_citations, validate_citations
from .claims import placeholder_ids, unreferenced_quantities, validate_fact_refs, validate_quantitative_claims
from .context import SeasonRagContext, build_season_context
from .contracts import AnswerGenerator, KnowledgeRetriever, SeasonFactsSource, SeasonScopeResolver, WhatIfSimulator
from .errors import (
    CitationMismatch,
    FactReferenceMismatch,
    GenerationUnavailable,
    GroundingFailed,
    InvalidGeneratedSchema,
    RagAccessDenied,
    RagError,
    RetrievalUnavailable,
    TenantIsolationViolation,
    UnsupportedWhatIfDimension,
)
from .facts import assert_fact_scope, build_fact_catalog, has_comparison_basis
from .grounding import validate_grounding
from .intents import INTENT_POLICIES, AccessLevel, IntentPolicy, RagIntent, RagMode, required_access
from .models import (
    SUPPORTED_WHAT_IF_DIMENSIONS,
    AnswerRecommendation,
    AuthorizedSeasonScope,
    CitedEvidence,
    EvidenceChunk,
    EvidenceRef,
    FactKind,
    FactRef,
    GeneratedAnswer,
    GroundedFact,
    HypotheticalChange,
    RagQuestionRequest,
    RetrievalQuery,
    TenantScope,
    WhatIfDimension,
    WhatIfResult,
)
from .orchestrator import RagOrchestrator
from .retrieval import assert_tenant_isolation, build_retrieval_query
from .what_if import CarbonScenarioWhatIf, ensure_supported

__all__ = [
    "INTENT_POLICIES",
    "SUPPORTED_WHAT_IF_DIMENSIONS",
    "AccessLevel",
    "AnswerBasis",
    "AnswerGenerator",
    "AnswerRecommendation",
    "AuthorizedSeasonScope",
    "CarbonScenarioWhatIf",
    "CitationMismatch",
    "CitedEvidence",
    "EvidenceChunk",
    "EvidenceRef",
    "FactKind",
    "FactRef",
    "FactReferenceMismatch",
    "GeneratedAnswer",
    "GenerationInput",
    "GenerationUnavailable",
    "GroundedFact",
    "GroundingFailed",
    "HypotheticalChange",
    "IntentPolicy",
    "InvalidGeneratedSchema",
    "KnowledgeRetriever",
    "RagAccessDenied",
    "RagAnswerResult",
    "RagError",
    "RagIntent",
    "RagMode",
    "RagOrchestrator",
    "RagQuestionRequest",
    "RetrievalQuery",
    "RetrievalUnavailable",
    "SeasonFactsSource",
    "SeasonRagContext",
    "SeasonScopeResolver",
    "TenantIsolationViolation",
    "TenantScope",
    "UnsupportedWhatIfDimension",
    "WhatIfDimension",
    "WhatIfResult",
    "WhatIfSimulator",
    "assert_fact_scope",
    "assert_tenant_isolation",
    "build_fact_catalog",
    "build_retrieval_query",
    "build_season_context",
    "ensure_supported",
    "has_comparison_basis",
    "placeholder_ids",
    "required_access",
    "resolve_citations",
    "unreferenced_quantities",
    "validate_citations",
    "validate_fact_refs",
    "validate_grounding",
    "validate_quantitative_claims",
]

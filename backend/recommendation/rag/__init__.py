"""RAG V1 core for Recommendation Q&A — provider-neutral contracts only.

No model provider, no vector store, no route, no persistence
(docs/rag/RAG_V1_ARCHITECTURE.md). Depends on pydantic, the stdlib, `carbon`'s
scenario vocabulary/error type and `recommendation.rules.CarbonCalculator`;
Core V1 `recommendation` never imports this package.
"""

from .answers import (
    MISSING_FACT_TEXT,
    AnswerBasis,
    GenerationInput,
    RagAnswerResult,
    format_fact,
    render_answer,
    render_facts,
)
from .citations import resolve_citations, validate_citations
from .claims import placeholder_ids, validate_fact_refs, validate_quantitative_claims
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
from .facts import assert_fact_scope, build_fact_catalog, has_comparison_basis, usable_facts
from .grounding import validate_grounding
from .intents import (
    CAPABILITY_ACCESS,
    CAPABILITY_FACT_USAGE,
    INTENT_POLICIES,
    AccessLevel,
    FactUsage,
    GenerationCapability,
    IntentPolicy,
    RagIntent,
    RagMode,
    allowed_fact_usage,
    required_access,
)
from .models import (
    FACT_USAGE,
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
    InformationalAnswer,
    RagQuestionRequest,
    RetrievalQuery,
    TenantScope,
    WhatIfDimension,
    WhatIfResult,
)
from .orchestrator import RagOrchestrator
from .prose import (
    validate_generated_prose,
    validate_no_raw_links,
    validate_no_raw_numbers,
    validate_placeholder_syntax,
    validate_supported_characters,
)
from .retrieval import assert_tenant_isolation, build_retrieval_query
from .what_if import CarbonScenarioWhatIf, ensure_supported

__all__ = [
    "CAPABILITY_ACCESS",
    "CAPABILITY_FACT_USAGE",
    "FACT_USAGE",
    "INTENT_POLICIES",
    "MISSING_FACT_TEXT",
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
    "FactUsage",
    "GeneratedAnswer",
    "GenerationCapability",
    "GenerationInput",
    "GenerationUnavailable",
    "GroundedFact",
    "GroundingFailed",
    "HypotheticalChange",
    "InformationalAnswer",
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
    "allowed_fact_usage",
    "assert_fact_scope",
    "assert_tenant_isolation",
    "build_fact_catalog",
    "build_retrieval_query",
    "build_season_context",
    "ensure_supported",
    "format_fact",
    "has_comparison_basis",
    "placeholder_ids",
    "render_answer",
    "render_facts",
    "required_access",
    "resolve_citations",
    "usable_facts",
    "validate_citations",
    "validate_fact_refs",
    "validate_generated_prose",
    "validate_grounding",
    "validate_no_raw_links",
    "validate_no_raw_numbers",
    "validate_placeholder_syntax",
    "validate_quantitative_claims",
    "validate_supported_characters",
]

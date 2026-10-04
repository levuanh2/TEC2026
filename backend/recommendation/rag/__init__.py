"""RAG V1 core for Recommendation Q&A — provider-neutral contracts only.

No model provider, no vector store, no route (docs/rag/RAG_V1_ARCHITECTURE.md).
Depends on pydantic, the stdlib, `carbon`'s scenario vocabulary/error type and
`recommendation.rules.CarbonCalculator`; Core V1 `recommendation` never
imports this package.
"""

from .answers import AnswerBasis, GenerationInput, RagAnswerResult
from .citations import resolve_citations, validate_citations
from .context import SeasonRagContext, build_season_context
from .contracts import AnswerGenerator, KnowledgeRetriever, SeasonAccessGate, SeasonFactsSource, WhatIfSimulator
from .errors import (
    CitationMismatch,
    GenerationUnavailable,
    GroundingFailed,
    InvalidGeneratedSchema,
    RagAccessDenied,
    RagError,
    RetrievalUnavailable,
    TenantIsolationViolation,
    UnsupportedHypothetical,
)
from .grounding import validate_grounding
from .intents import EVIDENCE_REQUIRED_INTENTS, AccessLevel, RagIntent, RagMode, required_access
from .models import (
    AnswerRecommendation,
    AuthorizedSeasonScope,
    CitedEvidence,
    EvidenceChunk,
    EvidenceRef,
    GeneratedAnswer,
    HypotheticalChange,
    RagQuestionRequest,
    RetrievalQuery,
    TenantScope,
    WhatIfResult,
)
from .orchestrator import RagOrchestrator
from .retrieval import assert_tenant_isolation, build_retrieval_query
from .what_if import CarbonScenarioWhatIf

__all__ = [
    "EVIDENCE_REQUIRED_INTENTS",
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
    "GeneratedAnswer",
    "GenerationInput",
    "GenerationUnavailable",
    "GroundingFailed",
    "HypotheticalChange",
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
    "SeasonAccessGate",
    "SeasonFactsSource",
    "SeasonRagContext",
    "TenantIsolationViolation",
    "TenantScope",
    "UnsupportedHypothetical",
    "WhatIfResult",
    "WhatIfSimulator",
    "assert_tenant_isolation",
    "build_retrieval_query",
    "build_season_context",
    "required_access",
    "resolve_citations",
    "validate_citations",
    "validate_grounding",
]

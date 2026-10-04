"""Typed contracts that cross RAG boundaries (docs/rag/RAG_V1_DATA_CONTRACT.md).

All are frozen pydantic models with `extra="forbid"`: a client cannot smuggle
an organization/permission/filter field into a request, and a generator cannot
add a number, a URL or a fact value to its answer — an unknown field is a
validation error.

Two grounding channels, never mixed:
  * SYSTEM FACTS — `GroundedFact`, built by trusted code from authoritative
    AgriCarbon results, referenced by `FactRef(fact_id)`;
  * KNOWLEDGE EVIDENCE — `EvidenceChunk`, retrieved approved documents,
    referenced by `EvidenceRef(source_id, chunk_id)`.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from carbon import SCENARIOS

from .intents import AccessLevel, RagIntent, RagMode

Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
FactId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:\-]+$", min_length=1, max_length=200)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
AnswerText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
HttpsUrl = Annotated[str, StringConstraints(pattern=r"^https://\S+$", max_length=2000)]
Scalar = str | int | float | bool | None

#: The season's recorded result; what-if compares every scenario against it.
BASELINE_SCENARIO = "as_recorded"
#: Scenarios `CarbonService` can simulate today — the engine's own vocabulary.
SIMULABLE_SCENARIOS: tuple[str, ...] = tuple(s for s in SCENARIOS if s != BASELINE_SCENARIO)

Visibility = Literal["public", "tenant"]
SourceType = Literal["guideline", "policy", "methodology", "research", "tenant_document"]
Authority = Literal["official", "peer_reviewed", "extension", "internal"]
Confidence = Literal["low", "medium", "high"]
GeneratedStatus = Literal["generated", "insufficient_evidence"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# -- authorization ----------------------------------------------------------

class AuthorizedSeasonScope(Contract):
    """What a `SeasonScopeResolver` proved about the caller and one season
    (decision D3). Only a resolver builds this, from the caller's JWT through
    Core V1 access checks — never from request fields. Everything
    tenant-scoped downstream (context reads, facts, retrieval filters) is
    derived from it."""

    actor_id: Identifier
    organization_id: Identifier
    farm_id: Identifier
    plot_id: Identifier
    crop_season_id: Identifier
    access: AccessLevel


# -- what-if ----------------------------------------------------------------

class WhatIfDimension(StrEnum):
    WATER_REGIME = "water_regime"
    FERTILIZER_AMOUNT = "fertilizer_amount"
    STRAW_MANAGEMENT = "straw_management"
    PESTICIDE = "pesticide"
    SEED_RATE = "seed_rate"
    OTHER_ACTIVITY = "other_activity"


#: V1 scope: only what `CarbonService.calculate(scenario=..., persist=False)`
#: can replay. Everything else needs a hypothetical-input API (decision D2).
SUPPORTED_WHAT_IF_DIMENSIONS: frozenset[WhatIfDimension] = frozenset({WhatIfDimension.WATER_REGIME})


class HypotheticalChange(Contract):
    """A what-if change. Unsupported dimensions are representable so they can
    be refused with a typed error instead of being guessed or dropped."""

    dimension: WhatIfDimension
    #: Target water regime scenario; set exactly for WATER_REGIME.
    scenario: str | None = None

    @model_validator(mode="after")
    def _scenario_matches_dimension(self) -> HypotheticalChange:
        if self.dimension is WhatIfDimension.WATER_REGIME:
            if self.scenario not in SIMULABLE_SCENARIOS:
                raise ValueError(f"water_regime scenario must be one of {SIMULABLE_SCENARIOS}")
        elif self.scenario is not None:
            raise ValueError("scenario applies to the water_regime dimension only")
        return self

    @property
    def supported(self) -> bool:
        return self.dimension in SUPPORTED_WHAT_IF_DIMENSIONS


class WhatIfResult(Contract):
    """Two `CarbonService.calculate(persist=False)` runs. Every number here is
    the engine's; `delta_co2e_kg` is the same before-minus-after difference
    the AWD rule stores (recommendation/rules.py), not emissions math."""

    change: HypotheticalChange
    status: Literal["available", "unavailable"]
    unavailable_reason: str | None = None
    baseline_total_co2e_kg: float | None = None
    hypothetical_total_co2e_kg: float | None = None
    delta_co2e_kg: float | None = None
    baseline_input_hash: str | None = None
    hypothetical_input_hash: str | None = None
    engine_version: str | None = None
    ef_config_version: str | None = None
    #: A what-if never writes; the type cannot say otherwise.
    persisted: Literal[False] = False

    @model_validator(mode="after")
    def _numbers_match_status(self) -> WhatIfResult:
        numbers = (self.baseline_total_co2e_kg, self.hypothetical_total_co2e_kg, self.delta_co2e_kg)
        if self.status == "available" and any(n is None for n in numbers):
            raise ValueError("an available what-if carries all engine totals")
        if self.status == "unavailable" and (any(n is not None for n in numbers) or not self.unavailable_reason):
            raise ValueError("an unavailable what-if carries a reason and no numbers")
        return self


# -- request ----------------------------------------------------------------

class RagQuestionRequest(Contract):
    """A farmer's question about one crop season. Deliberately has no
    organization, permission, filter, table or persist field: scope comes
    from the caller's JWT, and RAG V1 answers are ephemeral (decision D4)."""

    question: Question
    crop_season_id: Identifier
    intent: RagIntent | None = None
    mode: RagMode = RagMode.ASK
    hypothetical: HypotheticalChange | None = None

    @model_validator(mode="after")
    def _hypothetical_only_for_what_if(self) -> RagQuestionRequest:
        if (self.intent is RagIntent.WHAT_IF) != (self.hypothetical is not None):
            raise ValueError("`hypothetical` is required for intent 'what_if' and allowed only there")
        return self


# -- system facts -----------------------------------------------------------

class FactKind(StrEnum):
    SEASON_ATTRIBUTE = "season_attribute"
    RESOURCE_METRIC = "resource_metric"
    CARBON_TOTAL = "carbon_total"
    CARBON_INTENSITY = "carbon_intensity"
    CARBON_BREAKDOWN = "carbon_breakdown"
    DATA_COMPLETENESS = "data_completeness"
    CARBON_READINESS = "carbon_readiness"
    RULE_SIGNAL = "rule_signal"
    CV_SIGNAL = "cv_signal"
    BENCHMARK = "benchmark"
    COMPARISON_SEASON = "comparison_season"
    WHAT_IF = "what_if"


class GroundedFact(Contract):
    """One authoritative AgriCarbon value, built by trusted code
    (`facts.build_fact_catalog`) — never by a generator. A None value is a
    real fact ("not available"), never 0."""

    fact_id: FactId
    kind: FactKind
    value: Scalar
    unit: str | None = None
    #: Which Core V1 service produced the value.
    source: str
    #: Which record (calculation id, input hash, rule version, benchmark source...).
    provenance: dict[str, Scalar] = Field(default_factory=dict)
    #: Scope the value belongs to; None = not season/tenant specific (public benchmark).
    crop_season_id: Identifier | None = None
    organization_id: Identifier | None = None
    authoritative: Literal[True] = True


class FactRef(Contract):
    """A reference to a system fact. Only an id: a generator cannot state,
    override or round the value."""

    fact_id: FactId


# -- knowledge evidence -----------------------------------------------------

class TenantScope(Contract):
    organization_id: Identifier
    farm_id: Identifier | None = None
    crop_season_id: Identifier | None = None


class RetrievalQuery(Contract):
    """What a `KnowledgeRetriever` searches. `tenant` always comes from the
    authorized scope; a retriever must apply it inside the store query."""

    text: Question
    intent: RagIntent
    tenant: TenantScope
    include_public: bool = True
    top_k: int = Field(default=8, ge=1, le=50)


class EvidenceRef(Contract):
    """A document citation: must name a chunk retrieved for this very request."""

    source_id: Identifier
    chunk_id: Identifier


class EvidenceChunk(Contract):
    """One retrieved passage. `content` is UNTRUSTED data (prompt-injection
    boundary, docs/rag/RAG_V1_ARCHITECTURE.md §14); every other field is
    trusted metadata written at ingestion."""

    source_id: Identifier
    document_id: Identifier
    document_version: Identifier | None = None
    chunk_id: Identifier
    title: ShortText
    section: ShortText | None = None
    content: Annotated[str, StringConstraints(min_length=1)]
    source_type: SourceType
    visibility: Visibility
    #: Set exactly for tenant evidence; `farm_id` narrows it to one farm.
    organization_id: Identifier | None = None
    farm_id: Identifier | None = None
    url: HttpsUrl | None = None
    authority: Authority | None = None
    published_at: date | None = None
    metadata: dict[str, Scalar] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _tenant_fields_match_visibility(self) -> EvidenceChunk:
        if self.visibility == "tenant" and self.organization_id is None:
            raise ValueError("tenant evidence must carry its organization_id")
        if self.visibility == "public" and (self.organization_id is not None or self.farm_id is not None):
            raise ValueError("public evidence carries no tenant fields")
        return self

    @property
    def ref(self) -> EvidenceRef:
        return EvidenceRef(source_id=self.source_id, chunk_id=self.chunk_id)


class CitedEvidence(Contract):
    """A citation as shown to a user: display fields come from the trusted
    chunk metadata, never from generated text."""

    source_id: str
    chunk_id: str
    document_id: str
    document_version: str | None
    title: str
    section: str | None
    source_type: SourceType
    url: str | None
    published_at: date | None


# -- generation (UNTRUSTED until grounded) -----------------------------------

class AnswerRecommendation(Contract):
    """An expert claim in a generated answer; grounding requires ≥1 document
    citation. `rule_code` may only name a deterministic signal the season
    really has. Quantities appear only as `{{fact:<fact_id>}}` placeholders."""

    title: ShortText
    actions: tuple[ShortText, ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    fact_refs: tuple[FactRef, ...] = ()
    rule_code: Identifier | None = None


class GeneratedAnswer(Contract):
    """The ONLY shape a generator may return, validated with `model_validate`
    (never parsed out of free text). No number, URL or fact-value field: a
    quantity is a `{{fact:<fact_id>}}` placeholder backed by a `FactRef`, and
    the trusted assembler supplies its value (claims.py)."""

    status: GeneratedStatus
    answer: AnswerText
    rationale: AnswerText | None = None
    recommendations: tuple[AnswerRecommendation, ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    fact_refs: tuple[FactRef, ...] = ()
    limitations: tuple[ShortText, ...] = ()
    confidence: Confidence | None = None

    @model_validator(mode="after")
    def _insufficient_has_no_recommendations(self) -> GeneratedAnswer:
        if self.status == "insufficient_evidence" and self.recommendations:
            raise ValueError("an insufficient-evidence answer cannot recommend")
        return self

    def all_evidence_refs(self) -> tuple[EvidenceRef, ...]:
        return self.evidence_refs + tuple(ref for rec in self.recommendations for ref in rec.evidence_refs)

    def all_fact_refs(self) -> tuple[FactRef, ...]:
        return self.fact_refs + tuple(ref for rec in self.recommendations for ref in rec.fact_refs)

    def texts(self) -> tuple[str, ...]:
        """Every free-text field, for the placeholder and quantity checks."""
        out = [self.answer, *self.limitations]
        if self.rationale:
            out.append(self.rationale)
        for rec in self.recommendations:
            out.extend((rec.title, *rec.actions))
        return tuple(out)

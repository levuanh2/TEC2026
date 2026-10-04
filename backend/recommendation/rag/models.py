"""Typed contracts that cross RAG boundaries (docs/rag/RAG_V1_DATA_CONTRACT.md).

All are frozen pydantic models with `extra="forbid"`: a client cannot smuggle
an organization/permission/filter field into a request, and a generator cannot
add a Carbon number to its answer — an unknown field is a validation error.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

from carbon import SCENARIOS

from .intents import AccessLevel, RagIntent, RagMode

Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
AnswerText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
HttpsUrl = Annotated[str, StringConstraints(pattern=r"^https://\S+$", max_length=2000)]

#: The season's recorded result; what-if compares every scenario against it.
BASELINE_SCENARIO = "as_recorded"
#: Scenarios `CarbonService` can simulate today — the engine's own vocabulary.
SIMULABLE_SCENARIOS: tuple[str, ...] = tuple(s for s in SCENARIOS if s != BASELINE_SCENARIO)

Visibility = Literal["public", "tenant"]
SourceType = Literal["guideline", "policy", "methodology", "research", "tenant_document"]
Authority = Literal["official", "peer_reviewed", "extension", "internal"]
Confidence = Literal["low", "medium", "high"]
AnswerStatus = Literal["generated", "insufficient_evidence"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


# -- authorization ----------------------------------------------------------

class AuthorizedSeasonScope(Contract):
    """What a `SeasonAccessGate` proved about the caller and one season.

    Only a gate builds this, from the caller's JWT and RLS — never from
    request fields. Everything tenant-scoped downstream (context reads, the
    retrieval filter) is derived from it.
    """

    actor_id: Identifier
    organization_id: Identifier
    farm_id: Identifier
    plot_id: Identifier
    crop_season_id: Identifier
    access: AccessLevel


# -- request ----------------------------------------------------------------

class HypotheticalChange(Contract):
    """An allow-listed what-if change. V1: the water regime scenario only,
    because that is the only hypothetical input `CarbonService` accepts."""

    kind: Literal["water_regime_scenario"] = "water_regime_scenario"
    scenario: str

    @field_validator("scenario")
    @classmethod
    def _simulable(cls, value: str) -> str:
        if value not in SIMULABLE_SCENARIOS:
            raise ValueError(f"scenario must be one of {SIMULABLE_SCENARIOS}")
        return value


class RagQuestionRequest(Contract):
    """A farmer's question about one crop season. Deliberately has no
    organization, permission, filter or table field: scope comes from the
    caller's JWT through the access gate."""

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


# -- what-if ----------------------------------------------------------------

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


# -- retrieval --------------------------------------------------------------

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
    """A citation: must name a chunk retrieved for this very request."""

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
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

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


# -- generation -------------------------------------------------------------

class AnswerRecommendation(Contract):
    """An expert claim in a generated answer; grounding requires ≥1 citation.
    `rule_code` may only name a deterministic signal the season really has."""

    title: ShortText
    actions: tuple[ShortText, ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    rule_code: Identifier | None = None


class GeneratedAnswer(Contract):
    """The ONLY shape a generator may return, validated with
    `model_validate` (never parsed out of free text). It has no Carbon or
    Resource Metric number field on purpose."""

    status: AnswerStatus
    answer: AnswerText
    rationale: AnswerText | None = None
    recommendations: tuple[AnswerRecommendation, ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    limitations: tuple[ShortText, ...] = ()
    confidence: Confidence | None = None

    @model_validator(mode="after")
    def _insufficient_has_no_recommendations(self) -> GeneratedAnswer:
        if self.status == "insufficient_evidence" and self.recommendations:
            raise ValueError("an insufficient-evidence answer cannot recommend")
        return self

    def all_refs(self) -> tuple[EvidenceRef, ...]:
        return self.evidence_refs + tuple(ref for rec in self.recommendations for ref in rec.evidence_refs)

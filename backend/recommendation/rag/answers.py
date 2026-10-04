"""What goes into a generator and what the orchestrator hands back."""

from __future__ import annotations

from typing import Literal

from pydantic import model_validator

from .context import DeterministicSignal, SeasonRagContext
from .intents import RagIntent, RagMode
from .models import (
    AnswerRecommendation,
    AnswerStatus,
    CitedEvidence,
    Confidence,
    Contract,
    EvidenceChunk,
    Question,
    WhatIfResult,
)

InsufficientReason = Literal["no_evidence_retrieved", "generator_declined"]


class GenerationInput(Contract):
    """Everything a generator may see. Policy (system prompt, output schema)
    is NOT here — the adapter owns it and sends it on the provider's
    instruction channel; `evidence[*].content` is untrusted data and must be
    sent as delimited data, never merged into policy. No secrets, tokens or
    raw database rows."""

    question: Question
    intent: RagIntent
    context: SeasonRagContext
    evidence: tuple[EvidenceChunk, ...]
    what_if: WhatIfResult | None = None


class AnswerBasis(Contract):
    """Which authoritative records the answer was based on (provenance)."""

    carbon_calculation_id: str | None
    carbon_input_hash: str | None
    ef_config_version: str | None
    signal_rule_codes: tuple[str, ...]


class RagAnswerResult(Contract):
    """Assembled by trusted code only. Text fields come from the grounded
    generator answer; `signals`, `what_if` and `basis` come from
    authoritative sources and `evidence` from trusted chunk metadata."""

    status: AnswerStatus
    intent: RagIntent
    mode: RagMode
    crop_season_id: str
    answer: str | None
    rationale: str | None = None
    recommendations: tuple[AnswerRecommendation, ...] = ()
    evidence: tuple[CitedEvidence, ...] = ()
    limitations: tuple[str, ...] = ()
    confidence: Confidence | None = None
    insufficient_reason: InsufficientReason | None = None
    signals: tuple[DeterministicSignal, ...]
    what_if: WhatIfResult | None = None
    basis: AnswerBasis

    @model_validator(mode="after")
    def _reason_matches_status(self) -> RagAnswerResult:
        if (self.status == "insufficient_evidence") != (self.insufficient_reason is not None):
            raise ValueError("insufficient_reason is set exactly for insufficient_evidence")
        return self

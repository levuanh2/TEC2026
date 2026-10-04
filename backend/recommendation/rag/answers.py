"""What goes into a generator, and the trusted result the orchestrator
assembles from validated parts (never the provider's response itself)."""

from __future__ import annotations

from typing import Literal

from pydantic import model_validator

from .context import DeterministicSignal
from .intents import RagIntent, RagMode
from .models import (
    AnswerRecommendation,
    CitedEvidence,
    Confidence,
    Contract,
    EvidenceChunk,
    GroundedFact,
    Question,
    WhatIfResult,
)

AnswerStatus = Literal["generated", "insufficient_evidence", "needs_clarification"]
InsufficientReason = Literal["no_evidence_retrieved", "no_comparison_basis", "generator_declined"]

#: Trusted copy for states no generator is asked about.
NEEDS_CLARIFICATION_MESSAGE = (
    "Chưa rõ bạn muốn giải thích, so sánh, khuyến nghị hay mô phỏng. Hãy chọn một loại câu hỏi."
)
INSUFFICIENT_MESSAGES: dict[str, str] = {
    "no_evidence_retrieved": "Chưa có tài liệu đã duyệt đủ để trả lời câu hỏi này.",
    "no_comparison_basis": "Không có benchmark hoặc vụ đối chiếu đủ điều kiện để so sánh.",
}


class GenerationInput(Contract):
    """Everything a generator may see. Numbers reach it only as `facts`
    (id + trusted value) so it can reference them, never restate them.
    Policy (system prompt, output schema) is NOT here — the adapter owns it
    and sends it on the provider's instruction channel; `evidence[*].content`
    is untrusted data and must be sent as delimited data, never merged into
    policy. No secrets, tokens or raw database rows."""

    question: Question
    intent: RagIntent
    facts: tuple[GroundedFact, ...]
    evidence: tuple[EvidenceChunk, ...]


class AnswerBasis(Contract):
    """Which authoritative records the answer was based on (provenance)."""

    carbon_calculation_id: str | None
    carbon_input_hash: str | None
    ef_config_version: str | None
    signal_rule_codes: tuple[str, ...]


class RagAnswerResult(Contract):
    """TRUSTED result, assembled by the orchestrator only.

    Text fields come from the grounded generator answer and may contain
    `{{fact:<fact_id>}}` placeholders; `facts` carries exactly the referenced
    system facts, whose trusted values the client renders. `signals`,
    `what_if` and `basis` come from authoritative sources; `evidence` from
    trusted chunk metadata. Nothing here is persisted (decision D4).
    """

    status: AnswerStatus
    intent: RagIntent
    mode: RagMode
    crop_season_id: str
    answer: str | None
    rationale: str | None = None
    recommendations: tuple[AnswerRecommendation, ...] = ()
    evidence: tuple[CitedEvidence, ...] = ()
    facts: tuple[GroundedFact, ...] = ()
    limitations: tuple[str, ...] = ()
    confidence: Confidence | None = None
    insufficient_reason: InsufficientReason | None = None
    signals: tuple[DeterministicSignal, ...] = ()
    what_if: WhatIfResult | None = None
    basis: AnswerBasis | None = None

    @model_validator(mode="after")
    def _state_is_consistent(self) -> RagAnswerResult:
        if (self.status == "insufficient_evidence") != (self.insufficient_reason is not None):
            raise ValueError("insufficient_reason is set exactly for insufficient_evidence")
        if self.status != "generated" and self.recommendations:
            raise ValueError("only a generated answer carries recommendations")
        return self

"""What goes into a generator, the trusted fact renderer, and the trusted
result the orchestrator assembles from validated parts (never the provider's
response itself)."""

from __future__ import annotations

import math
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Literal

from pydantic import model_validator

from .claims import FACT_PLACEHOLDER
from .context import DeterministicSignal
from .errors import FactReferenceMismatch
from .intents import RagIntent, RagMode
from .models import (
    AnswerRecommendation,
    CitedEvidence,
    Confidence,
    Contract,
    EvidenceChunk,
    GeneratedAnswer,
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


#: How a fact whose authoritative value is None reads — never "0".
MISSING_FACT_TEXT = "chưa có dữ liệu"
_BOOLEAN_TEXT = {True: "có", False: "không"}
#: Dimensionless units: the number is shown alone (no conversion, e.g. never ×100 to "%").
_UNITLESS = frozenset({"fraction"})


def _vietnamese_number(value: int | float) -> str:
    """Vietnamese digit grouping ("." thousands, "," decimals) of the value's
    exact shortest representation: no rounding, no added precision; only
    trailing zeros of the fraction (2900.0 -> "2.900") are dropped."""
    if isinstance(value, float) and not math.isfinite(value):
        raise FactReferenceMismatch(f"system fact has a non-finite value: {value!r}")
    text = format(Decimal(repr(value)) if isinstance(value, float) else Decimal(value), "f")
    sign, text = ("-", text[1:]) if text.startswith("-") else ("", text)
    whole, _, fraction = text.partition(".")
    fraction = fraction.rstrip("0")
    return sign + f"{int(whole):,}".replace(",", ".") + ("," + fraction if fraction else "")


def format_fact(fact: GroundedFact) -> str:
    """Display text of one fact: its value as stored plus its own unit."""
    value = fact.value
    if value is None:
        return MISSING_FACT_TEXT
    if isinstance(value, bool):
        return _BOOLEAN_TEXT[value]
    if isinstance(value, str):
        return value
    number = _vietnamese_number(value)
    return number if not fact.unit or fact.unit in _UNITLESS else f"{number} {fact.unit}"


def render_facts(text: str, facts: Mapping[str, GroundedFact]) -> str:
    """Replace every `{{fact:<id>}}` with its formatted trusted value. Runs
    only after grounding; still fails closed on an unknown id or a malformed
    placeholder, so no raw placeholder ever reaches a client."""

    def replace(match: Any) -> str:
        fact = facts.get(match.group(1))
        if fact is None:
            raise FactReferenceMismatch(f"cannot render unknown fact {match.group(1)}")
        return format_fact(fact)

    rendered = FACT_PLACEHOLDER.sub(replace, text)
    if "{{fact:" in rendered:
        raise FactReferenceMismatch("malformed fact placeholder")
    return rendered


def render_answer(answer: GeneratedAnswer, facts: Mapping[str, GroundedFact]) -> dict[str, Any]:
    """The text fields of a GROUNDED answer, rendered; `answer_template`
    keeps the original placeholders for provenance/highlighting."""

    def render(text: str) -> str:
        return render_facts(text, facts)

    return {
        "answer": render(answer.answer),
        "answer_template": answer.answer,
        "rationale": render(answer.rationale) if answer.rationale is not None else None,
        "recommendations": tuple(
            rec.model_copy(update={"title": render(rec.title), "actions": tuple(map(render, rec.actions))})
            for rec in answer.recommendations
        ),
        "limitations": tuple(map(render, answer.limitations)),
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

    `answer`, `rationale`, `recommendations` and `limitations` are the
    grounded generator text with every `{{fact:<id>}}` already rendered by
    `render_facts` — clients display them as-is. `answer_template` keeps the
    unrendered answer and `facts` exactly the referenced system facts
    (canonical values) for provenance/highlighting. `signals`, `what_if` and
    `basis` come from authoritative sources; `evidence` from trusted chunk
    metadata. Nothing here is persisted (decision D4).
    """

    status: AnswerStatus
    intent: RagIntent
    mode: RagMode
    crop_season_id: str
    answer: str | None
    answer_template: str | None = None
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
        if self.status == "generated" and self.answer_template is None:
            raise ValueError("a generated answer keeps its template")
        return self

"""Grounding: a schema-valid generated answer is accepted only if every
citation is real, every expert claim is cited, and it does not invent a
deterministic rule. Fails closed; an ungrounded answer is never returned
or persisted."""

from __future__ import annotations

from collections.abc import Sequence

from .citations import validate_citations
from .context import SeasonRagContext
from .errors import GroundingFailed
from .intents import EVIDENCE_REQUIRED_INTENTS, RagIntent
from .models import EvidenceChunk, GeneratedAnswer


def validate_grounding(
    answer: GeneratedAnswer, *, intent: RagIntent, evidence: Sequence[EvidenceChunk], context: SeasonRagContext,
) -> GeneratedAnswer:
    validate_citations(answer.evidence_refs, evidence)
    for rec in answer.recommendations:
        validate_citations(rec.evidence_refs, evidence)
        if not rec.evidence_refs:
            raise GroundingFailed(f"recommendation without evidence: {rec.title!r}")
        if rec.rule_code is not None and rec.rule_code not in context.signal_rule_codes:
            raise GroundingFailed(f"recommendation names a rule the season does not have: {rec.rule_code}")
    if answer.status == "generated" and intent in EVIDENCE_REQUIRED_INTENTS and not answer.all_refs():
        raise GroundingFailed(f"intent '{intent}' requires cited evidence")
    return answer

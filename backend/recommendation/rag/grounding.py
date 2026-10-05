"""Grounding: the gate between UNTRUSTED generator output and a trusted result.

A schema-valid `GeneratedAnswer` is accepted only if, in this order:
  1. every document citation names a chunk retrieved for this request;
  2. its prose holds no raw number, link or malformed placeholder (prose.py),
     and every fact reference and `{{fact:..}}` placeholder names a system
     fact of this request's catalog;
  3. it obeys the intent policy: recommendations only for action-producing
     intents, each cited, none inventing a deterministic rule; documents
     cited when the intent needs them; COMPARE/WHAT_IF answers reference
     the comparison/what-if facts they are about.
Fails closed; an ungrounded answer is never returned or persisted.
"""

from __future__ import annotations

from collections.abc import Sequence

from .citations import validate_citations
from .claims import validate_fact_refs, validate_quantitative_claims
from .errors import GroundingFailed
from .facts import COMPARISON_KINDS
from .intents import INTENT_POLICIES, RagIntent
from .models import EvidenceChunk, FactKind, GeneratedAnswer, GroundedFact
from .prose import validate_generated_prose

#: Facts an answer of this intent must reference to be about the right thing.
_REQUIRED_FACT_KINDS: dict[RagIntent, frozenset[FactKind]] = {
    RagIntent.COMPARE: COMPARISON_KINDS,
    RagIntent.WHAT_IF: frozenset({FactKind.WHAT_IF}),
}


def validate_grounding(
    answer: GeneratedAnswer, *, intent: RagIntent, evidence: Sequence[EvidenceChunk],
    facts: Sequence[GroundedFact], rule_codes: frozenset[str],
) -> GeneratedAnswer:
    # 1. knowledge evidence
    validate_citations(answer.evidence_refs, evidence)
    for rec in answer.recommendations:
        validate_citations(rec.evidence_refs, evidence)

    # 2. generated prose, system facts and numbers
    validate_generated_prose(answer.texts())
    catalog = {fact.fact_id: fact for fact in facts}
    validate_fact_refs(answer.fact_refs, catalog)
    for rec in answer.recommendations:
        validate_fact_refs(rec.fact_refs, catalog)
    declared = {ref.fact_id for ref in answer.all_fact_refs()}
    validate_quantitative_claims(answer.texts(), declared, catalog)

    # 3. intent policy
    policy = INTENT_POLICIES[intent]
    if answer.recommendations and not policy.may_recommend:
        raise GroundingFailed(f"intent '{intent}' cannot produce recommendations")
    for rec in answer.recommendations:
        if not rec.evidence_refs:
            raise GroundingFailed(f"recommendation without evidence: {rec.title!r}")
        if rec.rule_code is not None and rec.rule_code not in rule_codes:
            raise GroundingFailed(f"recommendation names a rule the season does not have: {rec.rule_code}")
    if answer.status == "generated":
        if policy.needs_documents and not answer.all_evidence_refs():
            raise GroundingFailed(f"intent '{intent}' requires cited evidence")
        required = _REQUIRED_FACT_KINDS.get(intent)
        if required and not any(catalog[fact_id].kind in required for fact_id in declared):
            raise GroundingFailed(f"intent '{intent}' must reference a {'/'.join(sorted(required))} fact")
    return answer

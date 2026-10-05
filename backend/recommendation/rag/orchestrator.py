"""RAG orchestration for one question about one crop season.

Same shape as `service.RecommendationService`: long-lived collaborators
(retriever, generator, what-if) are injected once; per-request, caller-bound
ones (the scope resolver, the facts source) are passed to each call. No I/O of
its own, no provider logic, no persistence (decision D4).

Assembly boundary:
  UNTRUSTED generator output -> schema validation -> citation validation
  -> fact-reference validation -> grounding -> trusted fact rendering
  -> TRUSTED RagAnswerResult
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from pydantic import ValidationError

from .answers import (
    INSUFFICIENT_MESSAGES,
    NEEDS_CLARIFICATION_MESSAGE,
    AnswerBasis,
    GenerationInput,
    InsufficientReason,
    RagAnswerResult,
    render_answer,
)
from .citations import resolve_citations
from .context import DeterministicSignal, SeasonRagContext, build_season_context
from .contracts import AnswerGenerator, KnowledgeRetriever, SeasonFactsSource, SeasonScopeResolver, WhatIfSimulator
from .errors import GenerationUnavailable, InvalidGeneratedSchema, RagAccessDenied, RagError, RetrievalUnavailable
from .facts import assert_fact_scope, build_fact_catalog, has_comparison_basis, usable_facts
from .grounding import validate_grounding
from .intents import INTENT_POLICIES, FactUsage, GenerationCapability, RagIntent, allowed_fact_usage, required_access
from .models import GeneratedAnswer, GroundedFact, InformationalAnswer, RagQuestionRequest, WhatIfResult
from .retrieval import assert_tenant_isolation, build_retrieval_query
from .what_if import ensure_supported

_T = TypeVar("_T")


def _adapter_call(call: Callable[[], _T], unavailable: type[RagError]) -> _T:
    """A typed RAG error passes through; any other adapter failure becomes
    `unavailable` (fail closed, cause chained for the log)."""
    try:
        return call()
    except RagError:
        raise
    except Exception as exc:  # noqa: BLE001 - adapter boundary
        raise unavailable(str(exc) or type(exc).__name__) from exc


class RagOrchestrator:
    def __init__(self, *, retriever: KnowledgeRetriever, generator: AnswerGenerator, what_if: WhatIfSimulator) -> None:
        self._retriever = retriever
        self._generator = generator
        self._what_if = what_if

    def answer(
        self, request: RagQuestionRequest, *, scope_resolver: SeasonScopeResolver, facts: SeasonFactsSource,
    ) -> RagAnswerResult:
        intent = request.intent or RagIntent.UNKNOWN
        policy = INTENT_POLICIES[intent]
        # Authorization first: nothing is read, simulated, retrieved or
        # generated for a caller below the capability's Core V1 access level.
        scope = scope_resolver.resolve(request.crop_season_id, required_access(intent, request.mode))
        if scope.crop_season_id != request.crop_season_id:
            raise RagAccessDenied("scope resolver returned a different season")

        capability = policy.capability
        if capability is None:
            # UNKNOWN: never a backdoor to RECOMMEND/WHAT_IF — no context, no model.
            return RagAnswerResult(status="needs_clarification", intent=intent, mode=request.mode,
                                   crop_season_id=scope.crop_season_id, answer=NEEDS_CLARIFICATION_MESSAGE)
        if request.hypothetical is not None:
            ensure_supported(request.hypothetical)  # before any read or Carbon call

        context = build_season_context(scope, facts, mode=request.mode)
        what_if = self._what_if.simulate(scope, request.hypothetical) if request.hypothetical is not None else None
        catalog = build_fact_catalog(context, what_if)
        assert_fact_scope(catalog, scope, context)
        # What this capability may see, reference and render; INFORMATIONAL
        # never handles ACTION_CONTEXT (stored recommendations, what-if impact).
        usable = usable_facts(catalog, capability)
        signals = context.signals if FactUsage.ACTION_CONTEXT in allowed_fact_usage(capability) else ()

        if intent is RagIntent.COMPARE and not has_comparison_basis(usable):
            return _insufficient(request, intent, context, signals, what_if, "no_comparison_basis")

        query = build_retrieval_query(request.question, intent, scope)
        evidence = tuple(_adapter_call(lambda: self._retriever.retrieve(query), RetrievalUnavailable))
        assert_tenant_isolation(evidence, scope)
        if not evidence and policy.needs_documents:
            return _insufficient(request, intent, context, signals, what_if, "no_evidence_retrieved")

        raw = _adapter_call(
            lambda: self._generator.generate(GenerationInput(
                question=request.question, intent=intent, capability=capability, facts=usable, evidence=evidence,
            )),
            GenerationUnavailable,
        )
        generated = validate_grounding(
            _parse(raw, capability), intent=intent, evidence=evidence, facts=catalog, rule_codes=context.signal_rule_codes,
        )
        # Rendering only ever sees a grounded answer and the facts this
        # capability may use (grounding already rejected any other reference).
        rendered = render_answer(generated, {fact.fact_id: fact for fact in usable})

        if generated.status == "insufficient_evidence":
            return _insufficient(request, intent, context, signals, what_if, "generator_declined",
                                 answer=rendered["answer"], answer_template=rendered["answer_template"],
                                 facts=_referenced(generated, usable))
        return RagAnswerResult(
            status="generated", intent=intent, mode=request.mode, crop_season_id=scope.crop_season_id,
            **rendered, evidence=resolve_citations(generated.all_evidence_refs(), evidence),
            facts=_referenced(generated, usable), confidence=generated.confidence,
            signals=signals, what_if=what_if, basis=_basis(context, signals),
        )


def _insufficient(
    request: RagQuestionRequest, intent: RagIntent, context: SeasonRagContext,
    signals: tuple[DeterministicSignal, ...], what_if: WhatIfResult | None, reason: InsufficientReason, *,
    answer: str | None = None, answer_template: str | None = None, facts: tuple[GroundedFact, ...] = (),
) -> RagAnswerResult:
    # Deterministic facts stay valid without evidence: the signals this
    # capability may carry and the engine's what-if numbers are still returned.
    return RagAnswerResult(
        status="insufficient_evidence", intent=intent, mode=request.mode, crop_season_id=context.crop_season_id,
        answer=answer or INSUFFICIENT_MESSAGES[reason], answer_template=answer_template,
        insufficient_reason=reason, facts=facts,
        signals=signals, what_if=what_if, basis=_basis(context, signals),
    )


def _parse(raw: object, capability: GenerationCapability) -> GeneratedAnswer:
    """Validate against the capability's own schema: INFORMATIONAL output has
    no recommendation slot, so emitting one is a schema error. It is then
    lifted to the uniform `GeneratedAnswer` (no recommendations) for grounding."""
    try:
        if capability is GenerationCapability.INFORMATIONAL:
            return GeneratedAnswer.model_validate(InformationalAnswer.model_validate(raw).model_dump())
        return GeneratedAnswer.model_validate(raw)
    except ValidationError as exc:
        raise InvalidGeneratedSchema(f"generator output failed schema validation ({exc.error_count()} errors)") from exc


def _referenced(answer: GeneratedAnswer, catalog: tuple[GroundedFact, ...]) -> tuple[GroundedFact, ...]:
    """The catalog's own fact objects (trusted values), in catalog order."""
    ids = {ref.fact_id for ref in answer.all_fact_refs()}
    return tuple(fact for fact in catalog if fact.fact_id in ids)


def _basis(context: SeasonRagContext, signals: tuple[DeterministicSignal, ...]) -> AnswerBasis:
    carbon = context.carbon
    return AnswerBasis(
        carbon_calculation_id=carbon.calculation_id if carbon else None,
        carbon_input_hash=carbon.input_hash if carbon else None,
        ef_config_version=carbon.ef_config_version if carbon else None,
        signal_rule_codes=tuple(signal.rule_code for signal in signals),
    )

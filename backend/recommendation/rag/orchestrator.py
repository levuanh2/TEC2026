"""RAG orchestration for one question about one crop season.

Same shape as `service.RecommendationService`: long-lived collaborators
(retriever, generator, what-if) are injected once; per-request, caller-bound
ones (the scope resolver, the facts source) are passed to each call. No I/O of
its own, no provider logic, no persistence (decision D4).

Assembly boundary:
  UNTRUSTED generator output -> schema validation -> citation validation
  -> fact-reference validation -> grounding -> TRUSTED RagAnswerResult
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
)
from .citations import resolve_citations
from .context import SeasonRagContext, build_season_context
from .contracts import AnswerGenerator, KnowledgeRetriever, SeasonFactsSource, SeasonScopeResolver, WhatIfSimulator
from .errors import GenerationUnavailable, InvalidGeneratedSchema, RagAccessDenied, RagError, RetrievalUnavailable
from .facts import assert_fact_scope, build_fact_catalog, has_comparison_basis
from .grounding import validate_grounding
from .intents import INTENT_POLICIES, RagIntent, required_access
from .models import GeneratedAnswer, GroundedFact, RagQuestionRequest, WhatIfResult
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
        # Authorization first: nothing is read, simulated, retrieved or
        # generated for a caller below the intent's Core V1 access level.
        scope = scope_resolver.resolve(request.crop_season_id, required_access(intent, request.mode))
        if scope.crop_season_id != request.crop_season_id:
            raise RagAccessDenied("scope resolver returned a different season")

        if intent is RagIntent.UNKNOWN:
            # Never a backdoor to RECOMMEND/WHAT_IF: no context, no model.
            return RagAnswerResult(status="needs_clarification", intent=intent, mode=request.mode,
                                   crop_season_id=scope.crop_season_id, answer=NEEDS_CLARIFICATION_MESSAGE)
        if request.hypothetical is not None:
            ensure_supported(request.hypothetical)  # before any read or Carbon call

        context = build_season_context(scope, facts, mode=request.mode)
        what_if = self._what_if.simulate(scope, request.hypothetical) if request.hypothetical is not None else None
        catalog = build_fact_catalog(context, what_if)
        assert_fact_scope(catalog, scope, context)

        if intent is RagIntent.COMPARE and not has_comparison_basis(catalog):
            return _insufficient(request, intent, context, what_if, "no_comparison_basis")

        query = build_retrieval_query(request.question, intent, scope)
        evidence = tuple(_adapter_call(lambda: self._retriever.retrieve(query), RetrievalUnavailable))
        assert_tenant_isolation(evidence, scope)
        if not evidence and INTENT_POLICIES[intent].needs_documents:
            return _insufficient(request, intent, context, what_if, "no_evidence_retrieved")

        raw = _adapter_call(
            lambda: self._generator.generate(GenerationInput(
                question=request.question, intent=intent, facts=catalog, evidence=evidence,
            )),
            GenerationUnavailable,
        )
        generated = validate_grounding(
            _parse(raw), intent=intent, evidence=evidence, facts=catalog, rule_codes=context.signal_rule_codes,
        )

        if generated.status == "insufficient_evidence":
            return _insufficient(request, intent, context, what_if, "generator_declined",
                                 answer=generated.answer, facts=_referenced(generated, catalog))
        return RagAnswerResult(
            status="generated", intent=intent, mode=request.mode, crop_season_id=scope.crop_season_id,
            answer=generated.answer, rationale=generated.rationale, recommendations=generated.recommendations,
            evidence=resolve_citations(generated.all_evidence_refs(), evidence),
            facts=_referenced(generated, catalog), limitations=generated.limitations,
            confidence=generated.confidence, signals=context.signals, what_if=what_if, basis=_basis(context),
        )


def _insufficient(
    request: RagQuestionRequest, intent: RagIntent, context: SeasonRagContext, what_if: WhatIfResult | None,
    reason: InsufficientReason, *, answer: str | None = None, facts: tuple[GroundedFact, ...] = (),
) -> RagAnswerResult:
    # Deterministic facts stay valid without evidence: signals and the
    # engine's what-if numbers are still returned.
    return RagAnswerResult(
        status="insufficient_evidence", intent=intent, mode=request.mode, crop_season_id=context.crop_season_id,
        answer=answer or INSUFFICIENT_MESSAGES[reason], insufficient_reason=reason, facts=facts,
        signals=context.signals, what_if=what_if, basis=_basis(context),
    )


def _parse(raw: object) -> GeneratedAnswer:
    try:
        return GeneratedAnswer.model_validate(raw)
    except ValidationError as exc:
        raise InvalidGeneratedSchema(f"generator output failed schema validation ({exc.error_count()} errors)") from exc


def _referenced(answer: GeneratedAnswer, catalog: tuple[GroundedFact, ...]) -> tuple[GroundedFact, ...]:
    """The catalog's own fact objects (trusted values), in catalog order."""
    ids = {ref.fact_id for ref in answer.all_fact_refs()}
    return tuple(fact for fact in catalog if fact.fact_id in ids)


def _basis(context: SeasonRagContext) -> AnswerBasis:
    carbon = context.carbon
    return AnswerBasis(
        carbon_calculation_id=carbon.calculation_id if carbon else None,
        carbon_input_hash=carbon.input_hash if carbon else None,
        ef_config_version=carbon.ef_config_version if carbon else None,
        signal_rule_codes=tuple(signal.rule_code for signal in context.signals),
    )

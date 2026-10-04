"""RAG orchestration for one question about one crop season.

Same shape as `service.RecommendationService`: long-lived collaborators
(retriever, generator, what-if) are injected once; per-request, caller-bound
ones (the access gate, the facts source) are passed to each call. No I/O of
its own, no provider logic, no persistence.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from pydantic import ValidationError

from .answers import AnswerBasis, GenerationInput, InsufficientReason, RagAnswerResult
from .citations import resolve_citations
from .context import SeasonRagContext, build_season_context
from .contracts import AnswerGenerator, KnowledgeRetriever, SeasonAccessGate, SeasonFactsSource, WhatIfSimulator
from .errors import (
    GenerationUnavailable,
    InvalidGeneratedSchema,
    RagAccessDenied,
    RagError,
    RetrievalUnavailable,
    UnsupportedHypothetical,
)
from .grounding import validate_grounding
from .intents import EVIDENCE_REQUIRED_INTENTS, RagIntent, required_access
from .models import AuthorizedSeasonScope, GeneratedAnswer, RagQuestionRequest, WhatIfResult
from .retrieval import assert_tenant_isolation, build_retrieval_query

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
    def __init__(
        self, *, retriever: KnowledgeRetriever, generator: AnswerGenerator, what_if: WhatIfSimulator | None = None,
    ) -> None:
        self._retriever = retriever
        self._generator = generator
        self._what_if = what_if

    def answer(
        self, request: RagQuestionRequest, *, access_gate: SeasonAccessGate, facts: SeasonFactsSource,
    ) -> RagAnswerResult:
        intent = request.intent or RagIntent.UNKNOWN
        # Authorization first: nothing is read, retrieved or generated for a
        # caller who may not see this season.
        scope = access_gate.authorize(request.crop_season_id, required_access(intent, request.mode))
        if scope.crop_season_id != request.crop_season_id:
            raise RagAccessDenied("access gate returned a different season")

        context = build_season_context(scope, facts, mode=request.mode)
        what_if = self._simulate(request, scope) if intent is RagIntent.WHAT_IF else None

        query = build_retrieval_query(request.question, intent, scope)
        evidence = tuple(_adapter_call(lambda: self._retriever.retrieve(query), RetrievalUnavailable))
        assert_tenant_isolation(evidence, scope)

        if not evidence and intent in EVIDENCE_REQUIRED_INTENTS:
            return self._insufficient(request, intent, context, what_if, "no_evidence_retrieved")

        raw = _adapter_call(
            lambda: self._generator.generate(GenerationInput(
                question=request.question, intent=intent, context=context, evidence=evidence, what_if=what_if,
            )),
            GenerationUnavailable,
        )
        generated = validate_grounding(_parse(raw), intent=intent, evidence=evidence, context=context)

        if generated.status == "insufficient_evidence":
            return self._insufficient(request, intent, context, what_if, "generator_declined", generated.answer)
        return RagAnswerResult(
            status="generated", intent=intent, mode=request.mode, crop_season_id=scope.crop_season_id,
            answer=generated.answer, rationale=generated.rationale, recommendations=generated.recommendations,
            evidence=resolve_citations(generated.all_refs(), evidence), limitations=generated.limitations,
            confidence=generated.confidence, signals=context.signals, what_if=what_if, basis=_basis(context),
        )

    def _simulate(self, request: RagQuestionRequest, scope: AuthorizedSeasonScope) -> WhatIfResult:
        if self._what_if is None or request.hypothetical is None:
            raise UnsupportedHypothetical("no what-if simulator is configured")
        return self._what_if.simulate(scope, request.hypothetical)

    @staticmethod
    def _insufficient(
        request: RagQuestionRequest, intent: RagIntent, context: SeasonRagContext,
        what_if: WhatIfResult | None, reason: InsufficientReason, answer: str | None = None,
    ) -> RagAnswerResult:
        # Deterministic facts stay valid without evidence: signals and the
        # engine's what-if numbers are still returned.
        return RagAnswerResult(
            status="insufficient_evidence", intent=intent, mode=request.mode,
            crop_season_id=context.crop_season_id, answer=answer, insufficient_reason=reason,
            signals=context.signals, what_if=what_if, basis=_basis(context),
        )


def _parse(raw: object) -> GeneratedAnswer:
    try:
        return GeneratedAnswer.model_validate(raw)
    except ValidationError as exc:
        raise InvalidGeneratedSchema(f"generator output failed schema validation ({exc.error_count()} errors)") from exc


def _basis(context: SeasonRagContext) -> AnswerBasis:
    carbon = context.carbon
    return AnswerBasis(
        carbon_calculation_id=carbon.calculation_id if carbon else None,
        carbon_input_hash=carbon.input_hash if carbon else None,
        ef_config_version=carbon.ef_config_version if carbon else None,
        signal_rule_codes=tuple(signal.rule_code for signal in context.signals),
    )

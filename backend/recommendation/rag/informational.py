"""D8 closure, strategy B: READ-tier answers are composed by trusted server code.

D8 (docs/rag/RAG_V1_ARCHITECTURE.md §11): an INFORMATIONAL answer has no recommendation slot,
but free text written by a model can still phrase advice ("Bạn nên rút nước định kỳ."), and no
keyword list can be a security boundary against that. Strategy B removes the free text instead
of trying to detect it: an INFORMATIONAL generation is never sent to a model. Its answer is
assembled here, from fixed Vietnamese sentences that only DESCRIBE, plus `{{fact:<id>}}`
placeholders and citations of retrieved chunks. The output then goes through the same schema,
citation, fact-reference, prose and intent-policy gates as any generator output, and the
trusted renderer substitutes the values. There is no path by which retrieved text, the
question or a model can add a sentence.

`CapabilityRoutedGenerator` is the only generator a composition root may hand to
`RagOrchestrator`: INFORMATIONAL -> `TrustedInformationalComposer` (always), ACTION_PRODUCING
-> the injected provider adapter, which Core V1 only reaches with WRITE authority (D1).
`test_rag_architecture.py` enforces both.

Known, accepted limitation: the answer does not paraphrase the question. A model that writes
READ-tier prose needs strategy C (a semantic policy guard with its own evaluation set).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .answers import GenerationInput
from .contracts import AnswerGenerator
from .errors import GenerationUnavailable
from .intents import GenerationCapability, RagIntent
from .models import EvidenceChunk, FactKind, GroundedFact

#: How many retrieved chunks an informational answer cites (the panel lists them).
MAX_CITED_CHUNKS = 3
#: How many comparison seasons/benchmarks a COMPARE answer names.
MAX_COMPARISONS = 3

LIMITATION_SYSTEM_COMPOSED = (
    "Câu trả lời được hệ thống soạn từ dữ liệu đã ghi nhận và tài liệu đã duyệt; đây không phải lời khuyên canh tác."
)
LIMITATION_NO_EVIDENCE = "Chưa có đoạn tài liệu đã duyệt nào khớp với câu hỏi này."
LIMITATION_NO_CARBON = "Vụ này chưa có kết quả tính phát thải đã lưu."

_COMPLETENESS_LABELS = {
    "water": "lượng nước tưới",
    "fertilizer": "phân bón",
    "cost": "chi phí",
    "carbon": "kết quả tính phát thải",
}


def _p(fact_id: str) -> str:
    return "{{fact:" + fact_id + "}}"


class _Answer:
    def __init__(self, facts: Sequence[GroundedFact]) -> None:
        self._facts = {fact.fact_id: fact for fact in facts}
        self.sentences: list[str] = []
        self.fact_refs: list[str] = []
        self.limitations: list[str] = [LIMITATION_SYSTEM_COMPOSED]

    def fact(self, fact_id: str) -> GroundedFact | None:
        return self._facts.get(fact_id)

    def has_value(self, fact_id: str) -> bool:
        fact = self._facts.get(fact_id)
        return fact is not None and fact.value is not None

    def say(self, text: str, *fact_ids: str) -> None:
        self.sentences.append(text)
        for fact_id in fact_ids:
            if fact_id not in self.fact_refs:
                self.fact_refs.append(fact_id)

    def facts_of(self, kind: FactKind) -> list[GroundedFact]:
        return [fact for fact in self._facts.values() if fact.kind is kind]


def _cite(answer: _Answer, evidence: Sequence[EvidenceChunk]) -> list[dict[str, str]]:
    refs = [{"source_id": c.source_id, "chunk_id": c.chunk_id} for c in evidence[:MAX_CITED_CHUNKS]]
    if refs:
        answer.say("Các đoạn tài liệu đã duyệt liên quan đến câu hỏi được dẫn ở phần nguồn bên dưới.")
    else:
        answer.limitations.append(LIMITATION_NO_EVIDENCE)
    return refs


#: Fixed Vietnamese wording of the `crop_status` enum (baseline migration); an unknown
#: value falls back to the placeholder so the trusted renderer shows it verbatim.
_SEASON_STATUS_TEXT = {
    "planned": "Vụ đang ở trạng thái kế hoạch, chưa bắt đầu canh tác.",
    "active": "Vụ đang canh tác.",
    "harvested": "Vụ đã thu hoạch.",
    "closed": "Vụ đã kết thúc.",
    "cancelled": "Vụ đã bị huỷ.",
}


def _explain(answer: _Answer) -> None:
    if answer.has_value("current.season.status"):
        status = answer.fact("current.season.status").value  # type: ignore[union-attr]
        answer.say(_SEASON_STATUS_TEXT.get(str(status), f"Trạng thái ghi nhận của vụ: {_p('current.season.status')}."),
                   "current.season.status")
    if answer.has_value("current.season.ipcc_water_regime"):
        answer.say(f"Chế độ nước ghi nhận theo phương pháp luận: {_p('current.season.ipcc_water_regime')}.",
                   "current.season.ipcc_water_regime")
    if answer.has_value("current.carbon.total_co2e_kg"):
        answer.say(f"Tổng phát thải khí nhà kính đã tính cho vụ: {_p('current.carbon.total_co2e_kg')}.",
                   "current.carbon.total_co2e_kg")
    else:
        answer.limitations.append(LIMITATION_NO_CARBON)
    if answer.has_value("current.metrics.co2e_per_kg"):
        answer.say(f"Cường độ phát thải trên sản lượng: {_p('current.metrics.co2e_per_kg')}.",
                   "current.metrics.co2e_per_kg")
    if answer.has_value("current.metrics.yield_kg"):
        answer.say(f"Sản lượng đã ghi nhận: {_p('current.metrics.yield_kg')}.", "current.metrics.yield_kg")
    if not answer.sentences:
        answer.say("Vụ này chưa có dữ liệu đã ghi nhận đủ để mô tả.")


def _data_gap(answer: _Answer) -> None:
    if answer.fact("current.readiness.can_calculate") is not None:
        if answer.fact("current.readiness.can_calculate").value is True:  # type: ignore[union-attr]
            answer.say("Hệ thống đã có đủ dữ liệu đầu vào bắt buộc để tính phát thải cho vụ này.",
                       "current.readiness.can_calculate")
        else:
            answer.say("Hệ thống chưa thể tính phát thải cho vụ này vì còn thiếu dữ liệu đầu vào.",
                       "current.readiness.can_calculate")
    for fact in answer.facts_of(FactKind.CARBON_READINESS):
        if fact.fact_id.startswith("current.readiness.missing.") and fact.value is not None:
            # Carbon readiness labels are whole phrases ("Thiếu diện tích thửa", "Chưa ghi
            # sản lượng thu hoạch"); a "Còn thiếu:" prefix would read "Còn thiếu: Thiếu ...".
            answer.say(f"{_p(fact.fact_id)}.", fact.fact_id)
    for name, label in _COMPLETENESS_LABELS.items():
        fact_id = f"current.completeness.{name}"
        fact = answer.fact(fact_id)
        if fact is None:
            continue
        if fact.value is False:
            answer.say(f"Dữ liệu {label} của vụ chưa đầy đủ.", fact_id)
        elif fact.value is None:
            answer.say(f"Chưa xác định được mức đầy đủ của dữ liệu {label}.", fact_id)
    if not answer.sentences:
        answer.say("Hệ thống không ghi nhận dữ liệu còn thiếu cho vụ này.")


def _compare(answer: _Answer) -> None:
    if answer.has_value("current.metrics.co2e_per_kg"):
        answer.say(f"Cường độ phát thải trên sản lượng của vụ này: {_p('current.metrics.co2e_per_kg')}.",
                   "current.metrics.co2e_per_kg")
    named = 0
    for fact in answer.facts_of(FactKind.COMPARISON_SEASON):
        if named < MAX_COMPARISONS and fact.fact_id.endswith(".metrics.co2e_per_kg"):
            answer.say(f"Một vụ đối chiếu bạn được xem có cường độ phát thải trên sản lượng: {_p(fact.fact_id)}.",
                       fact.fact_id)
            named += 1
    for fact in answer.facts_of(FactKind.BENCHMARK):
        if named < MAX_COMPARISONS:
            answer.say(f"Mức tham chiếu đã công bố: {_p(fact.fact_id)}.", fact.fact_id)
            named += 1
    if not named:
        # A comparison basis exists (the orchestrator checked) but has no comparable value:
        # still reference one comparison fact so the answer is about the comparison.
        basis = (answer.facts_of(FactKind.COMPARISON_SEASON) + answer.facts_of(FactKind.BENCHMARK))[:1]
        for fact in basis:
            answer.say("Vụ đối chiếu chưa có đủ số liệu để đặt cạnh vụ này.", fact.fact_id)
    answer.limitations.append("Hệ thống chỉ đặt các số liệu cạnh nhau, không tự kết luận vụ nào tốt hơn.")


_COMPOSERS = {
    RagIntent.EXPLAIN: _explain,
    RagIntent.DATA_GAP: _data_gap,
    RagIntent.COMPARE: _compare,
    RagIntent.EVIDENCE: lambda answer: None,
}


class TrustedInformationalComposer:
    """`AnswerGenerator` for INFORMATIONAL capability only; no model, no I/O.

    Reads only `request.facts` (already restricted to INFORMATIONAL_SAFE facts by
    `GenerationInput`) and the retrieved chunks' ids. The question text and chunk content
    are never copied into the answer.
    """

    def generate(self, request: GenerationInput) -> Mapping[str, Any]:
        if request.capability is not GenerationCapability.INFORMATIONAL:
            raise GenerationUnavailable("the trusted composer only answers informational intents")
        compose = _COMPOSERS.get(request.intent)
        if compose is None:
            raise GenerationUnavailable(f"no informational composition for intent {request.intent}")
        answer = _Answer(request.facts)
        compose(answer)
        evidence_refs = _cite(answer, request.evidence)
        if request.intent is RagIntent.EVIDENCE and not evidence_refs:
            return {"status": "insufficient_evidence", "answer": LIMITATION_NO_EVIDENCE,
                    "limitations": [LIMITATION_SYSTEM_COMPOSED]}
        return {
            "status": "generated",
            "answer": " ".join(answer.sentences),
            "evidence_refs": evidence_refs,
            "fact_refs": [{"fact_id": fact_id} for fact_id in answer.fact_refs],
            "limitations": answer.limitations,
            "confidence": None,
        }


class CapabilityRoutedGenerator:
    """The only generator a composition root passes to `RagOrchestrator`.

    INFORMATIONAL always goes to the trusted composer; a provider adapter is reachable only
    for ACTION_PRODUCING, i.e. Core V1 WRITE authority (D1). Without one, action intents are
    `GenerationUnavailable` (503), never silently answered by something else.
    """

    def __init__(self, *, action: AnswerGenerator | None = None, read: AnswerGenerator | None = None) -> None:
        self._informational = TrustedInformationalComposer()
        self._action = action
        #: D8 strategy C (EXPERIMENTAL, off unless a composition root passes it): a grounded
        #: READ generator that must raise `GenerationUnavailable` for anything it cannot prove
        #: safe and grounded; the trusted composer (strategy B) then answers instead.
        self._read = read
        self.answered_by: str | None = None
        self.fallback_reason: str | None = None

    @property
    def action_configured(self) -> bool:
        return self._action is not None

    def generate(self, request: GenerationInput) -> Mapping[str, Any]:
        if request.capability is GenerationCapability.INFORMATIONAL:
            if self._read is not None:
                try:
                    answer = self._read.generate(request)
                    self.answered_by = "model_generated"
                    return answer
                except GenerationUnavailable as exc:
                    # Never an error and never a partial model answer: the deterministic B answer,
                    # labelled system-composed, with the reason recorded for provenance.
                    self.fallback_reason = str(exc) or "d8c_unavailable"
            self.answered_by = "system_composed"
            return self._informational.generate(request)
        self.answered_by = "model_generated"
        if self._action is None:
            raise GenerationUnavailable("no action generator is configured")
        return self._action.generate(request)

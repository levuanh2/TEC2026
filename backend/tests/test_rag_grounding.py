"""Retrieval tenant filter, tenant-isolation backstop, document citations,
system-fact references and grounding policy — the pure policy pieces of RAG V1."""

from __future__ import annotations

import pytest

from recommendation.rag import (
    CitationMismatch,
    EvidenceRef,
    FactReferenceMismatch,
    GeneratedAnswer,
    GroundingFailed,
    RagIntent,
    RagMode,
    TenantIsolationViolation,
    assert_tenant_isolation,
    build_fact_catalog,
    build_retrieval_query,
    build_season_context,
    resolve_citations,
    validate_citations,
    validate_grounding,
)
from tests.fixtures.rag_fakes import (
    AWD_RULE,
    FARM_ID,
    ORG_ID,
    OTHER_ORG_ID,
    OTHER_SEASON_ID,
    SEASON_ID,
    FakeFactsSource,
    benchmark_row,
    comparison_row,
    public_chunk,
    scope,
    tenant_chunk,
)

EVIDENCE = (public_chunk("c1"), public_chunk("c2"), public_chunk("x1", source_id="ipcc-2019", title="IPCC 2019"))
INTENSITY = "current.metrics.co2e_per_kg"
BENCHMARK = "benchmark.water-htx-2026"


def _ref(source_id: str = "guide-awd", chunk_id: str = "c1") -> dict:
    return {"source_id": source_id, "chunk_id": chunk_id}


def _fact(fact_id: str = INTENSITY) -> dict:
    return {"fact_id": fact_id}


def _ground(answer: GeneratedAnswer, intent: RagIntent = RagIntent.RECOMMEND, evidence=EVIDENCE, **source):
    context = build_season_context(scope(), FakeFactsSource(calls=[], **source), mode=RagMode.ASK)
    return validate_grounding(answer, intent=intent, evidence=evidence, facts=build_fact_catalog(context),
                              rule_codes=context.signal_rule_codes)


def _answer(**overrides) -> GeneratedAnswer:
    return GeneratedAnswer.model_validate({"status": "generated", "answer": "Nên cân nhắc AWD.",
                                           "evidence_refs": [_ref()], **overrides})


def _rec(**overrides) -> dict:
    return {"title": "Tưới AWD", "actions": ["Rút nước định kỳ"], "evidence_refs": [_ref("guide-awd", "c2")],
            "rule_code": AWD_RULE, **overrides}


# -- retrieval query / isolation ------------------------------------------------

def test_retrieval_query_tenant_filter_is_the_authorized_scope():
    query = build_retrieval_query("Có nên chuyển sang AWD?", RagIntent.RECOMMEND, scope())
    assert (query.tenant.organization_id, query.tenant.farm_id, query.tenant.crop_season_id) == (
        ORG_ID, FARM_ID, SEASON_ID)
    assert query.include_public is True


def test_public_and_own_tenant_evidence_pass_isolation():
    assert_tenant_isolation([public_chunk(), tenant_chunk(), tenant_chunk("t2", farm_id=FARM_ID)], scope())


@pytest.mark.parametrize("chunk", [
    tenant_chunk(organization_id=OTHER_ORG_ID),
    tenant_chunk(farm_id="another-farm-same-htx"),
])
def test_foreign_tenant_evidence_is_a_security_failure(chunk):
    with pytest.raises(TenantIsolationViolation) as exc:
        assert_tenant_isolation([public_chunk(), chunk], scope())
    assert OTHER_ORG_ID not in str(exc.value)


# -- document citations (EvidenceRef) -------------------------------------------

def test_valid_citations_are_accepted():
    validate_citations([EvidenceRef(**_ref()), EvidenceRef(**_ref("ipcc-2019", "x1"))], EVIDENCE)


@pytest.mark.parametrize(("refs", "message"), [
    ([_ref("invented-source", "c1")], "unknown source"),
    ([_ref("guide-awd", "c999")], "unknown chunk"),
    ([_ref("guide-awd", "x1")], "unknown chunk"),          # real chunk id, wrong source
    ([_ref(), _ref()], "duplicate citation"),
])
def test_citation_mismatch_is_rejected(refs, message):
    with pytest.raises(CitationMismatch, match=message):
        validate_citations([EvidenceRef(**ref) for ref in refs], EVIDENCE)


def test_resolved_citations_use_trusted_metadata_in_first_cited_order():
    cited = resolve_citations([EvidenceRef(**_ref("ipcc-2019", "x1")), EvidenceRef(**_ref()),
                               EvidenceRef(**_ref("ipcc-2019", "x1"))], EVIDENCE)
    assert [(c.source_id, c.chunk_id) for c in cited] == [("ipcc-2019", "x1"), ("guide-awd", "c1")]
    assert cited[0].title == "IPCC 2019"
    assert cited[1].url == "https://example.org/guide-awd"


def test_resolving_an_unknown_citation_fails_closed():
    with pytest.raises(CitationMismatch):
        resolve_citations([EvidenceRef(**_ref("nope", "c1"))], EVIDENCE)


# -- system facts (FactRef) ------------------------------------------------------

def test_fact_reference_to_a_catalog_fact_is_accepted():
    answer = _answer(answer="Cường độ là {{fact:%s}}." % INTENSITY, fact_refs=[_fact()], evidence_refs=[])
    assert _ground(answer, RagIntent.EXPLAIN) is answer


@pytest.mark.parametrize(("overrides", "message"), [
    ({"fact_refs": [_fact("current.metrics.invented")]}, "unknown fact"),
    ({"fact_refs": [_fact(), _fact()]}, "duplicate fact reference"),
    ({"answer": "Là {{fact:current.metrics.invented}}.", "fact_refs": []}, "unknown fact"),
    ({"answer": "Là {{fact:%s}}." % INTENSITY, "fact_refs": []}, "not listed in fact_refs"),
    ({"fact_refs": [_fact(f"season.{OTHER_SEASON_ID}.metrics.co2e_per_kg")]}, "unknown fact"),  # not authorized
])
def test_fact_reference_mismatch_is_rejected(overrides, message):
    with pytest.raises(FactReferenceMismatch, match=message):
        _ground(_answer(**{"evidence_refs": [], **overrides}), RagIntent.EXPLAIN)


def test_recommendation_level_fact_refs_are_validated_too():
    rec = _rec(actions=["Giảm {{fact:what_if.awd.delta_co2e_kg}}"], fact_refs=[_fact("what_if.awd.delta_co2e_kg")])
    with pytest.raises(FactReferenceMismatch):  # no what-if ran for this request
        _ground(_answer(recommendations=[rec]))


def test_a_document_citation_cannot_masquerade_as_a_fact():
    with pytest.raises(FactReferenceMismatch):
        _ground(_answer(fact_refs=[_fact("guide-awd")]))
    with pytest.raises(FactReferenceMismatch):
        _ground(_answer(answer="Theo {{fact:c1}}.", fact_refs=[_fact("c1")]))


def test_a_fact_cannot_masquerade_as_a_document_citation():
    with pytest.raises(CitationMismatch):
        _ground(_answer(evidence_refs=[_ref("current.metrics", "co2e_per_kg")]))
    with pytest.raises(CitationMismatch):
        _ground(_answer(evidence_refs=[_ref(INTENSITY, INTENSITY)]))


# -- numeric authority -------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Chuyển sang AWD giảm 18% phát thải.",
    "Tiết kiệm 340.000đ.",
    "Giảm 112 kg CO2e.",
    "Trung bình HTX là 1.8 m3/kg.",       # invented benchmark number
    "Nước/kg của vụ là 2 m3/kg.",         # metric restated by the model
])
def test_business_number_without_a_fact_fails_grounding(text):
    with pytest.raises(GroundingFailed, match="without a system fact"):
        _ground(_answer(answer=text, evidence_refs=[]), RagIntent.EXPLAIN)


def test_business_number_in_a_recommendation_action_fails_grounding():
    with pytest.raises(GroundingFailed, match="without a system fact"):
        _ground(_answer(recommendations=[_rec(actions=["Giảm 20% lượng đạm"])]))


def test_benchmark_number_is_accepted_only_as_a_trusted_fact():
    answer = _answer(answer="Nước/kg so với {{fact:%s}}." % BENCHMARK, evidence_refs=[], fact_refs=[_fact(BENCHMARK)])
    assert _ground(answer, RagIntent.COMPARE, benchmark_rows=[benchmark_row()]) is answer
    with pytest.raises(FactReferenceMismatch):  # same id, but no finalized benchmark exists
        _ground(answer, RagIntent.COMPARE, benchmark_rows=[benchmark_row(status="draft")])


# -- intent policy --------------------------------------------------------------------

def test_grounded_recommendation_is_accepted_unchanged():
    answer = _answer(recommendations=[_rec()])
    assert _ground(answer) is answer


def test_recommendation_without_evidence_is_rejected():
    with pytest.raises(GroundingFailed, match="without evidence"):
        _ground(_answer(recommendations=[_rec(evidence_refs=[])]))


def test_recommendation_with_invented_citation_is_rejected():
    with pytest.raises(CitationMismatch):
        _ground(_answer(recommendations=[_rec(evidence_refs=[_ref("made-up", "c1")])]))


def test_recommendation_cannot_invent_a_deterministic_rule():
    with pytest.raises(GroundingFailed, match="rule the season does not have"):
        _ground(_answer(recommendations=[_rec(rule_code="fertilizer.n_above_benchmark")]))


@pytest.mark.parametrize("intent", [RagIntent.EXPLAIN, RagIntent.COMPARE, RagIntent.EVIDENCE, RagIntent.DATA_GAP,
                                    RagIntent.UNKNOWN])
def test_read_only_intents_cannot_produce_recommendations(intent):
    with pytest.raises(GroundingFailed, match="cannot produce recommendations"):
        _ground(_answer(recommendations=[_rec()]), intent, benchmark_rows=[benchmark_row()])


@pytest.mark.parametrize("intent", [RagIntent.RECOMMEND, RagIntent.EVIDENCE])
def test_document_intents_without_citations_are_rejected(intent):
    with pytest.raises(GroundingFailed, match="requires cited evidence"):
        _ground(_answer(evidence_refs=[]), intent)


@pytest.mark.parametrize("intent", [RagIntent.EXPLAIN, RagIntent.DATA_GAP])
def test_fact_grounded_intents_may_answer_without_documents(intent):
    answer = _answer(evidence_refs=[])
    assert _ground(answer, intent) is answer


def test_compare_must_reference_a_comparison_fact():
    with pytest.raises(GroundingFailed, match="must reference a benchmark/comparison_season fact"):
        _ground(_answer(answer="Cường độ {{fact:%s}}." % INTENSITY, evidence_refs=[], fact_refs=[_fact()]),
                RagIntent.COMPARE, comparison_rows=[comparison_row()])
    other = f"season.{OTHER_SEASON_ID}.metrics.co2e_per_kg"
    ok = _answer(answer="{{fact:%s}} so với {{fact:%s}}." % (INTENSITY, other), evidence_refs=[],
                 fact_refs=[_fact(), _fact(other)])
    assert _ground(ok, RagIntent.COMPARE, comparison_rows=[comparison_row()]) is ok


def test_what_if_must_reference_a_what_if_fact():
    with pytest.raises(GroundingFailed, match="must reference a what_if fact"):
        _ground(_answer(evidence_refs=[]), RagIntent.WHAT_IF)


def test_insufficient_evidence_answer_is_valid_without_citations():
    answer = GeneratedAnswer(status="insufficient_evidence", answer="Chưa đủ tài liệu để trả lời.")
    assert _ground(answer, RagIntent.RECOMMEND, evidence=()) is answer

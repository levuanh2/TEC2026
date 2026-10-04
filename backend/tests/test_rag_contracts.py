"""RAG V1 typed contracts (docs/rag/RAG_V1_DATA_CONTRACT.md): valid shapes are
accepted, everything a client or a model could smuggle in is rejected."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from recommendation.rag import (
    AnswerBasis,
    EvidenceChunk,
    EvidenceRef,
    FactKind,
    FactRef,
    GeneratedAnswer,
    GroundedFact,
    HypotheticalChange,
    RagAnswerResult,
    RagIntent,
    RagMode,
    RagQuestionRequest,
    RetrievalQuery,
    TenantScope,
    WhatIfDimension,
    WhatIfResult,
)
from tests.fixtures.rag_fakes import ORG_ID, SEASON_ID, public_chunk, tenant_chunk

_BASIS = AnswerBasis(carbon_calculation_id=None, carbon_input_hash=None, ef_config_version=None, signal_rule_codes=())
_AWD = {"dimension": "water_regime", "scenario": "awd"}


# -- RagQuestionRequest -------------------------------------------------------

def test_minimal_question_defaults_to_ask_mode_and_unclassified_intent():
    request = RagQuestionRequest(question="  Tại sao vụ này carbon cao?  ", crop_season_id=SEASON_ID)
    assert request.question == "Tại sao vụ này carbon cao?"
    assert request.intent is None
    assert request.mode is RagMode.ASK


def test_intent_and_mode_parse_from_their_wire_values():
    request = RagQuestionRequest.model_validate(
        {"question": "Tôi còn thiếu dữ liệu nào?", "crop_season_id": SEASON_ID, "intent": "data_gap", "mode": "preview"})
    assert request.intent is RagIntent.DATA_GAP
    assert request.mode is RagMode.PREVIEW


@pytest.mark.parametrize("smuggled", [
    {"organization_id": ORG_ID},
    {"role": "cooperative_manager"},
    {"can_write": True},
    {"filter": "organization_id = any"},
    {"table": "carbon_calculations"},
    {"sql": "select 1"},
    {"persist": True},
    {"conversation_id": "c-1"},
])
def test_request_rejects_client_declared_scope_permission_query_or_persistence(smuggled):
    with pytest.raises(ValidationError):
        RagQuestionRequest.model_validate({"question": "q", "crop_season_id": SEASON_ID, **smuggled})


@pytest.mark.parametrize("payload", [
    {"question": "", "crop_season_id": SEASON_ID},
    {"question": "   ", "crop_season_id": SEASON_ID},
    {"question": "x" * 2001, "crop_season_id": SEASON_ID},
    {"question": "q", "crop_season_id": ""},
    {"question": "q", "crop_season_id": SEASON_ID, "intent": "diagnose_disease"},
    {"question": "q", "crop_season_id": SEASON_ID, "mode": "persist"},
])
def test_request_rejects_invalid_values(payload):
    with pytest.raises(ValidationError):
        RagQuestionRequest.model_validate(payload)


def test_what_if_requires_a_hypothetical_and_only_what_if_may_carry_one():
    change = HypotheticalChange.model_validate(_AWD)
    ok = RagQuestionRequest(question="Nếu chuyển sang AWD?", crop_season_id=SEASON_ID,
                            intent=RagIntent.WHAT_IF, hypothetical=change)
    assert ok.hypothetical == change
    with pytest.raises(ValidationError):
        RagQuestionRequest(question="q", crop_season_id=SEASON_ID, intent=RagIntent.WHAT_IF)
    with pytest.raises(ValidationError):
        RagQuestionRequest(question="q", crop_season_id=SEASON_ID, intent=RagIntent.EXPLAIN, hypothetical=change)
    with pytest.raises(ValidationError):
        RagQuestionRequest(question="q", crop_season_id=SEASON_ID, hypothetical=change)


# -- HypotheticalChange (V1 scope) ---------------------------------------------

@pytest.mark.parametrize("scenario", ["awd", "continuous_flooding"])
def test_water_regime_change_accepts_only_engine_scenarios(scenario):
    change = HypotheticalChange(dimension=WhatIfDimension.WATER_REGIME, scenario=scenario)
    assert change.supported is True


@pytest.mark.parametrize("dimension", ["fertilizer_amount", "straw_management", "pesticide", "seed_rate",
                                       "other_activity"])
def test_unsupported_dimensions_are_representable_but_flagged(dimension):
    change = HypotheticalChange.model_validate({"dimension": dimension})
    assert change.supported is False


@pytest.mark.parametrize("payload", [
    {"dimension": "water_regime"},                                # target scenario missing
    {"dimension": "water_regime", "scenario": "as_recorded"},     # the baseline is not a hypothetical
    {"dimension": "water_regime", "scenario": "rainfed"},
    {"dimension": "fertilizer_amount", "scenario": "awd"},        # scenario belongs to water only
    {"dimension": "irrigation_volume"},                           # unknown dimension
    {"dimension": "fertilizer_amount", "percent_change": -10},    # no value slot to compute from
    {**_AWD, "co2e_total_kg": 1.0},
])
def test_hypothetical_rejects_malformed_changes(payload):
    with pytest.raises(ValidationError):
        HypotheticalChange.model_validate(payload)


def test_contracts_are_immutable():
    request = RagQuestionRequest(question="q", crop_season_id=SEASON_ID)
    with pytest.raises(ValidationError):
        request.crop_season_id = "other"  # type: ignore[misc]


# -- system facts ---------------------------------------------------------------

def test_grounded_fact_is_authoritative_by_construction():
    fact = GroundedFact(fact_id="current.metrics.water_per_kg", kind=FactKind.RESOURCE_METRIC, value=None,
                        unit="m3/kg", source="resource_metrics")
    assert fact.authoritative is True and fact.value is None
    with pytest.raises(ValidationError):
        GroundedFact(fact_id="x", kind=FactKind.BENCHMARK, value=1.0, source="llm", authoritative=False)
    with pytest.raises(ValidationError):
        GroundedFact(fact_id="has space", kind=FactKind.BENCHMARK, value=1.0, source="benchmark")


@pytest.mark.parametrize("payload", [
    {"fact_id": "current.metrics.water_per_kg", "value": 0.0},
    {"fact_id": "current.metrics.water_per_kg", "unit": "m3/kg"},
    {"fact_id": "current.metrics.water_per_kg", "authoritative": True},
    {"fact_id": ""},
    {"fact_id": "{{fact:x}}"},
])
def test_fact_ref_is_only_an_id(payload):
    with pytest.raises(ValidationError):
        FactRef.model_validate(payload)


# -- retrieval / evidence -----------------------------------------------------

def test_retrieval_query_requires_a_tenant_scope_and_bounds_top_k():
    query = RetrievalQuery(text="AWD", intent=RagIntent.RECOMMEND, tenant=TenantScope(organization_id=ORG_ID))
    assert query.include_public is True and query.top_k == 8
    with pytest.raises(ValidationError):
        RetrievalQuery.model_validate({"text": "AWD", "intent": "recommend"})
    with pytest.raises(ValidationError):
        RetrievalQuery(text="AWD", intent=RagIntent.RECOMMEND, tenant=TenantScope(organization_id=ORG_ID), top_k=0)
    with pytest.raises(ValidationError):
        RetrievalQuery(text="AWD", intent=RagIntent.RECOMMEND, tenant=TenantScope(organization_id=ORG_ID), top_k=51)


def test_evidence_chunk_carries_stable_identifiers_and_a_hashable_ref():
    chunk = public_chunk()
    assert chunk.ref == EvidenceRef(source_id="guide-awd", chunk_id="c1")
    assert {chunk.ref, EvidenceRef(source_id="guide-awd", chunk_id="c1")} == {chunk.ref}


@pytest.mark.parametrize("missing", ["source_id", "document_id", "chunk_id", "title", "content", "source_type", "visibility"])
def test_evidence_chunk_requires_its_identifiers_and_core_fields(missing):
    payload = public_chunk().model_dump()
    del payload[missing]
    with pytest.raises(ValidationError):
        EvidenceChunk.model_validate(payload)


def test_tenant_evidence_must_name_its_organization_and_public_evidence_none():
    assert tenant_chunk().organization_id == ORG_ID
    with pytest.raises(ValidationError):
        EvidenceChunk.model_validate({**tenant_chunk().model_dump(), "organization_id": None})
    with pytest.raises(ValidationError):
        public_chunk(organization_id=ORG_ID)
    with pytest.raises(ValidationError):
        public_chunk(farm_id="farm")


@pytest.mark.parametrize("url", ["http://example.org/x", "javascript:alert(1)", "example.org"])
def test_evidence_url_is_https_trusted_metadata_only(url):
    with pytest.raises(ValidationError):
        public_chunk(url=url)


# -- generated answer -----------------------------------------------------------

def _generated(**overrides):
    return {"status": "generated", "answer": "Phát thải là {{fact:current.carbon.total_co2e_kg}}.",
            "evidence_refs": [{"source_id": "guide-awd", "chunk_id": "c1"}],
            "fact_refs": [{"fact_id": "current.carbon.total_co2e_kg"}], **overrides}


def test_generated_answer_accepts_the_structured_shape():
    answer = GeneratedAnswer.model_validate(_generated(
        recommendations=[{"title": "Tưới AWD", "actions": ["Rút nước khi mực nước xuống 15 cm"],
                          "evidence_refs": [{"source_id": "guide-awd", "chunk_id": "c1"}],
                          "fact_refs": [{"fact_id": "what_if.awd.delta_co2e_kg"}],
                          "rule_code": "water.awd_from_continuous_flooding"}],
        limitations=["Chưa có dữ liệu nước"], confidence="medium"))
    assert len(answer.all_evidence_refs()) == 2
    assert [r.fact_id for r in answer.all_fact_refs()] == ["current.carbon.total_co2e_kg", "what_if.awd.delta_co2e_kg"]
    assert "Rút nước khi mực nước xuống 15 cm" in answer.texts()


@pytest.mark.parametrize("smuggled", [
    {"co2e_total_kg": 0.0},
    {"co2e_per_kg": 0.1},
    {"water_per_kg": 1.0},
    {"emission_factor": 1.3},
    {"facts": [{"fact_id": "x", "value": 1}]},
    {"url": "https://evil.example"},
    {"permission": "write"},
])
def test_generated_answer_has_no_slot_for_numbers_values_urls_or_permissions(smuggled):
    with pytest.raises(ValidationError):
        GeneratedAnswer.model_validate(_generated(**smuggled))


@pytest.mark.parametrize("payload", [
    "Vụ này phát thải cao.",                       # raw str is not a structured result
    {"status": "maybe", "answer": "x"},
    {"status": "needs_clarification", "answer": "x"},  # trusted-only state
    {"status": "generated"},
    {"status": "generated", "answer": ""},
    {"status": "generated", "answer": "x", "confidence": "certain"},
    {"status": "generated", "answer": "x", "evidence_refs": [{"source_id": "s"}]},
    {"status": "generated", "answer": "x", "fact_refs": [{"fact_id": "a", "value": 2}]},
    {"status": "insufficient_evidence", "answer": "x", "recommendations": [{"title": "t"}]},
])
def test_generated_answer_rejects_malformed_output(payload):
    with pytest.raises(ValidationError):
        GeneratedAnswer.model_validate(payload)


# -- what-if / result -------------------------------------------------------------

def test_what_if_result_is_never_persisted_and_numbers_match_status():
    change = HypotheticalChange.model_validate(_AWD)
    ok = WhatIfResult(change=change, status="available", baseline_total_co2e_kg=10.0,
                      hypothetical_total_co2e_kg=7.0, delta_co2e_kg=3.0)
    assert ok.persisted is False
    with pytest.raises(ValidationError):
        WhatIfResult(change=change, status="available", baseline_total_co2e_kg=10.0, persisted=True)
    with pytest.raises(ValidationError):
        WhatIfResult(change=change, status="available", baseline_total_co2e_kg=10.0)
    with pytest.raises(ValidationError):
        WhatIfResult(change=change, status="unavailable", unavailable_reason="x", delta_co2e_kg=3.0)
    with pytest.raises(ValidationError):
        WhatIfResult(change=change, status="unavailable")


def test_answer_result_state_is_consistent():
    common = {"intent": RagIntent.RECOMMEND, "mode": RagMode.ASK, "crop_season_id": SEASON_ID,
              "answer": None, "basis": _BASIS}
    assert RagAnswerResult(status="insufficient_evidence", insufficient_reason="no_comparison_basis", **common)
    assert RagAnswerResult(status="needs_clarification", **common)
    with pytest.raises(ValidationError):
        RagAnswerResult(status="insufficient_evidence", **common)
    with pytest.raises(ValidationError):
        RagAnswerResult(status="generated", insufficient_reason="generator_declined", **common)
    with pytest.raises(ValidationError):
        RagAnswerResult(status="needs_clarification", recommendations=[{"title": "t"}], **common)

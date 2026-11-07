"""M05 recommendation quality on the RAG Q&A path: every scenario fails gracefully, no
action is ever produced without an existing deterministic rule_code, and a Carbon number is
never shown as an MRV figure. In-memory fakes from test_rag_qa; knowledge rows are TEST
FIXTURES, not approved sources; no network."""
from __future__ import annotations

import json

import pytest

from rag_qa import RagQuestionService
from recommendation.rag import GroundingFailed
from recommendation.rag.answers import INSUFFICIENT_MESSAGES
from recommendation.rag.informational import LIMITATION_NO_CARBON
from tests.fixtures.rag_fakes import AWD_RULE, signal_row
from tests.test_rag_qa import CARBON, GOOD_RECOMMEND, Carbon, Llm, Reader, _ask, gate

NOT_MRV = "chưa đạt yêu cầu MRV"
DATA_RULE = "data.completeness.water"


def _service(llm=None, carbon=None):
    return RagQuestionService(carbon_service=carbon or Carbon(), llm_client=llm, write_gate=gate())


def _knowledge_queries(reader):
    return [call for call in reader.calls if call[0] == "knowledge_matches"]


def _data_task_row():
    return signal_row(DATA_RULE, id="rec-2", type="data_task", title="Bổ sung lượng nước tưới",
                      reason="Một hoặc nhiều lần tưới của vụ này còn thiếu lượng nước.",
                      impact_status="unavailable", impact_unavailable_reason="Đây là gợi ý bổ sung dữ liệu.",
                      co2e_total_kg_before=None, co2e_total_kg_after=None, co2e_total_kg_delta=None,
                      co2e_percent_delta=None)


def _recommend(rule_code, **answer):
    rec = {**GOOD_RECOMMEND["recommendations"][0], "rule_code": rule_code}
    return {**GOOD_RECOMMEND, "recommendations": [rec], **answer}


class _NoCarbon(Carbon):
    """No stored Carbon result and the engine cannot calculate (inputs missing)."""

    def stored(self, season_id, scenario):
        return None

    def readiness(self, season_id):
        return {"can_calculate": False, "blocking_count": 1,
                "missing_inputs": [{"code": "area_ha", "label": "diện tích thửa", "flow": "plot"}]}


class _UnknownFactorSet(Carbon):
    """A stored result whose factor set the engine no longer knows (version unresolved)."""

    def stored(self, season_id, scenario):
        return {**CARBON, "ef_config_version": None}


# -- 1. a season without any recommendation --------------------------------------

def test_recommend_without_a_stored_rule_is_insufficient_before_retrieval_or_model():
    llm, reader = Llm(GOOD_RECOMMEND), Reader(signals=[])
    body = _ask(_service(llm), "recommend", reader=reader)
    assert body["status"] == "insufficient_evidence" and body["insufficient_reason"] == "no_rule_signal"
    assert body["answer"] == INSUFFICIENT_MESSAGES["no_rule_signal"]
    assert body["recommendations"] == [] and body["signals"] == []
    # nothing left the server: no provider call, no knowledge query
    assert llm.requests == [] and _knowledge_queries(reader) == []
    assert body["provenance"]["answer_source"] == "system_composed" and body["provenance"]["llm_calls"] == 0


def test_read_intents_still_answer_a_season_without_recommendations():
    body = _ask(_service(Llm(GOOD_RECOMMEND)), "explain", reader=Reader(signals=[]))
    assert body["status"] == "generated" and body["recommendations"] == []


# -- 2. only a data_task -----------------------------------------------------------

def test_only_a_data_task_limits_the_model_to_that_rule():
    llm = Llm(_recommend(DATA_RULE))
    body = _ask(_service(llm), "recommend", reader=Reader(signals=[_data_task_row()]))
    assert json.loads(llm.requests[0][1])["request"]["allowed_rule_codes"] == [DATA_RULE]
    assert [rec["rule_code"] for rec in body["recommendations"]] == [DATA_RULE]
    # a data task has no quantified impact, so no Carbon number and no MRV caveat is added
    assert not any(NOT_MRV in item for item in body["limitations"])


def test_only_a_data_task_refuses_an_optimization_the_season_does_not_have():
    with pytest.raises(GroundingFailed):
        _ask(_service(Llm(_recommend(AWD_RULE))), "recommend", reader=Reader(signals=[_data_task_row()]))


# -- 3. an AWD optimization ----------------------------------------------------------

def test_awd_impact_is_labelled_an_estimate_not_an_mrv_figure():
    answer = "Hệ thống quy tắc ước tính mức giảm {{fact:current.signal." + AWD_RULE + ".co2e_total_kg_delta}}."
    llm = Llm(_recommend(AWD_RULE, answer=answer,
                         fact_refs=[{"fact_id": f"current.signal.{AWD_RULE}.co2e_total_kg_delta"}]))
    body = _ask(_service(llm), "recommend")
    assert "600 kg CO2e" in body["answer"]
    caveats = [item for item in body["limitations"] if NOT_MRV in item]
    # the signal impact carries no factor-set version of its own: never guess one
    assert caveats == ["Số liệu phát thải là ước tính của Carbon Engine theo bộ hệ số chưa xác định; "
                       "chưa đạt yêu cầu MRV, không dùng làm số liệu tín chỉ carbon."]


def test_a_stored_carbon_total_names_its_factor_set_and_is_not_mrv():
    body = _ask(_service(), "explain")
    assert "2.900 kg CO2e" in body["answer"]
    assert any(NOT_MRV in item and "ef-1" in item for item in body["limitations"])


def test_a_what_if_number_is_labelled_an_estimate():
    llm = Llm({"status": "generated", "answer": "Mức chênh lệch là {{fact:what_if.awd.delta_co2e_kg}}.",
               "fact_refs": [{"fact_id": "what_if.awd.delta_co2e_kg"}]})
    body = _ask(_service(llm), "what_if", scenario="awd")
    assert any(NOT_MRV in item for item in body["limitations"])


def test_an_answer_without_carbon_numbers_gets_no_carbon_caveat():
    body = _ask(_service(), "data_gap")
    assert not any(NOT_MRV in item for item in body["limitations"])


# -- 4. no valid Carbon factors / no Carbon result ----------------------------------

def test_no_carbon_result_reads_as_missing_never_zero():
    body = _ask(_service(carbon=_NoCarbon()), "explain")
    assert body["status"] == "generated" and LIMITATION_NO_CARBON in body["limitations"]
    assert "Tổng phát thải khí nhà kính đã tính" not in body["answer"]  # no stored total is ever stated
    assert " 0 kg CO2e" not in body["answer"]


def test_no_carbon_result_data_gap_names_the_missing_input():
    body = _ask(_service(carbon=_NoCarbon()), "data_gap")
    assert "chưa thể tính phát thải" in body["answer"] and "diện tích thửa" in body["answer"]


def test_an_unknown_factor_set_is_said_so_not_invented():
    body = _ask(_service(carbon=_UnknownFactorSet()), "explain")
    assert any(NOT_MRV in item and "chưa xác định" in item for item in body["limitations"])


# -- 5. no approved knowledge evidence -----------------------------------------------

def test_no_approved_evidence_skips_the_model_and_keeps_the_stored_rules():
    llm = Llm(GOOD_RECOMMEND)
    body = _ask(_service(llm), "recommend", reader=Reader(chunks=[]))
    assert body["insufficient_reason"] == "no_evidence_retrieved" and llm.requests == []
    assert [signal["rule_code"] for signal in body["signals"]] == [AWD_RULE]  # M05 card data still true
    assert body["recommendations"] == []


# -- 6. a recommendation the retrieved documents do not support ----------------------

def test_the_model_declining_unsupported_advice_is_insufficient_without_recommendations():
    llm = Llm({"status": "insufficient_evidence", "answer": "Tài liệu đã duyệt không đủ để giải thích khuyến nghị này."})
    body = _ask(_service(llm), "recommend")
    assert body["status"] == "insufficient_evidence" and body["insufficient_reason"] == "generator_declined"
    assert body["recommendations"] == [] and len(llm.requests) == 1


def test_a_recommendation_without_a_citation_is_refused():
    rec = {**GOOD_RECOMMEND["recommendations"][0], "evidence_refs": []}
    with pytest.raises(GroundingFailed):
        _ask(_service(Llm({**GOOD_RECOMMEND, "recommendations": [rec]})), "recommend")

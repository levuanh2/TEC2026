"""Flash R2 finding: the model wrote "khí CO2e" and the raw-number gate refused the answer.
Decision (owner, 2026-11-07): keep the gate exactly as it is; fix the PROMPT so gas names are
written in words ("khí nhà kính quy đổi"); units of trusted facts stay the renderer's job.
These tests pin both halves: the gate still refuses formulas/numbers, the prescribed wording
passes, and the renderer is what prints "kg CO2e"."""

from __future__ import annotations

import pytest

from rag_qa import ACTION_SYSTEM_PROMPT
from recommendation.rag import GroundingFailed
from recommendation.rag.prose import validate_generated_prose
from tests.test_rag_orchestrator import DELTA, Harness

R2_WHAT_IF = ("Nếu chuyển sang tưới ngập khô xen kẽ, tổng phát thải giảm khoảng {{fact:%s}} khí CO2e, "
              "so với hiện tại." % DELTA)


@pytest.mark.parametrize("text", [
    R2_WHAT_IF,                                   # the exact R2 failure shape
    "Giảm khí CO2 nhờ tưới khô xen kẽ.",
    "Lượng CH4 giảm khi ruộng khô dần.",
    "Hạn chế N2O khi bón phân.",
    "giảm khí co2e",                              # case does not matter
    "Phát thải giảm 600 kg.",                     # an invented number
    "Giảm khoảng 20 phần trăm.",
    "Giảm {{fact:%s}}%%." % DELTA,                # a model-added % sign
])
def test_formulas_and_raw_numbers_are_still_refused(text):
    with pytest.raises(GroundingFailed):
        validate_generated_prose([text])


@pytest.mark.parametrize("text", [
    "Lượng khí nhà kính quy đổi giảm khoảng {{fact:%s}} so với hiện tại." % DELTA,
    "Tưới ngập khô xen kẽ giúp giảm khí mê-tan và khí nhà kính.",
    "Tổng phát thải khí nhà kính quy đổi là {{fact:current.carbon.total_co2e_kg}}.",
])
def test_gas_names_in_words_and_valid_placeholders_pass(text):
    validate_generated_prose([text])


def test_the_prompt_prescribes_words_and_leaves_units_to_the_renderer():
    assert "khí nhà kính quy đổi" in ACTION_SYSTEM_PROMPT
    assert "CO2e" in ACTION_SYSTEM_PROMPT and "Không viết công thức" in ACTION_SYSTEM_PROMPT
    assert "hệ thống tự thêm đơn vị" in ACTION_SYSTEM_PROMPT


def test_what_if_awd_with_the_prescribed_wording_renders_the_engine_unit():
    output = {"status": "generated",
              "answer": "Lượng khí nhà kính quy đổi giảm khoảng {{fact:%s}} so với hiện tại." % DELTA,
              "fact_refs": [{"fact_id": DELTA}]}
    result = Harness(output=output).what_if()
    assert result.status == "generated"
    assert result.answer == "Lượng khí nhà kính quy đổi giảm khoảng 600 kg CO2e so với hiện tại."


def test_what_if_awd_with_a_formula_is_refused_not_repaired():
    """No silent stripping: the R2 answer is refused as a whole."""
    output = {"status": "generated", "answer": R2_WHAT_IF, "fact_refs": [{"fact_id": DELTA}]}
    with pytest.raises(GroundingFailed, match="CO2e"):
        Harness(output=output).what_if()

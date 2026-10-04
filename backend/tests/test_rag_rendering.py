"""Server-side trusted fact rendering: runs after grounding, only formats the
catalog's own values, and never lets a raw placeholder reach a client."""

from __future__ import annotations

import pytest

from recommendation.rag import (
    MISSING_FACT_TEXT,
    FactKind,
    FactReferenceMismatch,
    GeneratedAnswer,
    GroundedFact,
    format_fact,
    render_answer,
    render_facts,
)


def _fact(fact_id: str, value, unit: str | None = None) -> GroundedFact:
    return GroundedFact(fact_id=fact_id, kind=FactKind.RESOURCE_METRIC, value=value, unit=unit,
                        source="resource_metrics", provenance={"calculation_id": "calc-1"})


CATALOG = {f.fact_id: f for f in (
    _fact("current.metrics.co2e_per_kg", 0.58, "kg CO2e/kg"),
    _fact("current.carbon.total_co2e_kg", 2900.0, "kg CO2e"),
    _fact("current.metrics.water_m3", 1234567.5, "m3"),
    _fact("current.metrics.cost_per_kg", 340000, "VND/kg"),
    _fact("current.metrics.water_per_kg", None, "m3/kg"),
    _fact("what_if.awd.delta_co2e_kg", -200.0, "kg CO2e"),
    _fact("current.signal.r.co2e_percent_delta", 0.2069, "fraction"),
    _fact("current.completeness.water", False),
    _fact("current.season.ipcc_water_regime", "irrigated_continuous_flooding"),
)}


# -- formatting --------------------------------------------------------------------

@pytest.mark.parametrize(("fact_id", "expected"), [
    ("current.metrics.co2e_per_kg", "0,58 kg CO2e/kg"),
    ("current.carbon.total_co2e_kg", "2.900 kg CO2e"),
    ("current.metrics.water_m3", "1.234.567,5 m3"),
    ("current.metrics.cost_per_kg", "340.000 VND/kg"),
    ("what_if.awd.delta_co2e_kg", "-200 kg CO2e"),
    ("current.signal.r.co2e_percent_delta", "0,2069"),       # dimensionless: never converted to %
    ("current.completeness.water", "không"),
    ("current.season.ipcc_water_regime", "irrigated_continuous_flooding"),
])
def test_vietnamese_formatting_of_value_and_own_unit(fact_id, expected):
    assert format_fact(CATALOG[fact_id]) == expected


def test_null_fact_reads_as_missing_never_zero():
    assert format_fact(CATALOG["current.metrics.water_per_kg"]) == MISSING_FACT_TEXT == "chưa có dữ liệu"


@pytest.mark.parametrize(("value", "expected"), [
    (0.1 + 0.2, "0,30000000000000004"),   # exact stored value: no rounding
    (1e-05, "0,00001"),                   # no exponent, no padding
    (12.0, "12"),                         # only trailing fraction zeros dropped
    (0, "0"),                             # a real zero stays zero
    (True, "có"),
])
def test_precision_is_the_stored_value_never_invented_or_rounded(value, expected):
    assert format_fact(_fact("x", value)) == expected


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_non_finite_values_fail_closed(value):
    with pytest.raises(FactReferenceMismatch):
        format_fact(_fact("x", value))


# -- placeholder replacement -----------------------------------------------------------

def test_several_facts_in_one_sentence_are_rendered():
    text = "Cường độ {{fact:current.metrics.co2e_per_kg}}, tổng {{fact:current.carbon.total_co2e_kg}}."
    assert render_facts(text, CATALOG) == "Cường độ 0,58 kg CO2e/kg, tổng 2.900 kg CO2e."


def test_text_without_placeholders_is_unchanged():
    assert render_facts("Áp dụng 1 phải 5 giảm.", CATALOG) == "Áp dụng 1 phải 5 giảm."


@pytest.mark.parametrize("text", [
    "Giá trị {{fact:current.metrics.unknown}}.",
    "Giá trị {{fact:bad id}}.",           # malformed: would otherwise leak raw
    "Giá trị {{fact:}}.",
])
def test_unknown_or_malformed_placeholder_fails_closed(text):
    with pytest.raises(FactReferenceMismatch):
        render_facts(text, CATALOG)


def test_rendering_does_not_mutate_the_facts():
    before = {fid: fact.model_dump() for fid, fact in CATALOG.items()}
    render_facts("{{fact:current.metrics.co2e_per_kg}} {{fact:current.metrics.water_per_kg}}", CATALOG)
    assert {fid: fact.model_dump() for fid, fact in CATALOG.items()} == before


def test_render_answer_renders_every_text_field_and_keeps_the_template():
    answer = GeneratedAnswer.model_validate({
        "status": "generated",
        "answer": "Cường độ {{fact:current.metrics.co2e_per_kg}}.",
        "rationale": "Nước/kg: {{fact:current.metrics.water_per_kg}}.",
        "recommendations": [{"title": "Giảm {{fact:what_if.awd.delta_co2e_kg}}",
                             "actions": ["Chi phí {{fact:current.metrics.cost_per_kg}}"],
                             "evidence_refs": [{"source_id": "s", "chunk_id": "c"}]}],
        "limitations": ["Tổng {{fact:current.carbon.total_co2e_kg}} là bản tính đã lưu."],
    })
    rendered = render_answer(answer, CATALOG)
    assert rendered["answer"] == "Cường độ 0,58 kg CO2e/kg."
    assert rendered["answer_template"] == "Cường độ {{fact:current.metrics.co2e_per_kg}}."
    assert rendered["rationale"] == "Nước/kg: chưa có dữ liệu."
    assert rendered["recommendations"][0].title == "Giảm -200 kg CO2e"
    assert rendered["recommendations"][0].actions == ("Chi phí 340.000 VND/kg",)
    assert rendered["limitations"] == ("Tổng 2.900 kg CO2e là bản tính đã lưu.",)
    # the grounded generator answer itself is untouched
    assert answer.recommendations[0].title == "Giảm {{fact:what_if.awd.delta_co2e_kg}}"

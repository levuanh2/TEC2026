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
    ("current.signal.r.co2e_percent_delta", "0,2069"),       # not a RULE_SIGNAL fact: no conversion
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


# -- percentage rendering of audited relative-change fractions (Flash R2 finding) ---------------

def _signal_percent(value):
    return GroundedFact(fact_id="current.signal.water.awd_from_continuous_flooding.co2e_percent_delta",
                        kind=FactKind.RULE_SIGNAL, value=value, unit="fraction", source="recommendation_rules",
                        provenance={"rule_code": "water.awd_from_continuous_flooding"})


@pytest.mark.parametrize(("value", "expected"), [
    (0.2069, "20,7%"), (0, "0%"), (0.0, "0%"), (1, "100%"), (1.0, "100%"), (0.5, "50%"),
    (-0.05, "-5%"), (-0.2069, "-20,7%"),               # negative = an increase, sign kept
    (0.0005, "0,1%"), (0.00049, "0%"), (-0.0004, "0%"),  # half-up at one decimal; never "-0%"
    (0.125, "12,5%"), (0.99999, "100%"), (12.345, "1.234,5%"),
    (0.1 + 0.2, "30%"),                                 # binary noise does not leak into the display
])
def test_a_relative_change_fraction_reads_as_a_percentage(value, expected):
    assert format_fact(_signal_percent(value)) == expected


def test_a_missing_percentage_reads_as_missing():
    assert format_fact(_signal_percent(None)) == MISSING_FACT_TEXT


def test_percentage_display_never_changes_the_stored_value():
    fact = _signal_percent(0.2069)
    text = render_facts("giảm khoảng {{fact:%s}}" % fact.fact_id, {fact.fact_id: fact})
    assert text == "giảm khoảng 20,7%" and fact.value == 0.2069


@pytest.mark.parametrize("fact_id", ["current.cv.0.confidence", "x.some_ratio", "current.metrics.share"])
def test_other_fraction_facts_are_not_converted(fact_id):
    """CV confidence is a probability, not a relative change; only audited ids become %."""
    assert format_fact(_fact(fact_id, 0.87, "fraction")) == "0,87"


def test_a_percentage_suffix_without_the_fraction_unit_is_not_converted():
    assert format_fact(_fact("current.signal.r.co2e_percent_delta", 0.2069, None)) == "0,2069"


@pytest.mark.parametrize("fact_id", ["benchmark.x.co2e_percent_delta", "season.s2.signal.r.co2e_percent_delta"])
def test_only_a_current_rule_signal_is_converted_even_with_the_same_suffix(fact_id):
    fact = GroundedFact(fact_id=fact_id, kind=FactKind.RULE_SIGNAL, value=0.2069, unit="fraction",
                        source="recommendation_rules", provenance={"rule_code": "r"})
    assert format_fact(fact) == "0,2069"

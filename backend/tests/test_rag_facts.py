"""System facts: built by trusted code from authoritative context, scoped to
the caller, and the only way a business number reaches an answer."""

from __future__ import annotations

import pytest

from recommendation.rag import (
    FactKind,
    HypotheticalChange,
    RagMode,
    TenantIsolationViolation,
    WhatIfResult,
    assert_fact_scope,
    build_fact_catalog,
    build_season_context,
    has_comparison_basis,
    placeholder_ids,
    unreferenced_quantities,
)
from tests.fixtures.rag_fakes import (
    AWD_RULE,
    ORG_ID,
    OTHER_ORG_ID,
    OTHER_SEASON_ID,
    SEASON_ID,
    FakeFactsSource,
    benchmark_row,
    comparison_row,
    scope,
)

_CARBON = {"calculation_id": "calc-1", "total_co2e_kg": 2900.0, "input_hash": "abc", "engine_version": "1",
           "ef_config_version": "factors-2026",
           "breakdown": [{"category": "rice_ch4", "gas": "CH4", "source": "rice_methane", "co2e_kg": 2500.0}]}
_READINESS = {"can_calculate": False, "blocking_count": 1,
              "missing_inputs": [{"code": "pre_season_water_regime", "label": "Chế độ nước trước vụ",
                                  "flow": "carbon_methodology"}]}
_CV = [{"label": "blast", "confidence": 0.97, "uncertain": False, "model_version": "cv-1"}]
_AWD_WHAT_IF = WhatIfResult(
    change=HypotheticalChange(dimension="water_regime", scenario="awd"), status="available",
    baseline_total_co2e_kg=2900.0, hypothetical_total_co2e_kg=2300.0, delta_co2e_kg=600.0,
    baseline_input_hash="h0", hypothetical_input_hash="h1", engine_version="1", ef_config_version="f")


def _context(**source):
    return build_season_context(scope(), FakeFactsSource(calls=[], **source), mode=RagMode.ASK)


def _catalog(what_if=None, **source):
    context = _context(**source)
    return context, {fact.fact_id: fact for fact in build_fact_catalog(context, what_if)}


# -- catalog -------------------------------------------------------------------

def test_metric_facts_copy_the_authoritative_values_including_null():
    _, facts = _catalog()
    assert facts["current.metrics.co2e_per_kg"].value == 0.58
    assert facts["current.metrics.co2e_per_kg"].kind is FactKind.CARBON_INTENSITY
    assert facts["current.metrics.co2e_per_kg"].unit == "kg CO2e/kg"
    assert facts["current.metrics.water_per_kg"].value is None          # null stays null, never 0
    assert facts["current.metrics.fertilizer_kg"].value == 250.5
    assert facts["current.completeness.water"].value is False
    assert facts["current.season.ipcc_water_regime"].value == "irrigated_continuous_flooding"
    assert all(f.authoritative and f.source for f in facts.values())


def test_every_fact_is_scoped_to_the_season_and_organization():
    _, facts = _catalog()
    assert {(f.crop_season_id, f.organization_id) for f in facts.values()} == {(SEASON_ID, ORG_ID)}


def test_carbon_readiness_cv_and_signal_facts_carry_provenance():
    _, facts = _catalog(carbon=_CARBON, readiness=_READINESS, cv=_CV)
    total = facts["current.carbon.total_co2e_kg"]
    assert (total.value, total.provenance["calculation_id"], total.provenance["input_hash"]) == (2900.0, "calc-1", "abc")
    assert facts["current.carbon.breakdown.0"].provenance["category"] == "rice_ch4"
    assert facts["current.readiness.missing.pre_season_water_regime"].value == "Chế độ nước trước vụ"
    assert facts["current.cv.0.label"].value == "blast"
    delta = facts[f"current.signal.{AWD_RULE}.co2e_total_kg_delta"]
    assert (delta.value, delta.kind, delta.provenance["rule_version"]) == (600.0, FactKind.RULE_SIGNAL, "1")


def test_what_if_facts_come_only_from_the_what_if_result():
    _, without = _catalog()
    assert not any(fid.startswith("what_if.") for fid in without)
    _, facts = _catalog(_AWD_WHAT_IF)
    assert facts["what_if.awd.delta_co2e_kg"].value == 600.0
    assert facts["what_if.awd.hypothetical_total_co2e_kg"].provenance["hypothetical_input_hash"] == "h1"
    assert facts["what_if.awd.status"].value == "available"


def test_benchmark_and_comparison_facts_are_namespaced_and_scoped():
    _, facts = _catalog(benchmark_rows=[benchmark_row()], comparison_rows=[comparison_row()])
    bench = facts["benchmark.water-htx-2026"]
    assert (bench.kind, bench.value, bench.crop_season_id, bench.organization_id) == (FactKind.BENCHMARK, 1.8, None, ORG_ID)
    assert bench.provenance["source_reference"] == "htx-report-2026"
    other = facts[f"season.{OTHER_SEASON_ID}.metrics.co2e_per_kg"]
    assert (other.kind, other.value, other.crop_season_id) == (FactKind.COMPARISON_SEASON, 0.71, OTHER_SEASON_ID)


def test_comparison_basis_needs_a_finalized_benchmark_or_comparison_value():
    assert has_comparison_basis(_catalog()[1].values()) is False
    assert has_comparison_basis(_catalog(benchmark_rows=[benchmark_row(status="draft")])[1].values()) is False
    assert has_comparison_basis(_catalog(benchmark_rows=[benchmark_row(value=None)])[1].values()) is False
    assert has_comparison_basis(_catalog(benchmark_rows=[benchmark_row()])[1].values()) is True
    assert has_comparison_basis(_catalog(comparison_rows=[comparison_row()])[1].values()) is True


# -- scope backstop ----------------------------------------------------------------

def test_own_and_public_facts_pass_the_scope_check():
    context = _context(benchmark_rows=[benchmark_row(), benchmark_row(benchmark_id="public", organization_id=None)],
                       comparison_rows=[comparison_row()])
    assert_fact_scope(build_fact_catalog(context), scope(), context)


@pytest.mark.parametrize("source", [
    {"comparison_rows": [comparison_row(organization_id=OTHER_ORG_ID)]},
    {"benchmark_rows": [benchmark_row(organization_id=OTHER_ORG_ID)]},
])
def test_cross_tenant_facts_are_a_security_failure(source):
    context = _context(**source)
    with pytest.raises(TenantIsolationViolation):
        assert_fact_scope(build_fact_catalog(context), scope(), context)


def test_fact_for_a_season_outside_the_authorized_set_is_rejected():
    context = _context()
    foreign = build_fact_catalog(_context(comparison_rows=[comparison_row()]))  # built with another season
    with pytest.raises(TenantIsolationViolation):
        assert_fact_scope(foreign, scope(), context)


# -- quantitative claims -------------------------------------------------------------

def test_placeholders_are_parsed():
    assert placeholder_ids("A {{fact:current.metrics.water_per_kg}} và {{fact:what_if.awd.delta_co2e_kg}}") == [
        "current.metrics.water_per_kg", "what_if.awd.delta_co2e_kg"]


@pytest.mark.parametrize("text", [
    "Chuyển sang AWD giảm 18% phát thải.",
    "Giảm 18 phần trăm CH4.",
    "Tiết kiệm 340.000đ mỗi vụ.",
    "Tiết kiệm 340.000 đồng.",
    "Giảm 112 kg CO2e.",
    "Giảm 0,5 tấn CO2e.",
    "Nước/kg là 1.8 m3/kg.",
    "Trung bình HTX là 2 m³ mỗi kg.",
    "Chi phí 2 triệu.",
    "Phát thải 2900 CO2e.",
    "Dùng 50 lít thuốc.",
    "Lợi nhuận 1,000,000 VND.",
])
def test_business_numbers_outside_placeholders_are_detected(text):
    assert unreferenced_quantities(text)


@pytest.mark.parametrize("text", [
    "Áp dụng nguyên tắc 1 phải 5 giảm.",
    "Rút nước khi mực nước xuống 15 cm dưới mặt đất.",
    "Bón phân 3 lần trong vụ 2026.",
    "Giảm {{fact:what_if.awd.delta_co2e_kg}} so với vụ hiện tại.",
    "Cường độ {{fact:current.metrics.co2e_per_kg}} kg CO2e/kg lúa.",
])
def test_harmless_numbers_and_placeholders_pass(text):
    assert unreferenced_quantities(text) == []


def test_duplicate_fact_ids_fail_loudly_instead_of_shadowing():
    with pytest.raises(ValueError, match="duplicate fact id"):
        _catalog(benchmark_rows=[benchmark_row(), benchmark_row(value=9.9)])

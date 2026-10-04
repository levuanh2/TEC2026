"""SeasonRagContext is assembled from existing authoritative rows by field
picking only: null stays null, numbers are copied, never recomputed."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from recommendation.rag import RagMode, build_season_context
from tests.fixtures.rag_fakes import (
    AWD_RULE,
    FARM_ID,
    ORG_ID,
    OTHER_SEASON_ID,
    PLOT_ID,
    SEASON_ID,
    FakeFactsSource,
    benchmark_row,
    comparison_row,
    scope,
    signal_row,
)


def _source(**overrides) -> FakeFactsSource:
    return FakeFactsSource(calls=[], **overrides)


def test_scope_ids_come_from_the_authorized_scope():
    context = build_season_context(scope(), _source(), mode=RagMode.ASK)
    assert (context.organization_id, context.farm_id, context.plot_id, context.crop_season_id) == (
        ORG_ID, FARM_ID, PLOT_ID, SEASON_ID)


def test_season_fields_map_from_the_season_view():
    context = build_season_context(scope(), _source(), mode=RagMode.ASK)
    assert context.season.season_code == "HT-2026"
    assert context.season.planting_date == date(2026, 5, 1)
    assert context.season.ipcc_water_regime == "irrigated_continuous_flooding"
    assert context.season.actual_harvest_date is None
    assert context.season.pre_season_water_regime is None


def test_metrics_null_stays_null_and_is_never_zero():
    context = build_season_context(scope(), _source(), mode=RagMode.ASK)
    assert context.metrics.water_m3 is None
    assert context.metrics.water_per_kg is None
    assert context.metrics.cost_per_kg is None
    assert context.metrics.data_completeness is not None
    assert context.metrics.data_completeness.water is False


def test_metrics_are_copied_not_recomputed():
    # Total and yield no longer match co2e_per_kg: a builder that divided
    # would return 9999.0 here instead of the source's 0.58.
    row = {**_source().metric_row, "total_co2e_kg": 9999.0, "yield_kg": 1.0}
    context = build_season_context(scope(), _source(metric_row=row), mode=RagMode.ASK)
    assert context.metrics.co2e_per_kg == 0.58
    assert context.metrics.total_co2e_kg == 9999.0


def test_numeric_strings_are_coerced_as_a_type_transform_only():
    context = build_season_context(scope(), _source(), mode=RagMode.ASK)
    assert context.metrics.fertilizer_kg == 250.5


def test_absent_source_keys_become_none_and_extra_keys_are_ignored():
    context = build_season_context(
        scope(), _source(metric_row={"yield_kg": None, "_total_cost_vnd": 12.0, "unexpected": "x"}), mode=RagMode.ASK)
    assert context.metrics.model_dump() == {key: None for key in context.metrics.model_dump()}


def test_missing_carbon_result_and_readiness_stay_none():
    context = build_season_context(scope(), _source(), mode=RagMode.ASK)
    assert context.carbon is None
    assert context.carbon_readiness is None


def test_carbon_facts_map_from_the_stored_view_including_breakdown():
    calc_id = uuid.uuid4()
    carbon = {
        "calculation_id": calc_id, "scenario": "as_recorded", "calculation_kind": "actual",
        "total_co2e_kg": "2900.25", "water_regime_applied": "irrigated_continuous_flooding",
        "ef_config_version": "factors-2026", "engine_version": "1", "input_hash": "abc",
        "calculated_at": datetime(2026, 9, 1, 10, 0, 0), "mrv_compliant": False, "factor_set_id": "ignored",
        "breakdown": [{"category": "rice_ch4", "gas": "CH4", "source": "rice_methane", "co2e_kg": 2500.0,
                       "factors_used": {"x": 1}}],
    }
    readiness = {"can_calculate": False, "blocking_count": 1, "input_hash": None,
                 "missing_inputs": [{"code": "pre_season_water_regime", "label": "Chế độ nước trước vụ",
                                     "flow": "carbon_methodology", "detail": "ignored"}]}
    context = build_season_context(scope(), _source(carbon=carbon, readiness=readiness), mode=RagMode.ASK)
    assert context.carbon is not None and context.carbon_readiness is not None
    assert context.carbon.calculation_id == str(calc_id)
    assert context.carbon.total_co2e_kg == 2900.25
    assert context.carbon.breakdown[0].co2e_kg == 2500.0
    assert context.carbon_readiness.missing_inputs[0].code == "pre_season_water_regime"
    assert context.carbon_readiness.can_calculate is False


def test_signals_are_verbatim_deterministic_rows():
    rows = [signal_row(), signal_row("data.completeness.water", type="data_task", impact_status="unavailable",
                                     co2e_total_kg_before=None, co2e_total_kg_after=None,
                                     co2e_total_kg_delta=None, co2e_percent_delta=None)]
    context = build_season_context(scope(), _source(signals=rows), mode=RagMode.ASK)
    assert context.signal_rule_codes == {AWD_RULE, "data.completeness.water"}
    assert context.signals[0].co2e_total_kg_delta == 600.0
    assert context.signals[1].co2e_total_kg_delta is None


def test_cv_signal_is_carried_as_recorded():
    cv = [{"label": None, "label_vi": None, "confidence": 0.41, "uncertain": True,
           "model_version": "cv-1", "created_at": "2026-09-01T00:00:00Z", "image_id": "ignored"}]
    context = build_season_context(scope(), _source(cv=cv), mode=RagMode.ASK)
    assert context.cv_signals[0].label is None
    assert context.cv_signals[0].uncertain is True


def test_ask_reads_stored_signals_and_preview_asks_for_fresh_ones():
    ask, preview = _source(), _source()
    build_season_context(scope(), ask, mode=RagMode.ASK)
    build_season_context(scope(), preview, mode=RagMode.PREVIEW)
    assert ask.fresh_flags == [False]
    assert preview.fresh_flags == [True]


def test_context_reads_only_through_the_port():
    source = _source()
    build_season_context(scope(), source, mode=RagMode.ASK)
    assert sorted(source.reads) == sorted([
        "season", "activity_summary", "metrics", "carbon_actual", "carbon_readiness",
        "recommendation_signals", "cv_signals", "benchmarks", "comparison_seasons",
    ])


def test_no_benchmark_source_gives_no_benchmarks():
    context = build_season_context(scope(), _source(), mode=RagMode.ASK)
    assert context.benchmarks == () and context.comparison_seasons == ()


def test_only_finalized_benchmarks_are_kept_verbatim():
    rows = [benchmark_row(), benchmark_row(benchmark_id="draft", status="draft"),
            benchmark_row(benchmark_id="unknown-status", status=None)]
    context = build_season_context(scope(), _source(benchmark_rows=rows), mode=RagMode.ASK)
    assert [b.benchmark_id for b in context.benchmarks] == ["water-htx-2026"]
    assert context.benchmarks[0].value == 1.8
    assert context.benchmarks[0].source_reference == "htx-report-2026"


def test_comparison_seasons_carry_their_own_authoritative_metrics():
    rows = [comparison_row(), comparison_row(crop_season_id=SEASON_ID)]  # the season itself is dropped
    context = build_season_context(scope(), _source(comparison_rows=rows), mode=RagMode.ASK)
    assert [c.crop_season_id for c in context.comparison_seasons] == [OTHER_SEASON_ID]
    other = context.comparison_seasons[0]
    assert other.metrics.co2e_per_kg == 0.71
    assert other.metrics.water_per_kg is None
    assert other.organization_id == ORG_ID

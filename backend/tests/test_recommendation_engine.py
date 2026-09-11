"""Unit tests for the M05 rule engine.

Every carbon-impact assertion here goes through the REAL `calculate_carbon`
function (imported unmodified from `carbon`), on the same fixture
(`tests/fixtures/demo_crop.json`) and test factor set
(`tests/fixtures/test_factors.yaml`) that `test_carbon_engine.py` already
verifies by hand — this is the architectural proof that the recommendation
module never re-implements CH4/N2O/GWP math (brief M05 §B21): the only
number this module produces is `before.total_co2e_kg - after.total_co2e_kg`.
"""
from __future__ import annotations

import copy
import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from carbon import CarbonResult, CropActivityData, ParameterSet, calculate_carbon  # noqa: E402
from recommendation import (  # noqa: E402
    AWD_RULE_CODE,
    DATA_TASK_RULE_CODE,
    evaluate_awd_rule,
    evaluate_data_completeness,
    generate_recommendations,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Hand-verified totals for tests/fixtures/demo_crop.json under test_factors.yaml
# (see test_carbon_engine.py's worked table) — reused here, not recomputed.
AWD_TOTAL = 2920.8
CF_TOTAL = 5435.4


@pytest.fixture
def params() -> ParameterSet:
    return ParameterSet.load(FIXTURES / "test_factors.yaml")


@pytest.fixture
def raw_demo() -> dict:
    with open(FIXTURES / "demo_crop.json", encoding="utf-8") as fh:
        return json.load(fh)


@dataclass
class _CalculationOutcome:
    result: CarbonResult
    calculation_id: str | None = None
    persisted: bool = False


class FixtureCarbonService:
    """Structurally matches `service.CarbonService.calculate(...)`, but runs
    the real engine directly against an in-memory `CropActivityData` instead
    of a Supabase-backed repository — no rule test needs a database."""

    def __init__(self, activity_data: CropActivityData, params: ParameterSet):
        self._activity_data = activity_data
        self._params = params
        self.calls: list[str] = []

    def calculate(self, crop_season_id: str, scenario: str = "as_recorded", *, persist: bool = True):
        self.calls.append(scenario)
        result = calculate_carbon(self._activity_data, scenario, self._params)
        return _CalculationOutcome(result=result)


def continuous_flooding_activity(raw_demo: dict) -> CropActivityData:
    raw = copy.deepcopy(raw_demo)
    raw["water_regime"] = "irrigated_continuous_flooding"
    return CropActivityData.from_dict(raw)


def awd_activity(raw_demo: dict) -> CropActivityData:
    raw = copy.deepcopy(raw_demo)
    raw["water_regime"] = "irrigated_multiple_drainage"
    return CropActivityData.from_dict(raw)


# ===========================================================================
# AWD rule — determinism, real-engine impact, no duplicated formula
# ===========================================================================


def test_awd_rule_recommends_when_baseline_is_continuous_flooding(raw_demo, params):
    carbon = FixtureCarbonService(continuous_flooding_activity(raw_demo), params)
    rec = evaluate_awd_rule("demo-001", carbon)

    assert rec is not None
    assert rec.rule_code == AWD_RULE_CODE
    assert rec.type == "optimization"
    assert rec.impact_status == "available"
    # These exact numbers come from calculate_carbon() itself, not from any
    # formula written in the recommendation module.
    assert rec.co2e_total_kg_before == pytest.approx(CF_TOTAL)
    assert rec.co2e_total_kg_after == pytest.approx(AWD_TOTAL)
    assert rec.co2e_total_kg_delta == pytest.approx(CF_TOTAL - AWD_TOTAL)
    assert rec.co2e_percent_delta == pytest.approx((CF_TOTAL - AWD_TOTAL) / CF_TOTAL)
    assert carbon.calls == ["as_recorded", "awd"]


def test_awd_rule_is_deterministic(raw_demo, params):
    carbon = FixtureCarbonService(continuous_flooding_activity(raw_demo), params)
    first = evaluate_awd_rule("demo-001", carbon)
    second = evaluate_awd_rule("demo-001", FixtureCarbonService(continuous_flooding_activity(raw_demo), params))

    assert first.co2e_total_kg_delta == second.co2e_total_kg_delta
    assert first.input_hash == second.input_hash


def test_awd_rule_does_not_fire_when_already_awd(raw_demo, params):
    carbon = FixtureCarbonService(awd_activity(raw_demo), params)
    assert evaluate_awd_rule("demo-001", carbon) is None
    # Precondition failed on the baseline call alone -> never spend a second
    # engine call proposing what's already the current regime.
    assert carbon.calls == ["as_recorded"]


def test_awd_rule_suppressed_when_baseline_calculation_fails(raw_demo, params):
    activity = continuous_flooding_activity(raw_demo)
    activity.fertilizer[0].n_content_pct = None  # same failure as test_carbon_engine.py
    carbon = FixtureCarbonService(activity, params)

    assert evaluate_awd_rule("demo-001", carbon) is None


def test_awd_rule_suppressed_not_crashed_by_a_transient_infra_error():
    """A dropped Supabase connection (httpx.RemoteProtocolError etc.) is not
    a CarbonEngineError — found for real via the hosted M05 E2E, where an
    unhandled exception here 500'd the whole /recommendations/generate
    request, including the unrelated data_task rules that don't touch
    Carbon at all. The rule must degrade to "not evaluable now", not crash."""

    class FlakyCarbon:
        def calculate(self, crop_season_id, scenario="as_recorded", *, persist=True):
            raise ConnectionError("Server disconnected")

    assert evaluate_awd_rule("demo-001", FlakyCarbon()) is None


def test_awd_rule_marks_impact_unavailable_when_only_the_proposed_scenario_fails(raw_demo, params):
    from carbon import MissingEmissionFactorError

    activity = continuous_flooding_activity(raw_demo)
    carbon = FixtureCarbonService(activity, params)
    real_calculate = carbon.calculate

    def flaky(crop_season_id, scenario="as_recorded", *, persist=True):
        if scenario == "awd":
            raise MissingEmissionFactorError("gwp.ch4 chưa được xác minh")
        return real_calculate(crop_season_id, scenario, persist=persist)

    carbon.calculate = flaky
    rec = evaluate_awd_rule("demo-001", carbon)

    assert rec is not None
    assert rec.impact_status == "unavailable"
    assert rec.co2e_total_kg_before is None
    assert rec.co2e_total_kg_delta is None
    assert "gwp.ch4" in rec.impact_unavailable_reason


def test_awd_rule_marks_impact_unavailable_with_a_generic_reason_when_the_proposed_scenario_hits_an_infra_error(raw_demo, params):
    """Same as above, but the proposed-scenario failure is a raw infra error
    (not a CarbonEngineError) — the rule still degrades gracefully instead of
    propagating, and the farmer-facing reason never leaks a raw exception."""
    activity = continuous_flooding_activity(raw_demo)
    carbon = FixtureCarbonService(activity, params)
    real_calculate = carbon.calculate

    def flaky(crop_season_id, scenario="as_recorded", *, persist=True):
        if scenario == "awd":
            raise TimeoutError("upstream timed out")
        return real_calculate(crop_season_id, scenario, persist=persist)

    carbon.calculate = flaky
    rec = evaluate_awd_rule("demo-001", carbon)

    assert rec is not None
    assert rec.impact_status == "unavailable"
    assert rec.co2e_total_kg_delta is None
    assert "upstream timed out" not in rec.impact_unavailable_reason


def test_awd_rule_never_recommends_a_non_positive_delta(raw_demo, params):
    """If the engine ever said AWD was not actually better for this data, the
    rule must not force a recommendation (brief §B15)."""
    carbon = FixtureCarbonService(continuous_flooding_activity(raw_demo), params)
    baseline = carbon.calculate("demo-001", "as_recorded")
    proposed = carbon.calculate("demo-001", "awd")
    proposed.result.total_co2e_kg = baseline.result.total_co2e_kg  # forced exact tie -> delta == 0

    class TiedCarbon:
        def calculate(self, crop_season_id, scenario="as_recorded", *, persist=True):
            return baseline if scenario == "as_recorded" else proposed

    assert evaluate_awd_rule("demo-001", TiedCarbon()) is None


# ===========================================================================
# Data-completeness rule — never a quantified impact
# ===========================================================================


def test_data_completeness_flags_each_missing_metric_independently():
    metrics = {
        "yield_kg": None,
        "data_completeness": {"water": False, "fertilizer": True, "cost": False, "carbon": False},
    }
    recs = evaluate_data_completeness("demo-001", metrics)

    codes = {rec.rule_code for rec in recs}
    assert codes == {
        f"{DATA_TASK_RULE_CODE}.yield",
        f"{DATA_TASK_RULE_CODE}.water",
        f"{DATA_TASK_RULE_CODE}.cost",
    }
    for rec in recs:
        assert rec.type == "data_task"
        assert rec.impact_status == "unavailable"
        assert rec.co2e_total_kg_delta is None  # never a fabricated quantified impact


def test_data_completeness_empty_when_everything_present():
    metrics = {
        "yield_kg": 3100.0,
        "data_completeness": {"water": True, "fertilizer": True, "cost": True, "carbon": True},
    }
    assert evaluate_data_completeness("demo-001", metrics) == []


def test_data_completeness_is_deterministic():
    metrics = {"yield_kg": None, "data_completeness": {}}
    first = evaluate_data_completeness("demo-001", metrics)
    second = evaluate_data_completeness("demo-001", metrics)
    assert [r.input_hash for r in first] == [r.input_hash for r in second]


# ===========================================================================
# Engine orchestration
# ===========================================================================


def test_generate_recommendations_combines_optimization_and_data_task(raw_demo, params):
    carbon = FixtureCarbonService(continuous_flooding_activity(raw_demo), params)
    metrics = {"yield_kg": None, "data_completeness": {"water": True, "fertilizer": True, "cost": True, "carbon": False}}

    recs = generate_recommendations("demo-001", carbon=carbon, metrics=metrics)

    types = {rec.rule_code: rec.type for rec in recs}
    assert types[AWD_RULE_CODE] == "optimization"
    assert types[f"{DATA_TASK_RULE_CODE}.yield"] == "data_task"

"""Recommendation rule contract pins (Mutation Hardening V1, docs/MUTATION_BASELINE.md).

Closes the "missing meaningful test" survivors of `recommendation/rules.py`:
the persisted identity of a recommendation (rule code/version, input hash),
the no-side-effect guarantee (`persist=False`), the evidence keys that make a
recommendation traceable, the strictly-positive-saving boundary and the
non-null user-facing fields. Every Carbon number still comes from the real
engine (tests/test_recommendation_engine.py's FixtureCarbonService pattern);
nothing here invents a benchmark or a Carbon result.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from carbon import CarbonEngineError, CarbonResult, CropActivityData, ParameterSet, calculate_carbon  # noqa: E402
from recommendation import evaluate_awd_rule, evaluate_data_completeness  # noqa: E402
from recommendation.rules import AWD_RULE_CODE, AWD_RULE_VERSION, DATA_TASK_RULE_CODE, DATA_TASK_RULE_VERSION  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@dataclass
class _Outcome:
    result: CarbonResult


class RecordingCarbon:
    """The real engine on the demo fixture; records every call's persist flag."""

    def __init__(self, regime: str = "irrigated_continuous_flooding", fail_awd: Exception | None = None):
        raw = json.loads((FIXTURES / "demo_crop.json").read_text(encoding="utf-8"))
        raw["water_regime"] = regime
        self._data = CropActivityData.from_dict(copy.deepcopy(raw))
        self._params = ParameterSet.load(FIXTURES / "test_factors.yaml")
        self._fail_awd = fail_awd
        self.calls: list[tuple[str, bool]] = []

    def calculate(self, crop_season_id, scenario="as_recorded", *, persist=True):
        self.calls.append((scenario, persist))
        if scenario == "awd" and self._fail_awd is not None:
            raise self._fail_awd
        return _Outcome(calculate_carbon(self._data, scenario, self._params))


# -- identity (idempotent regeneration keys on these) -------------------------------

def test_rule_identities_are_the_persisted_codes():
    assert (AWD_RULE_CODE, AWD_RULE_VERSION) == ("water.awd_from_continuous_flooding", "1")
    assert (DATA_TASK_RULE_CODE, DATA_TASK_RULE_VERSION) == ("data.completeness", "1")


def test_awd_recommendation_carries_its_identity_type_and_texts():
    rec = evaluate_awd_rule("demo-001", RecordingCarbon())
    assert (rec.rule_code, rec.rule_version, rec.type) == ("water.awd_from_continuous_flooding", "1", "optimization")
    for text in (rec.title, rec.reason, rec.compared_to):
        assert isinstance(text, str) and text.strip()


# -- no side effect: a recommendation never writes a Carbon result --------------------

def test_both_awd_calculations_are_hypothetical():
    carbon = RecordingCarbon()
    evaluate_awd_rule("demo-001", carbon)
    assert carbon.calls == [("as_recorded", False), ("awd", False)]


def test_an_unavailable_awd_impact_also_never_persists():
    carbon = RecordingCarbon(fail_awd=CarbonEngineError("awd scenario not computable"))
    rec = evaluate_awd_rule("demo-001", carbon)
    assert carbon.calls == [("as_recorded", False), ("awd", False)]
    assert rec.impact_status == "unavailable" and rec.impact_unavailable_reason == "awd scenario not computable"


# -- evidence: where the numbers came from -----------------------------------------

def test_available_impact_names_both_calculations_and_the_factor_set():
    carbon = RecordingCarbon()
    rec = evaluate_awd_rule("demo-001", carbon)
    baseline = calculate_carbon(carbon._data, "as_recorded", carbon._params)
    proposed = calculate_carbon(carbon._data, "awd", carbon._params)
    assert rec.evidence == {
        "baseline_input_hash": baseline.input_hash,
        "proposed_input_hash": proposed.input_hash,
        "baseline_water_regime": "irrigated_continuous_flooding",
        "proposed_water_regime": proposed.water_regime_applied,
        "ef_config_version": baseline.ef_config_version,
    }
    assert rec.input_hash == baseline.input_hash and rec.engine_version == baseline.engine_version


def test_unavailable_impact_still_names_the_baseline_and_fabricates_no_number():
    carbon = RecordingCarbon(fail_awd=CarbonEngineError("x"))
    rec = evaluate_awd_rule("demo-001", carbon)
    baseline = calculate_carbon(carbon._data, "as_recorded", carbon._params)
    assert rec.evidence == {"baseline_input_hash": baseline.input_hash,
                            "baseline_water_regime": "irrigated_continuous_flooding"}
    assert (rec.co2e_total_kg_before, rec.co2e_total_kg_after, rec.co2e_total_kg_delta, rec.co2e_percent_delta) == (None,) * 4
    assert rec.type == "optimization" and rec.title and rec.reason


# -- boundary: any strictly positive saving is reported ------------------------------

class FixedTotals:
    def __init__(self, before: float, after: float):
        base = RecordingCarbon()
        self._before = calculate_carbon(base._data, "as_recorded", base._params)
        self._after = calculate_carbon(base._data, "awd", base._params)
        self._totals = {"as_recorded": before, "awd": after}

    def calculate(self, crop_season_id, scenario="as_recorded", *, persist=True):
        result = self._before if scenario == "as_recorded" else self._after
        return _Outcome(replace(result, total_co2e_kg=self._totals[scenario]))


@pytest.mark.parametrize(("after", "recommended"), [(999.5, True), (999.0, True), (1000.0, False), (1000.5, False)])
def test_a_saving_below_one_kg_is_still_a_saving(after, recommended):
    rec = evaluate_awd_rule("demo-001", FixedTotals(1000.0, after))
    assert (rec is not None) is recommended
    if rec is not None:
        assert rec.co2e_total_kg_delta == pytest.approx(1000.0 - after) and rec.co2e_total_kg_delta > 0


# -- data tasks --------------------------------------------------------------------

def test_a_data_task_is_identified_by_season_and_missing_metric():
    tasks = evaluate_data_completeness("season-1", {"yield_kg": None, "data_completeness": {}})
    assert [t.rule_code for t in tasks] == [f"data.completeness.{k}" for k in ("yield", "water", "fertilizer", "cost")]
    for task, key in zip(tasks, ("yield", "water", "fertilizer", "cost")):
        assert task.input_hash == hashlib.sha256(f"season-1:{key}".encode("utf-8")).hexdigest()
        assert task.evidence == {"missing_metric": key}
        assert task.rule_version == "1" and task.type == "data_task"
        assert task.impact_status == "unavailable"
        assert isinstance(task.impact_unavailable_reason, str) and task.impact_unavailable_reason.strip()
        assert task.title.strip() and task.reason.strip() and task.engine_version is None
    other = evaluate_data_completeness("season-2", {"yield_kg": None, "data_completeness": {}})
    assert {t.input_hash for t in tasks}.isdisjoint({t.input_hash for t in other})

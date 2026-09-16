"""Cost belongs to Resource Metrics; it is never a Carbon input.

The Farmer dashboard shows "Thiếu chi phí vật tư" and a Carbon state next to each
other, so the domain rule has to be enforced somewhere a regression would trip
over it, not just written in a doc. These tests pin both halves:

  * adding cost moves `cost_per_kg` and nothing else;
  * a season with NO cost at all still calculates Carbon normally.
"""
from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from carbon import ParameterSet, calculate_carbon  # noqa: E402
from carbon.models import CropActivityData, FertilizerApplication, Harvest  # noqa: E402
from carbon.readiness import missing_inputs  # noqa: E402
from infrastructure.read_repo import SupabaseReadRepository  # noqa: E402

REAL = ParameterSet.load(BACKEND_DIR / "config" / "emission_factors.yaml")

# Activity rows in the shape `_compute_metric_totals` consumes.
ACTIVITIES_NO_COST = [
    {"activity_type": "irrigation", "payload": {"water_volume_m3": 4000, "total_cost_vnd": None}},
    {"activity_type": "fertilizer", "payload": {"amount_kg": 100, "nitrogen_percent": 46, "total_cost_vnd": None}},
    {"activity_type": "harvest", "payload": {"yield_kg": 6000, "total_cost_vnd": None}},
]
COSTS = {"irrigation": 300_000.0, "fertilizer": 850_000.0, "harvest": 1_200_000.0}
CARBON_ROWS = [{"status": "succeeded", "scenario": "actual", "calculated_at": "2026-06-21T00:00:00Z",
                "total_co2e_kg": 3473.4671}]


def with_costs(rows):
    out = deepcopy(rows)
    for row in out:
        row["payload"]["total_cost_vnd"] = COSTS[row["activity_type"]]
    return out


def totals(activities):
    return SupabaseReadRepository._compute_metric_totals(activities, CARBON_ROWS)


def season(**overrides) -> CropActivityData:
    base = dict(
        crop_season_id="cost-001", area_ha=1.0, water_regime="irrigated_continuous_flooding",
        pre_season_water_regime="non_flooded_pre_season_lt_180d", cultivation_days=100,
        harvest=Harvest(yield_kg=6000),
        fertilizer=[FertilizerApplication("Urea", 100, n_content_pct=46)],
    )
    base.update(overrides)
    return CropActivityData(**base)


# -- cost moves only the cost metric ------------------------------------------

def test_adding_cost_makes_cost_per_kg_appear():
    before, after = totals(ACTIVITIES_NO_COST), totals(with_costs(ACTIVITIES_NO_COST))
    assert before["cost_per_kg"] is None
    assert before["data_completeness"]["cost"] is False
    assert after["cost_per_kg"] == sum(COSTS.values()) / 6000.0
    assert after["data_completeness"]["cost"] is True


def test_adding_cost_does_not_change_total_co2e():
    before, after = totals(ACTIVITIES_NO_COST), totals(with_costs(ACTIVITIES_NO_COST))
    assert before["total_co2e_kg"] == after["total_co2e_kg"] == 3473.4671


def test_adding_cost_does_not_change_co2e_per_kg():
    before, after = totals(ACTIVITIES_NO_COST), totals(with_costs(ACTIVITIES_NO_COST))
    assert before["co2e_per_kg"] == after["co2e_per_kg"]


def test_adding_cost_changes_nothing_except_the_two_cost_keys():
    """The strongest form: diff every key and require only cost to move."""
    before, after = totals(ACTIVITIES_NO_COST), totals(with_costs(ACTIVITIES_NO_COST))
    moved = {k for k in before if before[k] != after[k]}
    assert moved == {"cost_per_kg", "_total_cost_vnd", "data_completeness"}
    before_c, after_c = before["data_completeness"], after["data_completeness"]
    assert {k for k in before_c if before_c[k] != after_c[k]} == {"cost"}


# -- missing cost never blocks Carbon -----------------------------------------

def test_missing_cost_does_not_block_the_carbon_calculation():
    """No activity in this season carries a cost, and Carbon still computes."""
    assert all(a["payload"]["total_cost_vnd"] is None for a in ACTIVITIES_NO_COST)
    result = calculate_carbon(season(), "as_recorded", REAL)
    assert result.total_co2e_kg > 0
    assert result.co2e_per_kg is not None
    assert totals(ACTIVITIES_NO_COST)["cost_per_kg"] is None


def test_carbon_readiness_never_asks_for_cost():
    """Readiness drives the dashboard's Carbon message; if it ever named cost it
    would tell the farmer something false about the methodology."""
    assert not any("chi phí" in m.detail.lower() or "chi phí" in m.label.lower()
                   for m in missing_inputs(season()))
    assert missing_inputs(season()) == []


def test_carbon_engine_input_model_has_no_cost_field_at_all():
    """Cost cannot reach the engine even by accident: no input dataclass has a
    field to put it in. Checked on the field names rather than a repr, so a
    fixture that merely happens to contain the word "cost" cannot fool it."""
    from dataclasses import fields

    from carbon.models import (
        FuelUsage, Harvest as H, IrrigationEvent, PesticideApplication, Seed, StrawEvent,
    )

    for model in (CropActivityData, FertilizerApplication, H, StrawEvent,
                  FuelUsage, IrrigationEvent, PesticideApplication, Seed):
        names = [f.name.lower() for f in fields(model)]
        assert not [n for n in names if "cost" in n or "vnd" in n or "price" in n], \
            f"{model.__name__} exposes a monetary field to the Carbon engine: {names}"

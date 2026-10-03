"""B1: resource completeness does not depend on record order.

A group (water, fertilizer) is complete only when it has records and none of
them is missing its quantity; one missing value anywhere makes the numerator
unknown (null, not a partial sum). Formulas are unchanged: sum numerator / sum
yield, never an average of ratios. Checked on the single-season path and on the
bulk path the farm/organization rollups and MRV use.
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infrastructure.read_repo import SupabaseReadRepository  # noqa: E402
from tests.test_read_repository import DUMMY_SETTINGS, FakeSupabaseClient  # noqa: E402

USER, ORG, FARM, PLOT, SEASON = "user-1", "org-1", "farm-1", "plot-1", "season-1"
BATCH = "batch-1"


def _activity(activity_id, kind):
    return {
        "id": activity_id, "production_batch_id": BATCH, "activity_type": kind,
        "occurred_at": "2026-06-01", "recorded_at": "2026-06-01", "recorded_by": USER,
        "source": "web", "deleted_at": None, "note": None,
    }


def repository(irrigation: list[float | None], fertilizer: list[float | None]) -> SupabaseReadRepository:
    activities, irrigation_rows, fertilizer_rows = [_activity("h1", "harvest")], [], []
    for index, volume in enumerate(irrigation):
        activities.append(_activity(f"i{index}", "irrigation"))
        irrigation_rows.append({"activity_id": f"i{index}", "method": "awd", "water_volume_m3": volume, "total_cost_vnd": 10})
    for index, amount in enumerate(fertilizer):
        activities.append(_activity(f"f{index}", "fertilizer"))
        fertilizer_rows.append({"activity_id": f"f{index}", "fertilizer_name": "Urea", "amount_kg": amount, "total_cost_vnd": 10})
    rows = {
        "profiles": [{"id": USER, "full_name": "QA"}],
        "organization_memberships": [{"user_id": USER, "organization_id": ORG, "role": "farmer"}],
        "farm_members": [{"user_id": USER, "farm_id": FARM, "farm_role": "owner"}],
        "farms": [{"id": FARM, "farm_code": FARM, "farm_name": FARM, "cooperative_id": ORG}],
        "plots": [{"id": PLOT, "farm_id": FARM, "plot_code": PLOT, "name": PLOT, "area_ha": 1.0}],
        "crop_seasons": [{"id": SEASON, "plot_id": PLOT, "season_code": SEASON, "crop_type": "rice", "status": "active"}],
        "production_batches": [{"id": BATCH, "crop_season_id": SEASON, "batch_code": "b1", "name": None, "started_on": None,
                                "closed_on": None, "status": "planned", "deleted_at": None}],
        "activities": activities,
        "harvest_events": [{"activity_id": "h1", "yield_kg": 1000.0, "total_cost_vnd": 10}],
        "irrigation_events": irrigation_rows,
        "fertilizer_applications": fertilizer_rows,
        "seeding_events": [], "pesticide_applications": [], "fuel_usages": [], "straw_management_events": [],
        "carbon_calculations": [],
    }
    return SupabaseReadRepository(DUMMY_SETTINGS, "token", client=FakeSupabaseClient(rows, USER))


def both_paths(repo: SupabaseReadRepository) -> tuple[dict, dict]:
    single = repo.metrics(SEASON)
    bulk = {k: v for k, v in repo.metrics_for_seasons([SEASON])[SEASON].items() if not k.startswith("_")}
    return single, bulk


@pytest.mark.parametrize("order", list(itertools.permutations([None, 100.0, 50.0])))
def test_one_missing_water_volume_makes_water_incomplete_in_any_order(order):
    for result in both_paths(repository(list(order), [])):
        assert result["data_completeness"]["water"] is False
        assert result["water_m3"] is None and result["water_per_kg"] is None


@pytest.mark.parametrize("order", list(itertools.permutations([None, 20.0])))
def test_one_missing_fertilizer_amount_makes_fertilizer_incomplete_in_any_order(order):
    for result in both_paths(repository([], list(order))):
        assert result["data_completeness"]["fertilizer"] is False
        assert result["fertilizer_kg"] is None and result["fertilizer_per_kg"] is None


def test_complete_then_incomplete_equals_incomplete_then_complete():
    assert both_paths(repository([100.0, None], [20.0, None])) == both_paths(repository([None, 100.0], [None, 20.0]))


@pytest.mark.parametrize("order", list(itertools.permutations([100.0, 50.0, 0.0])))
def test_all_complete_records_sum_the_same_in_any_order(order):
    single, bulk = both_paths(repository(list(order), [20.0, 5.0]))
    assert single == bulk
    assert single["data_completeness"]["water"] is True and single["data_completeness"]["fertilizer"] is True
    assert single["water_m3"] == 150.0 and single["water_per_kg"] == pytest.approx(0.15)
    assert single["fertilizer_kg"] == 25.0 and single["fertilizer_per_kg"] == pytest.approx(0.025)


def test_no_records_stays_unknown_not_zero():
    single, bulk = both_paths(repository([], []))
    assert single == bulk
    assert single["water_m3"] is None and single["data_completeness"]["water"] is False
    assert single["fertilizer_kg"] is None and single["data_completeness"]["fertilizer"] is False


@pytest.mark.parametrize("order", list(itertools.permutations([1.0, 1e-05, 1e-05])))
def test_single_season_and_rollup_agree_exactly_in_any_record_order(order):
    # Found by the strict property test: the single-season path lists records
    # newest first, the rollup in table order; a plain float sum gave the same
    # season 1.00002 in one and 1.0000200000000001 in the other (F-METRICS-FSUM).
    single, bulk = both_paths(repository(list(order), list(order)))
    assert single == bulk
    assert single["fertilizer_kg"] == single["water_m3"] == 1.00002

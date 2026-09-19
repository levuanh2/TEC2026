"""Carbon readiness: which inputs a season lacks, and that the list cannot drift.

`carbon/readiness.py` deliberately holds NO methodology — only field-presence
checks over the same `CropActivityData` the engine consumes. The risk with any
such list is that it goes stale when `methodology.py` starts requiring something
new. These tests close that: readiness and the engine are checked against each
other, in both directions, on the real factor set.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from carbon import ParameterSet, calculate_carbon  # noqa: E402
from carbon.errors import CarbonEngineError  # noqa: E402
from carbon.models import (  # noqa: E402
    CropActivityData, FertilizerApplication, FuelUsage, Harvest, StrawEvent,
)
from carbon.readiness import (  # noqa: E402
    FLOW_ACTIVITY, FLOW_FACTOR_UNAVAILABLE, FLOW_METHODOLOGY, RecordRef, missing_inputs, readiness,
)

REAL = ParameterSet.load(BACKEND_DIR / "config" / "emission_factors.yaml")


def season(**overrides) -> CropActivityData:
    base = dict(
        crop_season_id="ready-001", area_ha=1.0,
        water_regime="irrigated_continuous_flooding",
        pre_season_water_regime="non_flooded_pre_season_lt_180d",
        cultivation_days=100, harvest=Harvest(yield_kg=6000),
        fertilizer=[FertilizerApplication("Urea", 100, n_content_pct=46)],
    )
    base.update(overrides)
    return CropActivityData(**base)


def codes(data: CropActivityData) -> set[str]:
    return {m.code for m in missing_inputs(data)}


def engine_fails(data: CropActivityData) -> bool:
    try:
        calculate_carbon(data, "as_recorded", REAL)
        return False
    except CarbonEngineError:
        return True


# -- the two must agree, in both directions -----------------------------------

def test_a_complete_season_is_ready_and_the_engine_really_calculates():
    data = season()
    assert readiness(data)["can_calculate"] is True
    assert codes(data) == set()
    assert not engine_fails(data)


@pytest.mark.parametrize(("overrides", "expected_code"), [
    ({"water_regime": None}, "water_regime"),
    ({"pre_season_water_regime": None}, "pre_season_water_regime"),
    ({"cultivation_days": None}, "cultivation_days"),
    ({"fertilizer": [FertilizerApplication("Urea", 100, n_content_pct=None)]}, "fertilizer_nitrogen"),
])
def test_each_missing_input_is_named_and_really_blocks_the_engine(overrides, expected_code):
    """Both directions at once: readiness names it, AND the engine refuses without
    it. If methodology.py stopped requiring one, the second half fails here."""
    data = season(**overrides)
    assert expected_code in codes(data)
    assert readiness(data)["can_calculate"] is False
    assert engine_fails(data)


@pytest.mark.parametrize(("event", "expected_code"), [
    (StrawEvent(method="burned", mass_kg=2000, dry_matter_fraction=None), "straw_dry_matter"),
    (StrawEvent(method="incorporated", mass_kg=2000, dry_matter_fraction=0.85,
                days_before_cultivation=None), "straw_days_before_cultivation"),
    (StrawEvent(method="incorporated", mass_kg=2000, dry_matter_fraction=None,
                days_before_cultivation=10), "straw_dry_matter"),
    (StrawEvent(method="composted", mass_kg=2000, dry_matter_fraction=0.85,
                returned_to_field=None), "straw_returned_to_field"),
])
def test_straw_branches_are_named_and_block(event, expected_code):
    data = season(straw=[event])
    assert expected_code in codes(data)
    assert engine_fails(data)


@pytest.mark.parametrize("event", [
    StrawEvent(method="removed", mass_kg=2000),
    StrawEvent(method="burned", mass_kg=2000, dry_matter_fraction=0.85),
    StrawEvent(method="incorporated", mass_kg=2000, dry_matter_fraction=0.85, days_before_cultivation=10),
    StrawEvent(method="composted", mass_kg=2000, dry_matter_fraction=0.85, returned_to_field=False),
])
def test_complete_straw_records_are_not_reported_as_missing(event):
    data = season(straw=[event])
    assert not {c for c in codes(data) if c.startswith("straw")}
    assert not engine_fails(data)


# -- yield is honestly non-blocking -------------------------------------------

def test_missing_yield_is_reported_but_does_not_block():
    data = season(harvest=Harvest(yield_kg=None))
    result = readiness(data)
    assert "harvest_yield" in codes(data)
    assert result["can_calculate"] is True      # total still computable
    assert result["blocking_count"] == 0
    assert not engine_fails(data)
    calculated = calculate_carbon(data, "as_recorded", REAL)
    assert calculated.total_co2e_kg > 0
    assert calculated.co2e_per_kg is None


# -- fuel is a factor-set limit, not a user data-entry mistake -----------------

def test_fuel_is_reported_as_a_factor_limitation_and_blocks():
    data = season(fuel=[FuelUsage("diesel", 50)])
    entry = next(m for m in missing_inputs(data) if m.code == "fuel_factor_unverified")
    assert "không phải do bạn nhập thiếu" in entry.detail
    # Its own flow, so no client can render it as a form that would "fix" it.
    assert entry.flow == FLOW_FACTOR_UNAVAILABLE
    assert engine_fails(data)


# -- cost is not a Carbon input at all ----------------------------------------

def test_no_missing_input_mentions_cost():
    """Cost belongs to Resource Metrics. A Carbon readiness list that asked for
    money would be telling the user something false about the methodology."""
    for data in (season(), season(water_regime=None), season(fuel=[FuelUsage("diesel", 5)])):
        for entry in missing_inputs(data):
            blob = f"{entry.code} {entry.label} {entry.detail}".lower()
            assert "chi phí" not in blob and "cost" not in blob and "vnd" not in blob


# -- each missing input routes somewhere the user can actually act ------------

def test_every_missing_input_names_a_flow_the_client_can_route_to():
    data = season(water_regime=None, pre_season_water_regime=None, cultivation_days=None,
                  fertilizer=[FertilizerApplication("Urea", 100, n_content_pct=None)],
                  straw=[StrawEvent(method="burned", mass_kg=1, dry_matter_fraction=None)],
                  harvest=Harvest(yield_kg=None))
    entries = missing_inputs(data)
    assert {m.flow for m in entries} <= {FLOW_METHODOLOGY, FLOW_ACTIVITY, "plot", FLOW_FACTOR_UNAVAILABLE}
    for m in entries:
        if m.flow == FLOW_ACTIVITY:
            assert m.activity_type, f"{m.code} routes to an activity form but names none"
    # The three season-level inputs all go to the methodology panel, not a journal form.
    by_code = {m.code: m for m in entries}
    for code in ("water_regime", "pre_season_water_regime", "cultivation_days"):
        assert by_code[code].flow == FLOW_METHODOLOGY
    assert by_code["fertilizer_nitrogen"].activity_type == "fertilizer"
    assert by_code["straw_dry_matter"].activity_type == "straw_management"
    assert by_code["harvest_yield"].activity_type == "harvest"


def test_repeated_missing_field_across_records_is_one_task():
    data = season(straw=[
        StrawEvent(method="burned", mass_kg=1000, dry_matter_fraction=None),
        StrawEvent(method="burned", mass_kg=2000, dry_matter_fraction=None),
    ])
    assert [m.code for m in missing_inputs(data)].count("straw_dry_matter") == 1


def test_readiness_payload_is_json_serializable_and_shaped_for_the_api():
    payload = readiness(season(water_regime=None))
    assert set(payload) == {"can_calculate", "missing_inputs", "blocking_count"}
    entry = payload["missing_inputs"][0]
    assert set(entry) == {"code", "label", "detail", "flow", "activity_type", "blocking", "records"}
    assert entry["records"] == []


# -- record identity: which stored record to open ------------------------------

def _refs(prefix: str, n: int) -> list[RecordRef]:
    return [RecordRef(activity_id=f"{prefix}-{i}", occurred_on="2026-03-0{}".format(i + 1)) for i in range(n)]


def test_records_name_exactly_the_offending_fertilizer_applications():
    data = season(fertilizer=[
        FertilizerApplication("Urea", 100, n_content_pct=46),
        FertilizerApplication("NPK", 80, n_content_pct=None),
        FertilizerApplication("DAP", 50, n_content_pct=None),
    ])
    [entry] = [m for m in missing_inputs(data, {"fertilizer": _refs("f", 3)}) if m.code == "fertilizer_nitrogen"]
    assert [r.activity_id for r in entry.records] == ["f-1", "f-2"]


def test_straw_records_are_merged_per_missing_field():
    data = season(straw=[
        StrawEvent(method="burned", mass_kg=1000, dry_matter_fraction=None),
        StrawEvent(method="removed", mass_kg=500),
        StrawEvent(method="incorporated", mass_kg=900, dry_matter_fraction=None, days_before_cultivation=None),
    ])
    by_code = {m.code: m for m in missing_inputs(data, {"straw_management": _refs("s", 3)})}
    assert [r.activity_id for r in by_code["straw_dry_matter"].records] == ["s-0", "s-2"]
    assert [r.activity_id for r in by_code["straw_days_before_cultivation"].records] == ["s-2"]


def test_refs_never_change_which_issues_are_reported():
    data = season(water_regime=None, fertilizer=[FertilizerApplication("NPK", 80, n_content_pct=None)])
    without = [(m.code, m.flow, m.blocking) for m in missing_inputs(data)]
    with_refs = [(m.code, m.flow, m.blocking) for m in missing_inputs(data, {"fertilizer": _refs("f", 1)})]
    assert without == with_refs


def test_misaligned_refs_attach_no_record_rather_than_a_wrong_one():
    data = season(fertilizer=[FertilizerApplication("NPK", 80, n_content_pct=None)])
    [entry] = [m for m in missing_inputs(data, {"fertilizer": _refs("f", 2)}) if m.code == "fertilizer_nitrogen"]
    assert entry.records == ()


def test_fuel_limitation_lists_the_fuel_records_to_view():
    data = season(fuel=[FuelUsage("diesel", 50), FuelUsage("gasoline", 5)])
    [entry] = [m for m in missing_inputs(data, {"fuel": _refs("u", 2)}) if m.code == "fuel_factor_unverified"]
    assert [r.activity_id for r in entry.records] == ["u-0", "u-1"]


# -- when the row mapper refuses before the engine sees anything ---------------
#
# `CarbonService.readiness` runs the real mapper. The mapper refuses for two
# different reasons with two different fixes; each must route to its own fix.

from infrastructure.mapping import RawCropBundle  # noqa: E402
from service import CarbonService  # noqa: E402


class _BundleRepo:
    def __init__(self, bundle: RawCropBundle):
        self._bundle = bundle

    def get_crop_bundle(self, crop_season_id: str) -> RawCropBundle:
        return self._bundle


def _service_readiness(*, area_ha, irrigation_methods=()):
    bundle = RawCropBundle(
        crop_season={"id": "ready-001", "pre_season_water_regime": "non_flooded_pre_season_lt_180d",
                     "cultivation_days": 100},
        plot={"area_ha": area_ha},
        activities=[{"activity_type": "irrigation", "deleted_at": None, "detail": {"method": m}}
                    for m in irrigation_methods],
    )
    return CarbonService(_BundleRepo(bundle), REAL).readiness("ready-001")


def test_missing_plot_area_routes_to_the_plot_not_the_water_regime_panel():
    payload = _service_readiness(area_ha=None, irrigation_methods=["continuous_flooding"])
    assert payload["can_calculate"] is False
    [entry] = payload["missing_inputs"]
    assert (entry["code"], entry["flow"]) == ("area", "plot")


def test_service_readiness_names_the_stored_record_ids_through_the_real_mapper():
    """End to end over the real mapper: ids come from the bundle rows, in the
    order the mapper feeds the engine, and a deleted row never shows up."""
    def act(id_, type_, detail, deleted=None):
        return {"id": id_, "activity_type": type_, "occurred_at": "2026-03-05T00:00:00Z",
                "deleted_at": deleted, "detail": detail}
    bundle = RawCropBundle(
        crop_season={"id": "ready-001", "ipcc_water_regime": "irrigated_continuous_flooding",
                      "pre_season_water_regime": "non_flooded_pre_season_lt_180d", "cultivation_days": 100},
        plot={"area_ha": 1.0},
        activities=[
            act("gone", "fertilizer", {"fertilizer_name": "Cũ", "amount_kg": 10}, deleted="2026-03-06"),
            act("urea", "fertilizer", {"fertilizer_name": "Urê", "amount_kg": 100, "nitrogen_percent": 46}),
            act("npk", "fertilizer", {"fertilizer_name": "NPK", "amount_kg": 80}),
            act("burn", "straw_management", {"method": "burned", "straw_mass_kg": 900}),
        ],
    )
    payload = CarbonService(_BundleRepo(bundle), REAL).readiness("ready-001")
    by_code = {m["code"]: m for m in payload["missing_inputs"]}
    assert by_code["fertilizer_nitrogen"]["records"] == [
        {"activity_id": "npk", "occurred_on": "2026-03-05", "label": "NPK"}]
    assert [r["activity_id"] for r in by_code["straw_dry_matter"]["records"]] == ["burn"]


def test_unmappable_irrigation_routes_to_the_water_regime_panel():
    payload = _service_readiness(area_ha=1.0, irrigation_methods=["alternate"])
    [entry] = payload["missing_inputs"]
    assert (entry["code"], entry["flow"]) == ("water_regime", FLOW_METHODOLOGY)
    assert "ipcc_water_regime" in entry["detail"]

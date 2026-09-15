"""Carbon Engine with the REAL, sourced factor set (AR5 GWP-100, IPCC 2019 Tier 1).

These are not golden numbers copied from the engine: every expected value below
is computed by hand from the cited factors and written out, then compared with
the engine. Sources: backend/config/emission_factors.yaml (0.3.0-ipcc2019-tier1-ar5)
and docs/methodology/carbon-factor-register.md.

Factors used by the hand calculation
  EFc  1.22 kg CH4/ha/day  IPCC 2019 Ref. Vol.4 Ch.5 Table 5.11 (Southeast Asia)
  SFw  1.00 continuous flooding / 0.55 multiple drainage (AWD)   Table 5.12
  SFp  1.00 non-flooded pre-season <180 d                        Table 5.13
  SFo  (1 + ROA x CFOA)^0.59, CFOA straw <30 d = 1.00             Eq 5.3, Table 5.14
  EF1FR 0.003 continuous / 0.005 single & multiple drainage kg N2O-N/kg N   Ch.11 Table 11.1
  44/28 N2O-N -> N2O
  Cf 0.80 rice residues; Gef CH4 2.7, N2O 0.07 g/kg DM           2006 GL Vol.4 Ch.2 Tables 2.6, 2.5
  GWP-100 CH4 28, N2O 265                                        AR5 WG1 Ch.8 Table 8.A.1
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from carbon import ParameterSet, calculate_carbon  # noqa: E402
from carbon.errors import MethodologyGapError, MissingActivityDataError, MissingEmissionFactorError  # noqa: E402
from carbon.factor_register import CORE_CODES  # noqa: E402
from carbon.models import CropActivityData, FertilizerApplication, FuelUsage, Harvest, StrawEvent  # noqa: E402
from infrastructure.mapping import RawCropBundle  # noqa: E402
from infrastructure.repository import InMemoryCarbonRepository  # noqa: E402
from recommendation.rules import evaluate_awd_rule  # noqa: E402
from service import CarbonService  # noqa: E402
from tests.fixtures import supabase_rows as rows  # noqa: E402

REAL = ParameterSet.load(BACKEND_DIR / "config" / "emission_factors.yaml")
N2O_PER_N2ON = 44 / 28


def season(**overrides) -> CropActivityData:
    base = dict(
        crop_season_id="hand-001", area_ha=1.0, water_regime="irrigated_continuous_flooding",
        pre_season_water_regime="non_flooded_pre_season_lt_180d", cultivation_days=100,
        harvest=Harvest(yield_kg=6000), fertilizer=[FertilizerApplication("Urea", 100, n_content_pct=46)],
    )
    base.update(overrides)
    return CropActivityData(**base)


def source(result, name, gas):
    return next(e for e in result.breakdown if e.source == name and e.gas == gas)


# -- hand calculation (mandatory cross-check) ----------------------------------

def test_hand_calculation_baseline_season():
    """1 ha, 100 days, continuously flooded, pre-season <180 d non-flooded, no amendment,
    100 kg urea at 46 % N, 6,000 kg paddy.

      CH4   = 1.22 x 1.00 x 1.00 x 1.0 (SFo, no amendment) x 100 d x 1 ha = 122.0 kg CH4
      CO2e  = 122.0 x 28                                                    = 3,416.0 kg
      N     = 100 kg x 46 %                                                 = 46.0 kg N
      N2O-N = 46.0 x 0.003                                                  = 0.138 kg
      N2O   = 0.138 x 44/28                                                 = 0.2168571 kg
      CO2e  = 0.2168571 x 265                                               = 57.4671 kg
      total = 3,416.0 + 57.4671                                             = 3,473.4671 kg CO2e
      CO2e/kg paddy = 3,473.4671 / 6,000                                    = 0.5789112
    """
    result = calculate_carbon(season(), "as_recorded", REAL)
    ch4 = source(result, "ch4_rice_cultivation", "ch4")
    n2o = source(result, "n2o_fertilizer_direct", "n2o")
    assert ch4.gas_kg == pytest.approx(122.0, rel=1e-12)
    assert ch4.co2e_kg == pytest.approx(3416.0, rel=1e-12)
    assert n2o.activity_value == pytest.approx(46.0)
    assert n2o.gas_kg == pytest.approx(0.138 * N2O_PER_N2ON, rel=1e-12)
    assert n2o.gas_kg == pytest.approx(0.2168571, abs=1e-7)
    assert n2o.co2e_kg == pytest.approx(57.4671, abs=1e-4)
    assert result.total_co2e_kg == pytest.approx(3473.4671, abs=1e-4)
    assert result.co2e_per_kg == pytest.approx(0.5789112, abs=1e-7)
    assert len(result.breakdown) == 2  # nothing else silently added


def test_awd_scenario_changes_both_ch4_and_n2o_factors_not_a_flat_percentage():
    """Same season, scenario AWD (multiple drainage):
      CH4  = 1.22 x 0.55 x 100 x 1 = 67.1 kg -> x 28 = 1,878.8 kg CO2e   (baseline 3,416.0)
      N2O  = 46 x 0.005 x 44/28 = 0.3614286 kg -> x 265 = 95.7786        (baseline 57.4671)
      total = 1,974.5786; reduction = 1,498.8886 kg CO2e (43.15 %) — CH4 falls, N2O rises.
    """
    baseline = calculate_carbon(season(), "as_recorded", REAL)
    awd = calculate_carbon(season(), "awd", REAL)
    assert awd.water_regime_applied == "irrigated_multiple_drainage"
    assert source(awd, "ch4_rice_cultivation", "ch4").co2e_kg == pytest.approx(1878.8, abs=1e-9)
    assert source(awd, "n2o_fertilizer_direct", "n2o").co2e_kg == pytest.approx(95.7786, abs=1e-4)
    assert awd.total_co2e_kg == pytest.approx(1974.5786, abs=1e-4)
    assert baseline.total_co2e_kg - awd.total_co2e_kg == pytest.approx(1498.8886, abs=1e-4)
    assert source(awd, "n2o_fertilizer_direct", "n2o").co2e_kg > source(baseline, "n2o_fertilizer_direct", "n2o").co2e_kg
    reduction = 1 - awd.total_co2e_kg / baseline.total_co2e_kg
    assert reduction == pytest.approx(0.43153, abs=1e-5)
    assert reduction != pytest.approx(0.45)  # not the SFw ratio applied to the total


def test_straw_incorporated_goes_to_sfo_only():
    """5,000 kg straw at 0.85 DM on 1 ha, 10 days before cultivation (<30 d, CFOA 1.00):
      ROA = 5,000 x 0.85 / 1,000 / 1 = 4.25 t/ha;  SFo = (1 + 4.25 x 1.00)^0.59 = 5.25^0.59 ≈ 2.66008
      CH4 = 122.0 x 2.66008 = 324.53 kg -> x 28 ≈ 9,086.8 kg CO2e; no burning source.
    """
    data = season(straw=[StrawEvent("incorporated", 5000, 0.85, days_before_cultivation=10)])
    result = calculate_carbon(data, "as_recorded", REAL)
    ch4 = source(result, "ch4_rice_cultivation", "ch4")
    sfo = 5.25 ** 0.59
    assert sfo == pytest.approx(2.66008, abs=1e-5)
    assert ch4.factors_used["_derived.sfo"] == pytest.approx(sfo, rel=1e-12)
    assert ch4.gas_kg == pytest.approx(122.0 * sfo, rel=1e-12)
    assert ch4.co2e_kg == pytest.approx(9086.8, abs=0.1)
    assert not any(e.source == "straw_burning" for e in result.breakdown)


def test_straw_burned_is_a_separate_source_and_does_not_touch_sfo():
    """2,000 kg straw at 0.85 DM burned:
      DM = 1,700 kg; burnt = 1,700 x 0.80 = 1,360 kg
      CH4 = 1,360 x 2.7 / 1,000 = 3.672 kg -> x 28 = 102.816 kg CO2e
      N2O = 1,360 x 0.07 / 1,000 = 0.0952 kg -> x 265 = 25.228 kg CO2e
      Rice CH4 stays 122.0 kg (SFo = 1): burned straw is not an organic amendment (Table 5.14 note a).
    """
    data = season(straw=[StrawEvent("burned", 2000, 0.85)])
    result = calculate_carbon(data, "as_recorded", REAL)
    assert source(result, "ch4_rice_cultivation", "ch4").gas_kg == pytest.approx(122.0, rel=1e-12)
    assert source(result, "straw_burning", "ch4").co2e_kg == pytest.approx(102.816, abs=1e-9)
    assert source(result, "straw_burning", "n2o").co2e_kg == pytest.approx(25.228, abs=1e-9)
    assert result.total_co2e_kg == pytest.approx(3473.4671 + 102.816 + 25.228, abs=1e-4)


def test_fuel_still_fails_closed_because_no_verified_factor_exists():
    with pytest.raises(MissingEmissionFactorError, match="fuel.diesel"):
        calculate_carbon(season(fuel=[FuelUsage("diesel", 20)]), "as_recorded", REAL)


def test_no_harvest_gives_total_but_no_intensity():
    result = calculate_carbon(season(harvest=Harvest(yield_kg=None)), "as_recorded", REAL)
    assert result.total_co2e_kg == pytest.approx(3473.4671, abs=1e-4)
    assert result.co2e_per_kg is None
    assert any("yield" in w.lower() or "sản lượng" in w.lower() for w in result.warnings)


@pytest.mark.parametrize(("overrides", "error"), [
    ({"pre_season_water_regime": None}, MethodologyGapError),
    ({"cultivation_days": None}, MissingActivityDataError),
    ({"fertilizer": [FertilizerApplication("Urea", 100, n_content_pct=None)]}, MissingActivityDataError),
    ({"water_regime": None}, MissingActivityDataError),
])
def test_missing_required_input_fails_instead_of_defaulting(overrides, error):
    with pytest.raises(error):
        calculate_carbon(season(**overrides), "as_recorded", REAL)


def test_results_carry_verified_provenance_and_honest_warnings():
    result = calculate_carbon(season(), "as_recorded", REAL)
    for entry in result.breakdown:
        assert entry.provenance and set(entry.parameter_status.values()) == {"VERIFIED"}
    assert result.ef_config_version == "0.3.0-ipcc2019-tier1-ar5"
    assert result.methodology["tier"] == 1
    assert any("MRV-compliant" in w for w in result.warnings)       # Tier 1 default, not national factors
    assert any("gián tiếp" in w or "indirect" in w.lower() for w in result.warnings)  # indirect N2O excluded
    assert result.total_co2e_kg > 0 and all(e.co2e_kg >= 0 for e in result.breakdown)


# -- persistence + recommendation reuse ------------------------------------------

def _bundle_without_fuel(regime: str) -> RawCropBundle:
    crop = rows.crop_season()
    crop["ipcc_water_regime"] = regime
    return RawCropBundle(
        crop_season=crop, plot=rows.plot(), farm={"id": rows.FARM_ID, "name": "Hộ demo"},
        production_batches=rows.production_batches(1),
        activities=[a for a in copy.deepcopy(rows.activities()) if a["activity_type"] != "fuel"],
    )


def _repository(bundle) -> InMemoryCarbonRepository:
    return InMemoryCarbonRepository(
        bundles={rows.CROP_ID: bundle},
        factor_sets={REAL.version: "set-real"},
        factors={"set-real": {code: f"ef-{code}" for code in CORE_CODES}},
    )


def test_persisted_calculation_links_factor_set_and_breakdown_factors():
    repo = _repository(_bundle_without_fuel("irrigated_multiple_drainage"))
    outcome = CarbonService(repo, REAL).calculate(rows.CROP_ID, "as_recorded")
    assert outcome.persisted and outcome.calculation_id
    stored = repo.calculations[0]
    assert stored["factor_set_id"] == "set-real" and stored["scenario"] == "actual"
    assert stored["total_co2e_kg"] > 0 and stored["engine_version"] and stored["input_hash"]
    breakdown = repo.breakdowns[outcome.calculation_id]
    linked = {b["category"]: b["emission_factor_id"] for b in breakdown}
    assert linked["irrigation_ch4"] == "ef-ch4_rice.efc"
    assert linked["fertilizer_n2o"] == "ef-n2o_fertilizer.ef1fr.single_and_multiple_drainage"


def test_recommendation_awd_reuses_carbon_service_without_persisting():
    repo = _repository(_bundle_without_fuel("irrigated_continuous_flooding"))
    carbon = CarbonService(repo, REAL)
    recommendation = evaluate_awd_rule(rows.CROP_ID, carbon)
    assert recommendation is not None and recommendation.impact_status == "available"
    baseline = carbon.calculate(rows.CROP_ID, "as_recorded", persist=False).result.total_co2e_kg
    awd = carbon.calculate(rows.CROP_ID, "awd", persist=False).result.total_co2e_kg
    assert recommendation.co2e_total_kg_delta == pytest.approx(baseline - awd)
    assert recommendation.co2e_total_kg_delta > 0
    assert repo.calculations == []  # persist=False wrote nothing

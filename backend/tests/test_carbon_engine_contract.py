"""Carbon Engine contract pins (Mutation Hardening V1, docs/MUTATION_BASELINE.md).

Each test closes a "missing meaningful test" survivor of `carbon/engine.py`
with an expectation taken from the documented contract or an invariant -- not
from a snapshot of today's output. No formula, factor or GWP is involved
beyond the TEST factor set the engine tests already use.
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from carbon import CropActivityData, MissingActivityDataError, ParameterSet, calculate_carbon, compute_input_hash  # noqa: E402
from carbon.engine import ENGINE_VERSION  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
TEST_FACTORS = FIXTURES / "test_factors.yaml"


@pytest.fixture
def params() -> ParameterSet:
    return ParameterSet.load(TEST_FACTORS)


@pytest.fixture
def demo() -> CropActivityData:
    with open(FIXTURES / "demo_crop.json", encoding="utf-8") as fh:
        return CropActivityData.from_dict(json.load(fh))


# -- identity of a stored result (idempotent save) -----------------------------------

def test_engine_version_is_the_persisted_identity(demo, params):
    # Stored with every result and part of the input hash: a change must be a
    # deliberate decision that invalidates idempotent saves, never an accident.
    assert ENGINE_VERSION == "0.2.0"
    assert calculate_carbon(demo, "awd", params).engine_version == ENGINE_VERSION


def test_input_hash_is_sha256_of_the_documented_payload(demo, params):
    # compute_input_hash docstring + carbon_input_hash_chk: SHA-256 over
    # canonical activity data | scenario | factor-set version | engine version.
    payload = "|".join([demo.canonical_json(), "awd", params.version, "0.2.0"])
    expected = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    assert compute_input_hash(demo, "awd", params) == expected
    assert calculate_carbon(demo, "awd", params).input_hash == expected


# -- the API contract of a result ------------------------------------------------------

def test_result_dict_has_exactly_the_contract_keys(demo, params):
    result = calculate_carbon(demo, "awd", params)
    as_dict = result.to_dict()
    assert set(as_dict) == {
        "crop_season_id", "scenario", "water_regime_applied", "total_co2e_kg", "yield_kg", "co2e_per_kg",
        "breakdown", "methodology", "ef_config_version", "engine_version", "input_hash", "calculated_at", "warnings",
    }
    assert as_dict["crop_season_id"] == demo.crop_season_id == "demo-001"
    assert as_dict["water_regime_applied"] == result.water_regime_applied == "irrigated_multiple_drainage"


def test_the_default_scenario_is_as_recorded(demo, params):
    default = calculate_carbon(demo, methodology_config=params)
    explicit = calculate_carbon(demo, "as_recorded", params)
    assert default.scenario == "as_recorded"
    assert default.water_regime_applied == demo.water_regime
    assert default.input_hash == explicit.input_hash and default.total_co2e_kg == explicit.total_co2e_kg


# -- boundaries -------------------------------------------------------------------------

def test_zero_cultivation_days_is_refused_one_day_is_accepted(demo, params):
    demo.cultivation_days = 0
    with pytest.raises(MissingActivityDataError, match="= 0"):
        calculate_carbon(demo, "awd", params)

    demo.cultivation_days = 1
    one_day = calculate_carbon(demo, "awd", params)
    demo.cultivation_days = 100
    hundred = calculate_carbon(demo, "awd", params)
    ch4 = lambda r: sum(e.co2e_kg for e in r.breakdown if e.gas == "ch4")  # noqa: E731
    # Eq 5.1: CH4 = EFi x t x A -- linear in the cultivation days.
    assert ch4(one_day) == pytest.approx(ch4(hundred) / 100)
    assert ch4(one_day) > 0


@pytest.mark.parametrize("yield_kg", [0.5, 1.0])
def test_a_yield_up_to_one_kg_still_divides(demo, params, yield_kg):
    # Only yield <= 0 is invalid (carbon_yield_chk); a tiny positive yield is data.
    demo.harvest.yield_kg = yield_kg
    result = calculate_carbon(demo, "awd", params)
    assert result.co2e_per_kg == pytest.approx(result.total_co2e_kg / yield_kg)


# -- provenance: a factor without a citation must surface -------------------------------

def _factor_set_with_blank_sources(tmp_path, *paths: tuple[str, ...]) -> ParameterSet:
    root = yaml.safe_load(TEST_FACTORS.read_text(encoding="utf-8"))
    for path in paths:
        node = root
        for key in path:
            node = node[key]
        node["source"] = "   " if path[-1] == "efc" else ""
    target = tmp_path / "factors.yaml"
    target.write_text(yaml.safe_dump(root, allow_unicode=True), encoding="utf-8")
    return ParameterSet.load(target)


def _citation_warnings(result) -> list[str]:
    return [w for w in result.warnings if w.startswith("Tham số thiếu nguồn trích dẫn")]


def test_no_citation_warning_when_every_parameter_has_a_source(demo, params):
    assert _citation_warnings(calculate_carbon(demo, "awd", params)) == []


def test_parameters_without_a_source_are_named_in_one_sorted_warning(demo, params, tmp_path):
    used = calculate_carbon(demo, "awd", params)
    cited = sorted({path for entry in used.breakdown for path in entry.provenance})
    assert len(cited) >= 3
    blanked = _factor_set_with_blank_sources(tmp_path, ("gwp", "ch4"), ("factors", "ch4_rice", "efc"))
    result = calculate_carbon(demo, "awd", blanked)
    missing = sorted(path for entry in result.breakdown for path, source in entry.provenance.items() if not source.strip())
    assert len(missing) == 2, missing  # whitespace-only counts as missing
    assert _citation_warnings(result) == ["Tham số thiếu nguồn trích dẫn: " + ", ".join(missing) + "."]
    # Only the uncited ones are named; the total is untouched by a citation.
    assert all(path not in _citation_warnings(result)[0] for path in set(cited) - set(missing))
    assert result.total_co2e_kg == pytest.approx(used.total_co2e_kg)


def test_the_input_is_not_mutated(demo, params):
    before = copy.deepcopy(demo)
    calculate_carbon(demo, "awd", params)
    assert demo == before

"""Factor register + importer validation (no database, no network).

The real parameter file must be activation-eligible; every deliberately broken
fixture must be rejected for the right reason, and nothing about readiness may
be claimed beyond what the file records.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from carbon import ParameterSet, calculate_carbon  # noqa: E402
from carbon.factor_register import (  # noqa: E402
    CORE_CODES,
    OPTIONAL_CODES,
    FactorSetValidationError,
    factor_set_row,
    load_parameter_file,
    readiness,
    validate_parameter_set,
)
from carbon.models import (  # noqa: E402
    CropActivityData,
    FertilizerApplication,
    Harvest,
    StrawEvent,
)
from scripts import import_factor_set  # noqa: E402

REAL = BACKEND_DIR / "config" / "emission_factors.yaml"
BROKEN = Path(__file__).resolve().parent / "fixtures" / "factor_sets"

EMISSION_CATEGORY = {"irrigation_ch4", "fertilizer_n2o", "fuel", "straw", "other", "straw_burning_ch4", "straw_burning_n2o", "electricity"}
PARAMETER_KIND = {"emission_factor", "scaling_factor", "conversion_factor", "gwp", "exponent", "default_value"}
GREENHOUSE_GAS = {"co2", "ch4", "n2o", "co2e"}


def test_real_parameter_file_is_activation_eligible():
    report = validate_parameter_set(load_parameter_file(REAL))
    summary = report.summary()
    assert summary["activation_eligible"] is True, summary
    assert summary["factor_count"] == len(CORE_CODES) == 27
    assert summary["missing_optional"] == ["fuel.diesel", "fuel.gasoline", "fuel.lpg"]
    assert summary["methodology"]["gwp_basis"] == "AR5"


def test_every_active_factor_has_a_real_source_reference_not_just_ipcc():
    for row in validate_parameter_set(load_parameter_file(REAL)).rows:
        assert row.verification_status == "VERIFIED"
        assert row.source_table_reference and ("Table" in row.source_table_reference or "Eq" in row.source_table_reference
                                                or "44/28" in row.source_table_reference), row.factor_code
        assert row.source_reference.strip().upper() != "IPCC"


def test_gwp_values_are_the_decided_ar5_basis():
    params = ParameterSet.load(REAL)
    assert params.gwp("ch4").value == 28
    assert params.gwp("n2o").value == 265
    assert "AR5" in (params.gwp("ch4").source or "") and "Table 8.A.1" in (params.gwp("n2o").source or "")


@pytest.mark.parametrize(("fixture", "field", "expected"), [
    ("missing_gwp.yaml", "missing_core", "gwp.ch4"),
    ("wrong_unit.yaml", "unit_mismatches", "ch4_rice.efc"),
    ("unverified_source.yaml", "unverified", "straw_burning.gef_ch4"),
    ("incomplete_fuel.yaml", "errors", "fuel.diesel: unit is required"),
])
def test_broken_fixtures_are_rejected_for_the_right_reason(fixture, field, expected):
    report = validate_parameter_set(load_parameter_file(BROKEN / fixture))
    assert report.activation_eligible is False
    assert any(expected in item for item in getattr(report, field)), report.summary()


def test_duplicate_factor_key_is_rejected_at_load():
    with pytest.raises(FactorSetValidationError, match="duplicate key 'efc'"):
        load_parameter_file(BROKEN / "duplicate_factor.yaml")


@pytest.mark.parametrize(("mutate", "message"), [
    (lambda r: r["factors"]["ch4_rice"]["efc"].update(value="1.22"), "value must be a finite number"),
    (lambda r: r["factors"]["ch4_rice"]["efc"].update(value=-1), "must not be negative"),
    (lambda r: r["factors"]["ch4_rice"]["efc"].update(source=""), "source is required"),
    (lambda r: r["factors"]["ch4_rice"]["sfw"]["upland"].update(source="IPCC 2019 Refinement, Vol.4, Ch.5"), "table/equation reference"),
    (lambda r: r["methodology"].update(tier=2), "methodology.tier"),
    (lambda r: r["gwp"]["framework"].update(value="AR6"), "GWP basis"),
    (lambda r: r["methodology"]["sources"][0].update(url="ipcc.ch/report"), "https URL"),
    (lambda r: r["factors"]["ch4_rice"].update(sfs={"value": 1.0, "unit": "dimensionless", "status": "VERIFIED", "source": "Table X"}), None),
])
def test_fail_closed_validation_rules(mutate, message):
    root = copy.deepcopy(load_parameter_file(REAL))
    mutate(root)
    report = validate_parameter_set(root)
    assert report.activation_eligible is False
    if message is None:
        assert report.unsupported == ["ch4_rice.sfs"]
    else:
        assert any(message in e for e in report.errors), report.summary()


def test_db_rows_use_valid_schema_enums():
    report = validate_parameter_set(load_parameter_file(REAL))
    for row in report.rows:
        db = row.as_db_row("set-id")
        assert db["category"] in EMISSION_CATEGORY
        assert db["parameter_kind"] in PARAMETER_KIND
        assert db["gas"] is None or db["gas"] in GREENHOUSE_GAS
        if db["parameter_kind"] == "emission_factor":
            assert db["gas"] is not None  # ef_gas_required_for_emission_factor_chk
        assert db["activity_unit"].strip() and db["result_unit"].strip() and db["source_reference"].strip()
        assert db["factor_value"] >= 0
    set_row = factor_set_row(load_parameter_file(REAL))
    assert set_row["version_code"] == "0.3.0-ipcc2019-tier1-ar5"
    assert set_row["source_url"].startswith("https://")
    assert "Not a certification" in set_row["description"]


def test_engine_consumes_only_registered_factor_codes():
    """Guard against the register drifting from the engine."""
    data = CropActivityData(
        crop_season_id="s", area_ha=1.0, water_regime="rainfed_regular",
        pre_season_water_regime="flooded_pre_season_gt_30d", cultivation_days=100,
        harvest=Harvest(yield_kg=5000),
        fertilizer=[FertilizerApplication("Urea", 100, n_content_pct=46)],
        straw=[StrawEvent("incorporated", 1000, 0.85, days_before_cultivation=40),
               StrawEvent("burned", 1000, 0.85)],
    )
    result = calculate_carbon(data, "as_recorded", ParameterSet.load(REAL))
    used = {key.removeprefix("factors.") for entry in result.breakdown for key in entry.factors_used if not key.startswith("_")}
    assert used, "breakdown must record the factors it used"
    assert used <= set(CORE_CODES) | set(OPTIONAL_CODES), used - set(CORE_CODES)


def test_readiness_levels_follow_recorded_evidence():
    real = load_parameter_file(REAL)
    assert readiness(real)["level"] == "READY_FOR_DEMO"
    assert readiness(real)["domain_expert_review"] == "PENDING"
    assert readiness(load_parameter_file(BROKEN / "missing_gwp.yaml"))["level"] == "STILL_BLOCKED"
    reviewed = copy.deepcopy(real)
    reviewed["methodology"]["domain_expert_review"] = "COMPLETE"
    assert readiness(reviewed)["level"] == "READY_FOR_PILOT"


@pytest.mark.parametrize(("fixture", "exit_code"), [(REAL, 0), (BROKEN / "wrong_unit.yaml", 1), (BROKEN / "duplicate_factor.yaml", 2)])
def test_importer_dry_run_never_touches_the_database(monkeypatch, capsys, fixture, exit_code):
    monkeypatch.setattr(import_factor_set, "_connect", lambda: pytest.fail("dry run must not connect"))
    assert import_factor_set.main(["--file", str(fixture)]) == exit_code
    assert '"activation_eligible"' in capsys.readouterr().out


def test_importer_refuses_to_apply_an_ineligible_set_without_connecting(monkeypatch):
    monkeypatch.setattr(import_factor_set, "_connect", lambda: pytest.fail("ineligible set must not connect"))
    assert import_factor_set.main(["--file", str(BROKEN / "unverified_source.yaml"), "--apply", "--publish"]) == 1


def test_health_reports_demo_readiness_but_not_production_or_mrv():
    from fastapi.testclient import TestClient
    from main import app

    body = TestClient(app).get("/health").json()
    assert body["ef_config_version"] == "0.3.0-ipcc2019-tier1-ar5"
    assert body["carbon_scientific_readiness"]["level"] == "READY_FOR_DEMO"
    assert body["carbon_scientific_readiness"]["domain_expert_review"] == "PENDING"
    assert body["carbon_production_ready"] is False
    assert body["mrv_compliant"] is False

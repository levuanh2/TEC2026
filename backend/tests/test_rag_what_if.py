"""CarbonScenarioWhatIf: every number is the injected Carbon service's, every
call is persist=False, only the water regime is simulated (decision D2), an
engine refusal is an unavailable result."""

from __future__ import annotations

import pytest

from recommendation.rag import (
    SUPPORTED_WHAT_IF_DIMENSIONS,
    CarbonScenarioWhatIf,
    HypotheticalChange,
    UnsupportedWhatIfDimension,
    WhatIfDimension,
)
from tests.fixtures.rag_fakes import SEASON_ID, FakeCarbonCalculator, scope


def test_v1_supports_the_water_regime_only():
    assert SUPPORTED_WHAT_IF_DIMENSIONS == {WhatIfDimension.WATER_REGIME}


def test_both_runs_are_non_persistent_on_the_authorized_season():
    carbon = FakeCarbonCalculator(totals={"as_recorded": 10.0, "continuous_flooding": 12.5})
    result = CarbonScenarioWhatIf(carbon).simulate(
        scope(), HypotheticalChange(dimension="water_regime", scenario="continuous_flooding"))
    assert carbon.calls == [(SEASON_ID, "as_recorded", False), (SEASON_ID, "continuous_flooding", False)]
    assert result.status == "available"
    assert result.delta_co2e_kg == -2.5
    assert (result.baseline_input_hash, result.hypothetical_input_hash) == ("hash-as_recorded", "hash-continuous_flooding")
    assert result.engine_version == "carbon-1" and result.ef_config_version == "test-factors"
    assert result.persisted is False


@pytest.mark.parametrize("dimension", sorted(set(WhatIfDimension) - SUPPORTED_WHAT_IF_DIMENSIONS))
def test_simulator_itself_refuses_unsupported_dimensions(dimension):
    carbon = FakeCarbonCalculator(totals={"as_recorded": 10.0})
    with pytest.raises(UnsupportedWhatIfDimension):
        CarbonScenarioWhatIf(carbon).simulate(scope(), HypotheticalChange(dimension=dimension))
    assert carbon.calls == []


def test_engine_refusal_is_unavailable_with_the_engine_reason():
    result = CarbonScenarioWhatIf(FakeCarbonCalculator(totals={}, refuse=True)).simulate(
        scope(), HypotheticalChange(dimension="water_regime", scenario="awd"))
    assert result.status == "unavailable"
    assert "gwp.ch4" in (result.unavailable_reason or "")
    assert result.baseline_total_co2e_kg is None and result.delta_co2e_kg is None


def test_infrastructure_failure_is_not_turned_into_a_result():
    class Broken:
        def calculate(self, *args, **kwargs):
            raise ConnectionError("db down")

    with pytest.raises(ConnectionError):
        CarbonScenarioWhatIf(Broken()).simulate(scope(), HypotheticalChange(dimension="water_regime", scenario="awd"))

"""SeasonRagContext — the season's authoritative facts, typed for RAG.

`build_season_context` only PICKS fields from rows that existing Core V1
services already produced (Resource Metrics, CarbonService, the deterministic
rules, CV). Allowed transforms: field selection, renaming, and type coercion
(an ISO date string -> date, a numeric string -> float). Nothing is summed,
divided, defaulted or recomputed here: a missing value stays None, never 0.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Annotated, Any, Literal, TypeVar
from uuid import UUID

from pydantic import BeforeValidator

from .contracts import SeasonFactsSource
from .intents import RagMode
from .models import AuthorizedSeasonScope, Contract, Identifier


#: psycopg rows carry `uuid.UUID`; the API's JSON carries strings. Same value.
RowId = Annotated[str, BeforeValidator(lambda v: str(v) if isinstance(v, UUID) else v)]


class SeasonFacts(Contract):
    season_code: str | None = None
    crop_type: str | None = None
    variety_name: str | None = None
    status: str | None = None
    planting_date: date | None = None
    expected_harvest_date: date | None = None
    actual_harvest_date: date | None = None
    ipcc_water_regime: str | None = None
    pre_season_water_regime: str | None = None
    cultivation_days: int | None = None


class ActivityFacts(Contract):
    total: int | None = None
    count_by_type: dict[str, int] | None = None
    harvests: int | None = None
    harvests_with_area: int | None = None
    harvested_area_ha: float | None = None
    fertilizer_has_nutrient: bool | None = None
    first_seeding_at: str | None = None
    last_harvest_at: str | None = None


class MetricCompleteness(Contract):
    water: bool | None = None
    fertilizer: bool | None = None
    cost: bool | None = None
    carbon: bool | None = None


class ResourceMetricFacts(Contract):
    yield_kg: float | None = None
    water_m3: float | None = None
    fertilizer_kg: float | None = None
    total_co2e_kg: float | None = None
    water_per_kg: float | None = None
    fertilizer_per_kg: float | None = None
    co2e_per_kg: float | None = None
    cost_per_kg: float | None = None
    data_completeness: MetricCompleteness | None = None


class CarbonBreakdownFacts(Contract):
    category: str | None = None
    gas: str | None = None
    source: str | None = None
    co2e_kg: float | None = None


class CarbonFacts(Contract):
    calculation_id: RowId | None = None
    scenario: str | None = None
    calculation_kind: str | None = None
    total_co2e_kg: float | None = None
    water_regime_applied: str | None = None
    methodology_tier: str | None = None
    mrv_compliant: bool | None = None
    ef_config_version: str | None = None
    engine_version: str | None = None
    input_hash: str | None = None
    calculated_at: datetime | None = None
    breakdown: tuple[CarbonBreakdownFacts, ...] = ()


class MissingInputFacts(Contract):
    code: str | None = None
    label: str | None = None
    flow: str | None = None


class CarbonReadinessFacts(Contract):
    can_calculate: bool | None = None
    blocking_count: int | None = None
    input_hash: str | None = None
    missing_inputs: tuple[MissingInputFacts, ...] = ()


class DeterministicSignal(Contract):
    """One deterministic rule outcome, verbatim. `status` is None for a fresh
    (preview) evaluation that was never stored."""

    rule_code: str
    rule_version: str | None = None
    type: Literal["optimization", "data_task"]
    status: str | None = None
    title: str | None = None
    reason: str | None = None
    compared_to: str | None = None
    impact_status: str | None = None
    impact_unavailable_reason: str | None = None
    co2e_total_kg_before: float | None = None
    co2e_total_kg_after: float | None = None
    co2e_total_kg_delta: float | None = None
    co2e_percent_delta: float | None = None


class CvSignal(Contract):
    """A recorded CV inference — a signal only; RAG never re-diagnoses."""

    label: str | None = None
    confidence: float | None = None
    uncertain: bool | None = None
    model_version: str | None = None
    created_at: datetime | None = None


class SeasonRagContext(Contract):
    organization_id: Identifier
    farm_id: Identifier
    plot_id: Identifier
    crop_season_id: Identifier
    season: SeasonFacts
    activity: ActivityFacts
    metrics: ResourceMetricFacts
    carbon: CarbonFacts | None
    carbon_readiness: CarbonReadinessFacts | None
    signals: tuple[DeterministicSignal, ...]
    cv_signals: tuple[CvSignal, ...]

    @property
    def signal_rule_codes(self) -> frozenset[str]:
        return frozenset(signal.rule_code for signal in self.signals)


_Facts = TypeVar("_Facts", bound=Contract)


def _pick(model: type[_Facts], row: Mapping[str, Any]) -> _Facts:
    """Exactly the model's fields, taken as-is; an absent key is None."""
    return model.model_validate({name: row.get(name) for name in model.model_fields})


def _carbon(row: Mapping[str, Any]) -> CarbonFacts:
    scalars = {name: row.get(name) for name in CarbonFacts.model_fields if name != "breakdown"}
    breakdown = tuple(_pick(CarbonBreakdownFacts, item) for item in row.get("breakdown") or ())
    return CarbonFacts.model_validate({**scalars, "breakdown": breakdown})


def _readiness(row: Mapping[str, Any]) -> CarbonReadinessFacts:
    scalars = {name: row.get(name) for name in CarbonReadinessFacts.model_fields if name != "missing_inputs"}
    missing = tuple(_pick(MissingInputFacts, item) for item in row.get("missing_inputs") or ())
    return CarbonReadinessFacts.model_validate({**scalars, "missing_inputs": missing})


def _metrics(row: Mapping[str, Any]) -> ResourceMetricFacts:
    scalars = {name: row.get(name) for name in ResourceMetricFacts.model_fields if name != "data_completeness"}
    completeness = row.get("data_completeness")
    return ResourceMetricFacts.model_validate({
        **scalars,
        "data_completeness": _pick(MetricCompleteness, completeness) if completeness is not None else None,
    })


def build_season_context(
    scope: AuthorizedSeasonScope, facts: SeasonFactsSource, *, mode: RagMode,
) -> SeasonRagContext:
    sid = scope.crop_season_id
    carbon = facts.carbon_actual(sid)
    readiness = facts.carbon_readiness(sid)
    return SeasonRagContext(
        organization_id=scope.organization_id,
        farm_id=scope.farm_id,
        plot_id=scope.plot_id,
        crop_season_id=sid,
        season=_pick(SeasonFacts, facts.season(sid)),
        activity=_pick(ActivityFacts, facts.activity_summary(sid)),
        metrics=_metrics(facts.metrics(sid)),
        carbon=_carbon(carbon) if carbon is not None else None,
        carbon_readiness=_readiness(readiness) if readiness is not None else None,
        signals=tuple(
            _pick(DeterministicSignal, row)
            for row in facts.recommendation_signals(sid, fresh=mode is RagMode.PREVIEW)
        ),
        cv_signals=tuple(_pick(CvSignal, row) for row in facts.cv_signals(sid)),
    )

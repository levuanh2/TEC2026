"""System facts: the season's authoritative values as `GroundedFact`s with
stable, trusted ids — the only channel through which a number reaches an
answer (quantitative claim policy, docs/rag/RAG_V1_ARCHITECTURE.md §13).

Fact ids are `<subject>.<group>.<name>`, built here and nowhere else:
  current.metrics.water_per_kg            this season's Resource Metric
  current.carbon.total_co2e_kg            this season's stored Carbon result
  current.signal.<rule_code>.<field>      a deterministic rule outcome
  what_if.<scenario>.delta_co2e_kg        a Carbon-service what-if
  benchmark.<benchmark_id>                a finalized benchmark
  season.<crop_season_id>.metrics.<name>  an authorized comparison season

Values are copied from `SeasonRagContext` / `WhatIfResult`; nothing is computed.
"""

from __future__ import annotations

from collections.abc import Iterable

from .context import ResourceMetricFacts, SeasonRagContext
from .errors import TenantIsolationViolation
from .models import AuthorizedSeasonScope, FactKind, GroundedFact, Scalar, WhatIfResult

CURRENT = "current"

_KG_CO2E = "kg CO2e"
#: Resource Metric field -> (kind, unit). Units describe the Core V1 values.
METRIC_FACTS: dict[str, tuple[FactKind, str]] = {
    "yield_kg": (FactKind.RESOURCE_METRIC, "kg"),
    "water_m3": (FactKind.RESOURCE_METRIC, "m3"),
    "fertilizer_kg": (FactKind.RESOURCE_METRIC, "kg"),
    "total_co2e_kg": (FactKind.CARBON_TOTAL, _KG_CO2E),
    "water_per_kg": (FactKind.RESOURCE_METRIC, "m3/kg"),
    "fertilizer_per_kg": (FactKind.RESOURCE_METRIC, "kg/kg"),
    "co2e_per_kg": (FactKind.CARBON_INTENSITY, "kg CO2e/kg"),
    "cost_per_kg": (FactKind.RESOURCE_METRIC, "VND/kg"),
}
_SEASON_ATTRIBUTES = ("status", "crop_type", "ipcc_water_regime", "pre_season_water_regime", "cultivation_days")
_SIGNAL_TEXT = ("title", "reason", "compared_to", "impact_status", "impact_unavailable_reason", "status")
_SIGNAL_NUMBERS: dict[str, str] = {
    "co2e_total_kg_before": _KG_CO2E,
    "co2e_total_kg_after": _KG_CO2E,
    "co2e_total_kg_delta": _KG_CO2E,
    "co2e_percent_delta": "fraction",
}
_WHAT_IF_NUMBERS = ("baseline_total_co2e_kg", "hypothetical_total_co2e_kg", "delta_co2e_kg")

#: Kinds that give COMPARE something to compare against.
COMPARISON_KINDS = frozenset({FactKind.BENCHMARK, FactKind.COMPARISON_SEASON})


class _Catalog:
    def __init__(self, context: SeasonRagContext) -> None:
        self._context = context
        self._facts: dict[str, GroundedFact] = {}

    def add(
        self, fact_id: str, kind: FactKind, value: Scalar, *, source: str, unit: str | None = None,
        provenance: dict[str, Scalar] | None = None, season: str | None = None, organization: str | None = None,
        current: bool = True,
    ) -> None:
        if fact_id in self._facts:
            raise ValueError(f"duplicate fact id {fact_id}")
        self._facts[fact_id] = GroundedFact(
            fact_id=fact_id, kind=kind, value=value, unit=unit, source=source, provenance=provenance or {},
            crop_season_id=self._context.crop_season_id if current else season,
            organization_id=self._context.organization_id if current else organization,
        )

    def metrics(self, prefix: str, metrics: ResourceMetricFacts, *, kind: FactKind | None = None, **scope) -> None:
        for name, (metric_kind, unit) in METRIC_FACTS.items():
            self.add(f"{prefix}.metrics.{name}", kind or metric_kind, getattr(metrics, name),
                     unit=unit, source="resource_metrics", **scope)

    def facts(self) -> tuple[GroundedFact, ...]:
        return tuple(self._facts.values())


def build_fact_catalog(context: SeasonRagContext, what_if: WhatIfResult | None = None) -> tuple[GroundedFact, ...]:
    catalog = _Catalog(context)
    for name in _SEASON_ATTRIBUTES:
        catalog.add(f"{CURRENT}.season.{name}", FactKind.SEASON_ATTRIBUTE, getattr(context.season, name),
                    source="season")

    catalog.metrics(CURRENT, context.metrics)
    completeness = context.metrics.data_completeness
    if completeness is not None:
        for name, value in completeness.model_dump().items():
            catalog.add(f"{CURRENT}.completeness.{name}", FactKind.DATA_COMPLETENESS, value, source="resource_metrics")

    carbon = context.carbon
    if carbon is not None:
        provenance: dict[str, Scalar] = {
            "calculation_id": carbon.calculation_id, "input_hash": carbon.input_hash,
            "engine_version": carbon.engine_version, "ef_config_version": carbon.ef_config_version,
        }
        catalog.add(f"{CURRENT}.carbon.total_co2e_kg", FactKind.CARBON_TOTAL, carbon.total_co2e_kg,
                    unit=_KG_CO2E, source="carbon_service", provenance=provenance)
        for index, item in enumerate(carbon.breakdown):
            catalog.add(f"{CURRENT}.carbon.breakdown.{index}", FactKind.CARBON_BREAKDOWN, item.co2e_kg,
                        unit=_KG_CO2E, source="carbon_service",
                        provenance={**provenance, "category": item.category, "gas": item.gas, "source": item.source})

    readiness = context.carbon_readiness
    if readiness is not None:
        catalog.add(f"{CURRENT}.readiness.can_calculate", FactKind.CARBON_READINESS, readiness.can_calculate,
                    source="carbon_service")
        catalog.add(f"{CURRENT}.readiness.blocking_count", FactKind.CARBON_READINESS, readiness.blocking_count,
                    source="carbon_service")
        for item in readiness.missing_inputs:
            if item.code:
                catalog.add(f"{CURRENT}.readiness.missing.{item.code}", FactKind.CARBON_READINESS, item.label,
                            source="carbon_service", provenance={"flow": item.flow})

    for signal in context.signals:
        base = f"{CURRENT}.signal.{signal.rule_code}"
        provenance = {"rule_code": signal.rule_code, "rule_version": signal.rule_version, "type": signal.type}
        for name in _SIGNAL_TEXT:
            catalog.add(f"{base}.{name}", FactKind.RULE_SIGNAL, getattr(signal, name),
                        source="recommendation_rules", provenance=provenance)
        for name, unit in _SIGNAL_NUMBERS.items():
            catalog.add(f"{base}.{name}", FactKind.RULE_SIGNAL, getattr(signal, name), unit=unit,
                        source="recommendation_rules", provenance=provenance)

    for index, cv in enumerate(context.cv_signals):
        provenance = {"model_version": cv.model_version}
        catalog.add(f"{CURRENT}.cv.{index}.label", FactKind.CV_SIGNAL, cv.label, source="cv_service",
                    provenance=provenance)
        catalog.add(f"{CURRENT}.cv.{index}.confidence", FactKind.CV_SIGNAL, cv.confidence, unit="fraction",
                    source="cv_service", provenance=provenance)
        catalog.add(f"{CURRENT}.cv.{index}.uncertain", FactKind.CV_SIGNAL, cv.uncertain, source="cv_service",
                    provenance=provenance)

    for benchmark in context.benchmarks:
        catalog.add(f"benchmark.{benchmark.benchmark_id}", FactKind.BENCHMARK, benchmark.value, unit=benchmark.unit,
                    source="benchmark", current=False, organization=benchmark.organization_id,
                    provenance={"metric": benchmark.metric, "label": benchmark.label,
                                "source_reference": benchmark.source_reference, "status": benchmark.status})

    for other in context.comparison_seasons:
        catalog.metrics(f"season.{other.crop_season_id}", other.metrics, kind=FactKind.COMPARISON_SEASON,
                        current=False, season=other.crop_season_id, organization=other.organization_id)

    if what_if is not None:
        base = f"what_if.{what_if.change.scenario}"
        provenance = {
            "dimension": str(what_if.change.dimension), "scenario": what_if.change.scenario,
            "baseline_input_hash": what_if.baseline_input_hash,
            "hypothetical_input_hash": what_if.hypothetical_input_hash,
            "engine_version": what_if.engine_version, "ef_config_version": what_if.ef_config_version,
        }
        catalog.add(f"{base}.status", FactKind.WHAT_IF, what_if.status, source="carbon_service", provenance=provenance)
        catalog.add(f"{base}.unavailable_reason", FactKind.WHAT_IF, what_if.unavailable_reason,
                    source="carbon_service", provenance=provenance)
        for name in _WHAT_IF_NUMBERS:
            catalog.add(f"{base}.{name}", FactKind.WHAT_IF, getattr(what_if, name), unit=_KG_CO2E,
                        source="carbon_service", provenance=provenance)
    return catalog.facts()


def assert_fact_scope(facts: Iterable[GroundedFact], scope: AuthorizedSeasonScope, context: SeasonRagContext) -> None:
    """Backstop: every fact belongs to the caller's organization (or to none,
    a public benchmark) and to the season or one of its authorized
    comparison seasons. Anything else is a tenant-isolation failure."""
    seasons = {scope.crop_season_id, *(other.crop_season_id for other in context.comparison_seasons)}
    for fact in facts:
        if fact.organization_id not in (None, scope.organization_id) or fact.crop_season_id not in (None, *seasons):
            raise TenantIsolationViolation(f"system fact outside the caller's scope: {fact.fact_id}")


def has_comparison_basis(facts: Iterable[GroundedFact]) -> bool:
    return any(fact.kind in COMPARISON_KINDS and fact.value is not None for fact in facts)

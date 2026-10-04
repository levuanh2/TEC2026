"""Deterministic test doubles for the RAG ports (recommendation/rag/contracts.py).

⛔ Fake data. Every fake records its calls in a shared `calls` list so tests
can assert step order and that nothing ran after a refusal. No global state:
each test builds its own fakes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from carbon import CarbonEngineError
from recommendation.rag import (
    AccessLevel,
    AuthorizedSeasonScope,
    EvidenceChunk,
    GenerationInput,
    RagAccessDenied,
    RetrievalQuery,
)

SEASON_ID = "11111111-1111-1111-1111-111111111111"
PLOT_ID = "22222222-2222-2222-2222-222222222222"
FARM_ID = "33333333-3333-3333-3333-333333333333"
ORG_ID = "66666666-6666-6666-6666-666666666666"
OTHER_ORG_ID = "77777777-7777-7777-7777-777777777777"
ACTOR_ID = "88888888-8888-8888-8888-888888888888"
AWD_RULE = "water.awd_from_continuous_flooding"


def scope(*, crop_season_id: str = SEASON_ID, access: AccessLevel = AccessLevel.READ) -> AuthorizedSeasonScope:
    return AuthorizedSeasonScope(
        actor_id=ACTOR_ID, organization_id=ORG_ID, farm_id=FARM_ID, plot_id=PLOT_ID,
        crop_season_id=crop_season_id, access=access,
    )


def public_chunk(chunk_id: str = "c1", source_id: str = "guide-awd", **overrides: Any) -> EvidenceChunk:
    return EvidenceChunk(**{
        "source_id": source_id, "document_id": f"doc-{source_id}", "document_version": "2024.1",
        "chunk_id": chunk_id, "title": "Hướng dẫn tưới AWD", "section": "2. Kỹ thuật",
        "content": "Ruộng rút nước khi mực nước xuống 15 cm dưới mặt đất.", "source_type": "guideline",
        "visibility": "public", "url": f"https://example.org/{source_id}", **overrides,
    })


def tenant_chunk(chunk_id: str = "t1", *, organization_id: str = ORG_ID, farm_id: str | None = None) -> EvidenceChunk:
    return EvidenceChunk(
        source_id="htx-sop", document_id="doc-htx-sop", chunk_id=chunk_id, title="Quy trình HTX",
        content="Lịch tưới nội bộ của HTX.", source_type="tenant_document", visibility="tenant",
        organization_id=organization_id, farm_id=farm_id,
    )


def season_row() -> dict[str, Any]:
    return {
        "id": SEASON_ID, "plot_id": PLOT_ID, "season_code": "HT-2026", "crop_type": "rice",
        "variety_name": "OM5451", "planting_date": "2026-05-01", "expected_harvest_date": "2026-08-20",
        "actual_harvest_date": None, "status": "active", "ipcc_water_regime": "irrigated_continuous_flooding",
        "pre_season_water_regime": None, "cultivation_days": 100,
    }


def metrics_row() -> dict[str, Any]:
    # Deliberately inconsistent co2e_per_kg (≠ total/yield): proves the
    # context copies the authoritative number instead of recomputing it.
    return {
        "yield_kg": 5000.0, "water_m3": None, "fertilizer_kg": "250.5", "total_co2e_kg": 2900.0,
        "water_per_kg": None, "fertilizer_per_kg": 0.0501, "co2e_per_kg": 0.58, "cost_per_kg": None,
        "data_completeness": {"water": False, "fertilizer": True, "cost": False, "carbon": True},
    }


def signal_row(rule_code: str = AWD_RULE, **overrides: Any) -> dict[str, Any]:
    return {
        "id": "rec-1", "crop_season_id": SEASON_ID, "rule_code": rule_code, "rule_version": "1",
        "engine_version": "1", "type": "optimization", "status": "generated",
        "title": "Cân nhắc tưới AWD", "reason": "Vụ đang tưới ngập liên tục.", "compared_to": None,
        "impact_status": "available", "impact_unavailable_reason": None,
        "co2e_total_kg_before": 2900.0, "co2e_total_kg_after": 2300.0, "co2e_total_kg_delta": 600.0,
        "co2e_percent_delta": 0.2069, "generated_at": "2026-09-01T00:00:00Z", **overrides,
    }


@dataclass
class FakeAccessGate:
    calls: list[str]
    deny: bool = False
    returned_season_id: str | None = None
    levels: list[AccessLevel] = field(default_factory=list)

    def authorize(self, crop_season_id: str, level: AccessLevel) -> AuthorizedSeasonScope:
        self.calls.append("authorize")
        self.levels.append(level)
        if self.deny:
            raise RagAccessDenied(crop_season_id)
        return scope(crop_season_id=self.returned_season_id or crop_season_id, access=level)


@dataclass
class FakeFactsSource:
    """Rows shaped like the Core V1 reads they stand for (contract §9)."""

    calls: list[str]
    season_data: Mapping[str, Any] = field(default_factory=season_row)
    activity: Mapping[str, Any] = field(default_factory=lambda: {"total": 7, "harvests": 0})
    metric_row: Mapping[str, Any] = field(default_factory=metrics_row)
    carbon: Mapping[str, Any] | None = None
    readiness: Mapping[str, Any] | None = None
    signals: Sequence[Mapping[str, Any]] = field(default_factory=lambda: [signal_row()])
    cv: Sequence[Mapping[str, Any]] = ()
    reads: list[str] = field(default_factory=list)
    fresh_flags: list[bool] = field(default_factory=list)

    def _log(self, name: str) -> None:
        if not self.reads:
            self.calls.append("context")
        self.reads.append(name)

    def season(self, crop_season_id: str) -> Mapping[str, Any]:
        self._log("season")
        return self.season_data

    def activity_summary(self, crop_season_id: str) -> Mapping[str, Any]:
        self._log("activity_summary")
        return self.activity

    def metrics(self, crop_season_id: str) -> Mapping[str, Any]:
        self._log("metrics")
        return self.metric_row

    def carbon_actual(self, crop_season_id: str) -> Mapping[str, Any] | None:
        self._log("carbon_actual")
        return self.carbon

    def carbon_readiness(self, crop_season_id: str) -> Mapping[str, Any] | None:
        self._log("carbon_readiness")
        return self.readiness

    def recommendation_signals(self, crop_season_id: str, *, fresh: bool) -> Sequence[Mapping[str, Any]]:
        self._log("recommendation_signals")
        self.fresh_flags.append(fresh)
        return self.signals

    def cv_signals(self, crop_season_id: str) -> Sequence[Mapping[str, Any]]:
        self._log("cv_signals")
        return self.cv


@dataclass
class FakeRetriever:
    calls: list[str]
    chunks: Sequence[EvidenceChunk] = ()
    error: Exception | None = None
    queries: list[RetrievalQuery] = field(default_factory=list)

    def retrieve(self, query: RetrievalQuery) -> Sequence[EvidenceChunk]:
        self.calls.append("retrieve")
        self.queries.append(query)
        if self.error is not None:
            raise self.error
        return self.chunks


@dataclass
class FakeGenerator:
    calls: list[str]
    output: Any = None
    error: Exception | None = None
    inputs: list[GenerationInput] = field(default_factory=list)

    def generate(self, request: GenerationInput) -> Any:
        self.calls.append("generate")
        self.inputs.append(request)
        if self.error is not None:
            raise self.error
        return self.output


@dataclass
class _Result:
    total_co2e_kg: float
    input_hash: str
    engine_version: str = "carbon-1"
    ef_config_version: str = "test-factors"
    water_regime_applied: str = "irrigated_continuous_flooding"


@dataclass
class _Outcome:
    result: _Result
    persisted: bool = False


@dataclass
class FakeCarbonCalculator:
    """Stands in for `service.CarbonService`; totals per scenario are given."""

    totals: Mapping[str, float]
    refuse: bool = False
    calls: list[tuple[str, str, bool]] = field(default_factory=list)

    def calculate(self, crop_season_id: str, scenario: str = "as_recorded", *, persist: bool = True) -> _Outcome:
        self.calls.append((crop_season_id, scenario, persist))
        if self.refuse:
            raise CarbonEngineError("Thiếu hệ số gwp.ch4 — chưa xác minh")
        return _Outcome(_Result(total_co2e_kg=self.totals[scenario], input_hash=f"hash-{scenario}"), persisted=persist)

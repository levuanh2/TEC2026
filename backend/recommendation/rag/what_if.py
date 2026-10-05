"""What-if through the authoritative Carbon service, never through a model.

`CarbonScenarioWhatIf` wraps the same `CarbonCalculator` the AWD rule uses
(i.e. `service.CarbonService`) and always calls it with `persist=False`: the
real season is never written. V1 replays the water regime only; any other
dimension is refused before the calculator is touched (decision D2). The
caller must already hold a WRITE `AuthorizedSeasonScope` — Core V1 runs
`persist=False` engine calls for writers only (decision D1).
"""

from __future__ import annotations

from carbon import CarbonEngineError

from ..rules import CarbonCalculator
from .errors import UnsupportedWhatIfDimension
from .models import BASELINE_SCENARIO, AuthorizedSeasonScope, HypotheticalChange, WhatIfResult


def ensure_supported(change: HypotheticalChange) -> None:
    if not change.supported:
        raise UnsupportedWhatIfDimension(
            f"what-if over '{change.dimension}' is not supported in RAG V1 (water regime only)"
        )


class CarbonScenarioWhatIf:
    def __init__(self, carbon: CarbonCalculator) -> None:
        self._carbon = carbon

    def simulate(self, scope: AuthorizedSeasonScope, change: HypotheticalChange) -> WhatIfResult:
        ensure_supported(change)
        assert change.scenario is not None  # guaranteed for WATER_REGIME by HypotheticalChange
        sid = scope.crop_season_id
        try:
            baseline = self._carbon.calculate(sid, BASELINE_SCENARIO, persist=False).result
            proposed = self._carbon.calculate(sid, change.scenario, persist=False).result
        except CarbonEngineError as exc:
            # Same fail-closed meaning as the AWD rule: the engine refused, so
            # there is no number — not a guessed one.
            return WhatIfResult(change=change, status="unavailable", unavailable_reason=str(exc))
        return WhatIfResult(
            change=change,
            status="available",
            baseline_total_co2e_kg=baseline.total_co2e_kg,
            hypothetical_total_co2e_kg=proposed.total_co2e_kg,
            delta_co2e_kg=baseline.total_co2e_kg - proposed.total_co2e_kg,
            baseline_input_hash=baseline.input_hash,
            hypothetical_input_hash=proposed.input_hash,
            engine_version=baseline.engine_version,
            ef_config_version=baseline.ef_config_version,
        )

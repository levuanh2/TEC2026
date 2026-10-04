"""What-if through the authoritative Carbon service, never through a model.

`CarbonScenarioWhatIf` wraps the same `CarbonCalculator` the AWD rule uses
(i.e. `service.CarbonService`) and always calls it with `persist=False`: the
real season is never written. The caller must already hold an
`AuthorizedSeasonScope` — the Carbon service reads with the service role,
exactly like `GET /v1/crop-seasons/{id}/carbon` after its access check.
"""

from __future__ import annotations

from carbon import CarbonEngineError

from ..rules import CarbonCalculator
from .models import BASELINE_SCENARIO, AuthorizedSeasonScope, HypotheticalChange, WhatIfResult


class CarbonScenarioWhatIf:
    def __init__(self, carbon: CarbonCalculator) -> None:
        self._carbon = carbon

    def simulate(self, scope: AuthorizedSeasonScope, change: HypotheticalChange) -> WhatIfResult:
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

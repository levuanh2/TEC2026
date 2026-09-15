"""M3: an MRV package carries only the season's recorded Carbon calculation.

`carbon_calculations.scenario` already separates the recorded result (`actual`,
API `as_recorded`) from what-if scenarios (`awd`, `continuous_flooding`), and
`persist=False` runs never reach the table. The export must select the newest
succeeded `actual` row — never a newer hypothetical one, and never "whatever is
latest" as a fallback. Uses the real `CarbonService` + `InMemoryCarbonRepository`
(the same `latest_calculation` contract as the Supabase repository).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infrastructure.repository import InMemoryCarbonRepository  # noqa: E402
from mrv import manifest as m  # noqa: E402
from service import CarbonService, MrvExportService  # noqa: E402
from tests.test_mrv_export import CASE, FACTOR_SET, SEASON, FakeExportStore, FakeRead  # noqa: E402


class RecordingStore(FakeExportStore):
    def __init__(self):
        super().__init__()
        self.calculation_ids: list[list[str]] = []

    def create(self, **kw):
        self.calculation_ids.append(sorted(kw.get("calculation_ids") or []))
        return super().create(**kw)


def calc(calc_id: str, scenario: str, day: int, total: str = "100.000000") -> dict:
    return {
        "id": calc_id, "crop_season_id": SEASON, "status": "succeeded", "scenario": scenario,
        "calculated_at": datetime(2026, 9, day, tzinfo=timezone.utc),
        "total_co2e_kg": Decimal(total), "yield_kg": Decimal("1000.000000"), "co2e_per_kg": Decimal("0.1"),
        "engine_version": "0.2.0", "methodology_tier": 1, "factor_set_id": FACTOR_SET, "warnings": [],
    }


def export(calculations: list[dict]):
    repo = InMemoryCarbonRepository(calculations=calculations)
    store = RecordingStore()
    service = MrvExportService(store, CarbonService(repo, parameters=None))
    result = service.create(read_repository=FakeRead(), mrv_case_id=CASE)
    return result["manifest"]["carbon"]["per_crop_season"][SEASON], result["manifest"], store


def test_canonical_row_is_selected_over_a_newer_hypothetical_scenario():
    carbon, _, store = export([calc("A", "actual", 1), calc("B", "awd", 2, "55.000000")])
    assert carbon["status"] == "succeeded"
    assert carbon["calculation_id"] == "A"
    assert carbon["scenario"] == "actual"
    assert carbon["total_co2e_kg"] == "100.000000"
    assert store.calculation_ids[-1] == ["A"]  # mrv_export_calculations links only A


def test_a_newer_canonical_row_replaces_the_older_one():
    carbon, _, store = export([
        calc("A", "actual", 1), calc("B", "awd", 2), calc("C", "actual", 3, "120.000000"),
        calc("D", "continuous_flooding", 4),
    ])
    assert carbon["calculation_id"] == "C"
    assert carbon["total_co2e_kg"] == "120.000000"
    assert store.calculation_ids[-1] == ["C"]


def test_only_hypothetical_rows_means_carbon_unavailable_not_a_fallback():
    carbon, manifest, store = export([calc("B", "awd", 2), calc("D", "continuous_flooding", 4)])
    assert carbon["status"] == "unavailable"
    assert carbon["calculation_id"] is None
    assert any(w["code"] == m.WarningCode.CARBON_UNAVAILABLE for w in manifest["warnings"])
    assert manifest["readiness"]["carbon_available"] is False
    assert store.calculation_ids[-1] == []


def test_no_calculation_at_all_still_generates_the_package():
    carbon, manifest, _ = export([])
    assert carbon["status"] == "unavailable"
    assert manifest["package_integrity"]["manifest_sha256"]


def test_failed_canonical_rows_are_not_selected():
    failed = {**calc("F", "actual", 5), "status": "failed", "total_co2e_kg": None}
    carbon, _, _ = export([calc("A", "actual", 1), failed, calc("B", "awd", 6)])
    assert carbon["calculation_id"] == "A"


def test_export_asks_the_carbon_service_for_the_recorded_scenario():
    asked: list[tuple[str, str | None]] = []

    class Spy:
        def latest(self, season_id, scenario=None):
            asked.append((season_id, scenario))
            return None

    MrvExportService(RecordingStore(), Spy()).create(read_repository=FakeRead(), mrv_case_id=CASE)
    assert asked == [(SEASON, "as_recorded")]

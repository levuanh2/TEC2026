"""Fixture mô phỏng hàng Supabase — hình dạng bám đúng schema thật.

⛔ DỮ LIỆU BỊA. Không phải số liệu thực địa.

Tên cột lấy đúng từ supabase/migrations/20260907000000_baseline.sql + migration 20260908*, để test bắt
được lỗi ánh xạ cột (ví dụ `amount_liter` của DB vs `amount_litre` của engine).
"""

from __future__ import annotations

from typing import Any

CROP_ID = "11111111-1111-1111-1111-111111111111"
PLOT_ID = "22222222-2222-2222-2222-222222222222"
FARM_ID = "33333333-3333-3333-3333-333333333333"
BATCH_ID = "44444444-4444-4444-4444-444444444444"
FACTOR_SET_ID = "55555555-5555-5555-5555-555555555555"


def _activity(activity_id: str, activity_type: str, detail: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": activity_id,
        "production_batch_id": BATCH_ID,
        "activity_type": activity_type,
        "occurred_at": "2026-02-01T00:00:00+07:00",
        "recorded_at": "2026-02-01T00:00:00+07:00",
        "source": "mobile_offline",
        "deleted_at": None,
        "detail": detail,
    }


def crop_season(**overrides: Any) -> dict[str, Any]:
    row = {
        "id": CROP_ID,
        "plot_id": PLOT_ID,
        "season_code": "DX-2026",
        "crop_type": "rice",
        "variety_name": "OM5451",
        "planting_date": "2026-01-01",
        "expected_harvest_date": "2026-04-11",
        "actual_harvest_date": "2026-04-11",
        "default_irrigation_method": "awd",
        "status": "harvested",
        "deleted_at": None,
        # cột mới của migration 20260908
        "ipcc_water_regime": "irrigated_multiple_drainage",
        "pre_season_water_regime": "non_flooded_pre_season_lt_180d",
        "cultivation_days": 100,
        "drainage_event_count": 3,
    }
    row.update(overrides)
    return row


def plot(**overrides: Any) -> dict[str, Any]:
    row = {
        "id": PLOT_ID,
        "farm_id": FARM_ID,
        "plot_code": "A1",
        "name": "Thửa A1",
        "area_ha": 1.0,
        "deleted_at": None,
    }
    row.update(overrides)
    return row


def production_batches(count: int = 1) -> list[dict[str, Any]]:
    return [
        {
            "id": BATCH_ID if i == 0 else f"{BATCH_ID[:-1]}{i}",
            "crop_season_id": CROP_ID,
            "batch_code": f"B{i + 1}",
            "status": "closed",
            "deleted_at": None,
        }
        for i in range(count)
    ]


def activities() -> list[dict[str, Any]]:
    """Bộ hoạt động khớp demo_crop.json để kết quả trùng bảng tính tay trong test engine."""
    return [
        _activity(
            "a1",
            "seeding",
            {"activity_id": "a1", "variety_name": "OM5451", "seed_kg": 80, "seeding_method": "sạ hàng"},
        ),
        _activity(
            "a2",
            "fertilizer",
            {
                "activity_id": "a2",
                "fertilizer_name": "Urea",
                "fertilizer_type": "đạm",
                "amount_kg": 120,
                "nitrogen_percent": 46,
            },
        ),
        _activity(
            "a3",
            "irrigation",
            {
                "activity_id": "a3",
                "method": "awd",
                "water_volume_m3": 7400,
                "pump_energy_kwh": None,
            },
        ),
        _activity(
            "a4",
            "fuel",
            # DB dùng `amount_liter`, model engine dùng `amount_litre` — ánh xạ phải đúng.
            {"activity_id": "a4", "fuel_type": "diesel", "amount_liter": 25},
        ),
        _activity(
            "a5",
            "straw_management",
            {
                "activity_id": "a5",
                "method": "incorporated",
                "straw_mass_kg": 5000,
                "dry_matter_fraction": 0.85,
                "days_before_cultivation": 10,
                "returned_to_field": None,
            },
        ),
        _activity(
            "a6",
            "harvest",
            {"activity_id": "a6", "yield_kg": 5200, "harvested_area_ha": 1.0},
        ),
    ]

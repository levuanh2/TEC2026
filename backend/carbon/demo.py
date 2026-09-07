"""Chạy thử Carbon Engine end-to-end bằng DEMO FIXTURE + TEST FACTORS.

    python -m carbon.demo            # dùng TEST FACTORS (số bịa) — chạy được
    python -m carbon.demo --real     # dùng config thật — SẼ BÁO LỖI vì hệ số còn null

Mục đích: chứng minh pipeline chạy thông, KHÔNG phải để lấy số liệu.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .engine import calculate_carbon
from .errors import CarbonEngineError
from .factors import DEFAULT_CONFIG_PATH, EmissionFactorSet
from .models import CropActivityData

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

BANNER = """
================================================================================
  DEMO - DU LIEU MAU + HE SO TEST (SO BIA)
  KHONG PHAI SO LIEU THUC DIA. KHONG DUNG CHO BAO CAO MRV HAY PITCH.
  He so phat thai that chua co - xem open issue OI-02.
================================================================================
"""


def _print(result) -> None:
    print(f"\n--- kịch bản: {result.water_regime_scenario} "
          f"(áp dụng: {result.water_regime_applied}) ---")
    print(f"CO2e tổng      : {result.co2e_total_kg:,.2f} kg")
    print(f"Sản lượng      : {result.yield_kg}")
    per_kg = f"{result.co2e_per_kg:.6f}" if result.co2e_per_kg is not None else "None (thiếu sản lượng)"
    print(f"CO2e/kg        : {per_kg}")
    print(f"EF version     : {result.ef_config_version}")
    print("Phân rã:")
    for entry in result.breakdown:
        print(f"  {entry.source:<18} {entry.co2e_kg:>12,.2f} kg  "
              f"= {entry.activity_value:g} {entry.activity_unit} × {entry.ef_value:g}"
              f"  [{entry.ef_path}, {entry.ef_status}]")
    print("Cảnh báo:")
    for warning in result.warnings:
        print(f"  - {warning}")


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    use_real = "--real" in argv

    # Console Windows mac dinh cp1252, khong in duoc tieng Viet co dau.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    with open(FIXTURES / "demo_crop.json", encoding="utf-8") as fh:
        crop = CropActivityData.from_dict(json.load(fh))

    if use_real:
        factors = EmissionFactorSet.load(DEFAULT_CONFIG_PATH)
        print(f"\nDùng config thật: {DEFAULT_CONFIG_PATH}")
    else:
        factors = EmissionFactorSet.load(FIXTURES / "test_factors.yaml")
        print(BANNER)

    for scenario in ("awd", "continuous_flooding"):
        try:
            _print(calculate_carbon(crop, scenario, factors))
        except CarbonEngineError as exc:
            print(f"\n--- kịch bản: {scenario} ---")
            print(f"{type(exc).__name__}: {exc}")

    if not use_real:
        print(BANNER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

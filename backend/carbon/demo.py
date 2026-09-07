"""Chạy thử Carbon Engine end-to-end bằng DEMO FIXTURE + TEST FACTORS.

    python -m carbon.demo            # TEST FACTORS (số bịa) — chạy thông
    python -m carbon.demo --real     # config thật — dừng ở GWP vì chưa xác minh (OI-05)

Mục đích: chứng minh pipeline chạy thông, KHÔNG phải để lấy số liệu.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .engine import calculate_carbon
from .errors import CarbonEngineError
from .factors import DEFAULT_CONFIG_PATH, ParameterSet
from .models import CropActivityData

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

BANNER = """
================================================================================
  DEMO - DU LIEU MAU + TEST FACTORS (SO BIA)
  TEST ONLY - NOT SCIENTIFIC VALUES.
  KHONG PHAI SO LIEU THUC DIA. KHONG DUNG CHO BAO CAO MRV HAY PITCH.
================================================================================
"""


def _print(result) -> None:
    print(f"\n--- kịch bản: {result.scenario} (chế độ nước: {result.water_regime_applied}) ---")
    print(f"Phương pháp luận : {result.methodology['name']} (tier {result.methodology['tier']})")
    print(f"Bộ tham số       : {result.ef_config_version}")
    print(f"Engine           : {result.engine_version}")
    print(f"Input hash       : {result.input_hash[:16]}…")
    print(f"CO2e tổng        : {result.total_co2e_kg:,.3f} kg")
    print(f"Sản lượng        : {result.yield_kg}")
    per_kg = (
        f"{result.co2e_per_kg:.6f}" if result.co2e_per_kg is not None else "None (thiếu sản lượng)"
    )
    print(f"CO2e/kg          : {per_kg}")

    print("Phân rã:")
    for entry in result.breakdown:
        print(f"  {entry.source:<24} {entry.gas:<4} {entry.co2e_kg:>12,.3f} kgCO2e")
        print(f"      hoạt động : {entry.activity_value:g} {entry.activity_unit}"
              f"  ->  {entry.gas_kg:g} kg {entry.gas}")
        print(f"      công thức : {entry.formula}")
        for path, value in entry.factors_used.items():
            if path.startswith("_"):
                print(f"        {path:<44} = {value}")
            else:
                print(f"        {path:<44} = {value}   [{entry.provenance.get(path, '')}]")

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
        params = ParameterSet.load(DEFAULT_CONFIG_PATH)
        print(f"\nDùng config thật: {DEFAULT_CONFIG_PATH}")
    else:
        params = ParameterSet.load(FIXTURES / "test_factors.yaml")
        print(BANNER)

    for scenario in ("awd", "continuous_flooding"):
        try:
            _print(calculate_carbon(crop, scenario, params))
        except CarbonEngineError as exc:
            print(f"\n--- kịch bản: {scenario} ---")
            print(f"{type(exc).__name__}: {exc}")

    if not use_real:
        print(BANNER)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Kiểm tra schema Supabase thật có khớp thứ backend cần không.

CHỈ ĐỌC. Không tạo, không sửa, không xoá gì. Chạy được nhiều lần.

    pip install psycopg[binary]
    export SUPABASE_DB_URL='postgresql://...'      # hoặc đặt trong backend/.env
    python scripts/validate_supabase_schema.py

Phạm vi: đúng phần MVP lớp 1a (Farm→Plot→Crop→Batch→Activity→Carbon). Không kiểm CV,
recommendation, MRV export, project-management schema.

Exit code 0 = pass, 1 = có mục FAIL.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# PowerShell on Windows can default stdout to cp1252, while this validator
# deliberately reports Vietnamese labels. Keep the read-only validation usable
# in local CI and developer shells.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

REQUIRED_TABLES = [
    "organizations",
    "farms",
    "plots",
    "crop_seasons",
    "production_batches",
    "activities",
    "seeding_events",
    "fertilizer_applications",
    "irrigation_events",
    "pesticide_applications",
    "fuel_usages",
    "straw_management_events",
    "harvest_events",
    "emission_factor_sets",
    "emission_factors",
    "carbon_calculations",
    "carbon_breakdowns",
]

# Cột do migration 20260908000000 đến 20260908000002 thêm — thiếu là backend không chạy đúng.
REQUIRED_COLUMNS = {
    "crop_seasons": [
        "plot_id",
        "planting_date",
        "actual_harvest_date",
        "default_irrigation_method",
        "ipcc_water_regime",
        "pre_season_water_regime",
        "cultivation_days",
        "drainage_event_count",
    ],
    "plots": ["farm_id", "area_ha"],
    "production_batches": ["crop_season_id", "batch_code", "deleted_at"],
    "activities": ["production_batch_id", "activity_type", "deleted_at"],
    "fertilizer_applications": ["amount_kg", "nitrogen_percent"],
    "fuel_usages": ["fuel_type", "amount_liter"],
    "irrigation_events": ["method", "water_volume_m3", "pump_energy_kwh"],
    "harvest_events": ["yield_kg"],
    "straw_management_events": [
        "method",
        "straw_mass_kg",
        "days_before_cultivation",
        "dry_matter_fraction",
        "returned_to_field",
    ],
    "emission_factors": [
        "factor_set_id",
        "factor_code",
        "factor_value",
        "source_reference",
        "parameter_kind",
        "verification_status",
        "source_table_reference",
        "uncertainty_range",
    ],
    "emission_factor_sets": ["version_code", "status", "methodology_name", "source_name"],
    "carbon_calculations": [
        "production_batch_id",
        "crop_season_id",
        "scenario",
        "factor_set_id",
        "engine_version",
        "input_hash",
        "total_co2e_kg",
        "yield_kg",
        "co2e_per_kg",
        "status",
        "methodology_tier",
        "mrv_compliant",
        "warnings",
        "area_ha_used",
        "cultivation_days_used",
        "water_regime_applied",
        "pre_season_water_regime_applied",
    ],
    "carbon_breakdowns": [
        "calculation_id",
        "emission_factor_id",
        "category",
        "gas",
        "activity_value",
        "activity_unit",
        "factor_value_used",
        "co2e_kg",
        "formula_note",
        "formula_metadata",
        "gas_kg",
        "formula_expression",
    ],
}

REQUIRED_ENUM_VALUES = {
    "carbon_scenario": ["actual", "awd", "continuous_flooding"],
    "activity_type": [
        "seeding",
        "fertilizer",
        "irrigation",
        "pesticide",
        "fuel",
        "straw_management",
        "harvest",
    ],
    "straw_management_method": ["incorporated", "removed", "burned", "composted"],
    "emission_category": [
        "irrigation_ch4",
        "fertilizer_n2o",
        "fuel",
        "straw_burning_ch4",
        "straw_burning_n2o",
    ],
    "ipcc_water_regime": [
        "irrigated_continuous_flooding",
        "irrigated_single_drainage",
        "irrigated_multiple_drainage",
        "rainfed_regular",
        "rainfed_drought_prone",
        "deep_water",
        "upland",
    ],
    "ipcc_pre_season_regime": [
        "non_flooded_pre_season_lt_180d",
        "non_flooded_pre_season_gt_180d",
        "flooded_pre_season_gt_30d",
        "non_flooded_pre_season_gt_365d",
    ],
    "parameter_kind": ["emission_factor", "scaling_factor", "gwp", "exponent"],
    "parameter_verification_status": ["VERIFIED", "PENDING_VERIFICATION"],
}

RLS_REQUIRED_TABLES = [
    "farms",
    "plots",
    "crop_seasons",
    "production_batches",
    "activities",
    "carbon_calculations",
    "carbon_breakdowns",
    "emission_factors",
    "emission_factor_sets",
]

REQUIRED_POLICIES = {
    # Chính sách batch-scoped cũ VẪN giữ (đọc được dữ liệu cũ); crop-season-scoped mới
    # (migration 20260908000002) là đường đọc chính cho bản tính không gắn batch.
    "carbon_calculations": ["carbon_calculations_select", "carbon_calculations_select_crop_season"],
    "carbon_breakdowns": ["carbon_breakdowns_select", "carbon_breakdowns_select_crop_season"],
    "emission_factor_sets": ["ef_sets_select"],
    "emission_factors": ["ef_factors_select"],
}

REQUIRED_INDEXES = [
    "carbon_calculations_crop_season_idx",
    # Partial unique index cho bản tính whole-season (production_batch_id IS NULL).
    "carbon_calculations_season_input_uniq",
]

# Trigger giữ bất biến "batch link (nếu có) phải cùng crop_season với bản tính".
REQUIRED_TRIGGERS = {"carbon_calculations": ["carbon_calculations_batch_scope_guard"]}

# Hàm phân quyền mà policy carbon phụ thuộc — mất là RLS gãy âm thầm.
REQUIRED_FUNCTIONS = [
    ("private", "user_can_read_batch"),
    ("private", "user_can_write_batch"),
    ("private", "user_can_read_crop"),
]


class Report:
    def __init__(self) -> None:
        self.failures: list[str] = []
        self.warnings: list[str] = []

    def check(self, ok: bool, label: str, detail: str = "") -> None:
        if ok:
            print(f"  PASS  {label}")
        else:
            print(f"  FAIL  {label}{('  — ' + detail) if detail else ''}")
            self.failures.append(label)

    def warn(self, label: str) -> None:
        print(f"  WARN  {label}")
        self.warnings.append(label)


def _connection_string() -> str:
    from infrastructure.config import BACKEND_DIR, _load_dotenv

    _load_dotenv(BACKEND_DIR / ".env")
    url = os.environ.get("SUPABASE_DB_URL")
    if not url:
        print(
            "Thiếu SUPABASE_DB_URL.\n"
            "  Đặt trong backend/.env (đã gitignore) hoặc biến môi trường.\n"
            "  KHÔNG dán chuỗi kết nối kèm mật khẩu vào chat/commit/issue."
        )
        raise SystemExit(2)
    return url


def main() -> int:
    try:
        import psycopg
    except ImportError:
        print("Cần psycopg: pip install 'psycopg[binary]'")
        return 2

    report = Report()
    with psycopg.connect(_connection_string()) as conn, conn.cursor() as cur:
        print("\n== BẢNG ==")
        cur.execute(
            "select table_name from information_schema.tables where table_schema='public'"
        )
        tables = {r[0] for r in cur.fetchall()}
        for table in REQUIRED_TABLES:
            report.check(table in tables, f"bảng public.{table}")

        print("\n== CỘT ==")
        cur.execute(
            "select table_name, column_name from information_schema.columns "
            "where table_schema='public'"
        )
        columns: dict[str, set[str]] = {}
        for table, column in cur.fetchall():
            columns.setdefault(table, set()).add(column)
        for table, required in REQUIRED_COLUMNS.items():
            missing = [c for c in required if c not in columns.get(table, set())]
            report.check(not missing, f"cột của {table}", f"thiếu: {', '.join(missing)}")

        print("\n== ENUM ==")
        cur.execute(
            "select t.typname, e.enumlabel from pg_type t "
            "join pg_enum e on e.enumtypid = t.oid "
            "join pg_namespace n on n.oid = t.typnamespace where n.nspname='public'"
        )
        enums: dict[str, set[str]] = {}
        for name, label in cur.fetchall():
            enums.setdefault(name, set()).add(label)
        for enum_name, required in REQUIRED_ENUM_VALUES.items():
            missing = [v for v in required if v not in enums.get(enum_name, set())]
            report.check(not missing, f"enum {enum_name}", f"thiếu: {', '.join(missing)}")

        print("\n== INDEX ==")
        cur.execute("select indexname from pg_indexes where schemaname='public'")
        indexes = {r[0] for r in cur.fetchall()}
        for index in REQUIRED_INDEXES:
            report.check(index in indexes, f"index {index}")

        print("\n== RLS ==")
        cur.execute(
            "select c.relname, c.relrowsecurity from pg_class c "
            "join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname='public' and c.relkind='r'"
        )
        rls = dict(cur.fetchall())
        for table in RLS_REQUIRED_TABLES:
            report.check(rls.get(table) is True, f"RLS bật trên {table}")

        print("\n== POLICY ==")
        cur.execute("select tablename, policyname from pg_policies where schemaname='public'")
        policies: dict[str, set[str]] = {}
        for table, policy in cur.fetchall():
            policies.setdefault(table, set()).add(policy)
        for table, required in REQUIRED_POLICIES.items():
            missing = [p for p in required if p not in policies.get(table, set())]
            report.check(not missing, f"policy của {table}", f"thiếu: {', '.join(missing)}")

        print("\n== HÀM PHÂN QUYỀN ==")
        cur.execute(
            "select n.nspname, p.proname from pg_proc p "
            "join pg_namespace n on n.oid = p.pronamespace where n.nspname='private'"
        )
        functions = {(s, f) for s, f in cur.fetchall()}
        for schema, name in REQUIRED_FUNCTIONS:
            report.check((schema, name) in functions, f"hàm {schema}.{name}()")

        print("\n== TRIGGER ==")
        cur.execute(
            "select event_object_table, trigger_name from information_schema.triggers "
            "where trigger_schema='public'"
        )
        triggers: dict[str, set[str]] = {}
        for table, name in cur.fetchall():
            triggers.setdefault(table, set()).add(name)
        for table, required in REQUIRED_TRIGGERS.items():
            missing = [t for t in required if t not in triggers.get(table, set())]
            report.check(not missing, f"trigger của {table}", f"thiếu: {', '.join(missing)}")

        print("\n== VIEW ==")
        cur.execute(
            "select c.relname, coalesce(array_to_string(c.reloptions, ','), '') "
            "from pg_class c join pg_namespace n on n.oid = c.relnamespace "
            "where n.nspname='public' and c.relkind='v'"
        )
        for name, options in cur.fetchall():
            if name.startswith("v_carbon_results"):
                report.check(
                    "security_invoker=true" in options.replace(" ", ""),
                    f"view {name} có security_invoker",
                    "thiếu security_invoker -> view chạy quyền owner, BỎ QUA RLS",
                )

        print("\n== BỘ HỆ SỐ ==")
        cur.execute(
            "select version_code, status from public.emission_factor_sets order by created_at desc"
        )
        sets = cur.fetchall()
        if not sets:
            report.warn(
                "Chưa có emission_factor_set nào. Backend sẽ raise FactorSetNotFoundError khi ghi."
            )
        else:
            for version_code, status in sets:
                print(f"  INFO  {version_code} ({status})")

        print("\n== PHẠM VI TÍNH TOÁN ==")
        cur.execute(
            "select count(*) from information_schema.columns "
            "where table_schema='public' and table_name='carbon_calculations' "
            "and column_name='crop_season_id' and is_nullable='NO'"
        )
        report.check(cur.fetchone()[0] == 1, "carbon_calculations.crop_season_id NOT NULL")
        cur.execute(
            "select count(*) from information_schema.columns "
            "where table_schema='public' and table_name='carbon_calculations' "
            "and column_name='production_batch_id' and is_nullable='YES'"
        )
        report.check(cur.fetchone()[0] == 1, "carbon_calculations.production_batch_id nullable")

    print("\n" + "=" * 70)
    if report.failures:
        print(f"FAIL: {len(report.failures)} mục không đạt")
        for item in report.failures:
            print(f"  - {item}")
    else:
        print("PASS: schema khớp thứ backend MVP 1a cần")
    if report.warnings:
        print(f"\n{len(report.warnings)} cảnh báo:")
        for item in report.warnings:
            print(f"  - {item}")
    return 1 if report.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

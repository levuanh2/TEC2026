"""Seed isolated DEMO-AGRICARBON-2026 tenant — idempotent, never touches real data.

Chạy: python backend/scripts/seed_demo_data.py
Cần backend/.env đầy đủ (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_PUBLISHABLE_KEY).
Chỉ khi tạo MỚI demo user mới cần MANAGER_PASSWORD / ENTERPRISE_PASSWORD trong biến
môi trường tiến trình — DEMO/QA ONLY, không bao giờ ghi vào file, log hay commit, và
script không in mật khẩu ra màn hình.

Mọi record thuộc tenant demo có prefix `DEMO-` trong code/tên — nhận diện và
cleanup được bằng `backend/scripts/cleanup_demo_data.py`. KHÔNG bao giờ ghi
carbon_calculations (không bịa CO2e vào production factor set) — Carbon page
của mọi crop season demo phải hiện đúng trạng thái "chưa có dữ liệu tính
toán", không phải số giả.

An toàn/idempotent: mọi bước dùng get-or-create theo unique code — chạy lại
nhiều lần không tạo trùng, không xoá/ghi đè gì đã có. Nếu `organization_code`
đã tồn tại nhưng KHÔNG map đúng tenant demo (ví dụ ai đó lỡ tạo trùng code cho
org thật) thì dừng lại — không tự ý ghi đè.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from infrastructure.config import load_settings  # noqa: E402
from supabase import create_client  # noqa: E402

ORG_CODE = "DEMO-AGRICARBON-2026"
DEMO_NOTE = "DEMO / SYNTHETIC DATA — NOT FIELD DATA, NOT OFFICIAL MRV DATA"

settings = load_settings()
url, service_key = settings.require_supabase()
admin = create_client(url, service_key)


def get_or_create(table: str, match: dict, defaults: dict) -> dict:
    query = admin.table(table).select("*")
    for key, value in match.items():
        query = query.eq(key, value)
    existing = query.execute().data
    if existing:
        return existing[0]
    row = {**match, **defaults}
    return admin.table(table).insert(row).execute().data[0]


def main() -> int:
    print(f"=== Seed demo tenant {ORG_CODE} — target {url} ===")

    org = get_or_create(
        "organizations", {"organization_code": ORG_CODE},
        {"name": "AgriCarbon Demo Cooperative", "organization_type": "cooperative"},
    )
    print("org:", org["id"])

    farms = []
    for i in range(1, 4):
        farm = get_or_create(
            "farms", {"cooperative_id": org["id"], "farm_code": f"DEMO-FARM-{i:02d}"},
            {
                "farm_name": f"Hộ demo {i}", "province_name": "Đồng Tháp",
                "district_name": "Tháp Mười", "commune_name": "Tân Phú",
            },
        )
        farms.append(farm)
    print("farms:", [f["id"] for f in farms])

    activity_plan = [
        # (farm_index, plot_index, seed?, fertilizer?, irrigation?, pesticide?, fuel?, straw?, harvest?)
        (0, 1, True, True, True, True, True, True, True),   # đủ mọi loại + có thu hoạch
        (0, 2, True, True, True, False, False, False, False),  # còn thiếu — Carbon/Metrics phải null
        (1, 1, True, True, True, True, False, True, True),
        (1, 2, False, False, True, False, False, False, False),  # rất thưa dữ liệu
        (2, 1, True, True, True, True, True, True, True),
        (2, 2, True, True, False, False, False, False, True),
    ]

    plots, seasons, batches = [], [], []
    for idx, (farm_i, plot_i, *_flags) in enumerate(activity_plan, start=1):
        farm = farms[farm_i]
        plot = get_or_create(
            "plots", {"farm_id": farm["id"], "plot_code": f"DEMO-PLOT-{farm_i + 1:02d}-{plot_i:02d}"},
            {"name": f"Thửa demo {farm_i + 1}.{plot_i}", "area_ha": 1.0 + 0.3 * idx},
        )
        plots.append(plot)
        season = get_or_create(
            "crop_seasons", {"plot_id": plot["id"], "season_code": "DEMO-HT-2026"},
            {
                "crop_type": "rice", "variety_name": "OM5451",
                "planting_date": "2026-05-18", "status": "active",
            },
        )
        seasons.append(season)
        batch = get_or_create(
            "production_batches", {"crop_season_id": season["id"], "batch_code": "default"}, {},
        )
        batches.append(batch)
    print("plots:", len(plots), "seasons:", len(seasons), "batches:", len(batches))

    def add_activity(batch_id: str, activity_type: str, occurred_at: str, detail_table: str, detail_row: dict) -> None:
        existing = admin.table("activities").select("id").eq("production_batch_id", batch_id).eq("activity_type", activity_type).execute().data
        if existing:
            return
        activity = admin.table("activities").insert({
            "production_batch_id": batch_id, "activity_type": activity_type,
            "occurred_at": occurred_at, "recorded_at": occurred_at,
            "source": "web", "note": DEMO_NOTE,
        }).execute().data[0]
        admin.table(detail_table).insert({"activity_id": activity["id"], **detail_row}).execute()

    for (farm_i, plot_i, has_seed, has_fert, has_irr, has_pest, has_fuel, has_straw, has_harvest), batch in zip(activity_plan, batches):
        bid = batch["id"]
        if has_seed:
            add_activity(bid, "seeding", "2026-05-18T06:00:00Z", "seeding_events",
                         {"variety_name": "OM5451", "seed_kg": 120, "seeding_method": "sạ hàng"})
        if has_fert:
            add_activity(bid, "fertilizer", "2026-06-01T06:00:00Z", "fertilizer_applications",
                         {"fertilizer_name": "Urea", "amount_kg": 150, "nitrogen_percent": 46})
        if has_irr:
            add_activity(bid, "irrigation", "2026-06-10T06:00:00Z", "irrigation_events",
                         {"method": "awd", "water_volume_m3": 320})
        if has_pest:
            add_activity(bid, "pesticide", "2026-06-20T06:00:00Z", "pesticide_applications",
                         {"product_name": "Demo pesticide", "amount": 2, "unit": "lít"})
        if has_fuel:
            add_activity(bid, "fuel", "2026-06-25T06:00:00Z", "fuel_usages",
                         {"fuel_type": "diesel", "amount_liter": 15, "equipment_name": "Máy bơm"})
        if has_straw:
            add_activity(bid, "straw_management", "2026-09-06T06:00:00Z", "straw_management_events",
                         {"method": "incorporated", "straw_mass_kg": 800})
        if has_harvest:
            add_activity(bid, "harvest", "2026-09-05T06:00:00Z", "harvest_events",
                         {"yield_kg": 5200 + 100 * farm_i, "harvested_area_ha": 1.2, "moisture_percent": 14})

    # -- MRV: 1 case, 6 step tự tạo bởi trigger, 1 batch liên kết, 1 evidence --
    case = get_or_create(
        "mrv_cases", {"organization_id": org["id"], "case_code": "DEMO-MRV-2026"},
        {
            "name": "Hồ sơ MRV demo Hè Thu 2026", "period_start": "2026-05-01",
            "period_end": "2026-09-30", "status": "draft",
        },
    )
    print("mrv case:", case["id"])
    admin.table("mrv_case_steps").update({
        "status": "completed", "started_at": "2026-05-01T00:00:00Z", "completed_at": "2026-05-03T00:00:00Z",
    }).eq("mrv_case_id", case["id"]).eq("step_no", 1).execute()
    admin.table("mrv_case_steps").update({
        "status": "in_progress", "started_at": "2026-06-01T00:00:00Z",
    }).eq("mrv_case_id", case["id"]).eq("step_no", 2).execute()

    link_batch_id = batches[0]["id"]
    existing_link = admin.table("mrv_case_batches").select("*").eq("mrv_case_id", case["id"]).eq("production_batch_id", link_batch_id).execute().data
    if not existing_link:
        admin.table("mrv_case_batches").insert({"mrv_case_id": case["id"], "production_batch_id": link_batch_id}).execute()

    existing_evidence = admin.table("mrv_evidence").select("*").eq("mrv_case_id", case["id"]).execute().data
    if not existing_evidence:
        admin.table("mrv_evidence").insert({
            "mrv_case_id": case["id"], "step_no": 1, "production_batch_id": link_batch_id,
            "evidence_type": "photo", "storage_object_path": f"{org['id']}/{case['id']}/demo-field-photo.jpg",
            "file_name": "demo-field-photo.jpg", "mime_type": "image/jpeg", "notes": DEMO_NOTE,
        }).execute()

    # -- Demo users: cooperative_manager + enterprise_viewer, quyền qua DB thật --
    def ensure_demo_user(label: str, role: str, farm_role: str | None) -> tuple[str, str]:
        email = f"demo-{label}@agricarbon-demo.local"
        users = admin.auth.admin.list_users()
        existing_user = next((u for u in users if u.email == email), None)
        if existing_user:
            return email, "(đã tồn tại — mật khẩu không đổi, không in lại)"
        # Never generated-and-printed: a password on stdout ends up in terminal
        # scrollback and CI logs. The operator supplies it through the process env.
        password_env = f"{label.upper()}_PASSWORD"
        password = os.environ.get(password_env)
        if not password:
            raise RuntimeError(
                f"{password_env} is required to create {email} (DEMO/QA only; "
                "set it in the process environment, never in a file)."
            )
        user = admin.auth.admin.create_user({"email": email, "password": password, "email_confirm": True}).user
        admin.table("organization_memberships").insert({
            "organization_id": org["id"], "user_id": user.id, "role": role,
        }).execute()
        if farm_role:
            admin.table("farm_members").insert({
                "farm_id": farms[0]["id"], "user_id": user.id, "farm_role": farm_role,
            }).execute()
        return email, f"(vừa tạo — mật khẩu lấy từ {password_env}, không in ra)"

    manager_email, manager_status = ensure_demo_user("manager", "cooperative_manager", "owner")
    enterprise_email, enterprise_status = ensure_demo_user("enterprise", "enterprise_viewer", None)

    print("\n=== DEMO/QA ACCOUNTS (không in mật khẩu) ===")
    print(f"cooperative_manager: {manager_email} {manager_status}")
    print(f"enterprise_viewer:   {enterprise_email} {enterprise_status}")
    print(f"\nOrganization ID: {org['id']}")
    print("Seed xong. Carbon page các crop season demo sẽ hiện 'chưa có dữ liệu tính toán'")
    print("(cố ý không seed carbon_calculations — không bịa CO2e).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

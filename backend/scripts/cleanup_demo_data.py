"""Cleanup ONLY the DEMO-AGRICARBON-2026 tenant — safe, scoped, idempotent.

Chạy: python backend/scripts/cleanup_demo_data.py

KHÔNG bao giờ DELETE FROM <table> không điều kiện — mọi xoá đều lọc theo
organization_id/case_id/farm_id đã resolve từ organization_code cụ thể ở
trên cùng. Nếu tenant demo không tồn tại (đã cleanup trước đó, hoặc chưa
từng seed) thì thoát sạch (no-op), không lỗi.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from infrastructure.config import load_settings  # noqa: E402
from supabase import create_client  # noqa: E402

ORG_CODE = "DEMO-AGRICARBON-2026"

settings = load_settings()
url, service_key = settings.require_supabase()
admin = create_client(url, service_key)


def main() -> int:
    print(f"=== Cleanup demo tenant {ORG_CODE} — target {url} ===")
    orgs = admin.table("organizations").select("id").eq("organization_code", ORG_CODE).execute().data
    if not orgs:
        print("Không tìm thấy tenant demo — không có gì để dọn (no-op).")
        return 0
    org_id = orgs[0]["id"]
    print("org_id:", org_id)

    cases = admin.table("mrv_cases").select("id").eq("organization_id", org_id).execute().data
    for case in cases:
        cid = case["id"]
        admin.table("mrv_evidence").delete().eq("mrv_case_id", cid).execute()
        admin.table("mrv_exports").delete().eq("mrv_case_id", cid).execute()
        admin.table("mrv_case_batches").delete().eq("mrv_case_id", cid).execute()
        admin.table("mrv_case_steps").delete().eq("mrv_case_id", cid).execute()
        admin.table("mrv_cases").delete().eq("id", cid).execute()
    print(f"mrv_cases removed: {len(cases)}")

    farms = admin.table("farms").select("id").eq("cooperative_id", org_id).execute().data
    plot_count = season_count = batch_count = activity_count = 0
    for farm in farms:
        fid = farm["id"]
        plots = admin.table("plots").select("id").eq("farm_id", fid).execute().data
        for plot in plots:
            pid = plot["id"]
            seasons = admin.table("crop_seasons").select("id").eq("plot_id", pid).execute().data
            for season in seasons:
                sid = season["id"]
                batches = admin.table("production_batches").select("id").eq("crop_season_id", sid).execute().data
                for batch in batches:
                    bid = batch["id"]
                    acts = admin.table("activities").select("id").eq("production_batch_id", bid).execute().data
                    for act in acts:
                        aid = act["id"]
                        for table in (
                            "seeding_events", "fertilizer_applications", "irrigation_events",
                            "pesticide_applications", "fuel_usages", "straw_management_events",
                            "harvest_events",
                        ):
                            admin.table(table).delete().eq("activity_id", aid).execute()
                        admin.table("activities").delete().eq("id", aid).execute()
                        activity_count += 1
                    admin.table("carbon_calculations").delete().eq("production_batch_id", bid).execute()
                    admin.table("production_batches").delete().eq("id", bid).execute()
                    batch_count += 1
                admin.table("crop_seasons").delete().eq("id", sid).execute()
                season_count += 1
            admin.table("plots").delete().eq("id", pid).execute()
            plot_count += 1
        admin.table("farm_members").delete().eq("farm_id", fid).execute()
        admin.table("farms").delete().eq("id", fid).execute()
    print(f"farms removed: {len(farms)}, plots: {plot_count}, seasons: {season_count}, batches: {batch_count}, activities: {activity_count}")

    admin.table("organization_memberships").delete().eq("organization_id", org_id).execute()
    admin.table("organizations").delete().eq("id", org_id).execute()
    print("organization removed")

    users = admin.auth.admin.list_users()
    removed_users = 0
    for u in users:
        if u.email and u.email.endswith("@agricarbon-demo.local"):
            admin.auth.admin.delete_user(u.id)
            removed_users += 1
    print(f"demo auth users removed: {removed_users}")

    print("Cleanup xong.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

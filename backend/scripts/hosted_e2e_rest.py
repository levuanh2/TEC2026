"""Hosted Supabase E2E cho REST API đọc — SMOKE-TEST-REST.

LEGACY / NOT PART OF CURRENT CI. Last matched the schema on 2026-09-08: its
seeded PDF export row now violates `mrv_export_snapshot_lineage_chk`
(20260913150000) and the MRV export read path changed since. It runs in
neither ci.yml nor staging-e2e.yml; the replacement coverage is listed in
docs/CI_PIPELINE.md ("Legacy scripts").

Chạy: python backend/scripts/hosted_e2e_rest.py
Cần backend/.env đầy đủ (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_PUBLISHABLE_KEY).

Tạo 2 org/farm/plot/season/batch/activity/MRV case tách biệt (User A, User B) bằng
service-role client, tạo 2 Supabase Auth user thật, đăng nhập lấy JWT thật, gọi
QUA FastAPI app thật (main.app, KHÔNG override dependency) bằng Authorization
header thật — đây là đường đi giống hệt client thật, không phải unit test giả lập.

Dọn sạch ở `finally` bất kể pass/fail, rồi so số dòng mỗi bảng trước/sau — phải
bằng nhau. KHÔNG chạm dữ liệu không có prefix SMOKE-TEST-REST.
"""
from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient  # noqa: E402
from supabase import create_client  # noqa: E402

from infrastructure.config import load_settings  # noqa: E402

PREFIX = "SMOKE-TEST-REST"
RUN_ID = uuid.uuid4().hex[:8]

settings = load_settings()
url, service_key = settings.require_supabase()
_, publishable_key = settings.require_publishable()
admin = create_client(url, service_key)

TABLES_TO_COUNT = [
    "organizations", "farms", "plots", "crop_seasons", "production_batches",
    "activities", "harvest_events", "mrv_cases", "mrv_case_steps",
    "mrv_case_batches", "mrv_evidence", "mrv_exports", "emission_factor_sets",
    "emission_factors", "organization_memberships", "farm_members",
]

results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    results.append((name, condition, detail))
    print(("PASS" if condition else "FAIL") + f" — {name}" + (f" ({detail})" if detail and not condition else ""))


def table_counts() -> dict[str, int]:
    counts = {}
    for t in TABLES_TO_COUNT:
        counts[t] = admin.table(t).select("*", count="exact").limit(1).execute().count
    return counts


def seed_side(label: str) -> dict:
    org = admin.table("organizations").insert({
        "organization_code": f"{PREFIX}-{RUN_ID}-ORG-{label}", "name": f"{PREFIX} Org {label}",
        "organization_type": "cooperative",
    }).execute().data[0]
    farm = admin.table("farms").insert({
        "cooperative_id": org["id"], "farm_code": f"{PREFIX}-{RUN_ID}-FARM-{label}",
        "farm_name": f"{PREFIX} Farm {label}",
    }).execute().data[0]
    plot = admin.table("plots").insert({
        "farm_id": farm["id"], "plot_code": f"{PREFIX}-{RUN_ID}-PLOT-{label}",
        "name": f"{PREFIX} Plot {label}", "area_ha": 1.5,
    }).execute().data[0]
    season = admin.table("crop_seasons").insert({
        "plot_id": plot["id"], "season_code": f"{PREFIX}-{RUN_ID}-SEASON-{label}",
        "crop_type": "rice", "status": "active",
    }).execute().data[0]
    batch = admin.table("production_batches").insert({
        "crop_season_id": season["id"], "batch_code": "default",
    }).execute().data[0]
    activity = admin.table("activities").insert({
        "production_batch_id": batch["id"], "activity_type": "harvest",
        "occurred_at": "2026-06-01T00:00:00Z", "recorded_at": "2026-06-01T00:00:00Z",
        "source": "web",
    }).execute().data[0]
    admin.table("harvest_events").insert({"activity_id": activity["id"], "yield_kg": 1000.0}).execute()

    email = f"{PREFIX.lower()}-{RUN_ID}-{label.lower()}@agricarbon.invalid"
    password = f"Smoke-{uuid.uuid4().hex}!A1"
    user = admin.auth.admin.create_user({
        "email": email, "password": password, "email_confirm": True,
    }).user
    admin.table("organization_memberships").insert({
        "organization_id": org["id"], "user_id": user.id, "role": "farmer",
    }).execute()
    admin.table("farm_members").insert({
        "farm_id": farm["id"], "user_id": user.id, "farm_role": "owner",
    }).execute()

    return {
        "org": org, "farm": farm, "plot": plot, "season": season, "batch": batch,
        "activity": activity, "user_id": user.id, "email": email, "password": password,
    }


def sign_in(email: str, password: str) -> str:
    client = create_client(url, publishable_key)
    session = client.auth.sign_in_with_password({"email": email, "password": password})
    return session.session.access_token


def cleanup_by_run_id() -> None:
    """Dọn theo RUN_ID chứ không theo id đã lưu trong biến — an toàn kể cả khi
    seed lỗi giữa chừng (một object tạo thành công nhưng script crash trước khi
    gán vào biến Python thì vẫn bị quét ra và xoá theo prefix)."""
    def _try(fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            print(f"  cleanup warning: {exc}")

    cases = admin.table("mrv_cases").select("id").ilike("case_code", f"{PREFIX}-{RUN_ID}-%").execute().data
    for case in cases:
        _try(lambda cid=case["id"]: admin.table("mrv_evidence").delete().eq("mrv_case_id", cid).execute())
        _try(lambda cid=case["id"]: admin.table("mrv_exports").delete().eq("mrv_case_id", cid).execute())
        _try(lambda cid=case["id"]: admin.table("mrv_case_batches").delete().eq("mrv_case_id", cid).execute())
        _try(lambda cid=case["id"]: admin.table("mrv_case_steps").delete().eq("mrv_case_id", cid).execute())
        _try(lambda cid=case["id"]: admin.table("mrv_cases").delete().eq("id", cid).execute())

    orgs = admin.table("organizations").select("id").ilike("organization_code", f"{PREFIX}-{RUN_ID}-%").execute().data
    for org in orgs:
        oid = org["id"]
        farms = admin.table("farms").select("id").eq("cooperative_id", oid).execute().data
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
                            _try(lambda x=aid: admin.table("harvest_events").delete().eq("activity_id", x).execute())
                            _try(lambda x=aid: admin.table("activities").delete().eq("id", x).execute())
                        _try(lambda x=bid: admin.table("production_batches").delete().eq("id", x).execute())
                    _try(lambda x=sid: admin.table("crop_seasons").delete().eq("id", x).execute())
                _try(lambda x=pid: admin.table("plots").delete().eq("id", x).execute())
            _try(lambda x=fid: admin.table("farm_members").delete().eq("farm_id", x).execute())
            _try(lambda x=fid: admin.table("farms").delete().eq("id", x).execute())
        _try(lambda x=oid: admin.table("organization_memberships").delete().eq("organization_id", x).execute())
        _try(lambda x=oid: admin.table("organizations").delete().eq("id", x).execute())

    _try(lambda: admin.table("emission_factors").delete().ilike("factor_code", "smoke.%").eq("source_reference", "smoke-test").execute())
    _try(lambda: admin.table("emission_factor_sets").delete().eq("version_code", f"{PREFIX}-{RUN_ID}").execute())

    users = admin.auth.admin.list_users()
    for u in users:
        if u.email and f"{PREFIX.lower()}-{RUN_ID}" in u.email:
            _try(lambda uid=u.id: admin.auth.admin.delete_user(uid))


def main() -> int:
    print(f"=== Hosted E2E REST — run {RUN_ID} ===")
    baseline = table_counts()
    print("Baseline counts:", baseline)

    # state tích luỹ dần — finally chỉ dọn những gì THỰC SỰ đã tạo, kể cả khi seed
    # lỗi giữa chừng (không để rơi vào tình huống seed nửa chừng rồi không dọn).
    state: dict = {"a": None, "b": None, "ef_set": None, "ef": None, "case": None, "evidence": None, "export": None}

    try:
        state["a"] = a = seed_side("A")
        state["b"] = b = seed_side("B")
        state["ef_set"] = ef_set = admin.table("emission_factor_sets").insert({
            "version_code": f"{PREFIX}-{RUN_ID}", "name": f"{PREFIX} EF set",
            "methodology_name": "IPCC 2019 Refinement (TEST)", "source_name": "smoke-test",
            "status": "published", "published_at": "2026-01-01T00:00:00Z",
        }).execute().data[0]
        state["ef"] = ef = admin.table("emission_factors").insert({
            "factor_set_id": ef_set["id"], "factor_code": "smoke.ch4", "category": "irrigation_ch4",
            "gas": "ch4", "activity_unit": "ha_day", "factor_value": 1.0, "source_reference": "smoke-test",
        }).execute().data[0]

        state["case"] = case = admin.table("mrv_cases").insert({
            "organization_id": a["org"]["id"], "case_code": f"{PREFIX}-{RUN_ID}-CASE",
            "name": f"{PREFIX} MRV case", "period_start": "2026-01-01", "period_end": "2026-06-01",
            "status": "draft",
        }).execute().data[0]
        # populate_mrv_steps_trg (baseline migration) đã tự chèn đủ 6 step_no khi tạo case
        # (status mặc định 'not_started') — ở đây UPDATE bước 1 thay vì INSERT.
        admin.table("mrv_case_steps").update({
            "status": "completed",
            "started_at": "2026-01-01T00:00:00Z", "completed_at": "2026-01-02T00:00:00Z",
        }).eq("mrv_case_id", case["id"]).eq("step_no", 1).execute()
        admin.table("mrv_case_batches").insert({
            "mrv_case_id": case["id"], "production_batch_id": a["batch"]["id"],
        }).execute()
        # private.validate_mrv_file_path() bắt buộc path = <organization_uuid>/<mrv_case_uuid>/<file>
        state["evidence"] = evidence = admin.table("mrv_evidence").insert({
            "mrv_case_id": case["id"], "step_no": 1, "production_batch_id": a["batch"]["id"],
            "evidence_type": "photo", "storage_object_path": f"{a['org']['id']}/{case['id']}/a.jpg",
            "file_name": "a.jpg", "mime_type": "image/jpeg",
        }).execute().data[0]
        state["export"] = export = admin.table("mrv_exports").insert({
            "mrv_case_id": case["id"], "format": "pdf", "factor_set_id": ef_set["id"],
            "scope_description": "smoke test", "data_as_of_at": "2026-06-01T00:00:00Z",
            "contains_sample_data": True, "warning_text": "SMOKE TEST — KHONG PHAI DU LIEU THAT",
            "storage_object_path": f"{a['org']['id']}/{case['id']}/export.pdf",
            "export_payload": {"note": "smoke test placeholder"},
        }).execute().data[0]

        extra_a = {"case_id": case["id"], "evidence_id": evidence["id"], "export_id": export["id"]}
        token_a = sign_in(a["email"], a["password"])
        token_b = sign_in(b["email"], b["password"])
        check("sign_in_a_returns_token", bool(token_a))
        check("sign_in_b_returns_token", bool(token_b))

        from main import app  # import sau khi seed xong để chắc settings đã load .env thật
        client = TestClient(app)
        ha = {"Authorization": f"Bearer {token_a}"}
        hb = {"Authorization": f"Bearer {token_b}"}

        # -- User A đọc được đúng resource của mình --
        r = client.get("/v1/me", headers=ha)
        check("me_a_200", r.status_code == 200, str(r.status_code))
        check("me_a_has_org_membership", any(m["organization_id"] == a["org"]["id"] for m in r.json().get("organization_memberships", [])))

        r = client.get(f"/v1/farms/{a['farm']['id']}", headers=ha)
        check("farm_a_own_200", r.status_code == 200, r.text[:200])

        r = client.get(f"/v1/organizations/{a['org']['id']}/summary", headers=ha)
        check("org_a_summary_200", r.status_code == 200, r.text[:200])
        if r.status_code == 200:
            body = r.json()
            # Không seed carbon_calculations -> total_co2e null -> theo đúng thiết kế
            # "null nếu BẤT KỲ vụ nào thiếu carbon" thì total_yield_kg cũng phải null,
            # KHÔNG được trả 1000 (sẽ là bịa số khi thiếu carbon) — season_a_metrics_yield
            # đã xác nhận yield_kg=1000 ở cấp season riêng, nên đây đúng là null có chủ đích.
            check("org_a_summary_null_when_no_carbon", body["total_yield_kg"] is None and body["total_co2e_kg"] is None, str(body))

        r = client.get(f"/v1/crop-seasons/{a['season']['id']}/production-batches", headers=ha)
        check("season_a_batches_200", r.status_code == 200 and len(r.json()["items"]) == 1, r.text[:200])

        r = client.get(f"/v1/crop-seasons/{a['season']['id']}/metrics", headers=ha)
        check("season_a_metrics_yield", r.status_code == 200 and r.json()["yield_kg"] == 1000.0, r.text[:200])

        r = client.get(f"/v1/farms/{a['farm']['id']}/metrics", headers=ha)
        check("farm_a_metrics_yield", r.status_code == 200 and r.json()["yield_kg"] == 1000.0, r.text[:200])

        r = client.get(f"/v1/mrv/cases/{case['id']}", headers=ha)
        check("mrv_case_a_200", r.status_code == 200, r.text[:200])
        if r.status_code == 200:
            steps = r.json()["steps"]
            check("mrv_case_a_has_6_steps", len(steps) == 6, str(len(steps)))
            check("mrv_case_a_step1_completed", steps[0]["status"] == "completed")

        r = client.get(f"/v1/mrv/cases/{case['id']}/steps", headers=ha)
        check("mrv_steps_a_200", r.status_code == 200 and len(r.json()["items"]) == 6, r.text[:200])

        r = client.get(f"/v1/mrv/cases/{case['id']}/batches", headers=ha)
        check("mrv_batches_a_200", r.status_code == 200 and len(r.json()["items"]) == 1, r.text[:200])
        if r.status_code == 200 and r.json()["items"]:
            check("mrv_batch_a_resolves_farm", r.json()["items"][0]["farm_id"] == a["farm"]["id"])

        r = client.get(f"/v1/mrv/cases/{case['id']}/evidence", headers=ha)
        check("mrv_evidence_a_200", r.status_code == 200 and len(r.json()["items"]) == 1, r.text[:200])

        r = client.get(f"/v1/mrv/cases/{case['id']}/exports", headers=ha)
        check("mrv_exports_a_200", r.status_code == 200 and len(r.json()["items"]) == 1, r.text[:200])

        r = client.get(f"/v1/mrv/exports/{export['id']}", headers=ha)
        check("mrv_export_a_by_id_200", r.status_code == 200, r.text[:200])

        r = client.get("/v1/emission-factor-sets", headers=ha)
        check("ef_sets_list_includes_smoke_set", r.status_code == 200 and any(s["id"] == ef_set["id"] for s in r.json()["items"]), r.text[:200])

        r = client.get(f"/v1/emission-factor-sets/{ef_set['id']}/factors", headers=ha)
        check("ef_factors_200", r.status_code == 200 and any(f["id"] == ef["id"] for f in r.json()["items"]), r.text[:200])

        # -- Tenant isolation: A đọc resource của B PHẢI 404 (không phải leak/403) --
        cross_checks = [
            ("farm_b_via_a_404", f"/v1/farms/{b['farm']['id']}"),
            ("plot_b_via_a_404", f"/v1/plots/{b['plot']['id']}"),
            ("season_b_via_a_404", f"/v1/crop-seasons/{b['season']['id']}"),
            ("activities_b_via_a_404", f"/v1/crop-seasons/{b['season']['id']}/activities"),
            ("batches_b_via_a_404", f"/v1/crop-seasons/{b['season']['id']}/production-batches"),
            ("metrics_b_via_a_404", f"/v1/crop-seasons/{b['season']['id']}/metrics"),
            ("batch_b_via_a_404", f"/v1/production-batches/{b['batch']['id']}"),
            ("activity_b_via_a_404", f"/v1/activities/{b['activity']['id']}"),
            ("org_b_via_a_404", f"/v1/organizations/{b['org']['id']}"),
            ("org_b_summary_via_a_404", f"/v1/organizations/{b['org']['id']}/summary"),
            ("org_b_farms_via_a_404", f"/v1/organizations/{b['org']['id']}/farms"),
            ("org_b_metrics_via_a_404", f"/v1/organizations/{b['org']['id']}/metrics"),
            ("org_b_farm_perf_via_a_404", f"/v1/organizations/{b['org']['id']}/farm-performance"),
            ("farm_b_plots_via_a_404", f"/v1/farms/{b['farm']['id']}/plots"),
            ("farm_b_seasons_via_a_404", f"/v1/farms/{b['farm']['id']}/crop-seasons"),
            ("farm_b_metrics_via_a_404", f"/v1/farms/{b['farm']['id']}/metrics"),
        ]
        for name, path in cross_checks:
            r = client.get(path, headers=ha)
            check(name, r.status_code == 404, f"got {r.status_code}: {r.text[:150]}")

        # B tự đọc B vẫn phải OK (không phải toàn bộ B đều 404 — chỉ 404 với A)
        r = client.get(f"/v1/farms/{b['farm']['id']}", headers=hb)
        check("farm_b_own_200", r.status_code == 200, r.text[:200])

        # organizations/farms list KHÔNG được lẫn hàng của bên kia
        r = client.get("/v1/farms", headers=ha, params={"page_size": 100})
        check("farms_list_a_excludes_b", r.status_code == 200 and b["farm"]["id"] not in {f["id"] for f in r.json()["items"]}, r.text[:200])

        # -- error contract thống nhất --
        r = client.get(f"/v1/farms/{b['farm']['id']}", headers=ha)
        body = r.json()
        check("error_contract_nested", "code" in body.get("detail", {}).get("error", {}), str(body))

        # -- pagination --
        r = client.get("/v1/farms", headers=ha, params={"page": 1, "page_size": 1})
        check("pagination_page_size_respected", r.status_code == 200 and len(r.json()["items"]) <= 1, r.text[:200])
        r = client.get("/v1/farms", headers=ha, params={"page": 0})
        check("pagination_invalid_page_400", r.status_code == 400, str(r.status_code))

    finally:
        print("Cleaning up...")
        cleanup_by_run_id()
        time.sleep(1)
        after = table_counts()
        print("After-cleanup counts:", after)
        for t in TABLES_TO_COUNT:
            check(f"cleanup_count_restored[{t}]", after[t] == baseline[t], f"before={baseline[t]} after={after[t]}")

    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n=== {passed}/{total} checks passed ===")
    for name, ok, detail in results:
        if not ok:
            print(f"FAILED: {name} — {detail}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())

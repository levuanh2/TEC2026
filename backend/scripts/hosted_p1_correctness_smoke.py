"""Hosted Supabase smoke for the P1 correctness fixes — B4, M3, B5, B1, B2.

Run:  python backend/scripts/hosted_p1_correctness_smoke.py
Needs backend/.env (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_PUBLISHABLE_KEY,
SUPABASE_DB_URL).

Seeds an isolated tenant tagged `P1-CORRECTNESS-SMOKE-<run>` with the service role,
creates temporary Auth users (random passwords, never printed), signs them in and
calls the real FastAPI app (`main.app`, no overrides) against hosted Supabase.

No emission factor or GWP is filled. For M3 the script inserts Carbon rows
directly, pointing at a DRAFT factor set it creates (drafts are invisible to
clients) — the calculation rows are test data for the selection rule, not a
scientific result. Everything created is removed in `finally` and row counts are
compared. `audit.change_log` is append-only and is reported, not deleted.
"""
from __future__ import annotations

import hashlib
import sys
import time
import uuid
from datetime import date, timedelta
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import httpx  # noqa: E402
import psycopg  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from supabase import create_client  # noqa: E402

from infrastructure.config import load_settings  # noqa: E402

PREFIX = "P1-CORRECTNESS-SMOKE"
RUN_ID = uuid.uuid4().hex[:8]
TAG = f"{PREFIX}-{RUN_ID}"
EMAIL_PREFIX = f"{PREFIX.lower()}-{RUN_ID}"

settings = load_settings()
URL, SERVICE_KEY = settings.require_supabase()
_, PUBLISHABLE = settings.require_publishable()
DB_URL = settings.supabase_db_url
admin = create_client(URL, SERVICE_KEY)

COUNTED_TABLES = [
    "organizations", "organization_memberships", "organization_data_grants", "profiles", "farms",
    "farm_members", "plots", "crop_seasons", "production_batches", "activities", "irrigation_events",
    "fertilizer_applications", "harvest_events", "carbon_calculations", "carbon_breakdowns",
    "emission_factor_sets", "mrv_cases", "mrv_case_steps", "mrv_case_batches", "mrv_exports",
    "mrv_export_calculations",
]
DETAIL_TABLES = ("irrigation_events", "fertilizer_applications", "harvest_events", "seeding_events",
                 "pesticide_applications", "straw_management_events", "fuel_usages")

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(("PASS" if ok else "FAIL") + f"  {name}" + (f"  ({detail})" if detail and not ok else ""))


def db_scalar(sql: str, params: tuple = ()):
    with psycopg.connect(DB_URL) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()[0]


def snapshot() -> dict[str, int]:
    counts = {t: admin.table(t).select("*", count="exact").limit(1).execute().count for t in COUNTED_TABLES}
    counts["storage.objects[mrv-exports]"] = db_scalar("select count(*) from storage.objects where bucket_id = 'mrv-exports'")
    counts["auth.users[smoke]"] = db_scalar("select count(*) from auth.users where email like %s", (f"{PREFIX.lower()}-%",))
    return counts


def insert(table: str, row: dict) -> dict:
    return admin.table(table).insert(row).execute().data[0]


def activity(batch_id: str, kind: str, day: str, recorder: str, detail_table: str, detail: dict) -> str:
    row = insert("activities", {
        "production_batch_id": batch_id, "activity_type": kind, "occurred_at": f"2026-06-{day}T00:00:00Z",
        "recorded_at": f"2026-06-{day}T00:00:00Z", "source": "web", "recorded_by": recorder, "note": TAG,
    })
    insert(detail_table, {"activity_id": row["id"], **detail})
    return row["id"]


def seed() -> dict:
    s: dict = {}
    for key, kind in (("org", "cooperative"), ("org2", "cooperative"), ("gov", "government"), ("ent", "enterprise")):
        s[key] = insert("organizations", {"organization_code": f"{TAG}-{key.upper()}", "name": f"{TAG} {key}", "organization_type": kind})
    org = s["org"]["id"]
    s["farm"] = insert("farms", {"cooperative_id": org, "farm_code": f"{TAG}-FARM", "farm_name": f"{TAG} farm"})
    for n in (1, 2):
        plot = insert("plots", {"farm_id": s["farm"]["id"], "plot_code": f"{TAG}-PLOT{n}", "name": f"{TAG} plot {n}", "area_ha": 1.0})
        season = insert("crop_seasons", {
            "plot_id": plot["id"], "season_code": f"{TAG}-S{n}", "crop_type": "rice", "status": "active",
            "ipcc_water_regime": "irrigated_continuous_flooding",
            "pre_season_water_regime": "non_flooded_pre_season_lt_180d", "cultivation_days": 100,
        })
        s[f"season{n}"] = season
        s[f"batch{n}"] = insert("production_batches", {"crop_season_id": season["id"], "batch_code": "default"})
    s["case"] = insert("mrv_cases", {"organization_id": org, "case_code": f"{TAG}-CASE", "name": f"{TAG} case",
                                     "period_start": "2026-05-01", "period_end": "2026-09-30", "status": "draft"})
    insert("mrv_case_batches", {"mrv_case_id": s["case"]["id"], "production_batch_id": s["batch1"]["id"]})
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    for grantee in ("gov", "ent"):
        insert("organization_data_grants", {"grantee_organization_id": s[grantee]["id"], "source_organization_id": org,
                                            "access_level": "read", "valid_from": yesterday})
    s["factor_set"] = insert("emission_factor_sets", {
        "version_code": TAG, "name": f"{TAG} draft (selection-rule test data, not a factor set)",
        "methodology_name": "TEST ONLY", "source_name": "p1-correctness-smoke", "status": "draft",
    })

    users = {}
    for label in ("manager", "owner", "editor", "viewer", "regulator", "enterprise", "outsider"):
        email = f"{EMAIL_PREFIX}-{label}@agricarbon.invalid"
        password = f"P1-{uuid.uuid4().hex}!Aa1"
        user = admin.auth.admin.create_user({"email": email, "password": password, "email_confirm": True}).user
        users[label] = {"id": user.id, "email": email, "password": password}
    s["users"] = users
    member = lambda org_key, label, role: insert("organization_memberships", {"organization_id": s[org_key]["id"], "user_id": users[label]["id"], "role": role})
    member("org", "manager", "cooperative_manager")
    for label in ("owner", "editor", "viewer"):
        member("org", label, "farmer")
        insert("farm_members", {"farm_id": s["farm"]["id"], "user_id": users[label]["id"], "farm_role": label})
    member("gov", "regulator", "regulator")
    member("ent", "enterprise", "enterprise_viewer")
    member("org2", "outsider", "farmer")

    owner = users["owner"]["id"]
    b1, b2 = s["batch1"]["id"], s["batch2"]["id"]
    activity(b1, "harvest", "20", owner, "harvest_events", {"yield_kg": 1000})
    s["fertilizer"] = activity(b1, "fertilizer", "05", owner, "fertilizer_applications", {"fertilizer_name": "Urea", "amount_kg": 50, "nitrogen_percent": None})
    # B1: season 1 records the missing volume first, season 2 last.
    activity(b1, "irrigation", "01", owner, "irrigation_events", {"method": "continuous_flooding", "water_volume_m3": None})
    activity(b1, "irrigation", "02", owner, "irrigation_events", {"method": "continuous_flooding", "water_volume_m3": 100})
    activity(b2, "harvest", "20", owner, "harvest_events", {"yield_kg": 1000})
    activity(b2, "irrigation", "01", owner, "irrigation_events", {"method": "continuous_flooding", "water_volume_m3": 100})
    activity(b2, "irrigation", "02", owner, "irrigation_events", {"method": "continuous_flooding", "water_volume_m3": None})
    return s


def sign_in(user: dict) -> str:
    r = httpx.post(f"{URL}/auth/v1/token?grant_type=password", headers={"apikey": PUBLISHABLE},
                   json={"email": user["email"], "password": user["password"]}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def cleanup() -> None:
    def attempt(label, fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            print(f"  cleanup warning [{label}]: {exc}")

    for case in admin.table("mrv_cases").select("id").ilike("case_code", f"{TAG}-%").execute().data:
        cid = case["id"]
        for export in admin.table("mrv_exports").select("id").eq("mrv_case_id", cid).execute().data:
            attempt("export calcs", lambda x=export["id"]: admin.table("mrv_export_calculations").delete().eq("mrv_export_id", x).execute())
        attempt("renders", lambda x=cid: admin.table("mrv_exports").delete().eq("mrv_case_id", x).neq("format", "json").execute())
        attempt("exports", lambda x=cid: admin.table("mrv_exports").delete().eq("mrv_case_id", x).execute())
        for table in ("mrv_case_batches", "mrv_case_steps"):
            attempt(table, lambda t=table, x=cid: admin.table(t).delete().eq("mrv_case_id", x).execute())
        attempt("case", lambda x=cid: admin.table("mrv_cases").delete().eq("id", x).execute())

    orgs = admin.table("organizations").select("id").ilike("organization_code", f"{TAG}-%").execute().data
    org_ids = [o["id"] for o in orgs]
    for oid in org_ids:
        for farm in admin.table("farms").select("id").eq("cooperative_id", oid).execute().data:
            for plot in admin.table("plots").select("id").eq("farm_id", farm["id"]).execute().data:
                for season in admin.table("crop_seasons").select("id").eq("plot_id", plot["id"]).execute().data:
                    sid = season["id"]
                    for calc in admin.table("carbon_calculations").select("id").eq("crop_season_id", sid).execute().data:
                        attempt("breakdowns", lambda x=calc["id"]: admin.table("carbon_breakdowns").delete().eq("calculation_id", x).execute())
                    attempt("calculations", lambda x=sid: admin.table("carbon_calculations").delete().eq("crop_season_id", x).execute())
                    for batch in admin.table("production_batches").select("id").eq("crop_season_id", sid).execute().data:
                        for act in admin.table("activities").select("id").eq("production_batch_id", batch["id"]).execute().data:
                            for detail in DETAIL_TABLES:
                                attempt(detail, lambda t=detail, x=act["id"]: admin.table(t).delete().eq("activity_id", x).execute())
                            attempt("activity", lambda x=act["id"]: admin.table("activities").delete().eq("id", x).execute())
                        attempt("batch", lambda x=batch["id"]: admin.table("production_batches").delete().eq("id", x).execute())
                    attempt("season", lambda x=sid: admin.table("crop_seasons").delete().eq("id", x).execute())
                attempt("plot", lambda x=plot["id"]: admin.table("plots").delete().eq("id", x).execute())
            attempt("farm members", lambda x=farm["id"]: admin.table("farm_members").delete().eq("farm_id", x).execute())
            attempt("farm", lambda x=farm["id"]: admin.table("farms").delete().eq("id", x).execute())
    for oid in org_ids:
        attempt("grants", lambda x=oid: admin.table("organization_data_grants").delete().eq("grantee_organization_id", x).execute())
        attempt("grants src", lambda x=oid: admin.table("organization_data_grants").delete().eq("source_organization_id", x).execute())
        attempt("memberships", lambda x=oid: admin.table("organization_memberships").delete().eq("organization_id", x).execute())
    for oid in org_ids:
        attempt("org", lambda x=oid: admin.table("organizations").delete().eq("id", x).execute())
    attempt("factor set", lambda: admin.table("emission_factor_sets").delete().eq("version_code", TAG).execute())

    with psycopg.connect(DB_URL) as conn, conn.cursor() as cur:
        cur.execute("select id from auth.users where email like %s", (f"{EMAIL_PREFIX}-%",))
        user_ids = [str(r[0]) for r in cur.fetchall()]
    for uid in user_ids:
        attempt("devices", lambda x=uid: admin.table("devices").delete().eq("user_id", x).execute())
        attempt("user", lambda x=uid: admin.auth.admin.delete_user(x))
        attempt("profile", lambda x=uid: admin.table("profiles").delete().eq("id", x).execute())


def carbon_row(s: dict, calc_id: str, scenario: str, day: int, total: float) -> dict:
    return {
        "id": calc_id, "crop_season_id": s["season1"]["id"], "scenario": scenario, "status": "succeeded",
        "factor_set_id": s["factor_set"]["id"], "engine_version": "p1-smoke",
        "input_hash": hashlib.sha256(f"{TAG}-{calc_id}".encode()).hexdigest(),
        "total_co2e_kg": total, "yield_kg": 1000, "calculated_at": f"2026-09-{day:02d}T00:00:00Z", "warnings": [],
    }


def run_checks(s: dict, client: TestClient) -> None:
    users = s["users"]
    tokens = {label: sign_in(user) for label, user in users.items()}
    auth = lambda label: {"Authorization": f"Bearer {tokens[label]}"}
    season1, season2 = s["season1"]["id"], s["season2"]["id"]
    body = lambda: {"crop_season_id": season1, "water_regime_scenario": "as_recorded"}
    calc_count = lambda: admin.table("carbon_calculations").select("id", count="exact").eq("crop_season_id", season1).execute().count

    # ---- B2 ----------------------------------------------------------------
    me = client.get("/v1/me", headers=auth("enterprise")).json()
    check("b2_enterprise_me_roles_canonical", me.get("roles") == ["enterprise_viewer"], str(me.get("roles")))
    check("b2_enterprise_me_org", [m["organization_id"] for m in me.get("organization_memberships", [])] == [s["ent"]["id"]], str(me))
    check("b2_regulator_me_roles", client.get("/v1/me", headers=auth("regulator")).json().get("roles") == ["regulator"])

    # ---- B5 ----------------------------------------------------------------
    r = client.post("/v1/carbon/calculate", json=body(), headers=auth("owner"))
    error = r.json().get("detail", {}).get("error", {})
    check("b5_missing_nitrogen_422", r.status_code == 422 and error.get("code") == "missing_activity_data", f"{r.status_code} {r.text[:200]}")
    check("b5_message_names_field_no_internals", "nitrogen_percent" in error.get("message", "") and "Traceback" not in r.text)
    admin.table("fertilizer_applications").update({"nitrogen_percent": 46}).eq("activity_id", s["fertilizer"]).execute()
    r = client.post("/v1/carbon/calculate", json=body(), headers=auth("owner"))
    check("b5_valid_nitrogen_reaches_factor_gate", r.status_code == 422 and r.json()["detail"]["error"]["code"] == "missing_emission_factor", f"{r.status_code} {r.text[:160]}")

    # ---- B4 ----------------------------------------------------------------
    for label in ("viewer", "regulator", "enterprise"):
        r = client.get(f"/v1/crop-seasons/{season1}/carbon", headers=auth(label))
        check(f"b4_{label}_can_view_season_carbon", r.status_code == 404 and r.json()["detail"]["error"]["code"] == "no_calculation", f"{r.status_code} {r.text[:120]}")
        r = client.post("/v1/carbon/calculate", json=body(), headers=auth(label))
        check(f"b4_{label}_persist_denied_404", r.status_code == 404 and r.json()["detail"]["error"]["code"] == "crop_not_found", f"{r.status_code} {r.text[:120]}")
    r = client.post("/v1/carbon/calculate", json=body(), headers=auth("outsider"))
    check("b4_cross_scope_denied_404", r.status_code == 404 and r.json()["detail"]["error"]["code"] == "crop_not_found", f"{r.status_code}")
    r = client.post("/v1/carbon/calculate", json=body())
    check("b4_unauthenticated_401", r.status_code == 401, str(r.status_code))
    for label in ("owner", "editor", "manager"):
        r = client.post("/v1/carbon/calculate", json=body(), headers=auth(label))
        check(f"b4_{label}_passes_persist_gate", r.status_code == 422 and r.json()["detail"]["error"]["code"] == "missing_emission_factor", f"{r.status_code} {r.text[:120]}")
    check("b4_no_carbon_row_persisted", calc_count() == 0, str(calc_count()))

    # ---- M3 ----------------------------------------------------------------
    ids = {k: str(uuid.uuid4()) for k in "ABC"}
    admin.table("carbon_calculations").insert([
        carbon_row(s, ids["A"], "actual", 1, 100.0), carbon_row(s, ids["B"], "awd", 2, 55.0),
    ]).execute()

    def export_carbon(expect: str | None):
        r = client.post(f"/v1/mrv/cases/{s['case']['id']}/exports", json={"format": "json"}, headers=auth("manager"))
        if r.status_code != 201:
            return r.status_code, None, None, []
        created = r.json()
        per = created["manifest"]["carbon"]["per_crop_season"].get(season1, {})
        linked = [row["carbon_calculation_id"] for row in admin.table("mrv_export_calculations").select("carbon_calculation_id").eq("mrv_export_id", created["export_id"]).execute().data]
        return r.status_code, per, created["manifest"], linked

    status, per, _, linked = export_carbon("A")
    check("m3_canonical_over_newer_hypothetical", status == 201 and per and per["calculation_id"] == ids["A"] and per["scenario"] == "actual", f"{status} {per}")
    check("m3_export_links_only_canonical", linked == [ids["A"]], str(linked))
    r = client.get(f"/v1/crop-seasons/{season1}/metrics", headers=auth("manager"))
    check("m3_metrics_agree_with_export", r.status_code == 200 and r.json()["total_co2e_kg"] == 100.0, r.text[:160])

    admin.table("carbon_calculations").insert(carbon_row(s, ids["C"], "actual", 3, 120.0)).execute()
    status, per, _, linked = export_carbon("C")
    check("m3_newer_canonical_selected", status == 201 and per and per["calculation_id"] == ids["C"], f"{status} {per}")
    check("m3_export_links_new_canonical", linked == [ids["C"]], str(linked))

    # "Only hypothetical rows" on a second case whose only season has just an AWD
    # row. (A and C cannot be deleted: exported evidence references them, and the
    # FK protecting that is correct.)
    case2 = insert("mrv_cases", {"organization_id": s["org"]["id"], "case_code": f"{TAG}-CASE2", "name": f"{TAG} case 2",
                                 "period_start": "2026-05-01", "period_end": "2026-09-30", "status": "draft"})
    insert("mrv_case_batches", {"mrv_case_id": case2["id"], "production_batch_id": s["batch2"]["id"]})
    admin.table("carbon_calculations").insert({**carbon_row(s, str(uuid.uuid4()), "awd", 4, 40.0), "crop_season_id": season2}).execute()
    r = client.post(f"/v1/mrv/cases/{case2['id']}/exports", json={"format": "json"}, headers=auth("manager"))
    status, manifest = r.status_code, (r.json()["manifest"] if r.status_code == 201 else {})
    per = manifest.get("carbon", {}).get("per_crop_season", {}).get(season2) if manifest else None
    linked = [row["carbon_calculation_id"] for row in admin.table("mrv_export_calculations").select("carbon_calculation_id").eq("mrv_export_id", r.json().get("export_id")).execute().data] if status == 201 else ["n/a"]
    codes = [w["code"] for w in (manifest or {}).get("warnings", [])]
    check("m3_only_hypothetical_means_unavailable", status == 201 and per and per["status"] == "unavailable" and per["calculation_id"] is None, f"{status} {per}")
    check("m3_unavailable_warning_present", "carbon_unavailable" in codes, str(codes))
    check("m3_no_fallback_link", linked == [], str(linked))

    # ---- B1 ----------------------------------------------------------------
    for label, sid in (("missing_first", season1), ("missing_last", season2)):
        r = client.get(f"/v1/crop-seasons/{sid}/metrics", headers=auth("owner")).json()
        check(f"b1_{label}_water_incomplete", r["data_completeness"]["water"] is False and r["water_m3"] is None and r["water_per_kg"] is None, str(r))
    farm = client.get(f"/v1/farms/{s['farm']['id']}/metrics", headers=auth("owner")).json()
    check("b1_farm_rollup_water_null", farm["water_m3"] is None and farm["water_per_kg"] is None, str(farm))


def main() -> int:
    print(f"=== Hosted P1 correctness smoke — run {RUN_ID} ===")
    before = snapshot()
    audit_before = db_scalar("select count(*) from audit.change_log")
    try:
        state = seed()
        from main import app
        with TestClient(app) as client:
            run_checks(state, client)
    except Exception as exc:  # noqa: BLE001
        check("smoke_completed_without_exception", False, repr(exc))
    finally:
        print("Cleaning up ...")
        cleanup()
        time.sleep(1)
        after = snapshot()
        diff = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
        check("cleanup_row_counts_restored", not diff, str(diff))
        print(f"Row counts (unchanged={not diff}): {after}")
        print(f"audit.change_log rows added by this run (append-only, retained): {db_scalar('select count(*) from audit.change_log') - audit_before}")
    failed = [name for name, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("FAILED:", ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

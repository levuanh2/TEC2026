"""Hosted dev end-to-end smoke for the published Carbon factor set.

Run:  python backend/scripts/hosted_carbon_factor_smoke.py
Needs backend/.env (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_PUBLISHABLE_KEY,
SUPABASE_DB_URL) and the factor set `0.3.0-ipcc2019-tier1-ar5` imported with
`scripts/import_factor_set.py --apply --publish`.

Seeds an isolated tenant tagged `CARBON-FACTOR-SMOKE-<run>` with complete Carbon
inputs and no fuel (fuel has no verified factor and must still fail closed), creates
temporary Auth users (random passwords, never printed), signs them in and calls the
real FastAPI app (`main.app`) against hosted Supabase:

  * real calculations compared with the hand calculation below;
  * the persist authorization matrix;
  * recommendation generation (persist=False carbon what-ifs);
  * the MRV JSON snapshot, then XLSX and PDF rendered from that same snapshot.

Everything the run creates is removed in `finally` and row counts are compared. The
factor set itself is not touched. `audit.change_log` is append-only and reported.

Hand calculation (1 ha, 100 d, continuous flooding, pre-season non-flooded <180 d,
urea 100 kg @ 46 % N, 2,000 kg straw @ 0.85 DM burned, 6,000 kg paddy; AR5 GWP-100):
  rice CH4  1.22 x 1.00 x 1.00 x 1 x 100 x 1        = 122.0 kg   -> x 28  = 3,416.0
  N2O       46 kg N x 0.003 x 44/28                 = 0.2168571  -> x 265 = 57.4671
  straw     1,700 kg DM x 0.80 = 1,360 kg burnt; CH4 3.672 kg -> 102.816; N2O 0.0952 kg -> 25.228
  total                                                                   = 3,601.5111 kg CO2e
  per kg paddy                                                            = 0.6002519
  AWD: CH4 1,878.8 + N2O (0.005) 95.7786 + straw 128.044                  = 2,102.6226
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

from carbon import ParameterSet  # noqa: E402
from infrastructure.config import load_settings  # noqa: E402

PREFIX = "CARBON-FACTOR-SMOKE"
RUN_ID = uuid.uuid4().hex[:8]
TAG = f"{PREFIX}-{RUN_ID}"
EMAIL_PREFIX = f"{PREFIX.lower()}-{RUN_ID}"
BUCKET = "mrv-exports"
VERSION = "0.3.0-ipcc2019-tier1-ar5"
EXPECTED_TOTAL, EXPECTED_PER_KG, EXPECTED_AWD = 3601.5111, 0.6002519, 2102.6226

settings = load_settings()
URL, SERVICE_KEY = settings.require_supabase()
_, PUBLISHABLE = settings.require_publishable()
DB_URL = settings.supabase_db_url
admin = create_client(URL, SERVICE_KEY)

COUNTED_TABLES = [
    "organizations", "organization_memberships", "organization_data_grants", "profiles", "farms",
    "farm_members", "plots", "crop_seasons", "production_batches", "activities", "irrigation_events",
    "fertilizer_applications", "harvest_events", "straw_management_events", "carbon_calculations",
    "carbon_breakdowns", "season_recommendations", "emission_factor_sets", "emission_factors",
    "mrv_cases", "mrv_case_steps", "mrv_case_batches", "mrv_exports", "mrv_export_calculations",
]
DETAIL_TABLES = ("irrigation_events", "fertilizer_applications", "harvest_events", "seeding_events",
                 "pesticide_applications", "straw_management_events", "fuel_usages")

results: list[tuple[str, bool, str]] = []
timings: dict[str, float] = {}


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(("PASS" if ok else "FAIL") + f"  {name}" + (f"  ({detail})" if detail and not ok else ""))


def timed(label: str, fn):
    started = time.perf_counter()
    try:
        return fn()
    finally:
        timings[label] = round((time.perf_counter() - started) * 1000, 1)


def db_scalar(sql: str, params: tuple = ()):
    with psycopg.connect(DB_URL) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()[0]


def snapshot() -> dict[str, int]:
    counts = {t: admin.table(t).select("*", count="exact").limit(1).execute().count for t in COUNTED_TABLES}
    counts["storage.objects[mrv-exports]"] = db_scalar("select count(*) from storage.objects where bucket_id = %s", (BUCKET,))
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
    for key, kind in (("org", "cooperative"), ("gov", "government"), ("ent", "enterprise")):
        s[key] = insert("organizations", {"organization_code": f"{TAG}-{key.upper()}", "name": f"{TAG} {key}", "organization_type": kind})
    s["farm"] = insert("farms", {"cooperative_id": s["org"]["id"], "farm_code": f"{TAG}-FARM", "farm_name": f"{TAG} farm"})
    plot = insert("plots", {"farm_id": s["farm"]["id"], "plot_code": f"{TAG}-PLOT", "name": f"{TAG} plot", "area_ha": 1.0})
    s["season"] = insert("crop_seasons", {
        "plot_id": plot["id"], "season_code": f"{TAG}-S1", "crop_type": "rice", "status": "active",
        "ipcc_water_regime": "irrigated_continuous_flooding",
        "pre_season_water_regime": "non_flooded_pre_season_lt_180d", "cultivation_days": 100,
    })
    s["batch"] = insert("production_batches", {"crop_season_id": s["season"]["id"], "batch_code": "default"})
    s["case"] = insert("mrv_cases", {"organization_id": s["org"]["id"], "case_code": f"{TAG}-CASE", "name": f"{TAG} case",
                                     "period_start": "2026-05-01", "period_end": "2026-09-30", "status": "draft"})
    insert("mrv_case_batches", {"mrv_case_id": s["case"]["id"], "production_batch_id": s["batch"]["id"]})
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    for grantee in ("gov", "ent"):
        insert("organization_data_grants", {"grantee_organization_id": s[grantee]["id"], "source_organization_id": s["org"]["id"],
                                            "access_level": "read", "valid_from": yesterday})

    users = {}
    for label in ("manager", "owner", "editor", "viewer", "regulator", "enterprise"):
        email = f"{EMAIL_PREFIX}-{label}@agricarbon.invalid"
        password = f"CF-{uuid.uuid4().hex}!Aa1"
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

    owner, batch = users["owner"]["id"], s["batch"]["id"]
    activity(batch, "irrigation", "02", owner, "irrigation_events", {"method": "continuous_flooding", "water_volume_m3": 4000})
    activity(batch, "fertilizer", "05", owner, "fertilizer_applications", {"fertilizer_name": "Urea", "amount_kg": 100, "nitrogen_percent": 46})
    activity(batch, "harvest", "20", owner, "harvest_events", {"yield_kg": 6000})
    activity(batch, "straw_management", "21", owner, "straw_management_events", {"method": "burned", "straw_mass_kg": 2000, "dry_matter_fraction": 0.85})
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

    orgs = admin.table("organizations").select("id").ilike("organization_code", f"{TAG}-%").execute().data
    org_ids = [o["id"] for o in orgs]
    with psycopg.connect(DB_URL) as conn, conn.cursor() as cur:
        names: list[str] = []
        for oid in org_ids:
            cur.execute("select name from storage.objects where bucket_id = %s and name like %s", (BUCKET, f"{oid}/%"))
            names += [r[0] for r in cur.fetchall()]
    if names:
        attempt("storage", lambda: admin.storage.from_(BUCKET).remove(names))

    for case in admin.table("mrv_cases").select("id").ilike("case_code", f"{TAG}-%").execute().data:
        cid = case["id"]
        for export in admin.table("mrv_exports").select("id").eq("mrv_case_id", cid).execute().data:
            attempt("export calcs", lambda x=export["id"]: admin.table("mrv_export_calculations").delete().eq("mrv_export_id", x).execute())
        attempt("renders", lambda x=cid: admin.table("mrv_exports").delete().eq("mrv_case_id", x).neq("format", "json").execute())
        attempt("exports", lambda x=cid: admin.table("mrv_exports").delete().eq("mrv_case_id", x).execute())
        for table in ("mrv_case_batches", "mrv_case_steps"):
            attempt(table, lambda t=table, x=cid: admin.table(t).delete().eq("mrv_case_id", x).execute())
        attempt("case", lambda x=cid: admin.table("mrv_cases").delete().eq("id", x).execute())

    for oid in org_ids:
        for farm in admin.table("farms").select("id").eq("cooperative_id", oid).execute().data:
            for plot in admin.table("plots").select("id").eq("farm_id", farm["id"]).execute().data:
                for season in admin.table("crop_seasons").select("id").eq("plot_id", plot["id"]).execute().data:
                    sid = season["id"]
                    attempt("recommendations", lambda x=sid: admin.table("season_recommendations").delete().eq("crop_season_id", x).execute())
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

    with psycopg.connect(DB_URL) as conn, conn.cursor() as cur:
        cur.execute("select id from auth.users where email like %s", (f"{EMAIL_PREFIX}-%",))
        user_ids = [str(r[0]) for r in cur.fetchall()]
    for uid in user_ids:
        attempt("devices", lambda x=uid: admin.table("devices").delete().eq("user_id", x).execute())
        attempt("user", lambda x=uid: admin.auth.admin.delete_user(x))
        attempt("profile", lambda x=uid: admin.table("profiles").delete().eq("id", x).execute())


def run_checks(s: dict, client: TestClient) -> None:
    tokens = {label: sign_in(user) for label, user in s["users"].items()}
    auth = lambda label: {"Authorization": f"Bearer {tokens[label]}"}
    season, case = s["season"]["id"], s["case"]["id"]
    calc_count = lambda: admin.table("carbon_calculations").select("id", count="exact").eq("crop_season_id", season).execute().count
    calculate = lambda label, scenario="as_recorded": client.post(
        "/v1/carbon/calculate", json={"crop_season_id": season, "water_regime_scenario": scenario}, headers=auth(label))

    # ---- factor set ------------------------------------------------------------
    params = timed("factor_load_yaml_ms", lambda: ParameterSet.load(BACKEND_DIR / "config" / "emission_factors.yaml"))
    set_row = timed("factor_set_lookup_hosted_ms", lambda: admin.table("emission_factor_sets").select("id,version_code,status")
                    .eq("version_code", VERSION).execute().data)
    check("factor_set_published_on_hosted", len(set_row) == 1 and set_row[0]["status"] == "published", str(set_row))
    set_id = set_row[0]["id"] if set_row else None
    check("engine_yaml_matches_published_version", params.version == VERSION, params.version)
    health = client.get("/health").json()
    readiness = health.get("carbon_scientific_readiness", {})
    check("health_ready_for_demo_not_production", readiness.get("level") == "READY_FOR_DEMO"
          and health.get("carbon_production_ready") is False and health.get("mrv_compliant") is False, str(health)[:300])
    listed = client.get("/v1/emission-factor-sets", headers=auth("viewer"))
    check("viewer_sees_published_set", listed.status_code == 200 and any(i.get("version_code") == VERSION for i in listed.json()["items"]), listed.text[:200])

    # ---- real calculation (owner) ------------------------------------------------
    r = timed("carbon_calculate_as_recorded_ms", lambda: calculate("owner"))
    body = r.json()
    check("owner_as_recorded_200", r.status_code == 200, f"{r.status_code} {r.text[:300]}")
    if r.status_code != 200:
        return
    check("total_matches_hand_calculation", abs(body["total_co2e_kg"] - EXPECTED_TOTAL) < 1e-3, str(body["total_co2e_kg"]))
    check("per_kg_matches_hand_calculation", abs(body["co2e_per_kg"] - EXPECTED_PER_KG) < 1e-6, str(body["co2e_per_kg"]))
    sources = sorted((b["source"], b["gas"]) for b in body["breakdown"])
    check("breakdown_sources", sources == [("ch4_rice_cultivation", "ch4"), ("n2o_fertilizer_direct", "n2o"),
                                           ("straw_burning", "ch4"), ("straw_burning", "n2o")], str(sources))
    check("breakdown_all_verified", all(set(b["parameter_status"].values()) == {"VERIFIED"} for b in body["breakdown"]))
    check("no_factor_warning_left", not any("PENDING" in w or "chưa xác minh" in w for w in body["warnings"]), str(body["warnings"]))
    stored = admin.table("carbon_calculations").select("*").eq("id", body["calculation_id"]).execute().data
    check("calculation_persisted_with_factor_set", len(stored) == 1 and stored[0]["factor_set_id"] == set_id
          and stored[0]["scenario"] == "actual" and stored[0]["status"] == "succeeded" and stored[0]["mrv_compliant"] is False, str(stored)[:300])
    breakdowns = admin.table("carbon_breakdowns").select("category,emission_factor_id,co2e_kg").eq("calculation_id", body["calculation_id"]).execute().data
    factor_ids = {f["id"] for f in admin.table("emission_factors").select("id").eq("factor_set_id", set_id).execute().data}
    check("breakdown_rows_link_factors_of_published_set", len(breakdowns) == 4 and all(b["emission_factor_id"] in factor_ids for b in breakdowns), str(breakdowns))
    check("breakdown_sum_equals_total", abs(sum(float(b["co2e_kg"]) for b in breakdowns) - float(stored[0]["total_co2e_kg"])) < 1e-3)

    r = calculate("owner", "awd")
    check("owner_awd_matches_hand_calculation", r.status_code == 200 and abs(r.json()["total_co2e_kg"] - EXPECTED_AWD) < 1e-3, f"{r.status_code} {r.text[:160]}")

    # ---- authorization matrix ------------------------------------------------------
    for label in ("editor", "manager"):
        r = calculate(label)
        check(f"{label}_calculation_allowed_200", r.status_code == 200, f"{r.status_code} {r.text[:120]}")
        # Same inputs, same factor set: the recalculation reuses the stored row (idempotent).
        check(f"{label}_identical_recalculation_reuses_row", r.status_code == 200 and r.json()["calculation_id"] == body["calculation_id"], r.text[:120])
    before = calc_count()
    for label in ("viewer", "regulator", "enterprise"):
        r = calculate(label)
        check(f"{label}_calculation_denied_404", r.status_code == 404 and r.json()["detail"]["error"]["code"] == "crop_not_found", f"{r.status_code} {r.text[:120]}")
        r = client.get(f"/v1/crop-seasons/{season}/carbon", params={"scenario": "as_recorded"}, headers=auth(label))
        check(f"{label}_can_read_latest_carbon", r.status_code == 200 and abs(r.json()["total_co2e_kg"] - EXPECTED_TOTAL) < 1e-3, f"{r.status_code} {r.text[:120]}")
    check("denied_callers_persisted_nothing", calc_count() == before, f"{before} -> {calc_count()}")

    # ---- recommendation (persist=False carbon what-ifs) ----------------------------------
    before = calc_count()
    r = client.post(f"/v1/crop-seasons/{season}/recommendations/generate", headers=auth("owner"))
    items = r.json().get("items", []) if r.status_code == 200 else []
    awd = next((i for i in items if i["impact_status"] == "available" and i.get("co2e_total_kg_delta") is not None), None)
    check("recommendation_generate_200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    check("recommendation_awd_impact_matches_engine", awd is not None and abs(abs(awd["co2e_total_kg_delta"]) - (EXPECTED_TOTAL - EXPECTED_AWD)) < 1e-2, str(items)[:300])
    check("recommendation_persisted_no_carbon_row", calc_count() == before, f"{before} -> {calc_count()}")

    # ---- MRV: JSON snapshot, then XLSX + PDF from the same snapshot ---------------------------
    r = timed("mrv_json_generate_ms", lambda: client.post(f"/v1/mrv/cases/{case}/exports", json={"format": "json"}, headers=auth("manager")))
    check("mrv_json_201", r.status_code == 201, f"{r.status_code} {r.text[:200]}")
    if r.status_code != 201:
        return
    snap = r.json()
    manifest = snap["manifest"]
    per = manifest["carbon"]["per_crop_season"].get(season, {})
    latest_actual = admin.table("carbon_calculations").select("id").eq("crop_season_id", season).eq("scenario", "actual") \
        .order("calculated_at", desc=True).limit(1).execute().data[0]["id"]
    check("mrv_carbon_available_canonical_actual", per.get("status") == "succeeded" and per.get("scenario") == "actual"
          and per.get("calculation_id") == latest_actual, str(per)[:300])
    check("mrv_total_matches_hand_calculation", abs(float(per.get("total_co2e_kg") or 0) - EXPECTED_TOTAL) < 1e-3, str(per.get("total_co2e_kg")))
    provenance = manifest["provenance"]["emission_factor_sets"]
    check("mrv_provenance_names_published_set", len(provenance) == 1 and provenance[0]["version_code"] == VERSION
          and len(provenance[0]["factors"]) == 27 and all(f["verification_status"] == "VERIFIED" for f in provenance[0]["factors"]), str(provenance)[:300])
    codes = [w["code"] for w in manifest["warnings"]]
    check("mrv_no_provenance_or_unverified_warning", "factor_provenance_unavailable" not in codes and "factor_unverified" not in codes, str(codes))
    check("mrv_not_claimed_compliant", manifest["readiness"].get("carbon_available") is True and "mrv_compliant" not in str(manifest["readiness"]).replace("False", ""), str(manifest["readiness"]))
    linked = [row["carbon_calculation_id"] for row in admin.table("mrv_export_calculations").select("carbon_calculation_id").eq("mrv_export_id", snap["export_id"]).execute().data]
    check("mrv_links_only_canonical_calculation", linked == [latest_actual], str(linked))

    artifacts = {}
    for fmt in ("xlsx", "pdf"):
        r = timed(f"mrv_{fmt}_render_ms", lambda f=fmt: client.post(f"/v1/mrv/exports/{snap['export_id']}/render", json={"format": f}, headers=auth("manager")))
        check(f"mrv_{fmt}_render_201", r.status_code == 201, f"{r.status_code} {r.text[:200]}")
        if r.status_code == 201:
            artifacts[fmt] = r.json()
            check(f"mrv_{fmt}_from_same_snapshot", artifacts[fmt]["source_snapshot_export_id"] == snap["export_id"]
                  and artifacts[fmt]["payload_sha256"] == snap["payload_sha256"], str(artifacts[fmt])[:200])
    for fmt, meta in [("json", snap), *artifacts.items()]:
        r = client.get(f"/v1/mrv/exports/{meta['export_id']}/download", headers=auth("manager"))
        check(f"mrv_{fmt}_download_sha256_valid", r.status_code == 200 and hashlib.sha256(r.content).hexdigest() == meta["file_sha256"], str(r.status_code))
    print(f"factor_set_id={set_id} snapshot payload_sha256={snap['payload_sha256']}")


def main() -> int:
    print(f"=== Hosted Carbon factor smoke — run {RUN_ID} ===")
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
        print(f"audit.change_log rows added by this run (append-only, retained): {db_scalar('select count(*) from audit.change_log') - audit_before}")
    print(f"Timings (ms): {timings}")
    failed = [name for name, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("FAILED:", ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

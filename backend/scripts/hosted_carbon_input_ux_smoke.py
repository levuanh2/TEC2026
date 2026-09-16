"""Hosted dev smoke: can a NORMAL user produce a Carbon result through the API?

Run:  python backend/scripts/hosted_carbon_input_ux_smoke.py
Needs backend/.env (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_PUBLISHABLE_KEY,
SUPABASE_DB_URL) and the published factor set `0.3.0-ipcc2019-tier1-ar5`.

The point of this script is what it REFUSES to do. Service-role seeding creates only
what a Farmer Web user genuinely cannot create for themselves — the tenant shell
(organization, farm, plot, empty crop season, production batch) and the Auth users.
The season is seeded with `ipcc_water_regime`, `pre_season_water_regime` and
`cultivation_days` left NULL, exactly as a freshly created season looks.

Everything that decides the Carbon result then goes through the real FastAPI app
with a normal user's JWT:

  * the methodology inputs via PATCH /v1/crop-seasons/{id}/methodology (the route
    this sprint adds — before it, Farmer Web had no way to set SFw/SFp at all);
  * irrigation, fertilizer and harvest via POST /v1/crop-seasons/{id}/activities;
  * the calculation via POST /v1/carbon/calculate.

It first asserts the season CANNOT be calculated while the regimes are missing, so
a future regression that silently defaults a water regime fails here.

Hand calculation (1 ha, 100 d, continuous flooding, pre-season non-flooded <180 d,
urea 100 kg @ 46 % N, 6,000 kg paddy; AR5 GWP-100):
  CH4  1.22 x 1.00 x 1.00 x 1.0 x 100 x 1 = 122.0 kg  -> x 28  = 3,416.0
  N2O  46 kg N x 0.003 x 44/28 = 0.2168571 kg         -> x 265 =    57.4671
  total = 3,473.4671 kg CO2e ; per kg paddy = 0.5789112

Everything created is removed in `finally` and row counts are compared.
"""
from __future__ import annotations

import sys
import time
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import httpx  # noqa: E402
import psycopg  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from supabase import create_client  # noqa: E402

from infrastructure.config import load_settings  # noqa: E402

PREFIX = "CARBON-UX-SMOKE"
RUN_ID = uuid.uuid4().hex[:8]
TAG = f"{PREFIX}-{RUN_ID}"
EMAIL_PREFIX = f"{PREFIX.lower()}-{RUN_ID}"
EXPECTED_TOTAL, EXPECTED_PER_KG = 3473.4671, 0.5789112
IRRIGATION_COST, FERTILIZER_COST, HARVEST_COST = 300_000.0, 850_000.0, 1_200_000.0

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
]
DETAIL_TABLES = ("irrigation_events", "fertilizer_applications", "harvest_events", "seeding_events",
                 "pesticide_applications", "straw_management_events", "fuel_usages")

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(("PASS" if ok else "FAIL") + f"  {name}" + (f"  ({detail})" if detail and not ok else ""))


def close(a, b, tol=1e-3) -> bool:
    return a is not None and abs(float(a) - b) <= tol


def db_scalar(sql: str, params: tuple = ()):
    with psycopg.connect(DB_URL) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()[0]


def snapshot() -> dict[str, int]:
    counts = {t: admin.table(t).select("*", count="exact").limit(1).execute().count for t in COUNTED_TABLES}
    counts["auth.users[smoke]"] = db_scalar("select count(*) from auth.users where email like %s", (f"{PREFIX.lower()}-%",))
    return counts


def insert(table: str, row: dict) -> dict:
    return admin.table(table).insert(row).execute().data[0]


def seed() -> dict:
    """Only the tenant shell. NOTE the season's three methodology columns are left
    NULL on purpose — supplying them here would fake the very thing under test."""
    s: dict = {}
    for key, kind in (("org", "cooperative"), ("gov", "government")):
        s[key] = insert("organizations", {"organization_code": f"{TAG}-{key.upper()}", "name": f"{TAG} {key}", "organization_type": kind})
    s["farm"] = insert("farms", {"cooperative_id": s["org"]["id"], "farm_code": f"{TAG}-FARM", "farm_name": f"{TAG} farm"})
    plot = insert("plots", {"farm_id": s["farm"]["id"], "plot_code": f"{TAG}-PLOT", "name": f"{TAG} plot", "area_ha": 1.0})
    s["season"] = insert("crop_seasons", {
        "plot_id": plot["id"], "season_code": f"{TAG}-S1", "crop_type": "rice", "status": "active",
    })
    s["batch"] = insert("production_batches", {"crop_season_id": s["season"]["id"], "batch_code": "default"})

    users = {}
    for label in ("owner", "viewer", "manager", "regulator"):
        email = f"{EMAIL_PREFIX}-{label}@agricarbon.invalid"
        password = f"UX-{uuid.uuid4().hex}!Aa1"
        user = admin.auth.admin.create_user({"email": email, "password": password, "email_confirm": True}).user
        users[label] = {"id": user.id, "email": email, "password": password}
    s["users"] = users
    insert("organization_memberships", {"organization_id": s["org"]["id"], "user_id": users["manager"]["id"], "role": "cooperative_manager"})
    for label in ("owner", "viewer"):
        insert("organization_memberships", {"organization_id": s["org"]["id"], "user_id": users[label]["id"], "role": "farmer"})
        insert("farm_members", {"farm_id": s["farm"]["id"], "user_id": users[label]["id"], "farm_role": label})
    insert("organization_memberships", {"organization_id": s["gov"]["id"], "user_id": users["regulator"]["id"], "role": "regulator"})
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
        attempt("memberships", lambda x=oid: admin.table("organization_memberships").delete().eq("organization_id", x).execute())
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
    season = s["season"]["id"]
    methodology_url = f"/v1/crop-seasons/{season}/methodology"

    # -- 1. a fresh season really is missing the methodology inputs -------------
    fresh = client.get(f"/v1/crop-seasons/{season}", headers=auth("owner"))
    body = fresh.json()
    check("fresh_season_readable", fresh.status_code == 200, str(fresh.status_code))
    check("fresh_season_exposes_methodology_fields",
          all(k in body for k in ("ipcc_water_regime", "pre_season_water_regime", "cultivation_days")),
          str(sorted(body)))
    check("fresh_season_has_no_water_regime", body.get("ipcc_water_regime") is None, str(body.get("ipcc_water_regime")))
    check("fresh_season_has_no_pre_season_regime", body.get("pre_season_water_regime") is None, str(body.get("pre_season_water_regime")))

    # -- 2. and it fails closed rather than defaulting one ----------------------
    blocked = client.post("/v1/carbon/calculate", headers=auth("owner"),
                          json={"crop_season_id": season, "water_regime_scenario": "as_recorded"})
    blocked_code = (blocked.json().get("detail") or {}).get("error", {}).get("code")
    check("carbon_blocked_before_methodology_is_supplied", blocked.status_code == 422, str(blocked.status_code))
    check("carbon_block_reason_is_a_named_domain_error",
          blocked_code in {"missing_activity_data", "methodology_gap"}, str(blocked_code))
    check("blocked_calculation_persisted_nothing",
          admin.table("carbon_calculations").select("id", count="exact").eq("crop_season_id", season).execute().count == 0)

    # -- 3. authorization on the new route -------------------------------------
    for label, expected in (("viewer", 404), ("regulator", 404)):
        r = client.patch(methodology_url, headers=auth(label), json={"ipcc_water_regime": "upland"})
        check(f"methodology_patch_denied_{label}_{expected}", r.status_code == expected, str(r.status_code))
    anon = client.patch(methodology_url, json={"ipcc_water_regime": "upland"})
    check("methodology_patch_unauth_401", anon.status_code == 401, str(anon.status_code))
    check("denied_callers_changed_nothing",
          db_scalar("select ipcc_water_regime is null from public.crop_seasons where id = %s", (season,)))

    bad = client.patch(methodology_url, headers=auth("owner"), json={"ipcc_water_regime": "awd"})
    check("methodology_patch_rejects_a_non_ipcc_value_422", bad.status_code == 422, str(bad.status_code))

    # -- 4. the normal user supplies the inputs through the API ----------------
    patched = client.patch(methodology_url, headers=auth("owner"), json={
        "ipcc_water_regime": "irrigated_continuous_flooding",
        "pre_season_water_regime": "non_flooded_pre_season_lt_180d",
        "cultivation_days": 100,
    })
    check("owner_can_record_methodology_200", patched.status_code == 200, str(patched.status_code))
    check("methodology_persisted",
          patched.json().get("ipcc_water_regime") == "irrigated_continuous_flooding"
          and patched.json().get("pre_season_water_regime") == "non_flooded_pre_season_lt_180d"
          and patched.json().get("cultivation_days") == 100, str(patched.json()))

    partial = client.patch(methodology_url, headers=auth("manager"), json={"cultivation_days": 100})
    check("cooperative_manager_can_record_methodology_200", partial.status_code == 200, str(partial.status_code))
    check("partial_patch_left_the_regimes_alone",
          partial.json().get("ipcc_water_regime") == "irrigated_continuous_flooding", str(partial.json()))

    # -- 5. the journal activities, through the normal write API ---------------
    def post_activity(kind: str, day: str, data: dict) -> int:
        r = client.post(f"/v1/crop-seasons/{season}/activities", headers=auth("owner"), json={
            "activity_type": kind, "occurred_at": f"2026-06-{day}T00:00:00Z",
            "idempotency_key": str(uuid.uuid4()), "note": TAG, "data": data,
        })
        if r.status_code != 201:
            print(f"    activity {kind} -> {r.status_code} {r.text[:200]}")
        return r.status_code

    check("irrigation_created_201", post_activity("irrigation", "02", {
        "method": "continuous_flooding", "water_volume_m3": 4000,
        "total_cost_vnd": IRRIGATION_COST}) == 201)
    check("fertilizer_created_201", post_activity("fertilizer", "05", {
        "fertilizer_name": "Urea", "amount_kg": 100, "nitrogen_percent": 46,
        "total_cost_vnd": FERTILIZER_COST}) == 201)
    check("harvest_created_201", post_activity("harvest", "20", {
        "yield_kg": 6000, "total_cost_vnd": HARVEST_COST}) == 201)

    # The harvest ACTIVITY must land in the canonical `harvest_events` row the
    # Carbon intensity denominator reads; an activity without it would silently
    # drop the denominator.
    check("harvest_activity_wrote_canonical_harvest_events",
          db_scalar("""select count(*) from public.harvest_events he
                       join public.activities a on a.id = he.activity_id
                       join public.production_batches b on b.id = a.production_batch_id
                       where b.crop_season_id = %s and he.yield_kg = 6000""", (season,)) == 1)

    # -- 6. the calculation a normal user triggers ------------------------------
    calc = client.post("/v1/carbon/calculate", headers=auth("owner"),
                       json={"crop_season_id": season, "water_regime_scenario": "as_recorded"})
    check("carbon_calculate_succeeds_for_a_normal_user", calc.status_code in (200, 201), f"{calc.status_code} {calc.text[:200]}")
    result = calc.json() if calc.status_code in (200, 201) else {}
    total = result.get("total_co2e_kg", result.get("co2e_total_kg"))
    check("total_co2e_non_null", total is not None, str(total))
    check("total_matches_hand_calculation", close(total, EXPECTED_TOTAL), f"{total} != {EXPECTED_TOTAL}")
    check("intensity_non_null_because_harvest_exists", result.get("co2e_per_kg") is not None)
    check("intensity_matches_hand_calculation", close(result.get("co2e_per_kg"), EXPECTED_PER_KG, 1e-6),
          f"{result.get('co2e_per_kg')} != {EXPECTED_PER_KG}")
    breakdown = result.get("breakdown") or []
    check("breakdown_populated", len(breakdown) == 2, f"{len(breakdown)} entries")
    check("breakdown_has_ch4_and_n2o",
          {e.get("gas") for e in breakdown} == {"ch4", "n2o"}, str([e.get("gas") for e in breakdown]))

    stored = admin.table("carbon_calculations").select("id,scenario,factor_set_id").eq("crop_season_id", season).execute().data
    check("calculation_persisted_once", len(stored) == 1, str(len(stored)))
    check("persisted_as_canonical_actual_scenario", bool(stored) and stored[0]["scenario"] == "actual",
          str(stored[0]["scenario"] if stored else None))
    check("persisted_calculation_links_a_factor_set", bool(stored) and stored[0]["factor_set_id"] is not None)

    # -- 7. Resource cost is a separate metric and must not touch Carbon --------
    metrics = client.get(f"/v1/crop-seasons/{season}/metrics", headers=auth("owner"))
    m = metrics.json() if metrics.status_code == 200 else {}
    check("metrics_200", metrics.status_code == 200, str(metrics.status_code))
    check("metrics_yield_matches_harvest", close(m.get("yield_kg"), 6000.0))
    expected_cost_per_kg = (IRRIGATION_COST + FERTILIZER_COST + HARVEST_COST) / 6000.0
    check("resource_cost_per_kg_present_from_recorded_costs",
          close(m.get("cost_per_kg"), expected_cost_per_kg, 1e-6),
          f"{m.get('cost_per_kg')} != {expected_cost_per_kg}")
    check("cost_completeness_flag_true_when_every_activity_has_a_cost",
          (m.get("data_completeness") or {}).get("cost") is True, str(m.get("data_completeness")))
    check("carbon_intensity_unchanged_by_cost", close(m.get("co2e_per_kg"), EXPECTED_PER_KG, 1e-6),
          f"{m.get('co2e_per_kg')} != {EXPECTED_PER_KG}")
    # Cost is not an emission factor: no breakdown entry may reference it.
    check("no_cost_entry_in_carbon_breakdown",
          not any("cost" in str(e.get("source", "")).lower() for e in breakdown))

    # A cost recorded on only SOME activities must not produce a cost/kg: a
    # partial sum would understate the real cost per kilo. Same all-or-nothing
    # completeness rule the water and fertilizer numerators use (B1).
    costless = post_activity("pesticide", "10", {"product_name": "QA", "amount": 1, "unit": "L"})
    check("pesticide_without_cost_created_201", costless == 201)
    m2 = client.get(f"/v1/crop-seasons/{season}/metrics", headers=auth("owner")).json()
    check("cost_per_kg_null_when_one_activity_has_no_cost", m2.get("cost_per_kg") is None, str(m2.get("cost_per_kg")))
    check("cost_completeness_flag_false_when_partial",
          (m2.get("data_completeness") or {}).get("cost") is False, str(m2.get("data_completeness")))
    check("carbon_intensity_unaffected_by_missing_cost",
          close(m2.get("co2e_per_kg"), EXPECTED_PER_KG, 1e-6), str(m2.get("co2e_per_kg")))

    # -- 8. clearing an input blocks Carbon again (no silent default) ----------
    cleared = client.patch(methodology_url, headers=auth("owner"), json={"pre_season_water_regime": None})
    check("methodology_can_be_cleared_200", cleared.status_code == 200, str(cleared.status_code))
    check("cleared_field_reads_back_null", cleared.json().get("pre_season_water_regime") is None)
    reblocked = client.post("/v1/carbon/calculate", headers=auth("owner"),
                            json={"crop_season_id": season, "water_regime_scenario": "as_recorded"})
    check("carbon_blocked_again_after_clearing_pre_season", reblocked.status_code == 422, str(reblocked.status_code))


def main() -> int:
    print(f"=== Hosted Carbon input-UX smoke — run {RUN_ID} ===")
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
    failed = [name for name, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("FAILED:", ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

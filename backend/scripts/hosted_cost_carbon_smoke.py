"""Hosted dev smoke: cost and Carbon are independent metrics.

Run:  python backend/scripts/hosted_cost_carbon_smoke.py
Needs backend/.env (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_PUBLISHABLE_KEY,
SUPABASE_DB_URL) and the published factor set `0.3.0-ipcc2019-tier1-ar5`.

Scenario A records every Carbon input and NO cost at all; scenario B then adds a
cost to every activity. Between them, no Carbon figure may move by even one digit,
and cost_per_kg must go from null to a real number. The season is seeded with its
methodology columns NULL and filled through the real API.

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

PREFIX = "COST-CARBON-SMOKE"
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
    readiness_url = f"/v1/crop-seasons/{season}/carbon/readiness"

    # -- readiness names the missing inputs BEFORE anything is supplied --------
    r = client.get(readiness_url, headers=auth("owner"))
    payload = r.json() if r.status_code == 200 else {}
    entries = payload.get("missing_inputs", [])
    codes = {m["code"] for m in entries}
    check("readiness_200", r.status_code == 200, str(r.status_code))
    check("readiness_says_cannot_calculate", payload.get("can_calculate") is False, str(payload.get("can_calculate")))
    check("readiness_names_water_regime", "water_regime" in codes, str(sorted(codes)))
    check("readiness_names_pre_season_regime", "pre_season_water_regime" in codes, str(sorted(codes)))
    check("readiness_never_asks_for_cost",
          not any("chi ph" in (m["label"] + m["detail"]).lower() for m in entries))
    flows = {m["code"]: m["flow"] for m in entries}
    check("regimes_route_to_the_methodology_panel",
          flows.get("water_regime") == "carbon_methodology"
          and flows.get("pre_season_water_regime") == "carbon_methodology", str(flows))

    # Readiness explains an absent result, so it must never be readable by anyone
    # who could not read the result itself. Compared endpoint-to-endpoint rather
    # than against a hard-coded matrix, so it tracks the access rules as they are.
    def result_is_reachable(label: str) -> bool:
        """200, or a 404 whose code is `no_calculation` — that means the caller
        CAN see the season, there simply is no stored result yet. An access
        refusal is a 404 with code `not_found`, or a 401/403."""
        resp = client.get(f"/v1/crop-seasons/{season}/carbon", headers=auth(label))
        if resp.status_code == 200:
            return True
        code = ((resp.json() or {}).get("detail") or {}).get("error", {}).get("code")
        return resp.status_code == 404 and code == "no_calculation"

    for label in ("viewer", "regulator", "owner"):
        ready_code = client.get(readiness_url, headers=auth(label)).status_code
        check(f"readiness_access_matches_result_access_{label}",
              (ready_code == 200) == result_is_reachable(label),
              f"readiness={ready_code} result_reachable={result_is_reachable(label)}")
    check("readiness_readable_by_farm_viewer",
          client.get(readiness_url, headers=auth("viewer")).status_code == 200)
    check("readiness_unauth_401", client.get(readiness_url).status_code == 401)

    # -- supply the Carbon inputs through the normal API ----------------------
    patched = client.patch(f"/v1/crop-seasons/{season}/methodology", headers=auth("owner"), json={
        "ipcc_water_regime": "irrigated_continuous_flooding",
        "pre_season_water_regime": "non_flooded_pre_season_lt_180d",
        "cultivation_days": 100,
    })
    check("methodology_recorded_200", patched.status_code == 200, str(patched.status_code))

    def post_activity(kind: str, day: str, data: dict) -> int:
        resp = client.post(f"/v1/crop-seasons/{season}/activities", headers=auth("owner"), json={
            "activity_type": kind, "occurred_at": f"2026-06-{day}T00:00:00Z",
            "idempotency_key": str(uuid.uuid4()), "note": TAG, "data": data,
        })
        if resp.status_code != 201:
            print(f"    activity {kind} -> {resp.status_code} {resp.text[:200]}")
        return resp.status_code

    # NOTE: no cost on any of these. That is scenario A.
    check("irrigation_created_no_cost", post_activity("irrigation", "02", {
        "method": "continuous_flooding", "water_volume_m3": 4000}) == 201)
    check("fertilizer_created_no_cost", post_activity("fertilizer", "05", {
        "fertilizer_name": "Urea", "amount_kg": 100, "nitrogen_percent": 46}) == 201)
    check("harvest_created_no_cost", post_activity("harvest", "20", {"yield_kg": 6000}) == 201)

    ready = client.get(readiness_url, headers=auth("owner")).json()
    check("readiness_now_can_calculate", ready.get("can_calculate") is True, str(ready))

    # ============ A. Carbon inputs complete, costs incomplete ================
    calc = client.post("/v1/carbon/calculate", headers=auth("owner"),
                       json={"crop_season_id": season, "water_regime_scenario": "as_recorded"})
    check("A_carbon_calculate_succeeds_without_any_cost",
          calc.status_code in (200, 201), f"{calc.status_code} {calc.text[:200]}")
    a = calc.json() if calc.status_code in (200, 201) else {}
    a_total = a.get("total_co2e_kg", a.get("co2e_total_kg"))
    check("A_total_matches_hand_calculation", close(a_total, EXPECTED_TOTAL), str(a_total))
    check("A_intensity_matches_hand_calculation",
          close(a.get("co2e_per_kg"), EXPECTED_PER_KG, 1e-6), str(a.get("co2e_per_kg")))

    m_a = client.get(f"/v1/crop-seasons/{season}/metrics", headers=auth("owner")).json()
    check("A_cost_per_kg_is_null", m_a.get("cost_per_kg") is None, str(m_a.get("cost_per_kg")))
    check("A_cost_completeness_false",
          (m_a.get("data_completeness") or {}).get("cost") is False, str(m_a.get("data_completeness")))
    check("A_carbon_completeness_true",
          (m_a.get("data_completeness") or {}).get("carbon") is True, str(m_a.get("data_completeness")))
    check("A_carbon_visible_in_metrics",
          close(m_a.get("co2e_per_kg"), EXPECTED_PER_KG, 1e-6), str(m_a.get("co2e_per_kg")))

    # ==================== B. add every activity cost =========================
    acts = client.get(f"/v1/crop-seasons/{season}/activities", headers=auth("owner")).json()["items"]
    costs = {"irrigation": 300000.0, "fertilizer": 850000.0, "harvest": 1200000.0}
    for item in acts:
        kind = item["activity_type"]
        if kind not in costs:
            continue
        data = dict(item["payload"])
        data["total_cost_vnd"] = costs[kind]
        resp = client.patch(f"/v1/activities/{item['id']}", headers=auth("owner"), json={"data": data})
        if resp.status_code != 200:
            print(f"    cost patch {kind} -> {resp.status_code} {resp.text[:250]}")
        check(f"B_cost_added_to_{kind}", resp.status_code == 200, str(resp.status_code))

    m_b = client.get(f"/v1/crop-seasons/{season}/metrics", headers=auth("owner")).json()
    expected_cost = sum(costs.values()) / 6000.0
    check("B_cost_per_kg_now_non_null", m_b.get("cost_per_kg") is not None, str(m_b.get("cost_per_kg")))
    check("B_cost_per_kg_matches_recorded_costs",
          close(m_b.get("cost_per_kg"), expected_cost, 1e-6),
          f"{m_b.get('cost_per_kg')} != {expected_cost}")
    check("B_cost_completeness_true",
          (m_b.get("data_completeness") or {}).get("cost") is True, str(m_b.get("data_completeness")))

    # ---- the whole point: Carbon did not move -------------------------------
    check("B_total_co2e_unchanged", m_b.get("total_co2e_kg") == m_a.get("total_co2e_kg"),
          f"{m_a.get('total_co2e_kg')} -> {m_b.get('total_co2e_kg')}")
    check("B_co2e_per_kg_unchanged", m_b.get("co2e_per_kg") == m_a.get("co2e_per_kg"),
          f"{m_a.get('co2e_per_kg')} -> {m_b.get('co2e_per_kg')}")
    check("B_yield_unchanged", m_b.get("yield_kg") == m_a.get("yield_kg"))

    recalc = client.post("/v1/carbon/calculate", headers=auth("owner"),
                         json={"crop_season_id": season, "water_regime_scenario": "as_recorded"})
    b = recalc.json() if recalc.status_code in (200, 201) else {}
    b_total = b.get("total_co2e_kg", b.get("co2e_total_kg"))
    check("B_recalculation_gives_the_same_total", b_total == a_total, f"{a_total} -> {b_total}")
    check("B_recalculation_gives_the_same_intensity",
          b.get("co2e_per_kg") == a.get("co2e_per_kg"),
          f"{a.get('co2e_per_kg')} -> {b.get('co2e_per_kg')}")
    check("B_no_cost_entry_in_breakdown",
          not any("cost" in str(e.get("source", "")).lower() for e in (b.get("breakdown") or [])))
    check("B_readiness_still_clean",
          client.get(readiness_url, headers=auth("owner")).json().get("can_calculate") is True)


def main() -> int:
    print(f"=== Hosted cost/Carbon independence smoke - run {RUN_ID} ===")
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

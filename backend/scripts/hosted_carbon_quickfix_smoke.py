"""Hosted dev UI smoke: repair every missing Carbon input from the Carbon tab.

Run (backend on :8010 and the Vite dev server on :5173 already up):
    python backend/scripts/hosted_carbon_quickfix_smoke.py

Needs backend/.env (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_PUBLISHABLE_KEY,
SUPABASE_DB_URL). Seeds an ISOLATED tenant — never the shared demo farm:

  * service role creates only what a Farmer Web user cannot: organization, farm,
    plot (1 ha), an EMPTY season (methodology columns NULL), a production batch,
    and two throwaway Auth users (farm owner, farm viewer);
  * the owner then records, through the real API, a fertilizer application with
    no nitrogen %, a burned-straw record with no dry-matter fraction, and a harvest.

That leaves exactly five blocking inputs. The Playwright spec
`farmer-real-carbon-quickfix.spec.ts` then signs in as each user and drives the
real browser UI; credentials reach it only through the process environment.
Everything is deleted in `finally` and table row counts are compared.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BACKEND_DIR.parent / "web-dashboard"
sys.path.insert(0, str(BACKEND_DIR))

import httpx  # noqa: E402
import psycopg  # noqa: E402
from supabase import create_client  # noqa: E402

from infrastructure.config import load_settings  # noqa: E402

PREFIX = "CARBON-QUICKFIX-SMOKE"
RUN_ID = uuid.uuid4().hex[:8]
TAG = f"{PREFIX}-{RUN_ID}"
EMAIL_PREFIX = f"{PREFIX.lower()}-{RUN_ID}"
API = os.environ.get("QF_API_BASE_URL", "http://127.0.0.1:8010")
EXPECTED_BLOCKING = {"water_regime", "pre_season_water_regime", "cultivation_days",
                     "fertilizer_nitrogen", "straw_dry_matter"}

settings = load_settings()
URL, SERVICE_KEY = settings.require_supabase()
_, PUBLISHABLE = settings.require_publishable()
DB_URL = settings.supabase_db_url
admin = create_client(URL, SERVICE_KEY)

COUNTED_TABLES = [
    "organizations", "organization_memberships", "profiles", "farms", "farm_members", "plots",
    "crop_seasons", "production_batches", "activities", "fertilizer_applications", "harvest_events",
    "straw_management_events", "carbon_calculations", "carbon_breakdowns", "season_recommendations",
]
DETAIL_TABLES = ("irrigation_events", "fertilizer_applications", "harvest_events", "seeding_events",
                 "pesticide_applications", "straw_management_events", "fuel_usages")

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(("PASS" if ok else "FAIL") + f"  {name}" + (f"  ({detail})" if detail and not ok else ""))


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
    s: dict = {}
    s["org"] = insert("organizations", {"organization_code": f"{TAG}-ORG", "name": f"{TAG} org", "organization_type": "cooperative"})
    s["farm"] = insert("farms", {"cooperative_id": s["org"]["id"], "farm_code": f"{TAG}-FARM", "farm_name": f"{TAG} farm"})
    plot = insert("plots", {"farm_id": s["farm"]["id"], "plot_code": f"{TAG}-PLOT", "name": "Thửa QF", "area_ha": 1.0})
    s["season"] = insert("crop_seasons", {"plot_id": plot["id"], "season_code": f"{TAG}-S1", "crop_type": "rice", "status": "active"})
    insert("production_batches", {"crop_season_id": s["season"]["id"], "batch_code": "default"})
    users = {}
    for label in ("owner", "viewer"):
        email = f"{EMAIL_PREFIX}-{label}@agricarbon.invalid"
        password = f"QF-{uuid.uuid4().hex}!Aa1"
        user = admin.auth.admin.create_user({"email": email, "password": password, "email_confirm": True}).user
        users[label] = {"id": user.id, "email": email, "password": password}
        insert("organization_memberships", {"organization_id": s["org"]["id"], "user_id": user.id, "role": "farmer"})
        insert("farm_members", {"farm_id": s["farm"]["id"], "user_id": user.id, "farm_role": label})
    s["users"] = users
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

    for org in admin.table("organizations").select("id").ilike("organization_code", f"{TAG}-%").execute().data:
        oid = org["id"]
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
        attempt("memberships", lambda x=oid: admin.table("organization_memberships").delete().eq("organization_id", x).execute())
        attempt("org", lambda x=oid: admin.table("organizations").delete().eq("id", x).execute())

    with psycopg.connect(DB_URL) as conn, conn.cursor() as cur:
        cur.execute("select id from auth.users where email like %s", (f"{EMAIL_PREFIX}-%",))
        user_ids = [str(r[0]) for r in cur.fetchall()]
    for uid in user_ids:
        attempt("devices", lambda x=uid: admin.table("devices").delete().eq("user_id", x).execute())
        attempt("user", lambda x=uid: admin.auth.admin.delete_user(x))
        attempt("profile", lambda x=uid: admin.table("profiles").delete().eq("id", x).execute())


def run(s: dict) -> None:
    season = s["season"]["id"]
    owner = {"Authorization": f"Bearer {sign_in(s['users']['owner'])}"}
    http = httpx.Client(base_url=API, timeout=120)

    def post_activity(kind: str, day: str, data: dict) -> int:
        r = http.post(f"/v1/crop-seasons/{season}/activities", headers=owner, json={
            "activity_type": kind, "occurred_at": f"2026-06-{day}T00:00:00Z",
            "idempotency_key": str(uuid.uuid4()), "note": TAG, "data": data})
        if r.status_code != 201:
            print(f"    {kind} -> {r.status_code} {r.text[:200]}")
        return r.status_code

    check("seed_fertilizer_without_nitrogen", post_activity("fertilizer", "05", {"fertilizer_name": "NPK", "amount_kg": 80}) == 201)
    check("seed_burned_straw_without_dry_matter", post_activity("straw_management", "01", {"method": "burned", "straw_mass_kg": 900}) == 201)
    check("seed_harvest", post_activity("harvest", "20", {"yield_kg": 6000}) == 201)

    ready = http.get(f"/v1/crop-seasons/{season}/carbon/readiness", headers=owner).json()
    blocking = {m["code"] for m in ready["missing_inputs"] if m["blocking"]}
    check("readiness_names_exactly_the_five_seeded_gaps", blocking == EXPECTED_BLOCKING, str(sorted(blocking)))
    by_code = {m["code"]: m for m in ready["missing_inputs"]}
    check("readiness_identifies_the_fertilizer_record",
          len(by_code.get("fertilizer_nitrogen", {}).get("records", [])) == 1, str(by_code.get("fertilizer_nitrogen")))
    check("readiness_identifies_the_straw_record",
          len(by_code.get("straw_dry_matter", {}).get("records", [])) == 1, str(by_code.get("straw_dry_matter")))

    env = {**os.environ, "REAL_E2E": "true", "QF_SEASON_ID": season,
           "QF_OWNER_EMAIL": s["users"]["owner"]["email"], "QF_OWNER_PASSWORD": s["users"]["owner"]["password"],
           "QF_VIEWER_EMAIL": s["users"]["viewer"]["email"], "QF_VIEWER_PASSWORD": s["users"]["viewer"]["password"]}
    npx = "npx.cmd" if os.name == "nt" else "npx"
    proc = subprocess.run([npx, "playwright", "test", "--config=playwright.real.config.ts",
                           "tests/e2e/farmer-real-carbon-quickfix.spec.ts", "--reporter=line", "--workers=1"],
                          cwd=WEB_DIR, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = proc.stdout + proc.stderr
    print("\n".join(line for line in out.splitlines() if line.strip())[-4000:])
    check("playwright_ui_smoke_passed", proc.returncode == 0, f"exit {proc.returncode}")

    after = http.get(f"/v1/crop-seasons/{season}/carbon/readiness", headers=owner).json()
    check("readiness_complete_after_ui_repairs", after.get("can_calculate") is True and after.get("blocking_count") == 0, str(after))
    result = http.get(f"/v1/crop-seasons/{season}/carbon", headers=owner)
    body = result.json() if result.status_code == 200 else {}
    total = body.get("total_co2e_kg", body.get("co2e_total_kg"))
    check("carbon_result_stored_by_the_ui", result.status_code == 200 and total is not None and float(total) > 0, f"{result.status_code} {total}")
    print(f"    stored total_co2e_kg={total} co2e_per_kg={body.get('co2e_per_kg')}")


def main() -> int:
    print(f"=== Hosted Carbon quick-fix UI smoke - run {RUN_ID} ===")
    before = snapshot()
    try:
        run(seed())
    except Exception as exc:  # noqa: BLE001
        check("smoke_completed_without_exception", False, repr(exc))
    finally:
        print("Cleaning up ...")
        cleanup()
        time.sleep(1)
        after = snapshot()
        diff = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
        check("cleanup_row_counts_restored", not diff, str(diff))
    failed = [name for name, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("FAILED:", ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

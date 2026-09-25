"""Hosted smoke: farmer provisioning + Web season lifecycle, on a DISPOSABLE tenant.

Run (backend on :8010 with this branch, Vite dev server on :5173 against it):
    python backend/scripts/hosted_season_provisioning_smoke.py

Needs backend/.env (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_PUBLISHABLE_KEY,
SUPABASE_DB_URL). Never touches the shared demo identities:

  * service role creates only a throwaway cooperative and its manager;
  * everything else goes through the product: the manager provisions the farmer
    (account + farm + plot) in Management Web, the farmer starts a season and
    records an activity in Farmer Web (Playwright `season-provisioning-real.spec.ts`);
  * the database is checked in between, the season is then closed, and the
    closed-season behaviour is checked in the browser;
  * everything is deleted in `finally` and table row counts are compared.

Credentials exist only in this process and the Playwright child's environment;
the farmer's temporary password comes back through a scratch file that is
deleted immediately. Nothing secret is printed.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
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

PREFIX = "SEASON-PROV-SMOKE"
RUN_ID = uuid.uuid4().hex[:8]
TAG = f"{PREFIX}-{RUN_ID}"
EMAIL_PREFIX = f"{PREFIX.lower()}-{RUN_ID}"
API = os.environ.get("SP_API_BASE_URL", "http://127.0.0.1:8010")
# Case A must stay exactly as it is: a real no-season onboarding account.
CASE_A_PLOT = "490e58e0-5ee7-48af-a83f-ef4ddf46028d"
# Case B's farm and cooperative: out of scope for this tenant's users.
CASE_B_FARM = "c9184ab5-45c2-4af2-88ce-10b598818cbc"

settings = load_settings()
URL, SERVICE_KEY = settings.require_supabase()
_, PUBLISHABLE = settings.require_publishable()
DB_URL = settings.supabase_db_url
admin = create_client(URL, SERVICE_KEY)

COUNTED_TABLES = [
    "organizations", "organization_memberships", "profiles", "farms", "farm_members", "plots",
    "crop_seasons", "production_batches", "activities", "irrigation_events",
]
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(("PASS" if ok else "FAIL") + f"  {name}" + (f"  ({detail})" if detail and not ok else ""))


def q(sql: str, params: tuple = ()) -> list[tuple]:
    with psycopg.connect(DB_URL) as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def snapshot() -> dict[str, int]:
    counts = {t: admin.table(t).select("*", count="exact").limit(1).execute().count for t in COUNTED_TABLES}
    counts["auth.users[smoke]"] = q("select count(*) from auth.users where email like %s", (f"{PREFIX.lower()}-%",))[0][0]
    return counts


def case_a() -> tuple:
    return q("""select (select count(*) from public.crop_seasons where plot_id = %s),
                       (select updated_at from public.plots where id = %s)""", (CASE_A_PLOT, CASE_A_PLOT))[0]


def sign_in(email: str, password: str) -> str:
    r = httpx.post(f"{URL}/auth/v1/token?grant_type=password", headers={"apikey": PUBLISHABLE},
                   json={"email": email, "password": password}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def seed() -> dict:
    org = admin.table("organizations").insert({"organization_code": f"{TAG}-ORG", "name": f"{TAG} HTX", "organization_type": "cooperative"}).execute().data[0]
    email = f"{EMAIL_PREFIX}-manager@agricarbon.invalid"
    password = f"Sp-{uuid.uuid4().hex}!Aa1"
    user = admin.auth.admin.create_user({"email": email, "password": password, "email_confirm": True}).user
    admin.table("organization_memberships").insert({"organization_id": org["id"], "user_id": user.id, "role": "cooperative_manager"}).execute()
    return {"org": org["id"], "manager": {"id": user.id, "email": email, "password": password},
            "farmer_email": f"{EMAIL_PREFIX}-farmer@agricarbon.invalid"}


def playwright(env_extra: dict) -> bool:
    env = {**os.environ, "REAL_E2E": "true", "SP_TAG": TAG, **env_extra}
    npx = "npx.cmd" if os.name == "nt" else "npx"
    proc = subprocess.run([npx, "playwright", "test", "--config=playwright.real.config.ts",
                           "tests/e2e/season-provisioning-real.spec.ts", "--reporter=line", "--workers=1"],
                          cwd=WEB_DIR, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = proc.stdout + proc.stderr
    for secret in (env_extra.get("SP_MANAGER_PASSWORD"), env_extra.get("SP_FARMER_PASSWORD")):
        if secret:
            out = out.replace(secret, "***")
    print("\n".join(line for line in out.splitlines() if line.strip())[-4000:])
    return proc.returncode == 0


def run(s: dict) -> None:
    secret = Path(tempfile.gettempdir()) / f"sp-{RUN_ID}.txt"
    try:
        ok = playwright({"SP_PHASE": "onboard", "SP_MANAGER_EMAIL": s["manager"]["email"],
                         "SP_MANAGER_PASSWORD": s["manager"]["password"], "SP_FARMER_EMAIL": s["farmer_email"],
                         "SP_SECRET_FILE": str(secret)})
        check("ui_onboard_phase_passed", ok)
        lines = secret.read_text(encoding="utf-8").splitlines() if secret.exists() else []
    finally:
        secret.unlink(missing_ok=True)
    if len(lines) < 2:
        check("ui_handed_back_password_and_season", False, f"{len(lines)} line(s)")
        return
    farmer_password, season_id = lines[0], lines[1]

    # -- database after provisioning ----------------------------------------
    farmer = q("select id::text, email_confirmed_at is not null from auth.users where email = %s", (s["farmer_email"],))
    check("auth_user_created_confirmed", len(farmer) == 1 and farmer[0][1])
    fid = farmer[0][0] if farmer else None
    check("profile_has_the_name", q("select full_name from public.profiles where id = %s", (fid,)) == [(f"Nông dân {TAG}",)])
    check("membership_is_farmer_of_this_cooperative",
          q("select role::text from public.organization_memberships where user_id = %s and organization_id = %s", (fid, s["org"])) == [("farmer",)])
    farm = q("select f.id::text, fm.farm_role::text from public.farms f join public.farm_members fm on fm.farm_id = f.id "
             "where f.cooperative_id = %s and fm.user_id = %s", (s["org"], fid))
    check("farm_created_with_farmer_as_owner", len(farm) == 1 and farm[0][1] == "owner")
    plot = q("select id::text, area_ha::float from public.plots where farm_id = %s", (farm[0][0] if farm else None,))
    check("plot_created", len(plot) == 1 and plot[0][1] == 1.25, str(plot))
    season = q("select plot_id::text, status::text from public.crop_seasons where id = %s", (season_id,))
    check("season_on_the_plot_and_active", season == [(plot[0][0] if plot else None, "active")], str(season))
    batches = q("select id::text, batch_code from public.production_batches where crop_season_id = %s and deleted_at is null", (season_id,))
    check("exactly_one_default_batch", len(batches) == 1 and batches[0][1] == "default", str(batches))
    acts = q("select production_batch_id::text from public.activities where note = %s and deleted_at is null", (f"{TAG}-FIRST",))
    check("activity_belongs_to_the_default_batch", len(acts) == 1 and batches and acts[0][0] == batches[0][0], str(acts))

    # -- API: scope, cross-tenant, duplicate --------------------------------
    http = httpx.Client(base_url=API, timeout=120)
    f_auth = {"Authorization": f"Bearer {sign_in(s['farmer_email'], farmer_password)}"}
    m_auth = {"Authorization": f"Bearer {sign_in(s['manager']['email'], s['manager']['password'])}"}
    scope = http.get("/v1/farmer/scope", headers=f_auth).json()
    check("farmer_sees_only_its_own_farm", [x["id"] for x in scope.get("farms", [])] == [farm[0][0]], str([x.get("farm_code") for x in scope.get("farms", [])]))
    check("farmer_cannot_read_case_b_farm", http.get(f"/v1/farms/{CASE_B_FARM}", headers=f_auth).status_code == 404)
    case_b_org = q("select cooperative_id::text from public.farms where id = %s", (CASE_B_FARM,))[0][0]
    check("manager_cannot_list_another_cooperative", http.get(f"/v1/organizations/{case_b_org}/farmers", headers=m_auth).status_code == 404)
    check("manager_cannot_provision_into_another_cooperative",
          http.post(f"/v1/organizations/{case_b_org}/farmers", headers=m_auth, json={"full_name": "X", "email": f"{EMAIL_PREFIX}-x@agricarbon.invalid"}).status_code == 404)
    check("farmer_cannot_provision", http.post(f"/v1/organizations/{s['org']}/farmers", headers=f_auth,
                                               json={"full_name": "X", "email": f"{EMAIL_PREFIX}-y@agricarbon.invalid"}).status_code == 404)
    dup = http.post(f"/v1/organizations/{s['org']}/farmers", headers=m_auth, json={"full_name": "Again", "email": s["farmer_email"]})
    check("duplicate_email_is_409_farmer_already_member", dup.status_code == 409 and dup.json()["detail"]["error"]["code"] == "farmer_already_member", dup.text[:200])
    check("farmer_cannot_add_plots", http.post(f"/v1/farms/{farm[0][0]}/plots", headers=f_auth,
                                               json={"plot_code": "X", "name": "X", "area_ha": 1}).status_code == 404)
    again = http.post(f"/v1/plots/{plot[0][0]}/crop-seasons", headers=f_auth, json={"season_code": f"{TAG}-DX"})
    check("second_active_season_refused", again.status_code == 409 and again.json()["detail"]["error"]["code"] == "active_season_exists", again.text[:200])
    check("unauthenticated_season_create_is_401",
          http.post(f"/v1/plots/{plot[0][0]}/crop-seasons", json={"season_code": "X"}).status_code == 401)

    # -- close the season, then the browser must stop offering writes -------
    admin.table("crop_seasons").update({"status": "harvested", "actual_harvest_date": "2026-12-20"}).eq("id", season_id).execute()
    closed_write = http.post(f"/v1/crop-seasons/{season_id}/activities", headers=f_auth, json={
        "activity_type": "irrigation", "occurred_at": "2026-12-21T00:00:00Z", "idempotency_key": str(uuid.uuid4()),
        "note": TAG, "data": {"method": "awd"}})
    check("api_refuses_writes_to_a_harvested_season", closed_write.status_code == 422, str(closed_write.status_code))
    check("ui_closed_phase_passed", playwright({"SP_PHASE": "closed", "SP_FARMER_EMAIL": s["farmer_email"],
                                                "SP_FARMER_PASSWORD": farmer_password, "SP_SEASON_ID": season_id}))


def cleanup() -> None:
    def attempt(label, fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            print(f"  cleanup warning [{label}]: {type(exc).__name__}")

    for org in admin.table("organizations").select("id").ilike("organization_code", f"{TAG}-%").execute().data:
        oid = org["id"]
        for farm in admin.table("farms").select("id").eq("cooperative_id", oid).execute().data:
            for plot in admin.table("plots").select("id").eq("farm_id", farm["id"]).execute().data:
                for season in admin.table("crop_seasons").select("id").eq("plot_id", plot["id"]).execute().data:
                    for batch in admin.table("production_batches").select("id").eq("crop_season_id", season["id"]).execute().data:
                        for act in admin.table("activities").select("id").eq("production_batch_id", batch["id"]).execute().data:
                            attempt("irrigation", lambda x=act["id"]: admin.table("irrigation_events").delete().eq("activity_id", x).execute())
                            attempt("activity", lambda x=act["id"]: admin.table("activities").delete().eq("id", x).execute())
                        attempt("batch", lambda x=batch["id"]: admin.table("production_batches").delete().eq("id", x).execute())
                    attempt("recommendations", lambda x=season["id"]: admin.table("season_recommendations").delete().eq("crop_season_id", x).execute())
                    attempt("season", lambda x=season["id"]: admin.table("crop_seasons").delete().eq("id", x).execute())
                attempt("plot", lambda x=plot["id"]: admin.table("plots").delete().eq("id", x).execute())
            attempt("farm members", lambda x=farm["id"]: admin.table("farm_members").delete().eq("farm_id", x).execute())
            attempt("farm", lambda x=farm["id"]: admin.table("farms").delete().eq("id", x).execute())
        attempt("memberships", lambda x=oid: admin.table("organization_memberships").delete().eq("organization_id", x).execute())
        attempt("org", lambda x=oid: admin.table("organizations").delete().eq("id", x).execute())
    for (uid,) in q("select id::text from auth.users where email like %s", (f"{EMAIL_PREFIX}-%",)):
        attempt("user", lambda x=uid: admin.auth.admin.delete_user(x))
        attempt("profile", lambda x=uid: admin.table("profiles").delete().eq("id", x).execute())


def main() -> int:
    print(f"=== Hosted season + provisioning smoke - run {RUN_ID} ===")
    before, case_a_before = snapshot(), case_a()
    try:
        run(seed())
    except Exception as exc:  # noqa: BLE001
        check("smoke_completed_without_exception", False, f"{type(exc).__name__}: {str(exc)[:300]}")
    finally:
        print("Cleaning up ...")
        cleanup()
        time.sleep(1)
        after = snapshot()
        diff = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
        check("cleanup_row_counts_restored", not diff, str(diff))
        check("case_a_untouched_no_season", case_a() == case_a_before and case_a_before[0] == 0, str(case_a()))
    failed = [name for name, ok, _ in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    if failed:
        print("FAILED:", ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

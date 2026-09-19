"""Hosted dev smoke for P1 write-path reliability (P1-A atomicity, P1-B dead connections).

Run:  python backend/scripts/hosted_write_reliability_smoke.py

The real FastAPI app (`main.app`) runs IN THIS PROCESS through TestClient,
against hosted Supabase with the real pool, real JWTs and real Storage. That is
what makes both halves safe to run on shared hosted dev:

  A. Dead connections. Before a write, every idle session of THIS process's
     pool is terminated (found with `pg_backend_pid()` on the pool's own
     connections -- Supavisor rewrites application_name, so no other process's
     session can be matched or touched). The write must still succeed on its
     first attempt.
  B. Response atomicity. `schemas.success_payload` is made to reject one
     response model, standing in for a response the API cannot produce. The
     write must fail AND the hosted row / Storage object must be unchanged.

Seeds an ISOLATED tenant (organization, farm, plot, season, batch, MRV case, a
farm owner and a cooperative manager) and deletes everything in `finally`,
then compares table row counts and the Storage object count.
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
os.chdir(BACKEND_DIR)  # main.py reads config/emission_factors.yaml relatively
sys.path.insert(0, str(BACKEND_DIR))

import httpx  # noqa: E402
import psycopg  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from supabase import create_client  # noqa: E402

import api  # noqa: E402
import main  # noqa: E402
import schemas  # noqa: E402
from infrastructure import pg_pool  # noqa: E402
from infrastructure.config import load_settings  # noqa: E402

PREFIX = "WRITE-RELIABILITY-SMOKE"
RUN_ID = uuid.uuid4().hex[:8]
TAG = f"{PREFIX}-{RUN_ID}"
EMAIL_PREFIX = f"{PREFIX.lower()}-{RUN_ID}"
BUCKET = "mrv-exports"

settings = load_settings()
URL, SERVICE_KEY = settings.require_supabase()
_, PUBLISHABLE = settings.require_publishable()
DB_URL = settings.supabase_db_url
admin = create_client(URL, SERVICE_KEY)

COUNTED_TABLES = [
    "organizations", "organization_memberships", "profiles", "farms", "farm_members", "plots",
    "crop_seasons", "production_batches", "activities", "fertilizer_applications", "harvest_events",
    "carbon_calculations", "carbon_breakdowns", "season_recommendations",
    "mrv_cases", "mrv_case_batches", "mrv_exports", "mrv_export_calculations",
]
DETAIL_TABLES = ("irrigation_events", "fertilizer_applications", "harvest_events", "seeding_events",
                 "pesticide_applications", "straw_management_events", "fuel_usages")
METHODOLOGY = {"ipcc_water_regime": "irrigated_multiple_drainage",
               "pre_season_water_regime": "non_flooded_pre_season_lt_180d", "cultivation_days": 100}

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(("PASS" if ok else "FAIL") + f"  {name}" + (f"  ({detail})" if detail and not ok else ""))


def db_scalar(sql: str, params: tuple = ()):
    with psycopg.connect(DB_URL) as conn:
        return conn.execute(sql, params).fetchone()[0]


def snapshot() -> dict[str, int]:
    counts = {t: admin.table(t).select("*", count="exact").limit(1).execute().count for t in COUNTED_TABLES}
    counts["auth.users[smoke]"] = db_scalar("select count(*) from auth.users where email like %s", (f"{PREFIX.lower()}-%",))
    counts["storage.objects[mrv-exports]"] = db_scalar("select count(*) from storage.objects where bucket_id = %s", (BUCKET,))
    return counts


def insert(table: str, row: dict) -> dict:
    return admin.table(table).insert(row).execute().data[0]


def seed() -> dict:
    s: dict = {}
    s["org"] = insert("organizations", {"organization_code": f"{TAG}-COOP", "name": f"{TAG} coop", "organization_type": "cooperative"})
    farm = insert("farms", {"cooperative_id": s["org"]["id"], "farm_code": f"{TAG}-FARM", "farm_name": f"{TAG} farm"})
    plot = insert("plots", {"farm_id": farm["id"], "plot_code": f"{TAG}-PLOT", "name": "Thửa tin cậy", "area_ha": 1.0})
    s["season"] = insert("crop_seasons", {"plot_id": plot["id"], "season_code": f"{TAG}-S", "crop_type": "rice",
                                          "status": "active", **METHODOLOGY})
    batch = insert("production_batches", {"crop_season_id": s["season"]["id"], "batch_code": "default"})
    s["case"] = insert("mrv_cases", {
        "organization_id": s["org"]["id"], "case_code": f"{TAG}-CASE", "name": f"{TAG} case",
        "period_start": "2026-05-01", "period_end": "2026-09-30", "status": "draft",
    })
    insert("mrv_case_batches", {"mrv_case_id": s["case"]["id"], "production_batch_id": batch["id"]})
    users = {}
    for label, role in (("owner", "farmer"), ("manager", "cooperative_manager")):
        email = f"{EMAIL_PREFIX}-{label}@agricarbon.invalid"
        password = f"WR-{uuid.uuid4().hex}!Aa1"
        user = admin.auth.admin.create_user({"email": email, "password": password, "email_confirm": True}).user
        users[label] = {"id": user.id, "email": email, "password": password}
        insert("organization_memberships", {"organization_id": s["org"]["id"], "user_id": user.id, "role": role})
    insert("farm_members", {"farm_id": farm["id"], "user_id": users["owner"]["id"], "farm_role": "owner"})
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

    orgs = admin.table("organizations").select("id").ilike("organization_code", f"{TAG}-%").execute().data
    org_ids = [o["id"] for o in orgs]
    with psycopg.connect(DB_URL) as conn:
        names = [r[0] for oid in org_ids for r in conn.execute(
            "select name from storage.objects where bucket_id = %s and name like %s", (BUCKET, f"{oid}/%")).fetchall()]
    if names:
        attempt("storage", lambda: admin.storage.from_(BUCKET).remove(names))

    for case in admin.table("mrv_cases").select("id").ilike("case_code", f"{TAG}-%").execute().data:
        cid = case["id"]
        for export in admin.table("mrv_exports").select("id").eq("mrv_case_id", cid).execute().data:
            attempt("export calcs", lambda x=export["id"]: admin.table("mrv_export_calculations").delete().eq("mrv_export_id", x).execute())
        attempt("exports renders", lambda x=cid: admin.table("mrv_exports").delete().eq("mrv_case_id", x).neq("format", "json").execute())
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
        attempt("memberships", lambda x=oid: admin.table("organization_memberships").delete().eq("organization_id", x).execute())
        attempt("org", lambda x=oid: admin.table("organizations").delete().eq("id", x).execute())

    with psycopg.connect(DB_URL) as conn:
        user_ids = [str(r[0]) for r in conn.execute("select id from auth.users where email like %s", (f"{EMAIL_PREFIX}-%",)).fetchall()]
    for uid in user_ids:
        attempt("devices", lambda x=uid: admin.table("devices").delete().eq("user_id", x).execute())
        attempt("user", lambda x=uid: admin.auth.admin.delete_user(x))
        attempt("profile", lambda x=uid: admin.table("profiles").delete().eq("id", x).execute())


def kill_own_pool_sessions() -> int:
    """Terminate every idle session held by THIS process's pool, and only those."""
    pool = pg_pool._pool_for(DB_URL)
    pool.wait()
    held = [pool.getconn() for _ in range(pool.get_stats()["pool_available"])]
    pids = [conn.execute("select pg_backend_pid() as pid").fetchone()["pid"] for conn in held]
    for conn in held:
        conn.rollback()
        pool.putconn(conn)
    with psycopg.connect(DB_URL) as killer:
        for pid in pids:
            killer.execute("select pg_terminate_backend(%s)", (pid,))
    time.sleep(1)
    return len(pids)


class reject_model:
    """Make `success_payload` refuse one response model for the duration."""

    def __init__(self, model):
        self.model, self.real = model, schemas.success_payload

    def __enter__(self):
        real, model = self.real, self.model

        def patched(m, raw):
            if m is model:
                raise ValueError(f"forced: {m.__name__} rejected")
            return real(m, raw)

        schemas.success_payload = patched

    def __exit__(self, *exc):
        schemas.success_payload = self.real


def run(s: dict) -> None:
    season, case = s["season"]["id"], s["case"]["id"]
    owner = {"Authorization": f"Bearer {sign_in(s['users']['owner'])}"}
    manager = {"Authorization": f"Bearer {sign_in(s['users']['manager'])}"}
    client = TestClient(main.app, raise_server_exceptions=False)

    def post_activity(kind: str, day: str, data: dict):
        return client.post(f"/v1/crop-seasons/{season}/activities", headers=owner, json={
            "activity_type": kind, "occurred_at": f"2026-06-{day}T00:00:00Z",
            "idempotency_key": str(uuid.uuid4()), "note": TAG, "data": data})

    # ---- A. every write succeeds on its first attempt after its sessions die ----
    first = post_activity("fertilizer", "05", {"fertilizer_name": "Urea", "amount_kg": 100, "nitrogen_percent": 46})
    check("warmup_activity_create", first.status_code == 201, first.text[:200])
    fertilizer_id = first.json().get("id")

    killed = kill_own_pool_sessions()
    r = post_activity("harvest", "20", {"yield_kg": 6000})
    check("dead_pool_then_activity_create_first_attempt", killed >= 1 and r.status_code == 201, f"killed={killed} {r.status_code} {r.text[:200]}")

    killed = kill_own_pool_sessions()
    r = client.patch(f"/v1/activities/{fertilizer_id}", headers=owner, json={"note": f"{TAG}-edited"})
    check("dead_pool_then_activity_update_first_attempt", killed >= 1 and r.status_code == 200, f"killed={killed} {r.status_code} {r.text[:200]}")

    killed = kill_own_pool_sessions()
    r = client.patch(f"/v1/crop-seasons/{season}/methodology", headers=owner, json={"cultivation_days": 110})
    check("dead_pool_then_methodology_first_attempt", killed >= 1 and r.status_code == 200, f"killed={killed} {r.status_code} {r.text[:200]}")

    killed = kill_own_pool_sessions()
    r = client.post("/v1/carbon/calculate", headers=owner, json={"crop_season_id": season, "water_regime_scenario": "as_recorded"})
    calc_id = r.json().get("calculation_id") if r.status_code == 200 else None
    check("dead_pool_then_carbon_persist_first_attempt", killed >= 1 and r.status_code == 200 and calc_id, f"killed={killed} {r.status_code} {r.text[:300]}")
    if calc_id:
        n = db_scalar("select count(*) from public.carbon_breakdowns where calculation_id = %s", (calc_id,))
        check("carbon_calculation_has_its_breakdown", n > 0, str(n))

    killed = kill_own_pool_sessions()
    r = client.post(f"/v1/crop-seasons/{season}/recommendations/generate", headers=owner)
    recs = r.json().get("items", []) if r.status_code == 200 else []
    check("dead_pool_then_recommendation_generate_first_attempt", killed >= 1 and r.status_code == 200, f"killed={killed} {r.status_code} {r.text[:200]}")
    rec_id = recs[0]["id"] if recs else None
    if rec_id:
        killed = kill_own_pool_sessions()
        r = client.patch(f"/v1/recommendations/{rec_id}", headers=owner, json={"status": "accepted"})
        check("dead_pool_then_recommendation_status_first_attempt", killed >= 1 and r.status_code == 200, f"killed={killed} {r.status_code} {r.text[:200]}")
    else:
        print("    (no recommendation fired for this season; status mutation covered by the real-DB test)")

    killed = kill_own_pool_sessions()
    r = client.post(f"/v1/mrv/cases/{case}/exports", headers=manager, json={"format": "json"})
    snapshot_id = r.json().get("export_id") if r.status_code == 201 else None
    check("dead_pool_then_mrv_snapshot_first_attempt", killed >= 1 and r.status_code == 201, f"killed={killed} {r.status_code} {r.text[:300]}")
    killed = kill_own_pool_sessions()
    r = client.post(f"/v1/mrv/exports/{snapshot_id}/render", headers=manager, json={"format": "xlsx"})
    check("dead_pool_then_mrv_render_first_attempt", killed >= 1 and r.status_code == 201, f"killed={killed} {r.status_code} {r.text[:300]}")

    # ---- B. a rejected response leaves the hosted data exactly as it was ------------
    note_before = db_scalar("select note from public.activities where id = %s", (fertilizer_id,))
    with reject_model(schemas.ActivityWriteResponse):
        r = client.patch(f"/v1/activities/{fertilizer_id}", headers=owner, json={"note": f"{TAG}-MUST-NOT-SAVE"})
    after = db_scalar("select note from public.activities where id = %s", (fertilizer_id,))
    check("rejected_activity_update_is_not_saved", r.status_code >= 500 and after == note_before, f"{r.status_code} {after!r}")

    n_before = db_scalar("select count(*) from public.activities a join public.production_batches b on b.id = a.production_batch_id where b.crop_season_id = %s", (season,))
    with reject_model(schemas.ActivityWriteResponse):
        r = post_activity("irrigation", "10", {"method": "awd", "water_volume_m3": 5})
    n_after = db_scalar("select count(*) from public.activities a join public.production_batches b on b.id = a.production_batch_id where b.crop_season_id = %s", (season,))
    check("rejected_activity_create_is_not_saved", r.status_code >= 500 and n_after == n_before, f"{r.status_code} {n_before}->{n_after}")

    with reject_model(schemas.CropSeasonResponse):
        r = client.patch(f"/v1/crop-seasons/{season}/methodology", headers=owner, json={"cultivation_days": 120})
    days = db_scalar("select cultivation_days from public.crop_seasons where id = %s", (season,))
    check("rejected_methodology_update_is_not_saved", r.status_code >= 500 and days == 110, f"{r.status_code} days={days}")

    calcs_before = db_scalar("select count(*) from public.carbon_calculations where crop_season_id = %s", (season,))
    real_payload = api._payload
    api._payload = lambda result, calculation_id: {**real_payload(result, calculation_id), "total_co2e_kg": float("nan")}
    try:
        # A different scenario, so the save would be a NEW row if it were reached.
        r = client.post("/v1/carbon/calculate", headers=owner, json={"crop_season_id": season, "water_regime_scenario": "awd"})
    finally:
        api._payload = real_payload
    calcs_after = db_scalar("select count(*) from public.carbon_calculations where crop_season_id = %s", (season,))
    check("rejected_carbon_payload_is_not_saved", r.status_code >= 500 and calcs_after == calcs_before, f"{r.status_code} {calcs_before}->{calcs_after}")

    if rec_id:
        with reject_model(schemas.RecommendationResponse):
            r = client.patch(f"/v1/recommendations/{rec_id}", headers=owner, json={"status": "dismissed"})
        status = db_scalar("select status::text from public.season_recommendations where id = %s", (rec_id,))
        check("rejected_recommendation_status_is_not_saved", r.status_code >= 500 and status == "accepted", f"{r.status_code} {status}")

    def mrv_state():
        rows = db_scalar("select count(*) from public.mrv_exports where mrv_case_id = %s", (case,))
        objects = db_scalar("select count(*) from storage.objects where bucket_id = %s and name like %s", (BUCKET, f"{s['org']['id']}/%"))
        return rows, objects

    before = mrv_state()
    with reject_model(schemas.MrvArtifactResponse):
        r = client.post(f"/v1/mrv/exports/{snapshot_id}/render", headers=manager, json={"format": "pdf"})
    check("rejected_mrv_render_leaves_no_row_and_no_object", r.status_code >= 500 and mrv_state() == before, f"{r.status_code} {before}->{mrv_state()}")

    with reject_model(schemas.MrvExportCreatedResponse):
        r = client.post(f"/v1/mrv/cases/{case}/exports", headers=manager, json={"format": "json"})
    check("rejected_mrv_snapshot_is_not_saved", r.status_code >= 500 and mrv_state() == before, f"{r.status_code} {before}->{mrv_state()}")

    # After all of that the API still works normally.
    r = client.patch(f"/v1/activities/{fertilizer_id}", headers=owner, json={"note": f"{TAG}-final"})
    check("normal_write_after_rejections", r.status_code == 200 and r.json()["note"] == f"{TAG}-final", r.text[:200])


def main_() -> int:
    print(f"=== Hosted write reliability smoke - run {RUN_ID} ===")
    before = snapshot()
    try:
        run(seed())
    except Exception as exc:  # noqa: BLE001
        check("smoke_completed_without_exception", False, repr(exc))
    finally:
        print("Cleaning up ...")
        cleanup()
        pg_pool.close_all()
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
    raise SystemExit(main_())

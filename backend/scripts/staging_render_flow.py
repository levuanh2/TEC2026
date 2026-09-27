"""Hosted staging flow through the DEPLOYED Render API, on a disposable tenant.

    STAGING_API_URL=https://agricarbon-api-staging.onrender.com \
    python backend/scripts/staging_render_flow.py

Needs SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, SUPABASE_SERVICE_ROLE_KEY (backend/.env
or environment) and STAGING_API_URL. Run by .github/workflows/staging-e2e.yml.

No shared QA identity is used. The service role creates ONE disposable
cooperative and its manager under a unique run tag; everything else goes
through the Render API exactly as the web app does:

  manager: /v1/me -> provision a farmer with farm + plot (Auth Admin, server side)
  farmer:  sign in with the temporary password -> /v1/farmer/scope
           -> create season (+ default batch) -> irrigation activity: create,
           idempotent replay, edit, list -> Carbon readiness
           -> mark harvested -> a new write is refused (422)
  manager: MRV case list for the tenant (read-only) ; anonymous read is 401

Cleanup runs in `finally`: every row under the tag and every Auth user with the
run's e-mail prefix (including the farmer the API provisioned) is deleted, then
table row counts must equal the counts taken before the run. Exit 1 on any
failed check OR any cleanup difference; the run tag and created ids are
printed so leftovers can be found. Secrets, tokens and passwords are never printed.
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
from supabase import create_client  # noqa: E402

from infrastructure.config import load_settings  # noqa: E402

PREFIX = "ci-staging"
RUN = uuid.uuid4().hex[:8]
TAG = f"CI-STAGING-{RUN}"
EMAIL_PREFIX = f"{PREFIX}-{RUN}-"
API = os.environ.get("STAGING_API_URL", "").rstrip("/")

settings = load_settings()
URL, SERVICE = settings.require_supabase()
_, PUBLISHABLE = settings.require_publishable()
admin = create_client(URL, SERVICE)

COUNTED = ["organizations", "organization_memberships", "profiles", "farms", "farm_members", "plots",
           "crop_seasons", "production_batches", "activities", "irrigation_events"]
created: dict[str, str] = {}
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    print(("PASS" if ok else "FAIL") + f"  {name}" + (f"  ({detail})" if detail and not ok else ""), flush=True)
    return ok


def snapshot() -> dict[str, int]:
    return {t: admin.table(t).select("*", count="exact").limit(1).execute().count for t in COUNTED}


def sign_in(email: str, password: str) -> str:
    r = httpx.post(f"{URL}/auth/v1/token?grant_type=password", headers={"apikey": PUBLISHABLE},
                   json={"email": email, "password": password}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


def api(token: str | None, method: str, path: str, json=None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return httpx.request(method, f"{API}{path}", headers=headers, json=json, timeout=90)


def flow() -> None:
    org = admin.table("organizations").insert(
        {"organization_code": TAG, "name": TAG, "organization_type": "cooperative"}).execute().data[0]
    created["organization"] = org["id"]
    manager_email, manager_password = f"{EMAIL_PREFIX}manager@agricarbon-ci.invalid", f"Ci-{uuid.uuid4().hex}!A1"
    manager = admin.auth.admin.create_user(
        {"email": manager_email, "password": manager_password, "email_confirm": True}).user
    created["manager_user"] = manager.id
    admin.table("organization_memberships").insert(
        {"organization_id": org["id"], "user_id": manager.id, "role": "cooperative_manager"}).execute()
    mtok = sign_in(manager_email, manager_password)

    r = api(mtok, "GET", "/v1/me")
    check("manager_me_200", r.status_code == 200 and any(
        m.get("organization_id") == org["id"] for m in r.json().get("organization_memberships", [])), f"{r.status_code}")

    farmer_email = f"{EMAIL_PREFIX}farmer@agricarbon-ci.invalid"
    r = api(mtok, "POST", f"/v1/organizations/{org['id']}/farmers", {
        "full_name": f"{TAG} farmer", "email": farmer_email,
        "farm": {"farm_code": f"{TAG}-FARM", "farm_name": TAG},
        "plot": {"plot_code": f"{TAG}-PLOT", "name": TAG, "area_ha": 1.0},
    })
    if not check("provision_farmer_with_farm_and_plot_201", r.status_code == 201, f"{r.status_code} {r.text[:200]}"):
        return
    prov = r.json()
    created.update(farmer_user=prov["user_id"], farm=prov["farm_id"], plot=prov["plot_id"])
    ftok = sign_in(farmer_email, prov["temporary_password"])

    r = api(ftok, "GET", "/v1/farmer/scope")
    check("farmer_scope_has_provisioned_farm", r.status_code == 200 and prov["farm_id"] in r.text, f"{r.status_code}")

    r = api(ftok, "POST", f"/v1/plots/{prov['plot_id']}/crop-seasons",
            {"season_code": f"{TAG}-S1", "planting_date": "2026-09-01"})
    if not check("create_season_201_with_default_batch",
                 r.status_code == 201 and bool(r.json().get("default_production_batch_id")), f"{r.status_code} {r.text[:200]}"):
        return
    season = r.json()["id"]
    created["season"] = season

    body = {"idempotency_key": str(uuid.uuid4()), "activity_type": "irrigation",
            "occurred_at": "2026-09-05T06:30:00+07:00", "note": TAG, "data": {"method": "awd", "water_volume_m3": 32}}
    r = api(ftok, "POST", f"/v1/crop-seasons/{season}/activities", body)
    if not check("activity_create_201", r.status_code == 201, f"{r.status_code} {r.text[:200]}"):
        return
    activity = r.json()["id"]
    created["activity"] = activity
    r = api(ftok, "POST", f"/v1/crop-seasons/{season}/activities", body)
    check("activity_replay_is_idempotent", r.status_code in (200, 201) and r.json().get("id") == activity
          and r.json().get("idempotent_replay") is True, f"{r.status_code} {r.text[:200]}")
    r = api(ftok, "PATCH", f"/v1/activities/{activity}", {"note": f"{TAG} edited"})
    check("activity_edit_200", r.status_code == 200 and r.json().get("note") == f"{TAG} edited", f"{r.status_code}")
    r = api(ftok, "GET", f"/v1/crop-seasons/{season}/activities")
    check("activity_listed", r.status_code == 200 and activity in r.text, f"{r.status_code}")

    r = api(ftok, "GET", f"/v1/crop-seasons/{season}/carbon/readiness")
    check("carbon_readiness_200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")

    r = api(mtok, "GET", "/v1/mrv/cases")
    check("manager_mrv_cases_read_200", r.status_code == 200, f"{r.status_code}")

    r = api(ftok, "PATCH", f"/v1/crop-seasons/{season}/status", {"status": "harvested", "actual_harvest_date": "2026-09-20"})
    check("season_marked_harvested_200", r.status_code == 200, f"{r.status_code} {r.text[:200]}")
    r = api(ftok, "POST", f"/v1/crop-seasons/{season}/activities", {**body, "idempotency_key": str(uuid.uuid4())})
    check("write_to_harvested_season_refused_422", r.status_code == 422
          and r.json()["detail"]["error"]["code"] == "invalid_crop_season_state", f"{r.status_code} {r.text[:200]}")

    r = api(None, "GET", "/v1/farmer/scope")
    check("anonymous_read_401", r.status_code == 401, f"{r.status_code}")


def attempt(problems: list[str], label: str, fn, tries: int = 3):
    """Run one cleanup step, retrying transient errors; record, never raise."""
    for i in range(tries):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 -- every step must be tried
            last = exc
            time.sleep(2 * (i + 1))
    problems.append(f"{label}: {type(last).__name__}")
    return None


def cleanup() -> list[str]:
    """Delete everything under the run tag. Discovery queries are protected the
    same way as deletes, so one failed lookup cannot skip the rest."""
    problems: list[str] = []
    t = admin.table

    def rows(label, query):
        return attempt(problems, f"list {label}", lambda: query.execute().data) or []

    def delete(label, query):
        attempt(problems, f"delete {label}", query.execute)

    for org in rows("organizations", t("organizations").select("id").eq("organization_code", TAG)):
        for farm in rows("farms", t("farms").select("id").eq("cooperative_id", org["id"])):
            for plot in rows("plots", t("plots").select("id").eq("farm_id", farm["id"])):
                for s in rows("crop_seasons", t("crop_seasons").select("id").eq("plot_id", plot["id"])):
                    for b in rows("production_batches", t("production_batches").select("id").eq("crop_season_id", s["id"])):
                        for a in rows("activities", t("activities").select("id").eq("production_batch_id", b["id"])):
                            delete("irrigation_events", t("irrigation_events").delete().eq("activity_id", a["id"]))
                            delete("activities", t("activities").delete().eq("id", a["id"]))
                        delete("production_batches", t("production_batches").delete().eq("id", b["id"]))
                    delete("crop_seasons", t("crop_seasons").delete().eq("id", s["id"]))
                delete("plots", t("plots").delete().eq("id", plot["id"]))
            delete("farm_members", t("farm_members").delete().eq("farm_id", farm["id"]))
            delete("farms", t("farms").delete().eq("id", farm["id"]))
        delete("organization_memberships", t("organization_memberships").delete().eq("organization_id", org["id"]))
        delete("organizations", t("organizations").delete().eq("id", org["id"]))
    users = attempt(problems, "list auth users", lambda: admin.auth.admin.list_users(page=1, per_page=1000)) or []
    for u in users:
        if (u.email or "").startswith(EMAIL_PREFIX):
            attempt(problems, "delete auth user", lambda x=u.id: admin.auth.admin.delete_user(x))
            delete("profiles", t("profiles").delete().eq("id", u.id))
    return problems


def verify(before: dict[str, int]) -> tuple[dict, list[str], list[str]]:
    """Row counts back to baseline, and no Auth user of this run left
    (auth.users is not among the counted public tables)."""
    problems: list[str] = []
    after = attempt(problems, "count rows after cleanup", snapshot) or {}
    diff = {k: (before[k], after.get(k)) for k in before if before[k] != after.get(k)}
    users = attempt(problems, "list auth users after cleanup",
                    lambda: admin.auth.admin.list_users(page=1, per_page=1000))
    orphans = [u.id for u in (users or []) if (u.email or "").startswith(EMAIL_PREFIX)]
    return diff, orphans, problems


def main() -> int:
    if not API:
        sys.exit("STAGING_API_URL is required")
    print(f"=== staging Render flow, run tag {TAG} against {API} ===")
    before = snapshot()
    try:
        flow()
    except Exception as exc:  # noqa: BLE001 -- report, then still clean up
        check("flow_completed_without_exception", False, f"{type(exc).__name__}: {str(exc)[:200]}")
    finally:
        problems = cleanup()
        time.sleep(1)
        diff, orphans, verify_problems = verify(before)
    check("cleanup_steps_succeeded", not problems, "; ".join(problems))
    check("cleanup_verified", not verify_problems, "; ".join(verify_problems))
    check("cleanup_row_counts_restored", not diff, str(diff))
    check("cleanup_no_auth_users_left", not orphans, f"auth user ids: {orphans}")
    failed = [name for name, ok, _ in results if not ok]
    print(f"=== {len(results) - len(failed)}/{len(results)} checks passed ===")
    if problems or verify_problems or diff or orphans:
        # ids only -- never tokens or passwords
        print(f"LEFTOVER CHECK NEEDED for tag {TAG}: {created}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

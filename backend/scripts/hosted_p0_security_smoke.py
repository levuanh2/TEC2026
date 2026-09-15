"""Hosted Supabase smoke for the P0 security fixes — M7, B7, B3.

Run:  python backend/scripts/hosted_p0_security_smoke.py
Needs backend/.env (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_PUBLISHABLE_KEY,
SUPABASE_DB_URL).

What it does, against the REAL hosted stack:
  * seeds an isolated tenant whose every code carries `P0-SECURITY-SMOKE-<run>`
    (cooperative, second cooperative, government + enterprise grantee orgs, farm,
    plot, active season, batch, MRV case) with the service role;
  * creates temporary Supabase Auth users with random, never-printed passwords:
    manager, farm owner, editor, viewer, regulator, enterprise_viewer, an ended
    manager, and a user with an ended manager + active farmer membership;
  * signs each in for a real JWT and calls the real Storage API, PostgREST and
    FastAPI (`main.app`, no dependency overrides);
  * removes everything it created in `finally` — Storage objects, exports,
    activities, devices, memberships, orgs, users — and compares row counts.

It never touches demo/QA data or existing identities. `audit.change_log` rows
written by audit triggers are append-only by design and are reported, not
deleted.
"""
from __future__ import annotations

import hashlib
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

import httpx  # noqa: E402
import psycopg  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from supabase import create_client  # noqa: E402

from infrastructure.config import load_settings  # noqa: E402

PREFIX = "P0-SECURITY-SMOKE"
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
    "organizations", "organization_memberships", "organization_data_grants", "profiles",
    "farms", "farm_members", "plots", "crop_seasons", "production_batches", "activities",
    "irrigation_events", "devices", "mrv_cases", "mrv_case_steps", "mrv_case_batches",
    "mrv_exports", "mrv_export_calculations",
]

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
    counts["storage.objects[mrv-exports]"] = db_scalar("select count(*) from storage.objects where bucket_id = %s", (BUCKET,))
    counts["auth.users[smoke]"] = db_scalar("select count(*) from auth.users where email like %s", (f"{PREFIX.lower()}-%",))
    return counts


def insert(table: str, row: dict) -> dict:
    return admin.table(table).insert(row).execute().data[0]


# -- seeding ---------------------------------------------------------------

def seed() -> dict:
    s: dict = {}
    s["org"] = insert("organizations", {"organization_code": f"{TAG}-COOP", "name": f"{TAG} coop", "organization_type": "cooperative"})
    s["org2"] = insert("organizations", {"organization_code": f"{TAG}-COOP2", "name": f"{TAG} coop 2", "organization_type": "cooperative"})
    s["gov"] = insert("organizations", {"organization_code": f"{TAG}-GOV", "name": f"{TAG} regulator", "organization_type": "government"})
    s["ent"] = insert("organizations", {"organization_code": f"{TAG}-ENT", "name": f"{TAG} enterprise", "organization_type": "enterprise"})
    org = s["org"]["id"]
    s["farm"] = insert("farms", {"cooperative_id": org, "farm_code": f"{TAG}-FARM", "farm_name": f"{TAG} farm"})
    s["plot"] = insert("plots", {"farm_id": s["farm"]["id"], "plot_code": f"{TAG}-PLOT", "name": f"{TAG} plot", "area_ha": 1.0})
    s["season"] = insert("crop_seasons", {"plot_id": s["plot"]["id"], "season_code": f"{TAG}-SEASON", "crop_type": "rice", "status": "active"})
    s["batch"] = insert("production_batches", {"crop_season_id": s["season"]["id"], "batch_code": "default"})
    s["case"] = insert("mrv_cases", {
        "organization_id": org, "case_code": f"{TAG}-CASE", "name": f"{TAG} case",
        "period_start": "2026-05-01", "period_end": "2026-09-30", "status": "draft",
    })
    insert("mrv_case_batches", {"mrv_case_id": s["case"]["id"], "production_batch_id": s["batch"]["id"]})
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    for grantee in ("gov", "ent"):
        insert("organization_data_grants", {
            "grantee_organization_id": s[grantee]["id"], "source_organization_id": org,
            "access_level": "read", "valid_from": yesterday,
        })

    long_ago = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    users = {}
    for label in ("manager", "owner", "editor", "viewer", "regulator", "enterprise", "expired_manager", "mixed"):
        email = f"{EMAIL_PREFIX}-{label.replace('_', '-')}@agricarbon.invalid"
        password = f"P0-{uuid.uuid4().hex}!Aa1"
        user = admin.auth.admin.create_user({"email": email, "password": password, "email_confirm": True}).user
        users[label] = {"id": user.id, "email": email, "password": password}
    s["users"] = users

    def member(org_key: str, label: str, role: str, joined_at: str | None = None) -> None:
        row = {"organization_id": s[org_key]["id"], "user_id": users[label]["id"], "role": role}
        if joined_at:
            row["joined_at"] = joined_at
        insert("organization_memberships", row)

    member("org", "manager", "cooperative_manager")
    for label in ("owner", "editor", "viewer"):
        member("org", label, "farmer")
        insert("farm_members", {"farm_id": s["farm"]["id"], "user_id": users[label]["id"], "farm_role": label})
    member("gov", "regulator", "regulator")
    member("ent", "enterprise", "enterprise_viewer")
    member("org", "expired_manager", "cooperative_manager", long_ago)
    member("org", "mixed", "cooperative_manager", long_ago)
    member("org2", "mixed", "farmer")
    ended = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    for label in ("expired_manager", "mixed"):
        admin.table("organization_memberships").update({"ended_at": ended}).eq("organization_id", org).eq("user_id", users[label]["id"]).execute()
    return s


def sign_in(user: dict) -> str:
    r = httpx.post(f"{URL}/auth/v1/token?grant_type=password", headers={"apikey": PUBLISHABLE},
                   json={"email": user["email"], "password": user["password"]}, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


# -- cleanup ---------------------------------------------------------------

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

    cases = admin.table("mrv_cases").select("id").ilike("case_code", f"{TAG}-%").execute().data
    for case in cases:
        cid = case["id"]
        exports = admin.table("mrv_exports").select("id").eq("mrv_case_id", cid).execute().data
        for export in exports:
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
                    for batch in admin.table("production_batches").select("id").eq("crop_season_id", season["id"]).execute().data:
                        for act in admin.table("activities").select("id").eq("production_batch_id", batch["id"]).execute().data:
                            for detail in ("irrigation_events", "fertilizer_applications", "harvest_events", "seeding_events",
                                           "pesticide_applications", "straw_management_events", "fuel_usages"):
                                attempt(detail, lambda t=detail, x=act["id"]: admin.table(t).delete().eq("activity_id", x).execute())
                            attempt("activity", lambda x=act["id"]: admin.table("activities").delete().eq("id", x).execute())
                        attempt("batch", lambda x=batch["id"]: admin.table("production_batches").delete().eq("id", x).execute())
                    attempt("season", lambda x=season["id"]: admin.table("crop_seasons").delete().eq("id", x).execute())
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


# -- checks ----------------------------------------------------------------

def api_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def rest_headers(token: str) -> dict:
    return {"apikey": PUBLISHABLE, "Authorization": f"Bearer {token}", "Content-Type": "application/json", "Prefer": "return=representation"}


def storage_denied(token: str, path: str, prefix: str) -> tuple[bool, str]:
    headers = {"apikey": PUBLISHABLE, "Authorization": f"Bearer {token}"}
    got = httpx.get(f"{URL}/storage/v1/object/authenticated/{BUCKET}/{path}", headers=headers, timeout=30)
    listed = httpx.post(f"{URL}/storage/v1/object/list/{BUCKET}", headers=headers, json={"prefix": prefix, "limit": 100}, timeout=30)
    names = [o.get("name") for o in listed.json()] if listed.status_code == 200 and isinstance(listed.json(), list) else []
    return got.status_code != 200 and not names, f"download={got.status_code} list={listed.status_code} names={names}"


def run_checks(s: dict, client: TestClient) -> None:
    users = s["users"]
    tokens = {label: sign_in(user) for label, user in users.items()}
    check("sign_in_all_temporary_users", all(tokens.values()))
    org, case, season, batch = s["org"]["id"], s["case"]["id"], s["season"]["id"], s["batch"]["id"]

    # ---- B7: /v1/me ignores ended memberships -------------------------------
    me = client.get("/v1/me", headers=api_headers(tokens["manager"])).json()
    check("b7_active_manager_reported", "cooperative_manager" in me.get("roles", []), str(me.get("roles")))
    me = client.get("/v1/me", headers=api_headers(tokens["expired_manager"])).json()
    check("b7_ended_manager_not_reported", "cooperative_manager" not in me.get("roles", []) and me.get("organization_memberships") == [], str(me))
    me = client.get("/v1/me", headers=api_headers(tokens["mixed"])).json()
    check("b7_ended_manager_plus_active_farmer_only_farmer", me.get("roles") == ["farmer"]
          and [m["organization_id"] for m in me.get("organization_memberships", [])] == [s["org2"]["id"]], str(me))

    # ---- M7: backend artifact path keeps working ------------------------------
    created = client.post(f"/v1/mrv/cases/{case}/exports", json={"format": "xlsx"}, headers=api_headers(tokens["manager"]))
    check("m7_manager_creates_xlsx_export", created.status_code == 201, created.text[:200])
    rows = admin.table("mrv_exports").select("id,format,storage_object_path,file_sha256").eq("mrv_case_id", case).execute().data
    xlsx = next((r for r in rows if r["format"] == "xlsx"), None)
    snapshot_row = next((r for r in rows if r["format"] == "json"), None)
    check("m7_export_rows_written", xlsx is not None and snapshot_row is not None, str(rows))
    if not xlsx:
        return
    path, prefix = xlsx["storage_object_path"], f"{org}/{case}/"

    r = client.get(f"/v1/mrv/exports/{xlsx['id']}/download", headers=api_headers(tokens["manager"]))
    check("m7_manager_fastapi_download_200", r.status_code == 200, str(r.status_code))
    check("m7_manager_download_sha256_verified", hashlib.sha256(r.content).hexdigest() == xlsx["file_sha256"])
    r = client.get(f"/v1/mrv/exports/{snapshot_row['id']}/download", headers=api_headers(tokens["manager"]))
    check("m7_manager_snapshot_download_200", r.status_code == 200, str(r.status_code))
    check("m7_manager_metadata_200", client.get(f"/v1/mrv/exports/{xlsx['id']}", headers=api_headers(tokens["manager"])).status_code == 200)
    for label in ("owner", "regulator", "enterprise", "expired_manager"):
        r = client.get(f"/v1/mrv/exports/{xlsx['id']}/download", headers=api_headers(tokens[label]))
        check(f"m7_{label}_fastapi_download_404", r.status_code == 404 and r.json()["detail"]["error"]["code"] == "not_found", f"{r.status_code} {r.text[:120]}")
        r = client.get(f"/v1/mrv/exports/{xlsx['id']}", headers=api_headers(tokens[label]))
        check(f"m7_{label}_metadata_404", r.status_code == 404, str(r.status_code))
    r = client.post(f"/v1/mrv/cases/{case}/exports", json={"format": "json"}, headers=api_headers(tokens["expired_manager"]))
    check("b7_ended_manager_cannot_export_404", r.status_code == 404, str(r.status_code))

    # ---- M7: direct Storage API access is denied -------------------------------
    service = httpx.get(f"{URL}/storage/v1/object/authenticated/{BUCKET}/{path}",
                        headers={"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"}, timeout=30)
    check("m7_object_exists_for_service_role", service.status_code == 200, str(service.status_code))
    check("m7_bucket_still_private", db_scalar("select public from storage.buckets where id = %s", (BUCKET,)) is False)
    for label in ("owner", "viewer", "regulator", "enterprise", "manager", "expired_manager"):
        ok, detail = storage_denied(tokens[label], path, prefix)
        check(f"m7_{label}_direct_storage_read_denied", ok, detail)
    ok, detail = storage_denied(PUBLISHABLE, path, prefix)
    check("m7_anonymous_direct_storage_read_denied", ok, detail)
    public = httpx.get(f"{URL}/storage/v1/object/public/{BUCKET}/{path}", timeout=30)
    check("m7_public_url_denied", public.status_code != 200, str(public.status_code))
    planted = httpx.post(
        f"{URL}/storage/v1/object/{BUCKET}/{prefix}planted-{RUN_ID}.pdf", content=b"%PDF-planted",
        headers={"apikey": PUBLISHABLE, "Authorization": f"Bearer {tokens['manager']}", "Content-Type": "application/pdf"}, timeout=30,
    )
    check("m7_manager_client_upload_denied", planted.status_code not in (200, 201), str(planted.status_code))
    httpx.request("DELETE", f"{URL}/storage/v1/object/{BUCKET}", json={"prefixes": [path]},
                  headers={"apikey": PUBLISHABLE, "Authorization": f"Bearer {tokens['manager']}"}, timeout=30)
    r = client.get(f"/v1/mrv/exports/{xlsx['id']}/download", headers=api_headers(tokens["manager"]))
    check("m7_manager_client_delete_had_no_effect", r.status_code == 200 and hashlib.sha256(r.content).hexdigest() == xlsx["file_sha256"], str(r.status_code))

    # ---- B3: viewer read-only on FastAPI ------------------------------------------
    body = lambda: {"idempotency_key": str(uuid.uuid4()), "activity_type": "irrigation",
                    "occurred_at": "2026-09-15T00:00:00Z", "note": TAG, "data": {"method": "awd", "water_volume_m3": 1}}
    r = client.get(f"/v1/crop-seasons/{season}/activities", headers=api_headers(tokens["viewer"]))
    check("b3_viewer_fastapi_read_200", r.status_code == 200, str(r.status_code))
    r = client.post(f"/v1/crop-seasons/{season}/activities", json=body(), headers=api_headers(tokens["viewer"]))
    check("b3_viewer_fastapi_create_404", r.status_code == 404 and r.json()["detail"]["error"]["code"] == "not_found", f"{r.status_code} {r.text[:120]}")
    owned = {}
    for label in ("owner", "editor"):
        r = client.post(f"/v1/crop-seasons/{season}/activities", json=body(), headers=api_headers(tokens[label]))
        check(f"b3_{label}_fastapi_create_201", r.status_code == 201, f"{r.status_code} {r.text[:160]}")
        owned[label] = r.json().get("id") if r.status_code == 201 else None
    if owned["owner"]:
        r = client.patch(f"/v1/activities/{owned['owner']}", json={"note": f"{TAG} edited"}, headers=api_headers(tokens["owner"]))
        check("b3_owner_fastapi_update_200", r.status_code == 200, str(r.status_code))
    if owned["editor"]:
        r = client.delete(f"/v1/activities/{owned['editor']}", headers=api_headers(tokens["editor"]))
        check("b3_editor_fastapi_delete_204", r.status_code == 204, str(r.status_code))

    viewer_row = insert("activities", {
        "production_batch_id": batch, "activity_type": "irrigation", "occurred_at": "2026-09-14T00:00:00Z",
        "recorded_at": "2026-09-14T00:00:00Z", "source": "web", "recorded_by": users["viewer"]["id"], "note": TAG,
    })
    insert("irrigation_events", {"activity_id": viewer_row["id"], "method": "awd", "water_volume_m3": 2})
    r = client.patch(f"/v1/activities/{viewer_row['id']}", json={"note": "changed"}, headers=api_headers(tokens["viewer"]))
    check("b3_viewer_fastapi_update_own_404", r.status_code == 404, str(r.status_code))
    r = client.delete(f"/v1/activities/{viewer_row['id']}", headers=api_headers(tokens["viewer"]))
    check("b3_viewer_fastapi_delete_own_404", r.status_code == 404, str(r.status_code))
    after = admin.table("activities").select("note,deleted_at").eq("id", viewer_row["id"]).execute().data[0]
    check("b3_viewer_row_unchanged_after_fastapi", after == {"note": TAG, "deleted_at": None}, str(after))

    # ---- B3: viewer read-only on direct Supabase (Flutter path) --------------------
    def device(label: str) -> str:
        r = httpx.post(f"{URL}/rest/v1/devices", headers=rest_headers(tokens[label]),
                       json={"user_id": users[label]["id"], "installation_id": str(uuid.uuid4()), "platform": "android"}, timeout=30)
        r.raise_for_status()
        return r.json()[0]["id"]

    def direct_insert(label: str):
        return httpx.post(f"{URL}/rest/v1/activities", headers=rest_headers(tokens[label]), json={
            "production_batch_id": batch, "activity_type": "irrigation", "occurred_at": "2026-09-15T01:00:00Z",
            "recorded_at": "2026-09-15T01:00:00Z", "source": "mobile_offline", "recorded_by": users[label]["id"],
            "device_id": device(label), "client_event_id": str(uuid.uuid4()), "note": TAG,
        }, timeout=30)

    r = httpx.get(f"{URL}/rest/v1/activities?id=eq.{viewer_row['id']}&select=id", headers=rest_headers(tokens["viewer"]), timeout=30)
    check("b3_viewer_direct_select_allowed", r.status_code == 200 and len(r.json()) == 1, r.text[:120])
    r = direct_insert("viewer")
    check("b3_viewer_direct_insert_denied", r.status_code in (401, 403) and "42501" in r.text, f"{r.status_code} {r.text[:160]}")
    r = httpx.patch(f"{URL}/rest/v1/activities?id=eq.{viewer_row['id']}", headers=rest_headers(tokens["viewer"]), json={"note": "changed"}, timeout=30)
    check("b3_viewer_direct_update_no_rows", r.status_code in (200, 204) and (r.status_code == 204 or r.json() == []), f"{r.status_code} {r.text[:120]}")
    r = httpx.post(f"{URL}/rest/v1/rpc/soft_delete_activity", headers=rest_headers(tokens["viewer"]), json={"p_activity_id": viewer_row["id"]}, timeout=30)
    check("b3_viewer_direct_soft_delete_denied", r.status_code in (401, 403) and "42501" in r.text, f"{r.status_code} {r.text[:160]}")
    after = admin.table("activities").select("note,deleted_at").eq("id", viewer_row["id"]).execute().data[0]
    check("b3_viewer_row_unchanged_after_direct", after == {"note": TAG, "deleted_at": None}, str(after))

    for label in ("owner", "editor"):
        r = direct_insert(label)
        check(f"b3_{label}_direct_insert_allowed", r.status_code == 201, f"{r.status_code} {r.text[:160]}")
        if r.status_code == 201:
            new_id = r.json()[0]["id"]
            r = httpx.post(f"{URL}/rest/v1/rpc/soft_delete_activity", headers=rest_headers(tokens[label]), json={"p_activity_id": new_id}, timeout=30)
            check(f"b3_{label}_direct_soft_delete_own_allowed", r.status_code == 200 and r.json() is True, f"{r.status_code} {r.text[:120]}")


def main() -> int:
    print(f"=== Hosted P0 security smoke — run {RUN_ID} ===")
    before = snapshot()
    audit_before = db_scalar("select count(*) from audit.change_log")
    try:
        state = seed()
        from main import app  # after seeding so settings load exactly as the server would
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

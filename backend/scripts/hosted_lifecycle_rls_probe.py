"""Direct-PostgREST lifecycle/authorization probe on a DISPOSABLE tenant.

Drives exactly the calls the Flutter app makes (`app/lib/services/sync_gateway.dart`):
insert/update of `activities`, upsert/delete of an activity detail row, and the
`soft_delete_activity` RPC -- as real users with real JWTs, through PostgREST and
RLS, bypassing FastAPI entirely.

    python backend/scripts/hosted_lifecycle_rls_probe.py            # report only
    python backend/scripts/hosted_lifecycle_rls_probe.py --enforce  # exit 1 on any mismatch

Outcome per call:
  OK       the database performed the write (rows changed)
  SILENT   the call "succeeded" but changed 0 rows -- a client without
           `return=representation` (Flutter's update) cannot tell it failed
  DENIED   the database refused with an error (code shown)

Expected (the P1 lifecycle contract): only an active-membership writer on an
`active` season is OK; every other case is DENIED -- never SILENT.

Everything is created with the service role under a unique tag and deleted in
`finally`; table row counts are compared.
"""
from __future__ import annotations

import argparse
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
from supabase import create_client  # noqa: E402

from infrastructure.config import load_settings  # noqa: E402

PREFIX = "LIFECYCLE-RLS-PROBE"
RUN = uuid.uuid4().hex[:8]
TAG = f"{PREFIX}-{RUN}"
settings = load_settings()
URL, SERVICE = settings.require_supabase()
_, PUBLISHABLE = settings.require_publishable()
admin = create_client(URL, SERVICE)
COUNTED = ["organizations", "organization_memberships", "profiles", "farms", "farm_members", "plots",
           "crop_seasons", "production_batches", "activities", "irrigation_events", "devices"]


def ins(table: str, row: dict) -> dict:
    return admin.table(table).insert(row).execute().data[0]


def snapshot() -> dict:
    return {t: admin.table(t).select("*", count="exact").limit(1).execute().count for t in COUNTED}


def user(label: str) -> dict:
    email = f"{PREFIX.lower()}-{RUN}-{label}@agricarbon.invalid"
    password = f"Lp-{uuid.uuid4().hex}!A1"
    uid = admin.auth.admin.create_user({"email": email, "password": password, "email_confirm": True}).user.id
    token = httpx.post(f"{URL}/auth/v1/token?grant_type=password", headers={"apikey": PUBLISHABLE},
                       json={"email": email, "password": password}, timeout=30).json()["access_token"]
    return {"id": uid, "token": token, "label": label}


def seed() -> dict:
    org = ins("organizations", {"organization_code": f"{TAG}-ORG", "name": TAG, "organization_type": "cooperative"})
    other = ins("organizations", {"organization_code": f"{TAG}-OTHER", "name": f"{TAG} other", "organization_type": "cooperative"})
    u = {k: user(k) for k in ("owner", "former", "viewer", "outsider", "expired_manager")}
    for k, role in (("owner", "farmer"), ("former", "farmer"), ("viewer", "farmer"), ("expired_manager", "cooperative_manager")):
        ins("organization_memberships", {"organization_id": org["id"], "user_id": u[k]["id"], "role": role})
    ins("organization_memberships", {"organization_id": other["id"], "user_id": u["outsider"]["id"], "role": "farmer"})
    farm = ins("farms", {"cooperative_id": org["id"], "farm_code": f"{TAG}-FARM", "farm_name": TAG})
    other_farm = ins("farms", {"cooperative_id": other["id"], "farm_code": f"{TAG}-OFARM", "farm_name": f"{TAG} other"})
    for k, role in (("owner", "owner"), ("former", "owner"), ("viewer", "viewer")):
        ins("farm_members", {"farm_id": farm["id"], "user_id": u[k]["id"], "farm_role": role})
    ins("farm_members", {"farm_id": other_farm["id"], "user_id": u["outsider"]["id"], "farm_role": "owner"})
    # Memberships end AFTER the farm roles exist (the farm-member trigger needs them active).
    for k in ("former", "expired_manager"):
        admin.table("organization_memberships").update({"ended_at": "2026-01-01T00:00:00Z", "joined_at": "2025-01-01T00:00:00Z"}) \
            .eq("user_id", u[k]["id"]).eq("organization_id", org["id"]).execute()
    plot = ins("plots", {"farm_id": farm["id"], "plot_code": f"{TAG}-PLOT", "name": TAG, "area_ha": 1})
    seasons = {}
    for status in ("active", "harvested", "closed", "planned"):
        s = ins("crop_seasons", {"plot_id": plot["id"], "season_code": f"{TAG}-{status}", "status": status})
        b = ins("production_batches", {"crop_season_id": s["id"], "batch_code": "default"})
        seasons[status] = {"season": s["id"], "batch": b["id"]}
    devices = {k: ins("devices", {"user_id": v["id"], "installation_id": str(uuid.uuid4()), "platform": "android"})["id"] for k, v in u.items()}
    return {"org": org["id"], "users": u, "seasons": seasons, "devices": devices}


def seeded_activity(ctx: dict, status: str) -> str:
    """An activity the owner recorded earlier (service role), with its detail row."""
    a = ins("activities", {"production_batch_id": ctx["seasons"][status]["batch"], "activity_type": "irrigation",
                           "occurred_at": "2026-06-01T00:00:00Z", "recorded_at": "2026-06-01T00:00:00Z",
                           "source": "web", "recorded_by": ctx["users"]["owner"]["id"], "note": TAG})
    ins("irrigation_events", {"activity_id": a["id"], "method": "awd", "water_volume_m3": 1})
    return a["id"]


def call(u: dict, method: str, path: str, *, json=None, params=None, rep=True) -> str:
    headers = {"apikey": PUBLISHABLE, "Authorization": f"Bearer {u['token']}", "Content-Type": "application/json"}
    if rep:
        headers["Prefer"] = "return=representation"
    if params and "on_conflict" in params:
        # What supabase-js/-dart send for `.upsert(...)`.
        headers["Prefer"] = ",".join(filter(None, [headers.get("Prefer"), "resolution=merge-duplicates"]))
    r = httpx.request(method, f"{URL}/rest/v1/{path}", headers=headers, json=json, params=params, timeout=30)
    if r.status_code >= 400:
        body = r.json() if r.content else {}
        return f"DENIED:{body.get('code', r.status_code)}"
    if not rep:
        return "SILENT?" if r.status_code == 204 else "OK"
    data = r.json() if r.content else []
    if isinstance(data, list) and not data:
        return "SILENT"
    return "OK"


def probe(ctx: dict) -> list[tuple[str, str, str]]:
    out = []
    owner = ctx["users"]["owner"]

    def record(name, expected_ok, outcome):
        exp = "OK" if expected_ok else "DENIED"
        out.append((name, exp, outcome))

    def insert_as(u, status):
        return call(u, "POST", "activities", json={
            "production_batch_id": ctx["seasons"][status]["batch"], "activity_type": "irrigation",
            "occurred_at": "2026-06-02T00:00:00Z", "recorded_at": "2026-06-02T00:00:00Z",
            "source": "mobile_offline", "recorded_by": u["id"], "device_id": ctx["devices"][u["label"]],
            "client_event_id": str(uuid.uuid4()), "note": TAG})

    for status in ("active", "harvested", "closed", "planned"):
        ok = status == "active"
        record(f"owner insert activity [{status}]", ok, insert_as(owner, status))
        aid = seeded_activity(ctx, status)
        # Flutter's `updateActivityById`: no representation -> 0 rows looks like success.
        rep = call(owner, "PATCH", "activities", params={"id": f"eq.{aid}"}, json={"note": f"{TAG}-edited"})
        record(f"owner update activity [{status}]", ok, rep)
        record(f"owner upsert detail [{status}]", ok, call(owner, "POST", "irrigation_events", params={"on_conflict": "activity_id"},
               json={"activity_id": aid, "method": "awd", "water_volume_m3": 2}) if True else "")
        # Direct detail deletes are not a client operation (20260926110000):
        # refused in every season; activities are removed via the RPC.
        record(f"owner delete detail [{status}]", False,
               call(owner, "DELETE", "irrigation_events", params={"activity_id": f"eq.{aid}"}))
        # Flutter's ensureDefaultBatch upsert.
        record(f"owner upsert default batch [{status}]", status in ("active", "planned"),
               call(owner, "POST", "production_batches", params={"on_conflict": "crop_season_id,batch_code"},
                    json={"crop_season_id": ctx["seasons"][status]["season"], "batch_code": "default"}))
        record(f"owner soft_delete RPC [{status}]", ok, call(owner, "POST", "rpc/soft_delete_activity", json={"p_activity_id": aid}, rep=False))

    for who in ("former", "viewer", "outsider", "expired_manager"):
        u = ctx["users"][who]
        record(f"{who} insert activity [active]", False, insert_as(u, "active"))
        aid = seeded_activity(ctx, "active")
        # Someone who can READ the row must get an error; someone who cannot
        # read it (outsider, expired manager) matches nothing -- "HIDDEN".
        outcome = call(u, "PATCH", "activities", params={"id": f"eq.{aid}"}, json={"note": "x"})
        if who in ("outsider", "expired_manager"):
            out.append((f"{who} update activity [active]", "HIDDEN", "HIDDEN (0 rows, not readable)" if outcome == "SILENT" else outcome))
        else:
            record(f"{who} update activity [active]", False, outcome)
        record(f"{who} create season", False, call(u, "POST", "crop_seasons", json={
            "plot_id": admin.table("crop_seasons").select("plot_id").eq("id", ctx["seasons"]["active"]["season"]).execute().data[0]["plot_id"],
            "season_code": f"{TAG}-{who}", "status": "active"}))
    return out


def cleanup() -> list[str]:
    """Delete everything under the run tag; returns the steps that failed.

    Discovery queries are protected like the deletes (retried, recorded, never
    raised), so one failed lookup cannot skip the rest of the cleanup."""
    problems: list[str] = []

    def attempt(label, fn, tries=3):
        for i in range(tries):
            try:
                return fn()
            except Exception as exc:  # noqa: BLE001
                last = exc
                time.sleep(2 * (i + 1))
        problems.append(f"{label}: {type(last).__name__}")
        print(f"  cleanup FAILED: {label}: {type(last).__name__}")
        return None

    def rows(label, query):
        return attempt(f"list {label}", lambda: query.execute().data) or []

    t = admin.table
    for org in rows("organizations", t("organizations").select("id").ilike("organization_code", f"{TAG}-%")):
        for farm in rows("farms", t("farms").select("id").eq("cooperative_id", org["id"])):
            for plot in rows("plots", t("plots").select("id").eq("farm_id", farm["id"])):
                for s in rows("crop_seasons", t("crop_seasons").select("id").eq("plot_id", plot["id"])):
                    for b in rows("production_batches", t("production_batches").select("id").eq("crop_season_id", s["id"])):
                        for a in rows("activities", t("activities").select("id").eq("production_batch_id", b["id"])):
                            attempt("delete irrigation_events", t("irrigation_events").delete().eq("activity_id", a["id"]).execute)
                            attempt("delete activities", t("activities").delete().eq("id", a["id"]).execute)
                        attempt("delete production_batches", t("production_batches").delete().eq("id", b["id"]).execute)
                    attempt("delete crop_seasons", t("crop_seasons").delete().eq("id", s["id"]).execute)
                attempt("delete plots", t("plots").delete().eq("id", plot["id"]).execute)
            attempt("delete farm_members", t("farm_members").delete().eq("farm_id", farm["id"]).execute)
            attempt("delete farms", t("farms").delete().eq("id", farm["id"]).execute)
        attempt("delete organization_memberships", t("organization_memberships").delete().eq("organization_id", org["id"]).execute)
        attempt("delete organizations", t("organizations").delete().eq("id", org["id"]).execute)
    for u in attempt("list auth users", lambda: admin.auth.admin.list_users(page=1, per_page=1000)) or []:
        if (u.email or "").startswith(f"{PREFIX.lower()}-{RUN}-"):
            attempt("delete devices", t("devices").delete().eq("user_id", u.id).execute)
            attempt("delete auth user", lambda x=u.id: admin.auth.admin.delete_user(x))
            attempt("delete profiles", t("profiles").delete().eq("id", u.id).execute)
    return problems


def orphan_users() -> list[str] | None:
    """Auth users of this run still present (auth.users is not a counted table)."""
    try:
        users = admin.auth.admin.list_users(page=1, per_page=1000)
    except Exception:  # noqa: BLE001 -- unknown is reported as a failure
        return None
    return [u.id for u in users if (u.email or "").startswith(f"{PREFIX.lower()}-{RUN}-")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--enforce", action="store_true")
    args = ap.parse_args()
    print(f"=== Direct PostgREST lifecycle probe - run {RUN} ===")
    before = snapshot()
    rows: list[tuple[str, str, str]] = []
    try:
        rows = probe(seed())
    finally:
        problems = cleanup()
        time.sleep(1)
        try:
            after = snapshot()
            diff = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
        except Exception as exc:  # noqa: BLE001
            diff = {"row counts": f"could not be re-read ({type(exc).__name__})"}
        orphans = orphan_users()
    mismatches = 0
    print(f"\n{'operation':44} {'expected':9} actual")
    for name, exp, got in rows:
        good = got.startswith(exp)
        mismatches += 0 if good else 1
        print(f"{name:44} {exp:9} {got}{'' if good else '   <-- GAP'}")
    print(f"\ncleanup row counts restored: {not diff} {diff if diff else ''}")
    print(f"cleanup steps failed: {problems or 'none'}")
    print(f"auth users of this run left: {'unknown (list failed)' if orphans is None else (orphans or 'none')}")
    cleanup_ok = not diff and not problems and orphans == []
    if not cleanup_ok:
        print(f"LEFTOVER CHECK NEEDED for run tag {TAG}")
    print(f"{len(rows) - mismatches}/{len(rows)} match the lifecycle contract")
    return 1 if (args.enforce and (mismatches or not cleanup_ok)) else 0


if __name__ == "__main__":
    raise SystemExit(main())

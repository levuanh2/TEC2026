"""Hosted dev UI smoke: the Carbon straw quick-fix persists on a SEEDED record.

Run (backend on :8010 and the Vite dev server on :5173 already up):
    python backend/scripts/hosted_straw_quickfix_smoke.py

Reproduces the 2026-09-19 bug shape exactly: the demo seed writes activities
with `recorded_by` NULL, and the write API used to answer 404 for them, so the
Carbon "Sửa ngay" save never reached `straw_management_events`. The older
`hosted_carbon_quickfix_smoke.py` created its records through the API as the
owner, which is why it passed while real users were blocked.

Seeds an ISOLATED tenant with the service role (never the shared demo farm):

  * season A — methodology complete, and three seed-style records with no
    author: incorporated straw (days + dry matter NULL), fertilizer without
    nitrogen, and a harvest. Readiness: exactly the two straw gaps + nitrogen.
  * season B — methodology complete, a complete seed-style straw record and a
    diesel fuel record. Readiness: only the fuel-factor limitation.

The Playwright spec `farmer-real-straw-quickfix.spec.ts` repairs season A
through the real browser; this script then reads the rows back directly from
Postgres. Everything is deleted in `finally` and table row counts are compared.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from decimal import Decimal
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BACKEND_DIR.parent / "web-dashboard"
sys.path.insert(0, str(BACKEND_DIR))

import httpx  # noqa: E402
import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402
from supabase import create_client  # noqa: E402

from infrastructure.config import load_settings  # noqa: E402

PREFIX = "STRAW-QUICKFIX-SMOKE"
RUN_ID = uuid.uuid4().hex[:8]
TAG = f"{PREFIX}-{RUN_ID}"
EMAIL_PREFIX = f"{PREFIX.lower()}-{RUN_ID}"
API = os.environ.get("QF_API_BASE_URL", "http://127.0.0.1:8010")

settings = load_settings()
URL, SERVICE_KEY = settings.require_supabase()
_, PUBLISHABLE = settings.require_publishable()
DB_URL = settings.supabase_db_url
admin = create_client(URL, SERVICE_KEY)

COUNTED_TABLES = [
    "organizations", "organization_memberships", "profiles", "farms", "farm_members", "plots",
    "crop_seasons", "production_batches", "activities", "fertilizer_applications", "harvest_events",
    "straw_management_events", "fuel_usages", "carbon_calculations", "carbon_breakdowns", "season_recommendations",
]
DETAIL_TABLES = ("irrigation_events", "fertilizer_applications", "harvest_events", "seeding_events",
                 "pesticide_applications", "straw_management_events", "fuel_usages")
METHODOLOGY = {"ipcc_water_regime": "irrigated_continuous_flooding",
               "pre_season_water_regime": "non_flooded_pre_season_lt_180d", "cultivation_days": 100}

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(("PASS" if ok else "FAIL") + f"  {name}" + (f"  ({detail})" if detail and not ok else ""))


def db_one(sql: str, params: tuple = ()):
    with psycopg.connect(DB_URL, row_factory=dict_row) as conn:
        return conn.execute(sql, params).fetchone()


def snapshot() -> dict[str, int]:
    counts = {t: admin.table(t).select("*", count="exact").limit(1).execute().count for t in COUNTED_TABLES}
    counts["auth.users[smoke]"] = db_one("select count(*) as n from auth.users where email like %s", (f"{PREFIX.lower()}-%",))["n"]
    return counts


def insert(table: str, row: dict) -> dict:
    return admin.table(table).insert(row).execute().data[0]


def seeded_activity(batch: str, kind: str, day: str, table: str, detail: dict) -> str:
    """As the demo seed writes it: service role, `recorded_by` NULL."""
    activity = insert("activities", {
        "production_batch_id": batch, "activity_type": kind, "occurred_at": f"2026-06-{day}T00:00:00Z",
        "recorded_at": f"2026-06-{day}T00:00:00Z", "source": "web", "note": TAG,
    })
    insert(table, {"activity_id": activity["id"], **detail})
    return activity["id"]


def seed() -> dict:
    s: dict = {}
    org = insert("organizations", {"organization_code": f"{TAG}-ORG", "name": f"{TAG} org", "organization_type": "cooperative"})
    farm = insert("farms", {"cooperative_id": org["id"], "farm_code": f"{TAG}-FARM", "farm_name": f"{TAG} farm"})
    plot = insert("plots", {"farm_id": farm["id"], "plot_code": f"{TAG}-PLOT", "name": "Thửa rơm", "area_ha": 1.0})
    batches = {}
    for key in ("A", "B"):
        season = insert("crop_seasons", {"plot_id": plot["id"], "season_code": f"{TAG}-{key}", "crop_type": "rice",
                                         "status": "active", **METHODOLOGY})
        s[f"season_{key}"] = season["id"]
        batches[key] = insert("production_batches", {"crop_season_id": season["id"], "batch_code": "default"})["id"]

    s["straw"] = seeded_activity(batches["A"], "straw_management", "01", "straw_management_events",
                                 {"method": "incorporated", "straw_mass_kg": 800})
    s["fertilizer"] = seeded_activity(batches["A"], "fertilizer", "05", "fertilizer_applications",
                                      {"fertilizer_name": "NPK", "amount_kg": 80})
    seeded_activity(batches["A"], "harvest", "20", "harvest_events", {"yield_kg": 6000})
    seeded_activity(batches["B"], "straw_management", "01", "straw_management_events",
                    {"method": "incorporated", "straw_mass_kg": 800, "days_before_cultivation": 20, "dry_matter_fraction": 0.85})
    seeded_activity(batches["B"], "fuel", "03", "fuel_usages", {"fuel_type": "diesel", "amount_liter": 12})
    seeded_activity(batches["B"], "harvest", "20", "harvest_events", {"yield_kg": 6000})

    email = f"{EMAIL_PREFIX}-owner@agricarbon.invalid"
    password = f"QF-{uuid.uuid4().hex}!Aa1"
    user = admin.auth.admin.create_user({"email": email, "password": password, "email_confirm": True}).user
    insert("organization_memberships", {"organization_id": org["id"], "user_id": user.id, "role": "farmer"})
    insert("farm_members", {"farm_id": farm["id"], "user_id": user.id, "farm_role": "owner"})
    s["owner"] = {"id": user.id, "email": email, "password": password}
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


def straw_row(activity_id: str) -> dict:
    return db_one("""select s.days_before_cultivation, s.dry_matter_fraction, s.returned_to_field, s.straw_mass_kg,
                            s.method::text as method, a.recorded_by
                     from public.straw_management_events s join public.activities a on a.id = s.activity_id
                     where s.activity_id = %s""", (activity_id,))


def run(s: dict) -> None:
    token = sign_in(s["owner"])
    owner = {"Authorization": f"Bearer {token}"}
    http = httpx.Client(base_url=API, timeout=120)

    def codes(season: str) -> set[str]:
        body = http.get(f"/v1/crop-seasons/{season}/carbon/readiness", headers=owner).json()
        return {m["code"] for m in body["missing_inputs"] if m["blocking"]}

    before = straw_row(s["straw"])
    check("seeded_straw_is_unattributed_with_both_fields_null",
          before["recorded_by"] is None and before["days_before_cultivation"] is None and before["dry_matter_fraction"] is None,
          str(before))
    check("season_A_readiness_is_two_straw_gaps_plus_nitrogen",
          codes(s["season_A"]) == {"straw_days_before_cultivation", "straw_dry_matter", "fertilizer_nitrogen"},
          str(sorted(codes(s["season_A"]))))
    check("season_B_readiness_is_only_fuel", codes(s["season_B"]) == {"fuel_factor_unverified"},
          str(sorted(codes(s["season_B"]))))

    env = {**os.environ, "REAL_E2E": "true",
           "SQF_SEASON_A": s["season_A"], "SQF_SEASON_B": s["season_B"],
           "SQF_API": API, "SQF_API_TOKEN": token,
           "SQF_STRAW_ID": s["straw"], "SQF_FERTILIZER_ID": s["fertilizer"],
           "SQF_OWNER_EMAIL": s["owner"]["email"], "SQF_OWNER_PASSWORD": s["owner"]["password"]}
    npx = "npx.cmd" if os.name == "nt" else "npx"
    proc = subprocess.run([npx, "playwright", "test", "--config=playwright.real.config.ts",
                           "tests/e2e/farmer-real-straw-quickfix.spec.ts", "--reporter=line", "--workers=1"],
                          cwd=WEB_DIR, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = proc.stdout + proc.stderr
    print("\n".join(line for line in out.splitlines() if line.strip())[-6000:])
    check("playwright_ui_smoke_passed", proc.returncode == 0, f"exit {proc.returncode}")

    after = straw_row(s["straw"])
    print(f"    DB straw_management_events after UI: {after}")
    check("db_days_before_cultivation_persisted", after["days_before_cultivation"] == 20, str(after))
    check("db_dry_matter_fraction_persisted", after["dry_matter_fraction"] == Decimal("0.85"), str(after))
    check("db_returned_to_field_persisted", after["returned_to_field"] is True, str(after))
    check("db_other_straw_fields_untouched", after["method"] == "incorporated" and after["straw_mass_kg"] == Decimal("800"), str(after))
    check("db_edit_did_not_claim_authorship", after["recorded_by"] is None, str(after))
    n = db_one("select nitrogen_percent from public.fertilizer_applications where activity_id = %s", (s["fertilizer"],))
    check("db_fertilizer_nitrogen_persisted", n["nitrogen_percent"] == Decimal("16"), str(n))
    check("season_A_readiness_complete", codes(s["season_A"]) == set(), str(sorted(codes(s["season_A"]))))
    check("season_B_fuel_still_blocks", codes(s["season_B"]) == {"fuel_factor_unverified"}, str(sorted(codes(s["season_B"]))))


def main() -> int:
    print(f"=== Hosted straw quick-fix persistence smoke - run {RUN_ID} ===")
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

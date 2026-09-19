"""Hosted emulator E2E for Flutter Carbon UX parity.

Run (backend on 127.0.0.1:8010, Android emulator `emulator-5554` booted):
    python backend/scripts/hosted_flutter_carbon_parity_e2e.py

Seeds an ISOLATED tenant with the service role -- organization, farm, plot
(1 ha), an active season with NO Carbon methodology, a batch and a throwaway
farm owner -- then runs `app/integration_test/hosted_carbon_parity_test.dart`
on the emulator. The app itself (publishable key + the owner's JWT, no service
role) fills every user-enterable input through its real screens. When the test
prints `SMOKE| WAIT_OFFLINE` / `SMOKE| WAIT_ONLINE` this script cuts / restores
the emulator network with `adb shell svc`. Afterwards the rows are checked
directly in Postgres, and everything is deleted in `finally`.
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
APP_DIR = BACKEND_DIR.parent / "app"
sys.path.insert(0, str(BACKEND_DIR))

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402
from supabase import create_client  # noqa: E402

from infrastructure.config import load_settings  # noqa: E402

PREFIX = "FLUTTER-CARBON-PARITY"
RUN_ID = uuid.uuid4().hex[:8]
TAG = f"{PREFIX}-{RUN_ID}"
EMAIL_PREFIX = f"{PREFIX.lower()}-{RUN_ID}"
DEVICE = os.environ.get("E2E_DEVICE", "emulator-5554")
BACKEND_FOR_EMULATOR = os.environ.get("E2E_BACKEND_BASE_URL", "http://10.0.2.2:8010")

settings = load_settings()
URL, SERVICE_KEY = settings.require_supabase()
_, PUBLISHABLE = settings.require_publishable()
DB_URL = settings.supabase_db_url
admin = create_client(URL, SERVICE_KEY)

COUNTED_TABLES = [
    "organizations", "organization_memberships", "profiles", "farms", "farm_members", "plots",
    "crop_seasons", "production_batches", "activities", "fertilizer_applications", "harvest_events",
    "straw_management_events", "fuel_usages", "carbon_calculations", "carbon_breakdowns", "devices",
]
DETAIL_TABLES = ("irrigation_events", "fertilizer_applications", "harvest_events", "seeding_events",
                 "pesticide_applications", "straw_management_events", "fuel_usages")

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))
    print(("PASS" if ok else "FAIL") + f"  {name}" + (f"  ({detail})" if detail and not ok else ""))


def q(sql: str, params: tuple = ()):
    with psycopg.connect(DB_URL, row_factory=dict_row) as conn:
        return conn.execute(sql, params).fetchall()


def snapshot() -> dict[str, int]:
    counts = {t: admin.table(t).select("*", count="exact").limit(1).execute().count for t in COUNTED_TABLES}
    counts["auth.users[e2e]"] = q("select count(*) as n from auth.users where email like %s", (f"{PREFIX.lower()}-%",))[0]["n"]
    return counts


def insert(table: str, row: dict) -> dict:
    return admin.table(table).insert(row).execute().data[0]


def seed() -> dict:
    s: dict = {}
    org = insert("organizations", {"organization_code": f"{TAG}-ORG", "name": f"{TAG} org", "organization_type": "cooperative"})
    farm = insert("farms", {"cooperative_id": org["id"], "farm_code": f"{TAG}-FARM", "farm_name": f"{TAG} farm"})
    plot = insert("plots", {"farm_id": farm["id"], "plot_code": f"{TAG}-P", "name": "Thửa mobile", "area_ha": 1.0})
    s["season"] = insert("crop_seasons", {"plot_id": plot["id"], "season_code": f"{TAG}-S", "crop_type": "rice", "status": "active"})
    insert("production_batches", {"crop_season_id": s["season"]["id"], "batch_code": "default"})
    email = f"{EMAIL_PREFIX}-owner@agricarbon.invalid"
    password = f"FC-{uuid.uuid4().hex}!Aa1"
    user = admin.auth.admin.create_user({"email": email, "password": password, "email_confirm": True}).user
    insert("organization_memberships", {"organization_id": org["id"], "user_id": user.id, "role": "farmer"})
    insert("farm_members", {"farm_id": farm["id"], "user_id": user.id, "farm_role": "owner"})
    s["owner"] = {"id": user.id, "email": email, "password": password}
    return s


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
    for row in q("select id::text as id from auth.users where email like %s", (f"{EMAIL_PREFIX}-%",)):
        uid = row["id"]
        attempt("devices", lambda x=uid: admin.table("devices").delete().eq("user_id", x).execute())
        attempt("user", lambda x=uid: admin.auth.admin.delete_user(x))
        attempt("profile", lambda x=uid: admin.table("profiles").delete().eq("id", x).execute())


def adb_network(enabled: bool) -> None:
    state = "enable" if enabled else "disable"
    for radio in ("wifi", "data"):
        subprocess.run(["adb", "-s", DEVICE, "shell", "svc", radio, state], check=False, capture_output=True)
    print(f"    [driver] emulator network {state}d")


def run_flutter(s: dict) -> tuple[int, list[str]]:
    flutter = "flutter.bat" if os.name == "nt" else "flutter"
    cmd = [
        flutter, "test", "integration_test/hosted_carbon_parity_test.dart", "-d", DEVICE,
        f"--dart-define=SUPABASE_URL={URL}", f"--dart-define=SUPABASE_PUBLISHABLE_KEY={PUBLISHABLE}",
        f"--dart-define=BACKEND_BASE_URL={BACKEND_FOR_EMULATOR}",
        f"--dart-define=QA_EMAIL={s['owner']['email']}", f"--dart-define=QA_PASSWORD={s['owner']['password']}",
        f"--dart-define=QA_SEASON_ID={s['season']['id']}",
    ]
    smoke: list[str] = []
    proc = subprocess.Popen(cmd, cwd=APP_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    assert proc.stdout is not None
    log_path = Path(os.environ.get("E2E_LOG", str(APP_DIR / "build" / "carbon_parity_e2e.log")))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("w", encoding="utf-8")
    print(f"    [driver] full flutter log: {log_path}")
    for line in proc.stdout:
        line = line.rstrip()
        if "PASSWORD" not in line:
            log_file.write(line + chr(10))
        if "SMOKE|" in line:
            msg = line.split("SMOKE|", 1)[1].strip()
            smoke.append(msg)
            print(f"    [app] {msg}")
            if msg == "WAIT_OFFLINE":
                adb_network(False)
            elif msg == "WAIT_ONLINE":
                adb_network(True)
        elif any(k in line for k in ("EXCEPTION", "Expected:", "Actual:", "Test failed", "Some tests failed",
                                     "All tests passed", "timed out", "Error:")):
            print(f"    {line[:300]}")
    code = proc.wait()
    log_file.close()
    return code, smoke


def verify(s: dict, smoke: list[str]) -> None:
    sid, owner = s["season"]["id"], s["owner"]["id"]
    season = q("""select ipcc_water_regime::text as ipcc, pre_season_water_regime::text as pre, cultivation_days
                  from public.crop_seasons where id = %s""", (sid,))[0]
    check("db_season_methodology_from_the_app",
          season == {"ipcc": "irrigated_multiple_drainage", "pre": "non_flooded_pre_season_lt_180d", "cultivation_days": 105},
          str(season))
    acts = q("""select a.id::text as id, a.activity_type::text as type, a.deleted_at, a.recorded_by::text as recorded_by,
                       a.source::text as source, a.client_event_id::text as ceid
                from public.activities a join public.production_batches b on b.id = a.production_batch_id
                where b.crop_season_id = %s""", (sid,))
    by_type: dict[str, list] = {}
    for a in acts:
        by_type.setdefault(a["type"], []).append(a)
    check("db_one_row_per_client_event", len({a["ceid"] for a in acts}) == len(acts), str(len(acts)))
    check("db_recorded_by_is_the_mobile_user", all(a["recorded_by"] == owner for a in acts), str({a["recorded_by"] for a in acts}))
    check("db_source_is_mobile_offline", all(a["source"] == "mobile_offline" for a in acts), str({a["source"] for a in acts}))
    fert = q("""select f.fertilizer_name, f.nitrogen_percent from public.fertilizer_applications f
                join public.activities a on a.id = f.activity_id join public.production_batches b on b.id = a.production_batch_id
                where b.crop_season_id = %s and a.deleted_at is null order by f.fertilizer_name""", (sid,))
    check("db_fertilizer_nitrogen_quick_fix_and_offline_create",
          [(r["fertilizer_name"], r["nitrogen_percent"]) for r in fert] == [("NPK 16-16-8", Decimal("16")), ("Ure", Decimal("46"))],
          str(fert))
    straw = q("""select s.method::text as method, s.straw_mass_kg, s.dry_matter_fraction, s.days_before_cultivation, s.returned_to_field
                 from public.straw_management_events s join public.activities a on a.id = s.activity_id
                 join public.production_batches b on b.id = a.production_batch_id where b.crop_season_id = %s""", (sid,))
    check("db_straw_quick_fix", len(straw) == 1 and straw[0]["method"] == "incorporated"
          and straw[0]["dry_matter_fraction"] == Decimal("0.85") and straw[0]["days_before_cultivation"] == 20
          and straw[0]["straw_mass_kg"] == Decimal("800") and straw[0]["returned_to_field"] is None, str(straw))
    harvest = q("""select h.yield_kg from public.harvest_events h join public.activities a on a.id = h.activity_id
                   join public.production_batches b on b.id = a.production_batch_id where b.crop_season_id = %s""", (sid,))
    check("db_harvest_denominator_from_mobile", [r["yield_kg"] for r in harvest] == [Decimal("6000")], str(harvest))
    fuel = by_type.get("fuel", [])
    check("db_fuel_soft_deleted_via_rpc", len(fuel) == 1 and fuel[0]["deleted_at"] is not None, str(fuel))
    calcs = q("""select c.id::text as id, c.total_co2e_kg, c.co2e_per_kg,
                        (select count(*) from public.carbon_breakdowns b where b.calculation_id = c.id) as n
                 from public.carbon_calculations c where c.crop_season_id = %s and c.status = 'succeeded'""", (sid,))
    check("db_carbon_calculated_on_the_server_from_the_app",
          len(calcs) >= 1 and all(c["n"] > 0 and c["total_co2e_kg"] > 0 and c["co2e_per_kg"] is not None for c in calcs), str(calcs))
    for marker in ("METHODOLOGY_FIXED", "NITROGEN_FIXED", "STRAW_FIXED", "FUEL_LIMITATION_SHOWN", "CARBON",
                   "REOPEN_OK", "OFFLINE_KEPT_AFTER_RESTART", "ONLINE_SYNCED", "DONE"):
        check(f"app_step_{marker.lower()}", any(m.startswith(marker) for m in smoke))


def main() -> int:
    print(f"=== Hosted Flutter Carbon parity E2E - run {RUN_ID} ===")
    before = snapshot()
    try:
        s = seed()
        code, smoke = run_flutter(s)
        check("flutter_integration_test_passed", code == 0, f"exit {code}")
        verify(s, smoke)
    except Exception as exc:  # noqa: BLE001
        check("e2e_completed_without_exception", False, repr(exc))
    finally:
        adb_network(True)
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

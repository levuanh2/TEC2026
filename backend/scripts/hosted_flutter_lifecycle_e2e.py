"""Flutter emulator + hosted Supabase E2E for the P1 season lifecycle.

Prerequisites: an Android emulator running (`adb devices` shows it), and the
backend on :8010 with this branch (the app reaches it as http://10.0.2.2:8010).

    python backend/scripts/hosted_flutter_lifecycle_e2e.py [--device emulator-5554]

Creates a DISPOSABLE cooperative, farmer, farm and plot with the service role,
runs `app/integration_test/hosted_season_lifecycle_test.dart` on the emulator,
switches the emulator's network off/on with `adb` when the test logs
`SMOKE| WAIT_OFFLINE` / `SMOKE| WAIT_ONLINE`, then checks the database and
deletes everything (row counts compared). Nothing secret is printed.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
APP = BACKEND.parent / "app"
sys.path.insert(0, str(BACKEND))

import psycopg  # noqa: E402
from supabase import create_client  # noqa: E402

from infrastructure.config import load_settings  # noqa: E402

PREFIX = "FLUTTER-LIFECYCLE-E2E"
RUN = uuid.uuid4().hex[:8]
TAG = f"{PREFIX}-{RUN}"
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
settings = load_settings()
URL, SERVICE = settings.require_supabase()
_, PUBLISHABLE = settings.require_publishable()
admin = create_client(URL, SERVICE)
ADB = os.environ.get("ADB", "adb")
COUNTED = ["organizations", "organization_memberships", "profiles", "farms", "farm_members", "plots",
           "crop_seasons", "production_batches", "activities", "irrigation_events", "devices"]
results: list[tuple[str, bool]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok))
    print(("PASS" if ok else "FAIL") + f"  {name}" + (f"  ({detail})" if detail and not ok else ""))


def q(sql: str, params: tuple = ()):
    with psycopg.connect(settings.supabase_db_url) as c, c.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def snapshot() -> dict:
    return {t: admin.table(t).select("*", count="exact").limit(1).execute().count for t in COUNTED}


def seed() -> dict:
    org = admin.table("organizations").insert({"organization_code": f"{TAG}-ORG", "name": TAG, "organization_type": "cooperative"}).execute().data[0]
    email = f"{PREFIX.lower()}-{RUN}-farmer@agricarbon.invalid"
    password = f"Fl-{uuid.uuid4().hex}!A1"
    uid = admin.auth.admin.create_user({"email": email, "password": password, "email_confirm": True}).user.id
    admin.table("organization_memberships").insert({"organization_id": org["id"], "user_id": uid, "role": "farmer"}).execute()
    farm = admin.table("farms").insert({"cooperative_id": org["id"], "farm_code": f"{TAG}-FARM", "farm_name": TAG}).execute().data[0]
    admin.table("farm_members").insert({"farm_id": farm["id"], "user_id": uid, "farm_role": "owner"}).execute()
    plot = admin.table("plots").insert({"farm_id": farm["id"], "plot_code": f"{TAG}-PLOT", "name": TAG, "area_ha": 1}).execute().data[0]
    return {"email": email, "password": password, "plot": plot["id"], "user": uid}


def network(device: str, on: bool) -> None:
    state = "enable" if on else "disable"
    for svc in ("wifi", "data"):
        subprocess.run([ADB, "-s", device, "shell", "svc", svc, state], check=False, capture_output=True)


def run_flutter(s: dict, device: str) -> tuple[bool, str]:
    cmd = ["flutter.bat" if os.name == "nt" else "flutter", "test", "integration_test/hosted_season_lifecycle_test.dart",
           "-d", device,
           "--dart-define", f"SUPABASE_URL={URL}", "--dart-define", f"SUPABASE_PUBLISHABLE_KEY={PUBLISHABLE}",
           "--dart-define", f"QA_EMAIL={s['email']}", "--dart-define", f"QA_PASSWORD={s['password']}",
           "--dart-define", f"PLOT_ID={s['plot']}", "--dart-define", f"TAG={TAG}",
           "--dart-define", "API_BASE_URL=http://10.0.2.2:8010"]
    proc = subprocess.Popen(cmd, cwd=APP, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace")
    lines: list[str] = []

    def pump():
        assert proc.stdout
        for line in proc.stdout:
            line = line.replace(s["password"], "***")
            lines.append(line.rstrip())
            if "SMOKE|" in line or "EXCEPTION" in line or "Expected:" in line or "Actual:" in line:
                print("   " + line.rstrip())
            if "SMOKE| WAIT_OFFLINE" in line:
                network(device, False)
            elif "SMOKE| WAIT_ONLINE" in line:
                network(device, True)

    t = threading.Thread(target=pump, daemon=True)
    t.start()
    code = proc.wait(timeout=1500)
    t.join(timeout=10)
    network(device, True)  # never leave the emulator offline
    season = next((l.split("SEASON_ID=")[1].strip() for l in lines if "SEASON_ID=" in l), "")
    log_path = os.environ.get("FLUTTER_E2E_LOG")
    if log_path:  # full output, password already masked above
        Path(log_path).write_text("\n".join(lines), encoding="utf-8")
    return code == 0, season


def cleanup() -> None:
    def attempt(fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001
            print(f"  cleanup warning: {type(exc).__name__}")

    for org in admin.table("organizations").select("id").ilike("organization_code", f"{TAG}-%").execute().data:
        for farm in admin.table("farms").select("id").eq("cooperative_id", org["id"]).execute().data:
            for plot in admin.table("plots").select("id").eq("farm_id", farm["id"]).execute().data:
                for season in admin.table("crop_seasons").select("id").eq("plot_id", plot["id"]).execute().data:
                    for b in admin.table("production_batches").select("id").eq("crop_season_id", season["id"]).execute().data:
                        for a in admin.table("activities").select("id").eq("production_batch_id", b["id"]).execute().data:
                            attempt(lambda x=a["id"]: admin.table("irrigation_events").delete().eq("activity_id", x).execute())
                            attempt(lambda x=a["id"]: admin.table("activities").delete().eq("id", x).execute())
                        attempt(lambda x=b["id"]: admin.table("production_batches").delete().eq("id", x).execute())
                    attempt(lambda x=season["id"]: admin.table("crop_seasons").delete().eq("id", x).execute())
                attempt(lambda x=plot["id"]: admin.table("plots").delete().eq("id", x).execute())
            attempt(lambda x=farm["id"]: admin.table("farm_members").delete().eq("farm_id", x).execute())
            attempt(lambda x=farm["id"]: admin.table("farms").delete().eq("id", x).execute())
        attempt(lambda x=org["id"]: admin.table("organization_memberships").delete().eq("organization_id", x).execute())
        attempt(lambda x=org["id"]: admin.table("organizations").delete().eq("id", x).execute())
    for (uid,) in q("select id::text from auth.users where email like %s", (f"{PREFIX.lower()}-{RUN}-%",)):
        attempt(lambda x=uid: admin.table("devices").delete().eq("user_id", x).execute())
        attempt(lambda x=uid: admin.auth.admin.delete_user(x))
        attempt(lambda x=uid: admin.table("profiles").delete().eq("id", x).execute())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="emulator-5554")
    args = ap.parse_args()
    print(f"=== Flutter lifecycle E2E - run {RUN} ===")
    before = snapshot()
    try:
        s = seed()
        ok, season = run_flutter(s, args.device)
        check("flutter_integration_test_passed", ok)
        if season:
            status = q("select status::text from public.crop_seasons where id = %s", (season,))
            check("db_season_ended_by_web_path", status == [("harvested",)], str(status))
            batches = q("select batch_code from public.production_batches where crop_season_id = %s", (season,))
            check("db_exactly_one_default_batch", batches == [("default",)], str(batches))
            first = q("select a.production_batch_id::text from public.activities a where a.note = %s and a.deleted_at is null", (f"{TAG}-FIRST",))
            check("db_exactly_one_offline_recorded_activity", len(first) == 1)
            late = q("select count(*) from public.activities where note = %s", (f"{TAG}-LATE",))
            check("db_refused_the_late_activity", late == [(0,)], str(late))
    except Exception as exc:  # noqa: BLE001
        check("e2e_completed_without_exception", False, f"{type(exc).__name__}: {str(exc)[:200]}")
    finally:
        cleanup()
        time.sleep(1)
        after = snapshot()
        diff = {k: (before[k], after[k]) for k in before if before[k] != after[k]}
        check("cleanup_row_counts_restored", not diff, str(diff))
    failed = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

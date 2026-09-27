"""Android configuration + built-APK checks (flutter-android job).

    python scripts/ci/android_check.py                                  # source config only
    python scripts/ci/android_check.py --apk app/build/app/outputs/flutter-apk/app-debug.apk --mode debug

SOURCE (app/android/app)
  RELEASE_DEBUG_SIGNING  the release buildType signs with the DEBUG key -- a release
                         build would look distributable but be debug-signed. Allowed
                         only by the dated exception below while it is unexpired.
  MANIFEST_CLEARTEXT     main network security config / manifest permits cleartext HTTP
  MANIFEST_DEBUGGABLE    android:debuggable set in the main (release) manifest
APK (merged manifest via aapt2, strings from every file in the archive)
  APK_IDENTITY           package id / versionName differ from vn.agricarbon.mobile / pubspec
  APK_BUILD_MODE         debuggable flag does not match --mode (a "debug" artifact must
                         be debuggable, anything else must not)
  APK_EXPORTED           an exported component outside the allowlist, or an exported
                         non-activity without a protecting permission
  APK_PERMISSION         a permission outside the allowlist
  APK_SERVER_SECRET      service_role JWT, sb_secret_ key value, Postgres URL with a
                         password, or QA identity marker inside the APK
(report) allowBackup value -- no product policy yet (docs/CI_PIPELINE.md)
"""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "app" / "android" / "app"
PACKAGE = "vn.agricarbon.mobile"
EXPORTED_ALLOWED = {
    "vn.agricarbon.mobile.MainActivity": "launcher activity",
    "androidx.profileinstaller.ProfileInstallReceiver": "guarded by android.permission.DUMP (signature|privileged)",
}
PERMISSIONS_ALLOWED = {
    "android.permission.INTERNET": "Supabase / FastAPI",
    "android.permission.CAMERA": "CV field photo (image_picker)",
    "android.permission.ACCESS_NETWORK_STATE": "connectivity_plus online/offline",
    f"{PACKAGE}.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION": "AndroidX internal, app-private",
}
# EXC-ANDROID-01 (docs/CI_PIPELINE.md): main still has the Flutter template's
# debug-key release signing; the fail-closed signing work is on the unmerged
# release/agricarbon-flutter-staging-signing branch. Expires -> CI fails.
RELEASE_DEBUG_SIGNING_EXCEPTION_EXPIRES = dt.date(2026, 10, 31)

JWT = re.compile(rb"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
SECRET_KEY = re.compile(rb"sb_secret_[A-Za-z0-9_-]{16,}")
PG_URL = re.compile(rb"postgres(?:ql)?://[^:/\s\"']+:[^@\s\"']+@")
QA_MARKERS = (b"@agricarbon-demo.local", b"@agricarbon-ci.invalid", b"qa-farmer-fw1")

problems: list[str] = []
notes: list[str] = []


def fail(code: str, msg: str) -> None:
    problems.append(f"{code}: {msg}")


def check_source() -> None:
    gradle = (ANDROID / "build.gradle.kts").read_text(encoding="utf-8")
    release = re.search(r"release\s*\{(.*?)\n\s*\}", gradle, re.S)
    if release and 'signingConfigs.getByName("debug")' in release.group(1):
        if dt.date.today() <= RELEASE_DEBUG_SIGNING_EXCEPTION_EXPIRES:
            notes.append(f"EXC-ANDROID-01 active until {RELEASE_DEBUG_SIGNING_EXCEPTION_EXPIRES}: release buildType "
                         "signs with the DEBUG key -- never distribute a release APK built from this config")
        else:
            fail("RELEASE_DEBUG_SIGNING", "release buildType signs with the debug key and EXC-ANDROID-01 has expired")
    manifest = (ANDROID / "src/main/AndroidManifest.xml").read_text(encoding="utf-8")
    nsc = (ANDROID / "src/main/res/xml/network_security_config.xml").read_text(encoding="utf-8")
    if re.search(r'usesCleartextTraffic\s*=\s*"true"', manifest) or 'cleartextTrafficPermitted="true"' in nsc:
        fail("MANIFEST_CLEARTEXT", "the main (release) config permits cleartext HTTP")
    if re.search(r"android:debuggable", manifest):
        fail("MANIFEST_DEBUGGABLE", "android:debuggable must not be set in the main manifest")
    backup = re.search(r'android:allowBackup\s*=\s*"(\w+)"', manifest)
    notes.append(f"allowBackup: {backup.group(1) if backup else 'not set (Android default: backups ON)'}")


def aapt2(args: list[str]) -> str:
    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if not sdk:
        sys.exit("ANDROID_HOME / ANDROID_SDK_ROOT is not set: cannot inspect the APK")
    tools = sorted((Path(sdk) / "build-tools").iterdir(), key=lambda p: [int(x) if x.isdigit() else x for x in re.split(r"[.-]", p.name)])
    exe = tools[-1] / ("aapt2.exe" if os.name == "nt" else "aapt2")
    return subprocess.run([str(exe), *args], check=True, capture_output=True, text=True, encoding="utf-8").stdout


def check_apk(apk: Path, mode: str) -> None:
    if not apk.is_file():
        fail("APK_IDENTITY", f"{apk} does not exist")
        return
    badging = aapt2(["dump", "badging", str(apk)])
    pkg = re.search(r"package: name='([^']+)' versionCode='([^']+)' versionName='([^']+)'", badging)
    pubspec_version = re.search(r"^version:\s*([\w.]+)", (ROOT / "app/pubspec.yaml").read_text(encoding="utf-8"), re.M).group(1)
    if not pkg or pkg.group(1) != PACKAGE or pkg.group(3) != pubspec_version:
        fail("APK_IDENTITY", f"badging {pkg.groups() if pkg else None} != ({PACKAGE}, versionName {pubspec_version})")
    debuggable = "application-debuggable" in badging
    if debuggable != (mode == "debug"):
        fail("APK_BUILD_MODE", f"--mode {mode} but the APK is {'debuggable' if debuggable else 'not debuggable'}")
    for perm in re.findall(r"uses-permission: name='([^']+)'", badging):
        if perm not in PERMISSIONS_ALLOWED:
            fail("APK_PERMISSION", f"{perm} is not on the permission allowlist")
    tree = re.sub(r"\(Raw: [^)]*\)", "", aapt2(["dump", "xmltree", "--file", "AndroidManifest.xml", str(apk)]))
    for kind, body in re.findall(r"E: (activity|service|receiver|provider) \(line=\d+\)(.*?)(?=\n\s*E: (?:activity|service|receiver|provider) |\Z)", tree, re.S):
        name = re.search(r':name\(0x01010003\)="([^"]+)"', body)
        exported = re.search(r":exported\(0x01010010\)=true", body)
        if not exported or not name:
            continue
        if name.group(1) not in EXPORTED_ALLOWED:
            fail("APK_EXPORTED", f"{kind} {name.group(1)} is exported without an allowlist entry")
        elif kind != "activity" and not re.search(r':permission\(0x01010006\)="', body):
            fail("APK_EXPORTED", f"{kind} {name.group(1)} is exported without a protecting permission")
    with zipfile.ZipFile(apk) as z:
        for info in z.infolist():
            data = z.read(info)
            for token in set(JWT.findall(data)):
                try:
                    payload = token.split(b".")[1]
                    role = json.loads(base64.urlsafe_b64decode(payload + b"=" * (-len(payload) % 4))).get("role")
                except ValueError:
                    role = None
                if role == "service_role":
                    fail("APK_SERVER_SECRET", f"service_role JWT in {info.filename}")
            if SECRET_KEY.search(data):
                fail("APK_SERVER_SECRET", f"sb_secret_ key value in {info.filename}")
            if PG_URL.search(data):
                fail("APK_SERVER_SECRET", f"Postgres URL with password in {info.filename}")
            for marker in QA_MARKERS:
                if marker in data:
                    fail("APK_SERVER_SECRET", f"QA identity marker {marker.decode()} in {info.filename}")
    notes.append(f"APK {apk.name}: {pkg.groups() if pkg else '?'}, debuggable={debuggable}, {len(z.infolist())} entries scanned")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apk", type=Path)
    ap.add_argument("--mode", choices=["debug", "release"], default="debug")
    args = ap.parse_args()
    check_source()
    if args.apk:
        check_apk(args.apk, args.mode)
    for n in notes:
        print(f"note: {n}")
    for p in problems:
        print(f"::error title=Android check::{p}")
    print(f"android check: {'FAIL' if problems else 'PASS'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

"""Production-like web build artifact check (web-build job).

    python scripts/ci/web_dist_check.py --dist web-dashboard/dist --api-base https://api.ci.invalid

Fails (stable codes) when the built dist contains:
  DIST_MOCK_DATA        mock fixture ids -- VITE_USE_MOCK_DATA leaked into a real build
  DIST_API_BASE         the configured VITE_API_BASE_URL is absent, or a developer backend
                        address (127.0.0.1/localhost :8000 / :8010) is compiled in
  DIST_SERVER_SECRET    a Supabase secret key value (sb_secret_<key>), a JWT whose payload
                        role is service_role, or a Postgres URL with a password
  DIST_TEST_ARTIFACT    source maps, test/spec/coverage files, QA identity domains
  BUNDLE_GROWTH         entry JS / CSS / total dist grew more than bundle.max_growth_pct
                        over the recorded baseline (policy.json) -- reported always

Library internals are not findings: supabase-js contains the bare "sb_secret_"
prefix check and gotrue's default http://localhost:9999, which is why every rule
matches a VALUE shape, not a keyword. The public publishable/anon key is not a
server secret and is allowed.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POLICY = json.loads((ROOT / "scripts/ci/policy/policy.json").read_text(encoding="utf-8"))
MOCK_IDS = ("farm-demo-01", "plot-demo-01", "crop-demo-01", "act-demo-01")
DEV_API = re.compile(r"https?://(?:127\.0\.0\.1|localhost):(?:8000|8010)\b")
SECRET_KEY = re.compile(r"sb_secret_[A-Za-z0-9_-]{16,}")
JWT = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
PG_URL = re.compile(r"postgres(?:ql)?://[^:/\s\"'`]+:[^@\s\"'`]+@")
QA_MARKERS = ("@agricarbon-demo.local", "@agricarbon-ci.invalid", "qa-farmer-fw1")


def jwt_role(token: str) -> str | None:
    try:
        payload = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))).get("role")
    except (ValueError, json.JSONDecodeError):
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dist", type=Path, required=True)
    ap.add_argument("--api-base", required=True)
    args = ap.parse_args()
    problems: list[str] = []
    files = [p for p in args.dist.rglob("*") if p.is_file()]
    if not files:
        print(f"::error title=Web dist::DIST_MISSING: {args.dist} is empty")
        return 1
    text = {p: p.read_text(encoding="utf-8", errors="replace") for p in files}
    blob = "\n".join(text.values())

    for mock in MOCK_IDS:
        if mock in blob:
            problems.append(f"DIST_MOCK_DATA: mock fixture id {mock!r} is in the build")
    if args.api_base not in blob:
        problems.append(f"DIST_API_BASE: configured API base {args.api_base} was not compiled in")
    for m in sorted(set(DEV_API.findall(blob))):
        problems.append(f"DIST_API_BASE: developer backend address {m} is compiled in")
    if SECRET_KEY.search(blob):
        problems.append("DIST_SERVER_SECRET: a Supabase secret key value (sb_secret_...) is in the build")
    for token in set(JWT.findall(blob)):
        if jwt_role(token) == "service_role":
            problems.append("DIST_SERVER_SECRET: a service_role JWT is in the build")
    if PG_URL.search(blob):
        problems.append("DIST_SERVER_SECRET: a Postgres connection string with a password is in the build")
    for p in files:
        name = p.name
        if name.endswith(".map") or re.search(r"\.(test|spec)\.", name) or "coverage" in p.parts:
            problems.append(f"DIST_TEST_ARTIFACT: {p.relative_to(args.dist)} must not ship")
    for marker in QA_MARKERS:
        if marker in blob:
            problems.append(f"DIST_TEST_ARTIFACT: QA identity marker {marker!r} is in the build")

    b = POLICY["bundle"]
    js = [p for p in files if p.suffix == ".js"]
    css = [p for p in files if p.suffix == ".css"]
    index = text.get(args.dist / "index.html", "")
    entry = [p for p in js if p.name in index] or js
    sizes = {"entry_js_bytes": sum(p.stat().st_size for p in entry), "css_bytes": sum(p.stat().st_size for p in css),
             "total_dist_bytes": sum(p.stat().st_size for p in files)}
    rows = ["### Web dist", "", "| Size | Current | Baseline | Change |", "|---|---|---|---|"]
    for key, now in sizes.items():
        base = b[key]
        growth = 100.0 * (now - base) / base
        rows.append(f"| {key} | {now:,} | {base:,} | {growth:+.1f}% |")
        if growth > b["max_growth_pct"]:
            problems.append(f"BUNDLE_GROWTH: {key} grew {growth:.1f}% (limit {b['max_growth_pct']}%): {base:,} -> {now:,}")
    big = sorted(files, key=lambda p: p.stat().st_size, reverse=True)[:5]
    rows.append("")
    rows += [f"- largest: {p.relative_to(args.dist)} {p.stat().st_size:,} B" for p in big]

    print("\n".join(rows))
    for p in problems:
        print(f"::error title=Web dist::{p}")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write("\n".join(rows + [f"- {p}" for p in problems]) + "\n")
    print(f"web dist: {'FAIL' if problems else 'PASS'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

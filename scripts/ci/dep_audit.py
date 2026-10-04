"""Dependency security gate (dependency-audit job) + dependency diff summary.

    python scripts/ci/dep_audit.py --osv-scanner /path/to/osv-scanner      # audit all three ecosystems
    python scripts/ci/dep_audit.py --diff origin/main                       # summary of dependency changes

Policy (docs/CI_PIPELINE.md, "Dependency security"):
  npm   high/critical fail; moderate/low are reported
  PyPI  pip-audit carries no severity: every advisory fails
  pub   osv-scanner: every advisory fails
An advisory is tolerated only by an entry in policy.json `dependency_exceptions`
with id, package, reason, owner, added and expires (YYYY-MM-DD):
  DEP_ADVISORY               an advisory without a valid exception
  DEP_EXCEPTION_INVALID      an exception missing a field
  DEP_EXCEPTION_EXPIRED      an exception past its expiry date (fails even if unused)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POLICY = json.loads((ROOT / "scripts/ci/policy/policy.json").read_text(encoding="utf-8"))
REQUIRED = ("id", "package", "reason", "owner", "added", "expires")
problems: list[str] = []
report: list[str] = []


def run(cmd: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8")


def exceptions() -> dict[str, dict]:
    valid = {}
    today = dt.date.today()
    for exc in POLICY.get("dependency_exceptions", []):
        missing = [f for f in REQUIRED if not exc.get(f)]
        if missing:
            problems.append(f"DEP_EXCEPTION_INVALID: {exc.get('id', '?')} lacks {missing}")
            continue
        if dt.date.fromisoformat(exc["expires"]) < today:
            problems.append(f"DEP_EXCEPTION_EXPIRED: {exc['id']} ({exc['package']}) expired {exc['expires']}")
            continue
        valid[exc["id"]] = exc
    return valid


def audit(osv: str | None) -> None:
    allowed = exceptions()

    r = run([sys.executable, "-m", "pip_audit", "-r", "backend/requirements.txt", "--format", "json", "--progress-spinner", "off"])
    if r.returncode not in (0, 1) or not r.stdout.strip().startswith("{"):
        problems.append(f"DEP_TOOL_FAILED: pip-audit exited {r.returncode}: {r.stderr[-400:]}")
    else:
        vulns = [(d["name"], d["version"], v["id"]) for d in json.loads(r.stdout)["dependencies"] for v in d.get("vulns", [])]
        report.append(f"PyPI: {len(vulns)} advisory(ies)")
        for name, version, vid in vulns:
            (report if vid in allowed else problems).append(
                f"{'accepted ' + vid if vid in allowed else 'DEP_ADVISORY'}: PyPI {name} {version} {vid}")

    r = run([shutil.which("npm") or "npm", "audit", "--json"], cwd=ROOT / "web-dashboard")
    try:
        data = json.loads(r.stdout)
        counts = data["metadata"]["vulnerabilities"]
        report.append(f"npm: {counts}")
        for name, v in data.get("vulnerabilities", {}).items():
            ids = [str(x.get("source")) for x in v.get("via", []) if isinstance(x, dict)]
            if v["severity"] in ("high", "critical") and not any(i in allowed for i in ids):
                problems.append(f"DEP_ADVISORY: npm {name} {v['severity']} {ids}")
            elif v["severity"] not in ("high", "critical"):
                report.append(f"reported (not failing): npm {name} {v['severity']}")
    except (json.JSONDecodeError, KeyError) as exc:
        problems.append(f"DEP_TOOL_FAILED: npm audit output unreadable ({exc}): {r.stderr[-300:]}")

    if osv:
        r = run([osv, "scan", "source", "--format", "json", "--lockfile", "app/pubspec.lock"])
        if r.returncode not in (0, 1):
            problems.append(f"DEP_TOOL_FAILED: osv-scanner exited {r.returncode}: {r.stderr[-300:]}")
        else:
            vulns = [(p["package"]["name"], v["id"]) for res in json.loads(r.stdout or '{"results": []}').get("results", [])
                     for p in res.get("packages", []) for v in p.get("vulnerabilities", [])]
            report.append(f"pub: {len(vulns)} advisory(ies)")
            for name, vid in vulns:
                (report if vid in allowed else problems).append(
                    f"{'accepted ' + vid if vid in allowed else 'DEP_ADVISORY'}: pub {name} {vid}")
    else:
        problems.append("DEP_TOOL_FAILED: --osv-scanner is required for the pub audit")


def lock_versions(text: str, kind: str) -> dict[str, str]:
    if not text:
        return {}
    if kind == "npm":
        pk = json.loads(text).get("packages", {})
        return {k.split("node_modules/")[-1]: v.get("version", "") for k, v in pk.items() if k}
    if kind == "pub":
        return dict(re.findall(r"^  ([\w-]+):\n(?:    .*\n)*?    version: \"([^\"]+)\"", text, re.M))
    return {re.split(r"[\[<>=!~ ;]", l, 1)[0].lower(): l.strip() for l in text.splitlines()
            if l.strip() and not l.lstrip().startswith(("#", "-"))}


def diff(base: str) -> None:
    rows = ["### Dependency changes vs " + base, ""]
    for path, kind in (("web-dashboard/package-lock.json", "npm"), ("app/pubspec.lock", "pub"),
                       ("backend/requirements.txt", "pip"), ("backend/constraints.txt", "pip"),
                       ("ml/requirements.txt", "pip")):
        old = run(["git", "show", f"{base}:{path}"]).stdout
        new = (ROOT / path).read_text(encoding="utf-8") if (ROOT / path).exists() else ""
        o, n = lock_versions(old, kind), lock_versions(new, kind)
        added = sorted(set(n) - set(o))
        removed = sorted(set(o) - set(n))
        changed = sorted(k for k in set(o) & set(n) if o[k] != n[k])
        if added or removed or changed:
            rows.append(f"**{path}**: +{len(added)} / -{len(removed)} / ~{len(changed)}")
            rows += [f"- added `{k}` {n[k]}" for k in added[:40]]
            rows += [f"- removed `{k}` {o[k]}" for k in removed[:40]]
            rows += [f"- `{k}`: {o[k]} -> {n[k]}" for k in changed[:40]]
    direct = ROOT / "web-dashboard/package.json"
    old_pkg = run(["git", "show", f"{base}:web-dashboard/package.json"]).stdout
    if old_pkg:
        od, nd = json.loads(old_pkg).get("dependencies", {}), json.loads(direct.read_text(encoding="utf-8")).get("dependencies", {})
        for k in sorted(set(nd) - set(od)):
            rows.append(f"- **NEW DIRECT RUNTIME DEPENDENCY (web)**: `{k}` {nd[k]}")
    if len(rows) == 2:
        rows.append("no dependency changes")
    print("\n".join(rows))
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write("\n".join(rows) + "\n")


DRIFT_BASELINE = ROOT / "backend/constraints.txt"


def drift(freeze: Path, strict: bool) -> int:
    """backend/requirements.txt applies backend/constraints.txt, the exact tested
    set. Compare the clean venv's `pip freeze` with it: a difference means the
    lock is incomplete or out of date (a package it does not pin, or a pin pip
    could not honour). Both PR CI and strict CI pass --strict (DEP_DRIFT fails)."""
    def parse(text: str) -> dict[str, str]:  # PEP 503 names: `PyJWT` and `pyjwt` are one package
        pins = (l.split("#", 1)[0].strip().split("==", 1) for l in text.splitlines() if "==" in l.split("#", 1)[0])
        return {re.sub(r"[-_.]+", "-", name).lower(): version for name, version in pins}
    now = parse(freeze.read_text(encoding="utf-8"))
    if not DRIFT_BASELINE.is_file():
        msg = f"DEP_DRIFT: no baseline {DRIFT_BASELINE.relative_to(ROOT)}; commit this freeze as the baseline"
        print(f"::{'error' if strict else 'warning'} title=Dependency drift::{msg}")
        return 1 if strict else 0
    base = parse(DRIFT_BASELINE.read_text(encoding="utf-8"))
    changes = [f"{k}: {base.get(k, '-')} -> {now.get(k, '-')}" for k in sorted(set(base) | set(now)) if base.get(k) != now.get(k)]
    for c in changes:
        print(f"resolved change: {c}")
    if changes:
        msg = (f"DEP_DRIFT: {len(changes)} installed backend package version(s) differ from backend/constraints.txt "
               "-- the lock must pin the whole tested set; update it deliberately in a PR (docs/CI_PIPELINE.md)")
        print(f"::{'error' if strict else 'warning'} title=Dependency drift::{msg}")
        return 1 if strict else 0
    print(f"installed backend dependencies match backend/constraints.txt ({len(now)} packages)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--osv-scanner")
    ap.add_argument("--diff")
    ap.add_argument("--drift", type=Path, help="pip freeze of the clean backend venv")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()
    if args.diff:
        diff(args.diff)
        return 0
    if args.drift:
        return drift(args.drift, args.strict)
    audit(args.osv_scanner)
    for line in report:
        print(line)
    for p in problems:
        print(f"::error title=Dependency audit::{p}")
    print(f"dependency audit: {'FAIL' if problems else 'PASS'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

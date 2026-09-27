"""Coverage no-regression, critical-module and changed-line gates.

    python scripts/ci/coverage_gate.py --layer backend --report backend/reports/backend-coverage.xml --base-ref origin/main
    python scripts/ci/coverage_gate.py --layer web --report web-dashboard/coverage/lcov.info --base-ref origin/main
    python scripts/ci/coverage_gate.py --layer flutter --report app/coverage/lcov.info --base-ref origin/main

The BASELINE is read from the base ref's scripts/ci/policy/policy.json when
--base-ref is given (a PR cannot lower its own bar); without it (push to main,
local runs) from the working tree.

  COVERAGE_REGRESSION           layer line coverage < baseline - tolerance_pp
  CRITICAL_COVERAGE_REGRESSION  (backend) a critical module < its baseline - tolerance_pp,
                                or a critical module has no coverage data (renamed/removed
                                without a policy update)
  CHANGED_CODE_COVERAGE         (with --base-ref) executable lines added/modified in this
                                change are covered < changed_lines_min %

Reports: Cobertura XML (backend, paths relative to backend/) or lcov (web paths
relative to web-dashboard/, Flutter paths relative to app/).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PREFIX = {"backend": "backend/", "web": "web-dashboard/", "flutter": "app/"}


def load_policy(base_ref: str | None) -> tuple[dict, str]:
    if base_ref:
        r = subprocess.run(["git", "show", f"{base_ref}:scripts/ci/policy/policy.json"], cwd=ROOT,
                           capture_output=True, text=True, encoding="utf-8")
        if r.returncode == 0:
            return json.loads(r.stdout), f"{base_ref} (trusted base)"
        print(f"no policy.json on {base_ref}; using the working tree (first introduction)")
    return json.loads((ROOT / "scripts/ci/policy/policy.json").read_text(encoding="utf-8")), "working tree"


def line_hits(layer: str, report: Path) -> dict[str, dict[int, int]]:
    """{repo-relative file: {line: hits}} for executable lines."""
    out: dict[str, dict[int, int]] = defaultdict(dict)
    prefix = PREFIX[layer]
    if report.suffix == ".xml":
        for cls in ET.parse(report).getroot().iter("class"):
            f = prefix + cls.get("filename").replace("\\", "/")
            for ln in cls.iter("line"):
                out[f][int(ln.get("number"))] = int(ln.get("hits"))
    else:
        current = None
        for raw in report.read_text(encoding="utf-8").splitlines():
            if raw.startswith("SF:"):
                path = raw[3:].replace("\\", "/")
                # lcov may carry absolute paths; keep the part from the layer dir on.
                marker = prefix.rstrip("/") + "/"
                current = path[path.index(marker):] if marker in path else prefix + path.lstrip("./")
            elif raw.startswith("DA:") and current:
                n, hits = raw[3:].split(",")[:2]
                out[current][int(n)] = int(hits)
    return out


def pct(lines: dict[int, int]) -> float:
    return 100.0 * sum(1 for h in lines.values() if h > 0) / len(lines) if lines else 100.0


def changed_lines(base_ref: str, prefix: str) -> dict[str, set[int]]:
    diff = subprocess.run(["git", "diff", "-U0", "--diff-filter=AM", f"{base_ref}...HEAD", "--", prefix],
                          cwd=ROOT, check=True, capture_output=True, text=True, encoding="utf-8").stdout
    out: dict[str, set[int]] = defaultdict(set)
    current = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@") and current:
            m = re.search(r"\+(\d+)(?:,(\d+))?", line)
            start, count = int(m.group(1)), int(m.group(2) or 1)
            out[current].update(range(start, start + count))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--layer", choices=PREFIX, required=True)
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--base-ref")
    args = ap.parse_args()
    policy, source = load_policy(args.base_ref)
    cov = policy["coverage"]
    tol = cov["tolerance_pp"]
    problems: list[str] = []
    rows = [f"### Coverage: {args.layer} (baseline from {source}, tolerance {tol} pp)", "",
            "| Scope | Current | Baseline | Result |", "|---|---|---|---|"]

    if not args.report.is_file():
        print(f"::error title=Coverage {args.layer}::REPORT_MISSING: {args.report}")
        return 1
    hits = line_hits(args.layer, args.report)
    all_lines = {(f, n): h for f, lines in hits.items() for n, h in lines.items()}
    total = 100.0 * sum(1 for h in all_lines.values() if h > 0) / len(all_lines) if all_lines else 0.0
    base = cov["baseline"][args.layer]
    ok = total >= base - tol
    rows.append(f"| {args.layer} total | {total:.2f}% | {base:.2f}% | {'PASS' if ok else 'FAIL'} |")
    if not ok:
        problems.append(f"COVERAGE_REGRESSION: {args.layer} {total:.2f}% < baseline {base:.2f}% - {tol} pp")

    if args.layer == "backend":
        for module, mbase in cov["critical_backend"].items():
            lines = hits.get("backend/" + module)
            if lines is None:
                problems.append(f"CRITICAL_COVERAGE_REGRESSION: no coverage data for critical module {module}")
                rows.append(f"| {module} | missing | {mbase:.1f}% | FAIL |")
                continue
            mp = pct(lines)
            mok = mp >= mbase - tol
            rows.append(f"| {module} | {mp:.1f}% | {mbase:.1f}% | {'PASS' if mok else 'FAIL'} |")
            if not mok:
                problems.append(f"CRITICAL_COVERAGE_REGRESSION: {module} {mp:.1f}% < {mbase:.1f}% - {tol} pp")

    if args.base_ref:
        changed = changed_lines(args.base_ref, PREFIX[args.layer])
        exe = {(f, n): hits[f][n] for f, ns in changed.items() if f in hits for n in ns if n in hits[f]}
        if exe:
            cp = 100.0 * sum(1 for h in exe.values() if h > 0) / len(exe)
            cok = cp >= cov["changed_lines_min"]
            rows.append(f"| changed executable lines ({len(exe)}) | {cp:.1f}% | >= {cov['changed_lines_min']}% "
                        f"| {'PASS' if cok else 'FAIL'} |")
            if not cok:
                missed = sorted(f"{f}:{n}" for (f, n), h in exe.items() if h == 0)
                problems.append(f"CHANGED_CODE_COVERAGE: {cp:.1f}% of {len(exe)} changed executable lines covered, "
                                f"minimum {cov['changed_lines_min']}% -- uncovered: {', '.join(missed[:40])}")
        else:
            rows.append("| changed executable lines | none | - | PASS |")

    print("\n".join(rows))
    for p in problems:
        print(f"::error title=Coverage {args.layer}::{p}")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write("\n".join(rows + [f"- {p}" for p in problems]) + "\n")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

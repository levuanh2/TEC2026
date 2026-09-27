"""Summarise one test report and enforce discovery floors + the skip budget.

    python scripts/ci/ci_report.py --label "Backend unit" --junit reports/backend.xml \
        --floor backend --skips backend-unit
    python scripts/ci/ci_report.py --label "Flutter" --flutter-json reports/flutter.json \
        --floor flutter --skips flutter --coverage coverage/lcov.info
    python scripts/ci/ci_report.py --label "P0 security" --probe-log p0.log --probe p0_security

Floors, skip allowlists and probe minimums live in scripts/ci/policy/policy.json.
Exit 1 (with a stable code) when:

  REPORT_MISSING            the report is missing or unreadable (a crashed runner is not green)
  TESTS_FAILED              any test failed or errored (incl. suite-level import errors)
  TEST_DISCOVERY_REGRESSION fewer tests than the policy floor were discovered
  UNEXPECTED_SKIP           a skipped / xfail / todo / fixme test is not on the exact
                            allowlist -- entries are `reason:<exact skip reason>` or
                            `test:<exact test id>`; nothing fuzzy. Fewer skips than
                            allowed is fine (a gated test that became runnable).
  PROBE_REGRESSION          a security probe reported fewer checks than its minimum,
                            or not all of them passed, or printed no result line

Standard library only: it runs before any project dependency is installed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

POLICY = json.loads((Path(__file__).resolve().parent / "policy" / "policy.json").read_text(encoding="utf-8"))
Skip = tuple  # (test id, reason)


def junit_counts(path: Path) -> tuple[Counter, list[Skip]]:
    root = ET.parse(path).getroot()
    counts: Counter = Counter()
    skipped: list[Skip] = []
    for case in root.iter("testcase"):
        test_id = f"{case.get('classname', '')}::{case.get('name', '')}"
        if case.find("failure") is not None or case.find("error") is not None:
            counts["failed"] += 1
        elif case.find("skipped") is not None:
            counts["skipped"] += 1
            node = case.find("skipped")
            skipped.append((test_id, (node.get("message") or node.text or "").strip()))
        else:
            counts["passed"] += 1
    # A suite that fails to import reports an <error> on the suite, not a case.
    for suite in root.iter("testsuite"):
        if suite.find("error") is not None:
            counts["failed"] += 1
    return counts, skipped


def flutter_counts(path: Path) -> tuple[Counter, list[Skip]]:
    names: dict[int, str] = {}
    counts: Counter = Counter()
    skipped: list[Skip] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        event = json.loads(line)
        if event.get("type") == "testStart":
            names[event["test"]["id"]] = event["test"].get("name", "")
        elif event.get("type") == "testDone" and not event.get("hidden"):
            if event.get("skipped"):
                counts["skipped"] += 1
                skipped.append((names.get(event["testID"], str(event["testID"])), ""))
            elif event.get("result") == "success":
                counts["passed"] += 1
            else:
                counts["failed"] += 1
        elif event.get("type") == "done" and event.get("success") is False and not counts["failed"]:
            # Load/compile errors end the run without a failing testDone.
            counts["failed"] += 1
    return counts, skipped


def line_coverage(path: Path) -> str:
    """Line coverage % from Cobertura XML, lcov, or a Vitest json-summary (display only)."""
    if not path.is_file():
        return "n/a"
    if path.suffix == ".xml":
        return f"{float(ET.parse(path).getroot().get('line-rate', 0)) * 100:.2f}%"
    if path.suffix == ".json":
        return f"{json.loads(path.read_text(encoding='utf-8'))['total']['lines']['pct']:.2f}%"
    found = hit = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("LF:"):
            found += int(line[3:])
        elif line.startswith("LH:"):
            hit += int(line[3:])
    return f"{hit / found * 100:.2f}%" if found else "n/a"


def allowed(skip: Skip, allowlist: list[str]) -> bool:
    test_id, reason = skip
    return any((e.startswith("reason:") and reason == e[7:]) or (e.startswith("test:") and test_id == e[5:])
               for e in allowlist)


def summary(rows: list[str]) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\n".join(rows) + "\n")


def probe(args) -> int:
    minimum = POLICY["probe_minimums"][args.probe]
    text = args.probe_log.read_text(encoding="utf-8") if args.probe_log.is_file() else ""
    results = re.findall(r"(\d+)/(\d+) (?:checks passed|match the lifecycle contract)", text)
    problems = []
    if not results:
        problems.append(f"PROBE_REGRESSION: {args.probe} printed no result line (did it run?)")
    else:
        passed, total = map(int, results[-1])
        if total < minimum:
            problems.append(f"PROBE_REGRESSION: {args.probe} ran {total} checks, minimum is {minimum}")
        if passed != total:
            problems.append(f"PROBE_REGRESSION: {args.probe} passed {passed}/{total}")
    status = "FAIL" if problems else "PASS"
    shown = "/".join(results[-1]) if results else "none"
    print(f"{args.label}: {status} -- {shown} (minimum {minimum})")
    for p in problems:
        print(f"::error title={args.label}::{p}")
    summary([f"| {args.label} | {status} | {shown} checks (min {minimum}) |"])
    return 1 if problems else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--junit", type=Path)
    src.add_argument("--flutter-json", type=Path)
    src.add_argument("--probe-log", type=Path)
    ap.add_argument("--floor", help="key in policy test_floors")
    ap.add_argument("--skips", help="key in policy skip_allowlist")
    ap.add_argument("--probe", help="key in policy probe_minimums")
    ap.add_argument("--coverage", type=Path, help="Cobertura .xml, lcov .info or Vitest json-summary .json")
    args = ap.parse_args()
    if args.probe_log:
        return probe(args)
    if not args.floor or args.skips is None:
        ap.error("--floor and --skips are required for test reports")

    path = args.junit or args.flutter_json
    problems: list[str] = []
    counts: Counter = Counter()
    skipped: list[Skip] = []
    if not path.is_file():
        problems.append(f"REPORT_MISSING: {path} was not written")
    else:
        try:
            counts, skipped = junit_counts(path) if args.junit else flutter_counts(path)
        except (ET.ParseError, json.JSONDecodeError, KeyError) as exc:
            problems.append(f"REPORT_MISSING: {path} is unreadable: {exc}")

    total = sum(counts.values())
    floor = POLICY["test_floors"][args.floor]
    allowlist = POLICY["skip_allowlist"][args.skips]
    unexpected = [s for s in skipped if not allowed(s, allowlist)]
    if counts["failed"]:
        problems.append(f"TESTS_FAILED: {counts['failed']} failed")
    if total < floor:
        problems.append(f"TEST_DISCOVERY_REGRESSION: {total} tests discovered, policy floor is {floor}")
    if unexpected:
        problems.append(f"UNEXPECTED_SKIP: {len(unexpected)} skip(s) not on the '{args.skips}' allowlist")

    status = "FAIL" if problems else "PASS"
    coverage = line_coverage(args.coverage) if args.coverage else "-"
    print(f"{args.label}: {status} -- total {total} (floor {floor}), passed {counts['passed']}, "
          f"failed {counts['failed']}, skipped {counts['skipped']} (allowed {counts['skipped'] - len(unexpected)}, "
          f"unexpected {len(unexpected)}), line coverage {coverage}")
    for p in problems:
        print(f"::error title={args.label}::{p}")
    for test_id, reason in unexpected[:50]:
        print(f"  unexpected skip: {test_id} -- {reason!r}")
    summary(["| Suite | Result | Total (floor) | Passed | Failed | Skipped (unexpected) | Line coverage |",
             "|---|---|---|---|---|---|---|",
             f"| {args.label} | {status} | {total} ({floor}) | {counts['passed']} | {counts['failed']} "
             f"| {counts['skipped']} ({len(unexpected)}) | {coverage} |"] + [f"- {p}" for p in problems])
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

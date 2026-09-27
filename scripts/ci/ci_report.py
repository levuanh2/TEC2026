"""Summarise one test report for CI and guard against lost test discovery.

    python scripts/ci/ci_report.py --label "Backend unit" --junit reports/backend.xml --min-total 700
    python scripts/ci/ci_report.py --label "Flutter" --flutter-json reports/flutter.json --min-total 360

Reads a JUnit XML file (pytest, Vitest, Playwright) or the event stream written
by `flutter test --file-reporter json:<path>`, prints passed/failed/skipped,
appends one Markdown row to $GITHUB_STEP_SUMMARY, and exits 1 when:

* the report is missing or unreadable (a crashed runner must not look green),
* any test failed or errored,
* fewer than --min-total tests were discovered (a floor well under the current
  count -- it catches a broken glob or import, it is not a target),
* more than --max-skipped tests were skipped (used where every opt-in test is
  expected to run, e.g. the backend suite against the CI database).

Standard library only: it runs before any project dependency is installed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path


def junit_counts(path: Path) -> tuple[Counter, list[str]]:
    root = ET.parse(path).getroot()
    counts: Counter = Counter()
    skipped: list[str] = []
    for case in root.iter("testcase"):
        name = f"{case.get('classname', '')}::{case.get('name', '')}"
        if case.find("failure") is not None or case.find("error") is not None:
            counts["failed"] += 1
        elif case.find("skipped") is not None:
            counts["skipped"] += 1
            reason = case.find("skipped").get("message") or ""
            skipped.append(f"{name} -- {reason}".strip(" -"))
        else:
            counts["passed"] += 1
    # A suite that fails to import reports an <error> on the suite, not a case.
    for suite in root.iter("testsuite"):
        if suite.find("error") is not None:
            counts["failed"] += 1
    return counts, skipped


def flutter_counts(path: Path) -> tuple[Counter, list[str]]:
    names: dict[int, str] = {}
    counts: Counter = Counter()
    skipped: list[str] = []
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
                skipped.append(names.get(event["testID"], str(event["testID"])))
            elif event.get("result") == "success":
                counts["passed"] += 1
            else:
                counts["failed"] += 1
        elif event.get("type") == "done" and event.get("success") is False and not counts["failed"]:
            # Load/compile errors end the run without a failing testDone.
            counts["failed"] += 1
    return counts, skipped


def line_coverage(path: Path) -> str:
    """Line coverage % from Cobertura XML, lcov, or a Vitest json-summary.

    Reported only -- there is no threshold until a baseline is agreed
    (docs/CI_PIPELINE.md, "Coverage").
    """
    if not path.is_file():
        return "n/a"
    if path.suffix == ".xml":
        return f"{float(ET.parse(path).getroot().get('line-rate', 0)) * 100:.1f}%"
    if path.suffix == ".json":
        return f"{json.loads(path.read_text(encoding='utf-8'))['total']['lines']['pct']:.1f}%"
    found = hit = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("LF:"):
            found += int(line[3:])
        elif line.startswith("LH:"):
            hit += int(line[3:])
    return f"{hit / found * 100:.1f}%" if found else "n/a"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--junit", type=Path)
    src.add_argument("--flutter-json", type=Path)
    ap.add_argument("--min-total", type=int, default=1)
    ap.add_argument("--max-skipped", type=int, default=None)
    ap.add_argument("--coverage", type=Path, help="Cobertura .xml, lcov .info or Vitest json-summary .json")
    args = ap.parse_args()

    path = args.junit or args.flutter_json
    problems: list[str] = []
    counts: Counter = Counter()
    skipped: list[str] = []
    if not path.is_file():
        problems.append(f"report {path} was not written")
    else:
        try:
            counts, skipped = junit_counts(path) if args.junit else flutter_counts(path)
        except (ET.ParseError, json.JSONDecodeError, KeyError) as exc:
            problems.append(f"report {path} is unreadable: {exc}")

    total = sum(counts.values())
    if counts["failed"]:
        problems.append(f"{counts['failed']} failed")
    if total < args.min_total:
        problems.append(f"only {total} tests discovered, floor is {args.min_total} -- did discovery break?")
    if args.max_skipped is not None and counts["skipped"] > args.max_skipped:
        problems.append(f"{counts['skipped']} skipped, at most {args.max_skipped} allowed")

    status = "FAIL" if problems else "PASS"
    coverage = line_coverage(args.coverage) if args.coverage else "-"
    print(f"{args.label}: {status} -- total {total}, passed {counts['passed']}, "
          f"failed {counts['failed']}, skipped {counts['skipped']}, line coverage {coverage}")
    for problem in problems:
        print(f"::error title={args.label}::{problem}")
    if skipped and (args.max_skipped is not None or len(skipped) <= 20):
        print("skipped:\n  " + "\n  ".join(skipped[:50]))

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("| Suite | Result | Total | Passed | Failed | Skipped | Line coverage |\n|---|---|---|---|---|---|---|\n")
            fh.write(f"| {args.label} | {status} | {total} | {counts['passed']} | {counts['failed']} "
                     f"| {counts['skipped']} | {coverage} |\n")
            if problems:
                fh.write("\n" + "\n".join(f"- {p}" for p in problems) + "\n")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

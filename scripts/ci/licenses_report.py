"""License inventory of production dependencies (strict-ci, report only).

    <venv>/bin/python scripts/ci/licenses_report.py --npm-lock web-dashboard/package-lock.json

Python: every distribution installed in THIS interpreter's environment (run it
with the clean requirements.txt venv). npm: non-dev packages in the lockfile.
Flags GPL/AGPL/LGPL/SSPL and unknown licenses for review. There is no project
license policy yet (docs/CI_PIPELINE.md) -- this never fails the build.
"""
from __future__ import annotations

import argparse
import importlib.metadata as md
import json
import os
import re
from pathlib import Path

FLAG = re.compile(r"\b(A?GPL|LGPL|SSPL|EUPL)\b", re.I)


def py_license(dist: md.Distribution) -> str:
    meta = dist.metadata
    expr = meta.get("License-Expression") or ""
    classifiers = [c.split("::")[-1].strip() for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    text = expr or "; ".join(classifiers) or (meta.get("License") or "").splitlines()[0:1]
    return text if isinstance(text, str) else (text[0] if text else "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--npm-lock", type=Path)
    args = ap.parse_args()
    rows, flagged = [], []
    for d in sorted(md.distributions(), key=lambda d: d.metadata["Name"].lower()):
        lic = py_license(d) or "UNKNOWN"
        rows.append(f"pypi {d.metadata['Name']} {d.version}: {lic}")
        if lic == "UNKNOWN" or FLAG.search(lic):
            flagged.append(rows[-1])
    if args.npm_lock:
        for path, p in json.loads(args.npm_lock.read_text(encoding="utf-8")).get("packages", {}).items():
            if not path or p.get("dev"):
                continue
            lic = p.get("license") or "UNKNOWN"
            rows.append(f"npm {path.split('node_modules/')[-1]} {p.get('version')}: {lic}")
            if lic == "UNKNOWN" or FLAG.search(str(lic)):
                flagged.append(rows[-1])
    print("\n".join(rows))
    print(f"\n{len(rows)} production packages; {len(flagged)} flagged for review:")
    print("\n".join(f"  REVIEW {f}" for f in flagged) or "  none")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as fh:
            fh.write(f"### Licenses\n{len(rows)} production packages, {len(flagged)} flagged\n"
                     + "".join(f"- {f}\n" for f in flagged))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

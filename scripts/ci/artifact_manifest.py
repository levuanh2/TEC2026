"""Write ARTIFACT-MANIFEST.json next to an uploaded build artifact.

    python scripts/ci/artifact_manifest.py --mode debug-not-distributable --out app/build/app/outputs/flutter-apk app-debug.apk
    python scripts/ci/artifact_manifest.py --mode web-placeholder-endpoints --out web-dashboard/dist --tree

Records, for every file: path, size, SHA-256; plus the commit SHA, ref, run id
and the build mode, so an artifact from main is traceable to one exact commit
and can never be mistaken for a distributable release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True, help="e.g. debug-not-distributable")
    ap.add_argument("--out", type=Path, required=True, help="directory the artifact files live in")
    ap.add_argument("--tree", action="store_true", help="record every file under --out")
    ap.add_argument("files", nargs="*")
    args = ap.parse_args()
    if "release" in args.mode and "not" not in args.mode:
        sys.exit("refusing: CI never produces a distributable release artifact")
    paths = sorted(p for p in args.out.rglob("*") if p.is_file() and p.name != "ARTIFACT-MANIFEST.json") if args.tree \
        else [args.out / f for f in args.files]
    missing = [str(p) for p in paths if not p.is_file()]
    if missing or not paths:
        sys.exit(f"artifact files missing: {missing or 'none given'}")
    commit = os.environ.get("GITHUB_SHA") or subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                                                             text=True, encoding="utf-8").stdout.strip()
    manifest = {
        "build_mode": args.mode,
        "commit": commit,
        "ref": os.environ.get("GITHUB_REF", "local"),
        "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
        "files": [{"path": p.relative_to(args.out).as_posix(), "bytes": p.stat().st_size, "sha256": sha256(p)} for p in paths],
    }
    (args.out / "ARTIFACT-MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    for f in manifest["files"]:
        print(f"{f['sha256']}  {f['path']}  ({f['bytes']} B, {args.mode}, {commit[:12]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

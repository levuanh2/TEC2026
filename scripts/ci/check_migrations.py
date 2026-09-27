"""Static checks for supabase/migrations -- no database needed.

    python scripts/ci/check_migrations.py                      # naming/order/content
    python scripts/ci/check_migrations.py --base-ref origin/main   # + history rules for a PR

Fails when:
* a file is not `<14-digit version>_<snake_name>.sql`, or two files share a version;
* a file is empty or not UTF-8;
* (with --base-ref) a migration that already exists on the base branch was
  edited, renamed or deleted -- hosted databases record applied versions, so a
  changed file is never re-run and silently diverges;
* (with --base-ref) a new migration's version sorts at or before the newest
  one on the base branch -- `supabase db push` would refuse it or apply it out
  of order.

CHECKSUM MANIFEST (scripts/ci/policy/migrations.sha256, sha256 over LF-normalised
bytes so Windows checkouts agree):
* MIGRATION_MODIFIED     a registered file's content changed (comments included --
                         nothing is canonicalised);
* MIGRATION_DELETED      a registered file is gone;
* MIGRATION_UNREGISTERED a file is not in the manifest (register new ones with
                         --register-new, which only ever APPENDS);
* MANIFEST_REWRITTEN     (with --base-ref) an entry that exists on the base changed or
                         disappeared -- rewriting the manifest cannot launder an edit.

The clean apply of every migration from an empty database is done separately
by the Supabase CI stack (`supabase start`), which stops at the first failing file.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DIR = "supabase/migrations"
NAME = re.compile(r"^(\d{14})_[a-z0-9_]+\.sql$")
MANIFEST = "scripts/ci/policy/migrations.sha256"


def digest(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def parse_manifest(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        if line.strip() and not line.startswith("#"):
            sha, name = line.split(None, 1)
            out[name.strip()] = sha
    return out


def base_files(ref: str) -> dict[str, str]:
    """{filename: blob sha} of the migrations on the base ref."""
    out = subprocess.run(["git", "ls-tree", ref, f"{DIR}/"], cwd=ROOT, check=True,
                         capture_output=True, text=True, encoding="utf-8").stdout
    files = {}
    for line in out.splitlines():
        meta, path = line.split("\t", 1)
        files[Path(path).name] = meta.split()[2]
    return files


def head_blob(name: str) -> str:
    return subprocess.run(["git", "hash-object", f"{DIR}/{name}"], cwd=ROOT, check=True,
                          capture_output=True, text=True, encoding="utf-8").stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-ref")
    ap.add_argument("--register-new", action="store_true", help="append unregistered files to the manifest")
    args = ap.parse_args()

    errors: list[str] = []
    files = sorted(p for p in (ROOT / DIR).iterdir() if p.is_file())
    versions: dict[str, str] = {}
    for path in files:
        m = NAME.match(path.name)
        if not m:
            errors.append(f"{path.name}: name must be <YYYYMMDDHHMMSS>_<snake_case>.sql")
            continue
        if m.group(1) in versions:
            errors.append(f"{path.name}: version {m.group(1)} already used by {versions[m.group(1)]}")
        versions[m.group(1)] = path.name
        try:
            if not path.read_text(encoding="utf-8").strip():
                errors.append(f"{path.name}: empty migration")
        except UnicodeDecodeError:
            errors.append(f"{path.name}: not UTF-8")

    manifest_path = ROOT / MANIFEST
    manifest = parse_manifest(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    if args.register_new:
        new = [p for p in files if p.name not in manifest]
        with manifest_path.open("a", encoding="utf-8", newline="\n") as fh:
            for p in new:
                fh.write(f"{digest(p.read_bytes())}  {p.name}\n")
        print(f"registered {len(new)} new migration(s): {[p.name for p in new]}")
        return 0
    on_disk = {p.name: digest(p.read_bytes()) for p in files}
    for name, sha in sorted(manifest.items()):
        if name not in on_disk:
            errors.append(f"MIGRATION_DELETED: {name} is registered in {MANIFEST} but missing")
        elif on_disk[name] != sha:
            errors.append(f"MIGRATION_MODIFIED: {name} no longer matches its registered checksum -- "
                          "applied migrations are immutable; add a new migration instead")
    for name in sorted(set(on_disk) - set(manifest)):
        errors.append(f"MIGRATION_UNREGISTERED: {name} is not in {MANIFEST} "
                      "(run: python scripts/ci/check_migrations.py --register-new)")

    if args.base_ref:
        r = subprocess.run(["git", "show", f"{args.base_ref}:{MANIFEST}"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        if r.returncode == 0:
            for name, sha in sorted(parse_manifest(r.stdout).items()):
                if manifest.get(name) != sha:
                    errors.append(f"MANIFEST_REWRITTEN: entry for {name} changed or was removed vs {args.base_ref}")
        base = base_files(args.base_ref)
        current = {p.name for p in files}
        for name, blob in sorted(base.items()):
            if name not in current:
                errors.append(f"{name}: exists on {args.base_ref} but was deleted or renamed")
            elif head_blob(name) != blob:
                errors.append(f"{name}: already on {args.base_ref} and was edited -- add a new migration instead")
        newest_base = max((NAME.match(n).group(1) for n in base if NAME.match(n)), default="")
        for name in sorted(current - set(base)):
            m = NAME.match(name)
            if m and m.group(1) <= newest_base:
                errors.append(f"{name}: version is not newer than {newest_base} on {args.base_ref}")

    print(f"{len(files)} migration files checked" + (f" against {args.base_ref}" if args.base_ref else ""))
    for error in errors:
        print(f"::error title=Migration check::{error}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

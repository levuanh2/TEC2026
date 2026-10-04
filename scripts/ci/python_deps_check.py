"""Backend import boundary + dependency declaration check.

Run with the CLEAN venv's interpreter (backend_startup_smoke.sh does), never the
global one:

    <venv>/bin/python scripts/ci/python_deps_check.py

  ENV_NOT_ISOLATED     the interpreter is not a venv, or `pip` resolves to another
                       interpreter's site-packages
  IMPORT_BOUNDARY      a production module (backend/, excluding tests/ and scripts/)
                       fails to import from requirements.txt alone -- undeclared
                       dependency, missing optional-dependency guard, circular import
  UNDECLARED_DEPENDENCY  production code or backend/scripts imports a third-party
                       distribution that requirements.txt neither declares nor pulls in
  (report) TRANSITIVE_ONLY  imported directly but only present as a dependency of a
                       declared package -- works, but pinned by someone else

No PYTHONPATH hacks: only backend/ (and the repo root for the `ml` package, which
the CV service imports lazily behind its optional-dependency guard) are importable.
"""
from __future__ import annotations

import ast
import importlib
import importlib.metadata as md
import re
import subprocess
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
LOCAL_TOP = {p.stem for p in BACKEND.iterdir() if p.suffix == ".py" or (p.is_dir() and (p / "__init__.py").exists())}
LOCAL_TOP |= {p.name for p in BACKEND.iterdir() if p.is_dir()} | {"ml", "tests"}
problems: list[str] = []


def canon(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def declared() -> set[str]:
    out = set()
    for line in (BACKEND / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):  # `-c constraints.txt` declares nothing
            out.add(canon(re.split(r"[\[<>=!~ ;]", line, maxsplit=1)[0]))
    return out


def closure(names: set[str]) -> set[str]:
    seen, todo = set(), list(names)
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        try:
            reqs = md.requires(name) or []
        except md.PackageNotFoundError:
            continue
        for r in reqs:
            if "extra ==" in r and "extra == \"standard\"" not in r and "extra == \"binary\"" not in r:
                continue
            todo.append(canon(re.split(r"[\[<>=!~ ;(]", r, maxsplit=1)[0]))
    return seen


def check_isolation() -> None:
    print(f"interpreter: {sys.executable}\nsys.prefix:  {sys.prefix}")
    if sys.prefix == sys.base_prefix:
        problems.append(f"ENV_NOT_ISOLATED: {sys.executable} is not running in a virtual environment")
    pip = subprocess.run([sys.executable, "-m", "pip", "--version"], capture_output=True, text=True, encoding="utf-8")
    print(f"pip:         {pip.stdout.strip()}")
    if pip.returncode or str(Path(sys.prefix).resolve()).lower() not in str(Path(pip.stdout.split(" from ")[1].split(" (")[0]).resolve()).lower():
        problems.append("ENV_NOT_ISOLATED: pip does not belong to this interpreter's environment")


def production_modules() -> list[str]:
    mods = []
    for p in sorted(BACKEND.rglob("*.py")):
        rel = p.relative_to(BACKEND)
        if rel.parts[0] in {"tests", "tests_strict", "scripts"} or "__pycache__" in rel.parts:
            continue
        mods.append(".".join(rel.with_suffix("").parts).removesuffix(".__init__"))
    return mods


def check_imports() -> None:
    sys.path[:0] = [str(BACKEND), str(ROOT)]
    ok = 0
    for mod in production_modules():
        try:
            importlib.import_module(mod)
            ok += 1
        except Exception:  # noqa: BLE001 -- every failure is reported below
            problems.append(f"IMPORT_BOUNDARY: {mod} failed to import:\n{traceback.format_exc(limit=3)}")
    print(f"imported {ok}/{len(production_modules())} production modules")


def check_declared() -> None:
    dist_of = md.packages_distributions()
    decl = declared()
    reachable = closure(decl)
    files = [p for p in BACKEND.rglob("*.py") if not {"tests", "tests_strict"} & set(p.relative_to(BACKEND).parts) and "__pycache__" not in p.parts]
    seen: dict[str, str] = {}
    for f in files:
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                    [node.module] if isinstance(node, ast.ImportFrom) and node.module and not node.level else []
            for name in names:
                top = name.split(".")[0]
                if top in sys.stdlib_module_names or top in LOCAL_TOP or top == "__future__":
                    continue
                seen.setdefault(top, str(f.relative_to(ROOT)))
    transitive = []
    for top, where in sorted(seen.items()):
        dists = {canon(d) for d in dist_of.get(top, [])}
        if not dists:
            problems.append(f"UNDECLARED_DEPENDENCY: `{top}` (imported in {where}) is not installed from requirements.txt")
        elif not dists & decl:
            if dists & reachable:
                transitive.append(f"{top} ({'/'.join(sorted(dists))}, first import {where})")
            else:
                problems.append(f"UNDECLARED_DEPENDENCY: `{top}` -> {sorted(dists)} (imported in {where}) is not declared")
    print(f"third-party imports: {len(seen)}; declared directly: {len(seen) - len(transitive)}")
    for t in transitive:
        print(f"TRANSITIVE_ONLY: {t}")


def main() -> int:
    check_isolation()
    if not problems:
        check_imports()
        check_declared()
    for p in problems:
        print(f"::error title=Python deps::{p}")
    print(f"python deps: {'FAIL' if problems else 'PASS'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

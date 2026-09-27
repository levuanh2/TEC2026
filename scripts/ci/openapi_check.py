"""API contract gate: docs/openapi.json must equal the spec the backend generates,
and a change must not break the contract on the base branch unless acknowledged.

    python scripts/ci/openapi_check.py                        # drift only
    python scripts/ci/openapi_check.py --base-ref origin/main # + breaking changes
    python scripts/ci/openapi_check.py --write                # regenerate docs/openapi.json

  OPENAPI_DRIFT     docs/openapi.json differs from app.openapi() -- regenerate it in the
                    same change (--write, or backend/scripts/export_openapi.py)
  OPENAPI_BREAKING  vs the base's docs/openapi.json: an operation removed; a new required
                    parameter or request-body field; a request/response property whose
                    type changed; a success-response property removed; an operation that
                    no longer requires Authorization, or newly requires it.
                    Allowed only when docs/API_BREAKING_CHANGES.md contains the exact line
                    `ACK <change id>` printed below (reviewed in the same PR).

The spec is generated in-process with no Supabase settings (it is static; the app
prints notices to stdout, so the spec is written to a file, never parsed from stdout).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "openapi.json"
ACK = ROOT / "docs" / "API_BREAKING_CHANGES.md"
METHODS = ("get", "post", "put", "patch", "delete")


def generate() -> dict:
    out = ROOT / ".openapi-generated.json"
    env = {k: v for k, v in os.environ.items() if not k.startswith("SUPABASE_")}
    code = ("import json, sys; sys.path.insert(0, '.'); from main import app; "
            "open(sys.argv[1], 'w', encoding='utf-8').write(json.dumps(app.openapi(), ensure_ascii=False, indent=2))")
    try:
        subprocess.run([sys.executable, "-c", code, str(out)], cwd=ROOT / "backend", env=env, check=True,
                       stdout=subprocess.DEVNULL)
        return json.loads(out.read_text(encoding="utf-8"))
    finally:
        out.unlink(missing_ok=True)


def resolve(spec: dict, schema: dict | None, depth: int = 0) -> dict:
    schema = schema or {}
    if "$ref" in schema and depth < 8:
        name = schema["$ref"].split("/")[-1]
        return resolve(spec, spec["components"]["schemas"][name], depth + 1)
    return schema


def type_of(spec: dict, schema: dict) -> str:
    s = resolve(spec, schema)
    if "anyOf" in s:
        return "|".join(sorted(type_of(spec, x) for x in s["anyOf"]))
    if "$ref" in schema:
        return schema["$ref"].split("/")[-1]
    return s.get("type", "object") + (f"[{type_of(spec, s['items'])}]" if s.get("type") == "array" else "")


def ops(spec: dict):
    for path, item in spec["paths"].items():
        for m in METHODS:
            if m in item:
                yield f"{m.upper()} {path}", item[m]


def body_schema(spec: dict, op: dict) -> dict:
    content = (op.get("requestBody") or {}).get("content") or {}
    return resolve(spec, next(iter(content.values()), {}).get("schema"))


def success_schema(spec: dict, op: dict) -> dict:
    for code in ("200", "201"):
        content = (op.get("responses", {}).get(code) or {}).get("content") or {}
        if content:
            return resolve(spec, next(iter(content.values()), {}).get("schema"))
    return {}


def needs_auth(op: dict) -> bool:
    return any(p.get("name", "").lower() == "authorization" and p.get("required") for p in op.get("parameters", [])) \
        or bool(op.get("security"))


def breaking(base: dict, head: dict) -> list[str]:
    out = []
    head_ops = dict(ops(head))
    for key, bop in ops(base):
        hop = head_ops.get(key)
        if hop is None:
            out.append(f"removed-operation:{key}")
            continue
        bparams = {(p["in"], p["name"]) for p in bop.get("parameters", []) if p.get("required")}
        for p in hop.get("parameters", []):
            if p.get("required") and (p["in"], p["name"]) not in bparams and p["name"].lower() != "authorization":
                out.append(f"new-required-parameter:{key}:{p['in']}.{p['name']}")
        if needs_auth(bop) != needs_auth(hop):
            out.append(f"auth-requirement-changed:{key}")
        bb, hb = body_schema(base, bop), body_schema(head, hop)
        for field in set(hb.get("required", [])) - set(bb.get("required", [])):
            out.append(f"new-required-request-field:{key}:{field}")
        for field, fs in (bb.get("properties") or {}).items():
            hs = (hb.get("properties") or {}).get(field)
            if hs is not None and type_of(base, fs) != type_of(head, hs):
                out.append(f"request-type-changed:{key}:{field}")
        br, hr = success_schema(base, bop), success_schema(head, hop)
        for field, fs in (br.get("properties") or {}).items():
            hs = (hr.get("properties") or {}).get(field)
            if hs is None:
                out.append(f"removed-response-field:{key}:{field}")
            elif type_of(base, fs) != type_of(head, hs):
                out.append(f"response-type-changed:{key}:{field}")
    return sorted(set(out))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-ref")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    live = generate()
    text = json.dumps(live, ensure_ascii=False, indent=2)
    if args.write:
        DOC.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {DOC.relative_to(ROOT)} ({len(live['paths'])} paths)")
        return 0
    problems = []
    committed = json.loads(DOC.read_text(encoding="utf-8"))
    if committed != live:
        c_ops, l_ops = set(k for k, _ in ops(committed)), set(k for k, _ in ops(live))
        detail = f"only in code: {sorted(l_ops - c_ops)}; only in docs: {sorted(c_ops - l_ops)}"
        problems.append(f"OPENAPI_DRIFT: docs/openapi.json is stale ({detail}); "
                        "run python scripts/ci/openapi_check.py --write")
    if args.base_ref:
        r = subprocess.run(["git", "show", f"{args.base_ref}:docs/openapi.json"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        if r.returncode == 0:
            acked = set()
            if ACK.is_file():
                acked = {line[4:].strip() for line in ACK.read_text(encoding="utf-8").splitlines() if line.startswith("ACK ")}
            changes = breaking(json.loads(r.stdout), live)
            for c in changes:
                print(f"{'ACKNOWLEDGED' if c in acked else 'BREAKING'}: {c}")
            unacked = [c for c in changes if c not in acked]
            if unacked:
                problems.append(f"OPENAPI_BREAKING: {len(unacked)} unacknowledged breaking change(s) vs {args.base_ref}; "
                                f"add `ACK <id>` lines to {ACK.relative_to(ROOT)} if intended")
            print(f"breaking changes vs {args.base_ref}: {len(changes)} ({len(changes) - len(unacked)} acknowledged)")
    print(f"openapi: {len(list(ops(live)))} operations; {'FAIL' if problems else 'PASS'}")
    for p in problems:
        print(f"::error title=OpenAPI contract::{p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

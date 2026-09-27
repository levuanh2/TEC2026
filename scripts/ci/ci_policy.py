"""CI self-integrity and anti-bypass policy -- the `workflow-policy` job.

    python scripts/ci/ci_policy.py                         # all checks
    python scripts/ci/ci_policy.py --base-ref origin/main  # + policy-relaxation check (PRs)
    python scripts/ci/ci_policy.py --inventory             # print current source inventories

Checks (each failure prints ::error with a stable CODE):

WORKFLOWS (.github/workflows/*.yml)
  CI_UNPINNED_ACTION        every `uses:` is owner/repo@<40-hex sha> (or ./local)
  CI_NO_TIMEOUT             every job has timeout-minutes (<= 45)
  CI_PERMISSIONS            top-level permissions is exactly {contents: read}; no job widens it
  CI_FORBIDDEN_TRIGGER      no pull_request_target anywhere
  CI_SECRETS_IN_PR_CI       ci.yml never references secrets.*
  CI_CODEOWNERS_MISSING     a guarded path (or supabase/migrations/) has no CODEOWNERS entry
  CI_UNGUARDED_SCRIPT       a workflow runs a script outside policy guarded_paths
  CI_UNGUARDED_TEST         a protected_tests module is outside policy guarded_paths
  DEP_SOURCE                a lockfile/requirements entry installs from outside the public registry
  TEST_ENV_DETECTION        production code references the test runner or CI environment
  HIDDEN_ROUTE              production code uses include_in_schema (routes invisible to the sweeps)
  ROUTE_MUTATION            product code edits the routing table / lifespan outside router decorators
  CI_GUARDED_CHANGE         a file under policy guarded_paths changed without the trailer
  CI_GATE_INCOMPLETE        ci-gate needs every other ci.yml job, and fails on non-success
  CI_MISSING_SCRIPT         every scripts/... path a workflow runs exists
BYPASS PATTERNS (workflow run blocks + scripts/ci/*)
  CI_BYPASS                 continue-on-error, `|| true`, `|| :`, `|| exit 0`, `set +e`,
                            bare `except: pass` / `except Exception: pass`
                            -- only exact (file, line) pairs in policy.json bypass_allowlist pass
SYNTAX
  CI_SYNTAX                 bash -n on scripts/ci/*.sh, py_compile on scripts/ci/*.py
SOURCE INVENTORIES (compared with policy.json; an INCREASE fails)
  DISABLED_TEST_ADDED       skip / xfail / fixme / todo markers per test file
  FOCUSED_TEST              .only( in any JS/TS test -- always fails
  TS_SUPPRESSION_ADDED      @ts-ignore / @ts-nocheck per file
  DART_IGNORE_ADDED         // ignore: / ignore_for_file per file
  ANALYZER_RELAXED          analysis_options.yaml errors:/ignore overrides
CONFIG
  AUTH_SIGNUP_POLICY        supabase/config.toml: public sign-up off, email sign-in on
  GITLEAKS_BROAD_ALLOWLIST  .gitleaks.toml allowlists only value shapes (no paths/commits)
RELAXATION (with --base-ref)
  CI_POLICY_RELAXED         floors/minimums/coverage baselines lowered, tolerances or
                            allowlists grown vs the base -- allowed only when a commit in
                            base..HEAD carries a `CI-Policy-Change: <reason>` trailer

Standard library + PyYAML (installed by the job).
"""
from __future__ import annotations

import argparse
import ast
import io
import json
import os
import py_compile
import re
import subprocess
import sys
import tokenize
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
POLICY_FILE = ROOT / "scripts" / "ci" / "policy" / "policy.json"
WORKFLOWS = ROOT / ".github" / "workflows"
SHA_PIN = re.compile(r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$")
BYPASS = [
    (re.compile(r"continue-on-error"), "continue-on-error"),
    (re.compile(r"\|\|\s*true\b"), "|| true"),
    (re.compile(r"\|\|\s*:\s*(?:$|[;)#])"), "|| :"),
    (re.compile(r"\|\|\s*exit\s+0\b"), "|| exit 0"),
    (re.compile(r"^\s*set\s+\+e\b"), "set +e"),
    (re.compile(r"except(?:\s+(?:Exception|BaseException))?\s*:\s*pass\b"), "except: pass"),
]
DISABLED_PATTERNS = {
    "py": re.compile(r"pytest\.mark\.(?:skip|skipif|xfail)\b|pytest\.(?:skip|xfail)\(|pytest\.importorskip\("),
    "ts": re.compile(r"\b(?:test|it|describe)\.(?:skip|fixme|todo)\b|\b(?:xit|xdescribe)\("),
    "dart": re.compile(r"\bskip\s*:"),
}
FOCUSED = re.compile(r"\b(?:test|it|describe)\.only\(|\b(?:fit|fdescribe)\(")
TS_SUPPRESS = re.compile(r"@ts-(?:ignore|nocheck)\b")
DART_IGNORE = re.compile(r"//\s*ignore(?:_for_file)?\s*:")

errors: list[str] = []


def fail(code: str, msg: str) -> None:
    errors.append(f"{code}: {msg}")
    print(f"::error title={code}::{msg}")


def rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


# --------------------------------------------------------------- workflows
def run_blocks(doc: dict):
    for job_id, job in (doc.get("jobs") or {}).items():
        for i, step in enumerate(job.get("steps") or []):
            if "run" in step:
                yield job_id, i, step["run"]


def check_workflows(policy: dict) -> None:
    allow = {(a["file"], a["line"].strip()) for a in policy["bypass_allowlist"]}
    for wf in sorted(WORKFLOWS.glob("*.yml")):
        text = wf.read_text(encoding="utf-8")
        doc = yaml.safe_load(text)
        on = doc.get(True, doc.get("on"))  # PyYAML parses `on:` as True
        triggers = on if isinstance(on, dict) else {t: None for t in (on if isinstance(on, list) else [on])}
        if "pull_request_target" in triggers:
            fail("CI_FORBIDDEN_TRIGGER", f"{rel(wf)} uses pull_request_target")
        if doc.get("permissions") != {"contents": "read"}:
            fail("CI_PERMISSIONS", f"{rel(wf)} top-level permissions must be exactly contents: read")
        for job_id, job in (doc.get("jobs") or {}).items():
            tm = job.get("timeout-minutes")
            if not isinstance(tm, int) or tm > 45:
                fail("CI_NO_TIMEOUT", f"{rel(wf)} job {job_id} needs timeout-minutes <= 45 (got {tm!r})")
            if "permissions" in job:
                fail("CI_PERMISSIONS", f"{rel(wf)} job {job_id} sets its own permissions")
            if "continue-on-error" in job:
                fail("CI_BYPASS", f"{rel(wf)} job {job_id} sets continue-on-error")
            for step in job.get("steps") or []:
                uses = step.get("uses")
                if uses and not uses.startswith("./") and not SHA_PIN.match(uses):
                    fail("CI_UNPINNED_ACTION", f"{rel(wf)} job {job_id}: {uses} is not pinned to a commit SHA")
                if "continue-on-error" in step:
                    fail("CI_BYPASS", f"{rel(wf)} job {job_id} step {step.get('name', uses)} sets continue-on-error")
        for job_id, i, run in run_blocks(doc):
            for line in run.splitlines():
                for pat, label in BYPASS:
                    if pat.search(line) and (rel(wf), line.strip()) not in allow:
                        fail("CI_BYPASS", f"{rel(wf)} job {job_id}: `{line.strip()}` ({label})")
            if re.search(r"\b(?:npm|npx)\b", run):
                check_npm(rel(wf), job_id, run, policy)
            for path in re.findall(r"(?<![\w/.-])((?:\.\./)*(?:scripts|backend/scripts)/[\w./-]+\.(?:py|sh))", run):
                cands = [ROOT / path.lstrip("./"), ROOT / "backend" / path, ROOT / path.replace("../", "")]
                found = [c for c in cands if c.is_file()]
                if not found:
                    fail("CI_MISSING_SCRIPT", f"{rel(wf)} job {job_id} runs {path}, which does not exist")
                # Whatever a workflow executes decides a gate (a probe that prints
                # "50/50 checks passed" IS the gate), so it must be guarded + owned.
                for c in found:
                    if not is_guarded(rel(c.resolve()), policy):
                        fail("CI_UNGUARDED_SCRIPT", f"{rel(wf)} job {job_id} runs {rel(c.resolve())}, "
                                                    "which is not under policy guarded_paths")
        if wf.name == "ci.yml":
            if "secrets." in text:
                fail("CI_SECRETS_IN_PR_CI", "ci.yml references secrets.* -- PR CI must not receive secrets")
            jobs = doc.get("jobs") or {}
            gate = jobs.get("ci-gate")
            if gate is None:
                fail("CI_GATE_INCOMPLETE", "ci.yml has no ci-gate job")
            else:
                needs = set(gate.get("needs") or [])
                missing = set(jobs) - {"ci-gate"} - needs - set(policy["gate_optional_jobs"])
                if missing:
                    fail("CI_GATE_INCOMPLETE", f"ci-gate does not need: {sorted(missing)}")
                if gate.get("if") != "${{ always() }}":
                    fail("CI_GATE_INCOMPLETE", "ci-gate must run with if: ${{ always() }}")
                body = "".join(s.get("run", "") for s in gate.get("steps") or [])
                gate_sh = ROOT / "scripts" / "ci" / "ci_gate.sh"
                gate_logic = gate_sh.read_text(encoding="utf-8") if gate_sh.is_file() else ""
                if "bash scripts/ci/ci_gate.sh" not in body or 'select(.value.result != "success")' not in gate_logic:
                    fail("CI_GATE_INCOMPLETE", "ci-gate must run scripts/ci/ci_gate.sh, which fails on every non-success upstream result")
                policy_runs = "".join(s.get("run", "") for s in (jobs.get("workflow-policy") or {}).get("steps") or [])
                if "bash scripts/ci/ci_gate_selftest.sh" not in policy_runs:
                    fail("CI_GATE_INCOMPLETE", "workflow-policy must run scripts/ci/ci_gate_selftest.sh")


def check_helpers(policy: dict) -> None:
    allow = {(a["file"], a["line"].strip()) for a in policy["bypass_allowlist"]}
    for f in sorted((ROOT / "scripts" / "ci").glob("*")):
        if f.suffix not in {".sh", ".py"} or f.name == "ci_policy.py":
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            for pat, label in BYPASS:
                if pat.search(line) and (rel(f), line.strip()) not in allow:
                    fail("CI_BYPASS", f"{rel(f)}: `{line.strip()}` ({label})")
        if f.suffix == ".sh":
            r = subprocess.run(["bash", "-n", rel(f)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
            if r.returncode:
                fail("CI_SYNTAX", f"{rel(f)}: {r.stderr.strip()}")
        else:
            try:
                py_compile.compile(str(f), doraise=True)
            except py_compile.PyCompileError as exc:
                fail("CI_SYNTAX", f"{rel(f)}: {exc.msg}")


# ------------------------------------------------------------ inventories
def test_files():
    # Every file under the test trees, not only test_*.py: a skip marker defined in
    # a helper (_markers.py, conftest.py) disables every test that uses it.
    for tree in ("backend/tests", "backend/tests_strict", "ml/tests"):
        yield from ((p, "py") for p in (ROOT / tree).rglob("*.py"))
    web = ROOT / "web-dashboard"
    for pat in ("src/**/*.test.ts", "src/**/*.test.tsx", "tests/e2e/**/*.ts"):
        yield from ((p, "ts") for p in web.glob(pat))
    for sub in ("test", "integration_test"):
        yield from ((p, "dart") for p in (ROOT / "app" / sub).rglob("*.dart"))


def inventories() -> dict:
    disabled, ts, dart = Counter(), Counter(), Counter()
    focused = []
    for p, kind in test_files():
        text = p.read_text(encoding="utf-8")
        n = len(DISABLED_PATTERNS[kind].findall(text))
        if n:
            disabled[rel(p)] = n
        if kind == "ts" and FOCUSED.search(text):
            focused.append(rel(p))
    for p in (ROOT / "web-dashboard").glob("src/**/*.ts*"):
        n = len(TS_SUPPRESS.findall(p.read_text(encoding="utf-8")))
        if n:
            ts[rel(p)] = n
    for p in (ROOT / "web-dashboard" / "tests").rglob("*.ts"):
        n = len(TS_SUPPRESS.findall(p.read_text(encoding="utf-8")))
        if n:
            ts[rel(p)] = n
    for sub in ("lib", "test", "integration_test"):
        for p in (ROOT / "app" / sub).rglob("*.dart"):
            n = len(DART_IGNORE.findall(p.read_text(encoding="utf-8")))
            if n:
                dart[rel(p)] = n
    return {"disabled_tests": dict(sorted(disabled.items())), "ts_suppressions": dict(sorted(ts.items())),
            "dart_ignores": dict(sorted(dart.items())), "focused": focused}


def check_inventories(policy: dict) -> None:
    inv = inventories()
    for f in inv["focused"]:
        fail("FOCUSED_TEST", f"{f} contains .only( -- a focused test silently skips all others")
    for key, code in (("disabled_tests", "DISABLED_TEST_ADDED"), ("ts_suppressions", "TS_SUPPRESSION_ADDED"),
                      ("dart_ignores", "DART_IGNORE_ADDED")):
        allowed = policy[key]
        for f, n in inv[key].items():
            if n > allowed.get(f, 0):
                fail(code, f"{f}: {n} occurrence(s), policy allows {allowed.get(f, 0)} "
                           f"(update scripts/ci/policy/policy.json with a CI-Policy-Change trailer)")
    ao = yaml.safe_load((ROOT / "app" / "analysis_options.yaml").read_text(encoding="utf-8")) or {}
    analyzer = ao.get("analyzer") or {}
    if analyzer.get("errors") or analyzer.get("exclude") != policy["dart_analyzer_exclude"]:
        fail("ANALYZER_RELAXED", "app/analysis_options.yaml analyzer errors/exclude differ from policy")
    rules = (ao.get("linter") or {}).get("rules")
    if rules:  # disabling lints (rule: false) is a relaxation
        off = [k for k, v in (rules.items() if isinstance(rules, dict) else []) if v is False]
        if off:
            fail("ANALYZER_RELAXED", f"app/analysis_options.yaml disables lints: {off}")


def check_config() -> None:
    import tomllib
    cfg = tomllib.loads((ROOT / "supabase" / "config.toml").read_text(encoding="utf-8"))
    auth = cfg.get("auth", {})
    if auth.get("enable_signup") is not False:
        fail("AUTH_SIGNUP_POLICY", "supabase/config.toml [auth] enable_signup must be false (no public sign-up)")
    if auth.get("email", {}).get("enable_signup") is not True:
        fail("AUTH_SIGNUP_POLICY", "supabase/config.toml [auth.email] enable_signup must be true (keeps password sign-in)")
    if auth.get("enable_anonymous_sign_ins") is not False:
        fail("AUTH_SIGNUP_POLICY", "supabase/config.toml anonymous sign-ins must stay off")
    gl = tomllib.loads((ROOT / ".gitleaks.toml").read_text(encoding="utf-8"))
    for al in gl.get("allowlists", []) + ([gl["allowlist"]] if "allowlist" in gl else []):
        if set(al) & {"paths", "commits", "stopwords"} or al.get("regexTarget") != "match":
            fail("GITLEAKS_BROAD_ALLOWLIST", ".gitleaks.toml allowlists must be regexTarget=match value shapes only")
    if not gl.get("extend", {}).get("useDefault"):
        fail("GITLEAKS_BROAD_ALLOWLIST", ".gitleaks.toml must extend the default ruleset")


# -------------------------------------------------------------- relaxation
def relaxations(base: dict, head: dict) -> list[str]:
    out = []
    for suite, floor in base["test_floors"].items():
        if head["test_floors"].get(suite, 0) < floor:
            out.append(f"test floor {suite} {floor} -> {head['test_floors'].get(suite)}")
    for probe, n in base["probe_minimums"].items():
        if head["probe_minimums"].get(probe, 0) < n:
            out.append(f"probe minimum {probe} {n} -> {head['probe_minimums'].get(probe)}")
    for suite, mins in base.get("protected_tests", {}).items():
        for module, n in mins.items():
            if head.get("protected_tests", {}).get(suite, {}).get(module, 0) < n:
                out.append(f"protected tests {suite}/{module} {n} -> {head.get('protected_tests', {}).get(suite, {}).get(module)}")
    bc, hc = base["coverage"], head["coverage"]
    if hc["tolerance_pp"] > bc["tolerance_pp"]:
        out.append(f"coverage tolerance {bc['tolerance_pp']} -> {hc['tolerance_pp']}")
    if hc["changed_lines_min"] < bc["changed_lines_min"]:
        out.append(f"changed-line coverage {bc['changed_lines_min']} -> {hc['changed_lines_min']}")
    for layer in ("baseline", "critical_backend"):
        for k, v in bc[layer].items():
            if hc[layer].get(k, -1) < v:
                out.append(f"coverage {layer} {k} {v} -> {hc[layer].get(k)}")
    for suite, allowed in base["skip_allowlist"].items():
        grown = set(head["skip_allowlist"].get(suite, [])) - set(allowed)
        if grown:
            out.append(f"skip allowlist {suite} grew: {sorted(grown)}")
    for key in ("disabled_tests", "ts_suppressions", "dart_ignores"):
        for f, n in head[key].items():
            if n > base[key].get(f, 0):
                out.append(f"{key} {f} {base[key].get(f, 0)} -> {n}")
    if len(head["bypass_allowlist"]) > len(base["bypass_allowlist"]):
        out.append("bypass allowlist grew")
    if set(head["gate_optional_jobs"]) - set(base["gate_optional_jobs"]):
        out.append("ci-gate optional jobs grew")
    if head["bundle"]["max_growth_pct"] > base["bundle"]["max_growth_pct"]:
        out.append("bundle growth tolerance raised")
    bx, hx = base.get("db_exceptions", {}), head.get("db_exceptions", {})
    for key in ("anon_table_write", "function_execute", "open_read_policies"):
        grown = [e for e in hx.get(key, []) if e not in bx.get(key, [])]
        if grown and key in bx:
            out.append(f"db_exceptions {key} grew: {grown}")
    grown = set(head.get("route_mutation_exempt_files", [])) - set(base.get("route_mutation_exempt_files", []))
    if grown and "route_mutation_exempt_files" in base:
        out.append(f"route_mutation_exempt_files grew: {sorted(grown)}")
    grown = set(head.get("route_mutation_allow", [])) - set(base.get("route_mutation_allow", []))
    if grown and "route_mutation_allow" in base:
        out.append(f"route_mutation_allow grew: {sorted(grown)}")
    dropped = set(base.get("guarded_paths", [])) - set(head.get("guarded_paths", []))
    if dropped:
        out.append(f"guarded_paths shrank: {sorted(dropped)}")
    return out


def check_npm(wf: str, job_id: str, run: str, policy: dict) -> None:
    """npm/npx resolve through web-dashboard/package.json (scripts, and the
    devDependencies whose bins npx runs): it must be guarded, and any local file
    an `npm run <script>` body executes must be guarded too."""
    pkg_rel = "web-dashboard/package.json"
    if not is_guarded(pkg_rel, policy):
        fail("CI_UNGUARDED_SCRIPT", f"{wf} job {job_id} runs npm/npx, but {pkg_rel} is not under guarded_paths")
    scripts = json.loads((ROOT / pkg_rel).read_text(encoding="utf-8")).get("scripts", {})
    for name in re.findall(r"\bnpm (?:run(?:-script)?\s+([\w:-]+)|(test)\b)", run):
        name = name[0] or name[1]
        body = scripts.get(name)
        if body is None:
            fail("CI_MISSING_SCRIPT", f"{wf} job {job_id} runs npm script {name!r}, which package.json lacks")
            continue
        for ref in re.findall(r"(?<![\w@/-])((?:\./)?[\w./-]+\.(?:[cm]?js|ts|py|sh))\b", body):
            target = f"web-dashboard/{ref.removeprefix('./')}"
            if (ROOT / target).is_file() and not is_guarded(target, policy):
                fail("CI_UNGUARDED_SCRIPT", f"{wf} job {job_id}: npm script {name!r} runs {target}, "
                                            "which is not under guarded_paths")


ENV_DETECTION = {
    # Any string literal naming a CI/test variable counts, whatever the access
    # idiom (`"CI" in os.environ`, `environ["CI"]`, `getenv("CI")`, a dict of names).
    "py": re.compile(r"^\s*(?:import|from)\s+(?:pytest|_pytest|hypothesis)\b|\.modules\b"
                     r"|[\"'](?:_?pytest|hypothesis|unittest|CI|GITHUB_ACTIONS|PYTEST_CURRENT_TEST)[\"']"
                     r"|PYTEST_|GITHUB_ACTIONS"),
    # import.meta.env: only VITE_* build variables; MODE / DEV / PROD / TEST /
    # SSR, destructuring and bracket access are how Vite code tells it is tested.
    "ts": re.compile(r"\bVITEST\b|import\.meta\.vitest|import\.meta\.env(?!\.VITE_[A-Z0-9_]+\b)|__vitest|__VITEST"
                     r"|navigator\.webdriver|GITHUB_ACTIONS|process\.env"
                     r"|\bprocess\s*\[|import\.meta\s*\[|\[\s*[\"'`](?:webdriver|env)[\"'`]\s*\]"
                     r"|[\"'`](?:CI|VITEST|PLAYWRIGHT)[\"'`]|__playwright|PLAYWRIGHT"),
    "dart": re.compile(r"FLUTTER_TEST|Platform\.environment|GITHUB_ACTIONS|[\"'](?:CI)[\"']"),
}


# Any use at all: an alias (`include_in_schema=EXPOSED`) hides a route just as well.
HIDDEN_ROUTE = re.compile(r"include_in_schema")


def py_code_lines(text: str) -> list[str]:
    """Source lines with comments removed by the tokenizer (a `#` inside a string
    literal is code, not a comment). Untokenizable source is scanned as is."""
    lines = text.splitlines()
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                row, col = tok.start
                lines[row - 1] = lines[row - 1][:col]
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return lines


ROUTE_MUTATION = re.compile(
    r"\.routes\s*(?:\.(?:append|insert|extend|remove|pop|clear)\b|\[|[-+*|]?=(?!=))|lifespan_context|\blifespan\s*="
    r"|\badd_(?:api_)?(?:websocket_)?route\s*\(|\.mount\s*\(|\bsetattr\s*\(|\binclude_router\s*\("
    # undoing infrastructure/route_freeze.py
    r"|__class__\s*=(?!=)|\bobject\s*\.\s*__setattr__|__frozen_routing__|\bfrozen_class\b|_frozen_classes")
# A router/app route method is only allowed as a decorator: called as a plain
# function (e.g. from a timer) it registers a route after the inventory looked.
ROUTE_METHOD_CALL = re.compile(
    r"\b(?:app|\w*router)\s*\.\s*(?:get|post|put|patch|delete|head|options|trace|api_route|websocket|route)\s*\(")


def check_route_mutation(policy: dict) -> None:
    """Routes come only from decorators on routers: code that edits the routing
    table directly, mounts sub-apps, sets route attributes dynamically or plugs
    into the lifespan (where a delayed task could add a route after the
    inventory looked) could serve an operation the auth inventory never sees.
    Exact `file: line` exceptions only (policy.json route_mutation_allow)."""
    allow = set(policy.get("route_mutation_allow", []))
    exempt = set(policy.get("route_mutation_exempt_files", []))  # the freezer itself (guarded)
    for base in (ROOT / "backend", ROOT / "ml"):
        for f in base.rglob("*.py"):
            if set(f.relative_to(base).parts) & {"tests", "tests_strict", "scripts", ".venv", "runs", "datasets"}:
                continue
            r = rel(f)
            if r in exempt:
                continue
            text = f.read_text(encoding="utf-8")
            for n, (line, code) in enumerate(zip(text.splitlines(), py_code_lines(text)), 1):
                hit = ROUTE_MUTATION.search(code) or (
                    ROUTE_METHOD_CALL.search(code) and not code.lstrip().startswith("@"))
                if hit and f"{r}: {line.strip()}" not in allow:
                    fail("ROUTE_MUTATION", f"{r}:{n}: routing table / lifespan changed outside router decorators: `{line.strip()}`")
            # A route decorator registers when its `def` executes: only a
            # module-level def runs at import, before the inventory walks the
            # table. Inside a function (called later, e.g. from a timer) it is a
            # late registration. AST, so formatting cannot hide it.
            try:
                tree = ast.parse(text)
            except SyntaxError:
                fail("ROUTE_MUTATION", f"{r}: does not parse")
                continue
            top_level = {id(node) for node in tree.body}
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and id(node) not in top_level:
                    for dec in node.decorator_list:
                        if ROUTE_METHOD_CALL.search(ast.unparse(dec) + "("):
                            fail("ROUTE_MUTATION", f"{r}:{node.lineno}: route decorator on a nested `{node.name}` "
                                                   "registers a route when called, after the inventory ran")


def check_env_detection(policy: dict) -> None:
    """Production code must not detect the test runner or CI: code that behaves
    only under pytest / vitest / Playwright / flutter test would pass every gate
    and ship something else. Exact `file: line` exceptions only."""
    allow = set(policy.get("env_detection_allow", []))
    # ml/ is production code too: backend/service.py imports ml.infer for CV.
    trees = [("py", ROOT / "backend", "*.py"), ("py", ROOT / "ml", "*.py"),
             ("ts", ROOT / "web-dashboard" / "src", "*.ts*"), ("dart", ROOT / "app" / "lib", "*.dart")]
    for kind, base, pat in trees:
        for f in base.rglob(pat):
            r = rel(f)
            if kind == "py" and (set(f.relative_to(base).parts)
                                 & {"tests", "tests_strict", "scripts", ".venv", "runs", "datasets"}):
                continue
            if kind == "py" and HIDDEN_ROUTE.search("\n".join(py_code_lines(f.read_text(encoding="utf-8")))):
                # The route sweeps (pytest and live) enumerate the OpenAPI
                # schema; a route hidden from it is never checked.
                fail("HIDDEN_ROUTE", f"{r}: include_in_schema hides routes from the auth/contract sweeps")
            # Nothing under web-dashboard/src or app/lib is exempt by name: a
            # `.test.`/mocks module can be imported by production code.
            text = f.read_text(encoding="utf-8")
            raw = text.splitlines()
            code_lines = py_code_lines(text) if kind == "py" else raw
            for n, (line, code) in enumerate(zip(raw, code_lines), 1):
                if ENV_DETECTION[kind].search(code) and f"{r}: {line.strip()}" not in allow:
                    fail("TEST_ENV_DETECTION", f"{r}:{n}: production code detects the test runner/CI: `{line.strip()}`")


def check_dependency_sources() -> None:
    """Test runners and tools come from the dependency manifests, so a manifest
    that installs from an arbitrary tarball/URL/index could ship a fake pytest,
    vitest or playwright that "passes". Only the public registries, pinned by
    integrity where the ecosystem has it."""
    lock = json.loads((ROOT / "web-dashboard" / "package-lock.json").read_text(encoding="utf-8"))
    for name, pkg in lock.get("packages", {}).items():
        if not name:
            continue
        resolved, integrity = pkg.get("resolved", ""), pkg.get("integrity", "")
        if pkg.get("link") or not resolved.startswith("https://registry.npmjs.org/") or not integrity.startswith("sha512-"):
            fail("DEP_SOURCE", f"web-dashboard/package-lock.json {name}: must resolve from registry.npmjs.org "
                               f"with a sha512 integrity (resolved={resolved or pkg.get('link')!r})")
    for req in ("backend/requirements.txt", "ml/requirements.txt"):
        for n, line in enumerate((ROOT / req).read_text(encoding="utf-8").splitlines(), 1):
            spec = line.split("#", 1)[0].strip()
            if spec and (spec.startswith("-") or "://" in spec or " @ " in spec or spec.startswith(("git+", "."))):
                fail("DEP_SOURCE", f"{req}:{n}: `{spec}` installs from outside PyPI (option, URL or path)")
    pub = yaml.safe_load((ROOT / "app" / "pubspec.lock").read_text(encoding="utf-8"))
    for name, pkg in (pub.get("packages") or {}).items():
        url = (pkg.get("description") or {}).get("url") if isinstance(pkg.get("description"), dict) else None
        if pkg.get("source") == "sdk":
            continue
        if pkg.get("source") != "hosted" or url != "https://pub.dev":
            fail("DEP_SOURCE", f"app/pubspec.lock {name}: must be hosted on https://pub.dev "
                               f"(source={pkg.get('source')!r}, url={url!r})")


def is_guarded(path: str, policy: dict) -> bool:
    return any(path == g or (g.endswith("/") and path.startswith(g)) for g in policy["guarded_paths"])


def guarded_changes(ref: str, head_policy: dict) -> list[str]:
    """Files under the policy's guarded paths that differ from the base: gates,
    their data and the configs that decide what is measured (coverage omit/
    exclude, page-health allowlist, analyzer config, gitleaks, ACK files)."""
    changed = subprocess.run(["git", "diff", "--name-only", f"{ref}...HEAD"], cwd=ROOT, check=True,
                             capture_output=True, text=True, encoding="utf-8").stdout.split()
    return [f for f in changed if is_guarded(f, head_policy)]


def check_relaxation(ref: str, head_policy: dict) -> None:
    """A relaxed policy, or any change under guarded_paths, needs a
    `CI-Policy-Change: <reason>` trailer in the PR's commits. The trailer is
    self-declared -- it makes the change explicit and searchable; approval is
    CODEOWNERS review on the same paths (docs/CI_PIPELINE.md, "CI change review")."""
    try:
        base_text = subprocess.run(["git", "show", f"{ref}:scripts/ci/policy/policy.json"], cwd=ROOT,
                                   check=True, capture_output=True, text=True, encoding="utf-8").stdout
        found = relaxations(json.loads(base_text), head_policy)
    except subprocess.CalledProcessError:
        print(f"no policy.json on {ref}: policy introduced by this change")
        found = []
    guarded = guarded_changes(ref, head_policy)
    for item in found:
        print(f"POLICY RELAXED: {item}")
    for f in guarded:
        print(f"GUARDED PATH CHANGED: {f}")
    if not found and not guarded:
        print("policy not relaxed; no guarded path changed")
        return
    log = subprocess.run(["git", "log", "--format=%B", f"{ref}..HEAD"], cwd=ROOT, check=True,
                         capture_output=True, text=True, encoding="utf-8").stdout
    trailer = re.search(r"^CI-Policy-Change:\s*\S.*$", log, re.M)
    what = "; ".join(found + [f"changed {f}" for f in guarded])
    if not trailer:
        if found:
            fail("CI_POLICY_RELAXED", "policy relaxed without a `CI-Policy-Change: <reason>` commit trailer: "
                                      + "; ".join(found))
        if guarded:
            fail("CI_GUARDED_CHANGE", f"{len(guarded)} guarded CI file(s) changed without a "
                                      "`CI-Policy-Change: <reason>` commit trailer: " + ", ".join(guarded))
    else:
        print(f"::warning title=CI policy change::{trailer.group(0)} -- CODEOWNERS must review: {what}")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write("### CI policy changes in this PR\n" + "".join(f"- {x}\n" for x in found + guarded))


def check_codeowners(policy: dict) -> None:
    path = ROOT / ".github" / "CODEOWNERS"
    owned = set()
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) >= 2 and not line.startswith("#"):
                owned.add(parts[0].lstrip("/"))
    for suite, modules in policy["protected_tests"].items():
        for module in modules:
            if not is_guarded(f"backend/tests/{module}.py", policy):
                fail("CI_UNGUARDED_TEST", f"protected test module backend/tests/{module}.py is not under guarded_paths")
    for g in policy["guarded_paths"] + ["supabase/migrations/"]:
        if g not in owned:
            fail("CI_CODEOWNERS_MISSING", f".github/CODEOWNERS has no owner for guarded path {g}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-ref")
    ap.add_argument("--inventory", action="store_true")
    args = ap.parse_args()
    if args.inventory:
        print(json.dumps(inventories(), indent=2))
        return 0
    policy = json.loads(POLICY_FILE.read_text(encoding="utf-8"))
    check_workflows(policy)
    check_helpers(policy)
    check_inventories(policy)
    check_config()
    check_codeowners(policy)
    check_dependency_sources()
    check_env_detection(policy)
    check_route_mutation(policy)
    if args.base_ref:
        check_relaxation(args.base_ref, policy)
    print(f"ci_policy: {'FAIL' if errors else 'PASS'} ({len(errors)} violation(s))")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

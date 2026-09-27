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
import json
import py_compile
import re
import subprocess
import sys
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
    "py": re.compile(r"pytest\.mark\.(?:skip|xfail)\b|pytest\.(?:skip|xfail)\(|pytest\.importorskip\("),
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
            for path in re.findall(r"(?<![\w/.-])((?:\.\./)*(?:scripts|backend/scripts)/[\w./-]+\.(?:py|sh))", run):
                cands = [ROOT / path.lstrip("./"), ROOT / "backend" / path, ROOT / path.replace("../", "")]
                if not any(c.is_file() for c in cands):
                    fail("CI_MISSING_SCRIPT", f"{rel(wf)} job {job_id} runs {path}, which does not exist")
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
                if 'select(.value.result != "success")' not in body:
                    fail("CI_GATE_INCOMPLETE", "ci-gate must fail on every non-success upstream result")


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
    yield from ((p, "py") for p in (ROOT / "backend" / "tests").rglob("test_*.py"))
    yield from ((p, "py") for p in (ROOT / "ml" / "tests").rglob("test_*.py"))
    web = ROOT / "web-dashboard"
    for pat in ("src/**/*.test.ts", "src/**/*.test.tsx", "tests/e2e/**/*.ts"):
        yield from ((p, "ts") for p in web.glob(pat))
    for sub in ("test", "integration_test"):
        yield from ((p, "dart") for p in (ROOT / "app" / sub).rglob("*_test.dart"))


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
    return out


def check_relaxation(ref: str, head_policy: dict) -> None:
    try:
        base_text = subprocess.run(["git", "show", f"{ref}:scripts/ci/policy/policy.json"], cwd=ROOT,
                                   check=True, capture_output=True, text=True, encoding="utf-8").stdout
    except subprocess.CalledProcessError:
        print(f"no policy.json on {ref}: relaxation check not applicable (first introduction)")
        return
    found = relaxations(json.loads(base_text), head_policy)
    if not found:
        print("policy not relaxed")
        return
    log = subprocess.run(["git", "log", "--format=%B", f"{ref}..HEAD"], cwd=ROOT, check=True,
                         capture_output=True, text=True, encoding="utf-8").stdout
    trailer = re.search(r"^CI-Policy-Change:\s*\S.*$", log, re.M)
    for item in found:
        print(f"POLICY RELAXED: {item}")
    if not trailer:
        fail("CI_POLICY_RELAXED", "policy relaxed without a `CI-Policy-Change: <reason>` commit trailer: "
                                  + "; ".join(found))
    else:
        print(f"::warning title=CI policy relaxed::{trailer.group(0)} -- reviewers must approve: " + "; ".join(found))


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
    if args.base_ref:
        check_relaxation(args.base_ref, policy)
    print(f"ci_policy: {'FAIL' if errors else 'PASS'} ({len(errors)} violation(s))")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

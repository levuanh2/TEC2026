"""Mutation ratchet: a module's mutation result may not get worse than the
triaged baseline in scripts/ci/policy/mutation.json (docs/MUTATION_BASELINE.md).

    cd backend && python ../scripts/ci/mutation_ratchet.py --module carbon/engine.py \
        --junit mutation-report/carbon_engine_py.junit.xml \
        --survivors mutation-report/carbon_engine_py.survivors.diff

Per module the policy holds the module's sha256 at triage time, the mutant
total, min_killed / max_survived and every accepted survivor with its class and
reason. Fails (exit 1) when:

  * the policy is inconsistent: accepted survivors != max_survived, or
    min_killed + max_survived != total;
  * an accepted survivor is class A (a real test gap is a test to write, never
    an accepted survivor), has no reason, or is class E (a product/science
    decision) without a `decision` reference;
  * the module changed since triage (sha256): mutmut numbers mutants by
    position, so every survivor must be re-triaged;
  * the mutant total differs, killed < min_killed or survived > max_survived;
  * a survivor is not in the accepted list -- with the module unchanged, its id
    is the same mutant, so a new survivor is a regression, not a renumbering.

Raising min_killed / lowering max_survived is the ratchet. The policy file sits
under scripts/ci/ (CODEOWNERS; a change needs a CI-Policy-Change trailer).
Standard library only. Self-test: scripts/ci/mutation_ratchet_selftest.py.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "scripts" / "ci" / "policy" / "mutation.json"
MODULE_ROOT = ROOT / "backend"
CLASSES = {"A": "real test gap", "B": "equivalent", "C": "unreachable", "D": "low value", "E": "product/science decision"}


def counts(junit: Path) -> tuple[int, int]:
    cases = list(ET.parse(junit).iter("testcase"))
    survived = sum(1 for c in cases if c.find("failure") is not None)
    return len(cases) - survived, survived


def survivor_ids(diff: Path) -> list[str]:
    return re.findall(r"^# mutant (\d+)$", diff.read_text(encoding="utf-8"), re.M)


def module_sha256(path: Path) -> str:
    """Line endings normalized: a Windows checkout and the Linux runner agree."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def policy_errors(policy: dict) -> list[str]:
    errors: list[str] = []
    accepted: dict[str, dict] = policy["accepted_survivors"]
    if len(accepted) != policy["max_survived"]:
        errors.append(f"policy lists {len(accepted)} accepted survivors but max_survived is {policy['max_survived']}")
    if policy["min_killed"] + policy["max_survived"] != policy["total"]:
        errors.append(f"min_killed {policy['min_killed']} + max_survived {policy['max_survived']} != total {policy['total']}")
    for mutant, entry in accepted.items():
        cls = entry.get("class")
        if cls not in CLASSES or cls == "A":
            errors.append(f"accepted survivor {mutant}: class {cls!r} -- must be B, C, D or E (A is a test to write)")
        if not str(entry.get("reason", "")).strip():
            errors.append(f"accepted survivor {mutant}: no reason")
        if cls == "E" and not str(entry.get("decision", "")).strip():
            errors.append(f"accepted survivor {mutant}: class E needs a recorded product/science `decision`")
    return errors


def check(module: str, junit: Path, survivors: Path, *, policy_path: Path = POLICY, module_root: Path = MODULE_ROOT) -> list[str]:
    modules = json.loads(policy_path.read_text(encoding="utf-8"))["modules"]
    policy = modules.get(module)
    if policy is None:
        return [f"{module} has no entry in {policy_path.name}"]
    errors = policy_errors(policy)

    actual_sha = module_sha256(module_root / module)
    if actual_sha != policy["module_sha256"]:
        errors.append(f"{module} changed since triage (sha256 {actual_sha[:12]} != {policy['module_sha256'][:12]}): "
                      "mutant ids moved -- re-run, re-triage every survivor and update the policy")

    killed, survived = counts(junit)
    print(f"{module}: {killed}/{killed + survived} killed, {survived} survived "
          f"(ratchet: total {policy['total']}, killed >= {policy['min_killed']}, survived <= {policy['max_survived']})")
    if killed + survived != policy["total"]:
        errors.append(f"{killed + survived} mutants, policy total is {policy['total']}")
    if killed < policy["min_killed"]:
        errors.append(f"killed {killed} < min_killed {policy['min_killed']}")
    if survived > policy["max_survived"]:
        errors.append(f"survived {survived} > max_survived {policy['max_survived']}")

    ids = survivor_ids(survivors)
    if len(ids) != survived:
        errors.append(f"survivors diff lists {len(ids)} mutants, junit counts {survived} survivors")
    accepted = policy["accepted_survivors"]
    for mutant in ids:
        if mutant not in accepted:
            errors.append(f"mutant {mutant} survived and is not an accepted survivor -- kill it, or classify it "
                          "(docs/MUTATION_BASELINE.md)")
    newly_killed = sorted(set(accepted) - set(ids), key=int)
    if newly_killed and not errors:
        print(f"note: accepted survivors now killed: {', '.join(newly_killed)} -- tighten the ratchet")
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--module", required=True)
    ap.add_argument("--junit", required=True, type=Path)
    ap.add_argument("--survivors", required=True, type=Path)
    ap.add_argument("--policy", type=Path, default=POLICY)
    ap.add_argument("--module-root", type=Path, default=MODULE_ROOT)
    args = ap.parse_args(argv)

    errors = check(args.module, args.junit, args.survivors, policy_path=args.policy, module_root=args.module_root)
    for e in errors:
        print(f"::error title=Mutation ratchet::{args.module}: {e}")
    print(f"mutation ratchet {args.module}: {'FAIL' if errors else 'PASS'}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

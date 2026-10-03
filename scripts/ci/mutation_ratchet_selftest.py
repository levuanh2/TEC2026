"""Synthetic-input test of mutation_ratchet.py: only a result that is no worse
than the triaged policy, on the triaged module, may pass.

    python scripts/ci/mutation_ratchet_selftest.py

Standard library only; writes to a temporary directory.
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mutation_ratchet as ratchet  # noqa: E402

MODULE = "pkg/mod.py"
SOURCE = b"def f(x):\n    return x + 1\n"


def junit(killed: int, survived: int) -> str:
    cases = [f'<testcase name="k{i}"/>' for i in range(killed)]
    cases += [f'<testcase name="s{i}"><failure message="survived"/></testcase>' for i in range(survived)]
    return f'<testsuites><testsuite name="mutmut">{"".join(cases)}</testsuite></testsuites>'


def diff(ids: list[str]) -> str:
    return "".join(f"# mutant {i}\n--- pkg/mod.py\n+++ pkg/mod.py\n@@ -1 +1 @@\n-a\n+b\n\n" for i in ids)


BASE = {
    "total": 10, "min_killed": 8, "max_survived": 2,
    "accepted_survivors": {"3": {"class": "B", "reason": "equivalent"}, "7": {"class": "D", "reason": "message text"}},
}


def run(tmp: Path, *, policy: dict, killed: int, survived_ids: list[str],
        source: bytes = SOURCE, junit_survived: int | None = None) -> int:
    (tmp / "pkg").mkdir(exist_ok=True)
    (tmp / MODULE).write_bytes(source)
    entry = copy.deepcopy(policy)
    entry.setdefault("module_sha256", ratchet.hashlib.sha256(SOURCE).hexdigest())  # the triaged source
    (tmp / "mutation.json").write_text(json.dumps({"modules": {MODULE: entry}}), encoding="utf-8")
    survived = len(survived_ids) if junit_survived is None else junit_survived
    (tmp / "junit.xml").write_text(junit(killed, survived), encoding="utf-8")
    (tmp / "survivors.diff").write_text(diff(survived_ids), encoding="utf-8")
    with contextlib.redirect_stdout(io.StringIO()):
        return ratchet.main(["--module", MODULE, "--junit", str(tmp / "junit.xml"), "--survivors", str(tmp / "survivors.diff"),
                             "--policy", str(tmp / "mutation.json"), "--module-root", str(tmp)])


def main() -> int:
    fails = 0

    def expect(want: str, label: str, **kw) -> None:
        nonlocal fails
        with tempfile.TemporaryDirectory() as d:
            got = "pass" if run(Path(d), **kw) == 0 else "fail"
        if got == want:
            print(f"ok   {label} -> {got}")
        else:
            print(f"::error title=MUTATION_RATCHET_SELFTEST::{label}: expected {want}, got {got}")
            fails += 1

    expect("pass", "exactly the baseline", policy=BASE, killed=8, survived_ids=["3", "7"])
    expect("pass", "an accepted survivor now killed", policy=BASE, killed=9, survived_ids=["3"])
    expect("pass", "CRLF checkout of the same module", policy=BASE, killed=8, survived_ids=["3", "7"],
           source=SOURCE.replace(b"\n", b"\r\n"))
    expect("fail", "one more survivor (score drops)", policy=BASE, killed=7, survived_ids=["3", "7", "5"])
    expect("fail", "new survivor swapped for a killed accepted one", policy=BASE, killed=8, survived_ids=["3", "5"])
    expect("fail", "module edited since triage", policy=BASE, killed=8, survived_ids=["3", "7"],
           source=SOURCE + b"# edit\n")
    expect("fail", "mutant total changed", policy=BASE, killed=9, survived_ids=["3", "7"])
    expect("fail", "diff and junit disagree", policy=BASE, killed=8, survived_ids=["3"], junit_survived=2)
    expect("fail", "accepted survivor of class A",
           policy={**BASE, "accepted_survivors": {**BASE["accepted_survivors"], "7": {"class": "A", "reason": "gap"}}},
           killed=8, survived_ids=["3", "7"])
    expect("fail", "accepted survivor without a reason",
           policy={**BASE, "accepted_survivors": {**BASE["accepted_survivors"], "7": {"class": "D", "reason": " "}}},
           killed=8, survived_ids=["3", "7"])
    expect("fail", "class E without a recorded decision",
           policy={**BASE, "accepted_survivors": {**BASE["accepted_survivors"], "7": {"class": "E", "reason": "science"}}},
           killed=8, survived_ids=["3", "7"])
    expect("pass", "class E with a recorded decision",
           policy={**BASE, "accepted_survivors": {**BASE["accepted_survivors"],
                                                  "7": {"class": "E", "reason": "science", "decision": "docs/X.md"}}},
           killed=8, survived_ids=["3", "7"])
    expect("fail", "ceiling raised without naming the survivor", policy={**BASE, "max_survived": 3, "min_killed": 7},
           killed=7, survived_ids=["3", "7", "5"])
    expect("fail", "min_killed + max_survived != total", policy={**BASE, "min_killed": 7}, killed=8, survived_ids=["3", "7"])

    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "mutation.json").write_text(json.dumps({"modules": {}}), encoding="utf-8")
        (Path(d) / "j.xml").write_text(junit(1, 0), encoding="utf-8")
        (Path(d) / "s.diff").write_text("", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            rc = ratchet.main(["--module", MODULE, "--junit", str(Path(d) / "j.xml"), "--survivors", str(Path(d) / "s.diff"),
                               "--policy", str(Path(d) / "mutation.json"), "--module-root", d])
        print(f"{'ok  ' if rc else '::error title=MUTATION_RATCHET_SELFTEST::'} module without a policy entry -> "
              f"{'fail' if rc else 'pass'}")
        fails += 0 if rc else 1

    print(f"mutation ratchet self-test: {'FAIL' if fails else 'PASS'} ({fails} unexpected)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())

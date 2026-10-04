"""Synthetic-input test of the backend dependency lock gates: a test job may not
move a package of backend/constraints.txt, statically or at runtime.

    python scripts/ci/dep_lock_selftest.py

* ci_policy CI_UNCONSTRAINED_INSTALL: a job that installs the backend and then
  anything else must pass `-c backend/constraints.txt` (path resolved against
  the step's working-directory) and prove the lock afterwards.
* dep_audit --drift --lock-subset: extra test-only packages pass; a locked
  package bumped, downgraded or missing fails. The two-way --strict drift of a
  clean venv still refuses extras (not weakened).

Standard library + PyYAML (as ci_policy.py); writes to a temporary directory.
"""
from __future__ import annotations

import contextlib
import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ci_policy  # noqa: E402
import dep_audit  # noqa: E402

failures: list[str] = []


def check(label: str, ok: bool) -> None:
    print(f"{'ok  ' if ok else 'FAIL'} {label}")
    if not ok:
        failures.append(label)


# ------------------------------------------------- static install contract
VERIFY = 'python scripts/ci/dep_audit.py --drift "$RUNNER_TEMP/f.txt" --lock-subset'
TORCH = 'python -m pip install --index-url https://download.pytorch.org/whl/cpu "torch>=2.12"'


def job(*runs: str, wd: str | None = None) -> dict:
    j = {"steps": [{"run": r} for r in runs]}
    if wd:
        j["defaults"] = {"run": {"working-directory": wd}}
    return {"jobs": {"j": j}}


def problems(doc: dict) -> list[str]:
    return ci_policy.install_constraint_problems("wf.yml", doc)


check("constrained extras + proof after them pass", not problems(job(
    "python -m pip install -r backend/requirements.txt\n"
    f"{TORCH.replace('install', 'install -c backend/constraints.txt', 1)}\n"
    "python -m pip install -c backend/constraints.txt -r ml/requirements.txt", VERIFY)))
check("working-directory backend: `-c constraints.txt` resolves to the lock", not problems(job(
    "python -m pip install -r requirements.txt\n"
    "python -m pip install -c constraints.txt -r ../ml/requirements.txt",
    VERIFY.replace("scripts/", "../scripts/"), wd="backend")))
check("backend only (lock applied by requirements.txt) needs no proof", not problems(job(
    'python -m pip install -r backend/requirements.txt "pytest-cov==7.1.0"')))
check("a job without the backend is out of scope", not problems(job(
    'python -m pip install --quiet "pip-audit==2.10.1"')))
check("unconstrained torch next to the backend fails", any("torch" in p for p in problems(job(
    f"python -m pip install -r backend/requirements.txt\n{TORCH}", VERIFY))))
check("unconstrained ml/requirements.txt fails", any("ml/requirements" in p for p in problems(job(
    "python -m pip install -r backend/requirements.txt\npython -m pip install -r ml/requirements.txt", VERIFY))))
check("a constraint that is not the backend lock fails", bool(problems(job(
    "python -m pip install -r backend/requirements.txt\n"
    "python -m pip install -c other/constraints.txt -r ml/requirements.txt", VERIFY))))
check("`-c constraints.txt` from the repo root is not the lock", bool(problems(job(
    "python -m pip install -r backend/requirements.txt\n"
    "python -m pip install -c constraints.txt -r ml/requirements.txt", VERIFY))))
check("constrained extras without the proof fail", any("lock-subset" in p for p in problems(job(
    "python -m pip install -r backend/requirements.txt\n"
    "python -m pip install -c backend/constraints.txt -r ml/requirements.txt"))))
check("a proof that runs before the last install fails", any("lock-subset" in p for p in problems(job(
    "python -m pip install -r backend/requirements.txt", VERIFY,
    "python -m pip install -c backend/constraints.txt -r ml/requirements.txt"))))

# ------------------------------------------------------- runtime lock proof
LOCK = "# comment == ignored\nPyJWT==2.15.1\npillow==12.3.0\npackaging==26.3\ntyping_extensions==4.16.0\n"
EXACT = "pyjwt==2.15.1\nPillow==12.3.0\npackaging==26.3\ntyping-extensions==4.16.0\n"


def run_drift(freeze: str, *, subset: bool, strict: bool = True) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        lock, frz = Path(tmp) / "constraints.txt", Path(tmp) / "freeze.txt"
        lock.write_text(LOCK, encoding="utf-8")
        frz.write_text(freeze, encoding="utf-8")
        saved, dep_audit.DRIFT_BASELINE = dep_audit.DRIFT_BASELINE, lock
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                return dep_audit.drift(frz, strict, subset=subset)
        finally:
            dep_audit.DRIFT_BASELINE = saved


EXTRAS = EXACT + "torch==2.14.1+cpu\nnumpy==2.4.6\n"
check("subset: exact lock passes", run_drift(EXACT, subset=True) == 0)
check("subset: extra test-only packages pass", run_drift(EXTRAS, subset=True) == 0)
check("subset: typing_extensions bumped fails",
      run_drift(EXTRAS.replace("typing-extensions==4.16.0", "typing-extensions==4.17.0"), subset=True) == 1)
check("subset: pillow downgraded fails", run_drift(EXTRAS.replace("Pillow==12.3.0", "Pillow==11.0.0"), subset=True) == 1)
check("subset: packaging missing fails", run_drift(EXTRAS.replace("packaging==26.3\n", ""), subset=True) == 1)
check("subset fails even without --strict", run_drift(EXTRAS.replace("pyjwt==2.15.1", "pyjwt==2.16.0"),
                                                      subset=True, strict=False) == 1)
check("two-way strict drift: exact passes", run_drift(EXACT, subset=False) == 0)
check("two-way strict drift still refuses extras", run_drift(EXTRAS, subset=False) == 1)

print(f"dep lock selftest: {'FAIL' if failures else 'PASS'} ({len(failures)} failure(s))")
sys.exit(1 if failures else 0)

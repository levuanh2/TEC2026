"""Give the throw-away CI Supabase stack the shape the hosted project has.

    python scripts/ci/seed_ci_db.py      # after scripts/ci/supabase_stack.sh

Refuses to run unless BOTH SUPABASE_URL and SUPABASE_DB_URL point at a local
stack (127.0.0.1/localhost): it creates users and data through both, and must
never be aimed at a hosted project.

Some real-database tests look up the demo tenant instead of building their own
rows, so the empty CI database is provisioned the way the hosted one was, with
the project's own tools and documented steps only:

0. `backend/scripts/import_factor_set.py --apply --publish`, then `--verify`
   -- the published emission factor set, imported from the YAML exactly as on
   hosted (the Carbon persist gate refuses to write without it)
1. `backend/scripts/seed_demo_data.py`       -- DEMO-AGRICARBON-2026 tenant
2. `backend/scripts/create_farmer_qa_identity.py` -- the scoped QA farmer
3. the PRIVATE Storage buckets the baseline migration says to create via the
   Storage API (plant-images, mrv-evidence, mrv-exports), plus `knowledge-artifacts`
   for RAG V1.3-C artifact copies (docs/rag/RAG_V1_INGESTION.md)
4. one Auth user with no membership (hosted always has users outside the demo)
5. one CV model version registered through the app's own repository call,
   labelled as a CI fixture (on hosted it is registered when the model loads)

Passwords are random per run, exist only inside the runner's local stack, and
are never printed.
"""
from __future__ import annotations

import os
import secrets
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from supabase import create_client  # noqa: E402

from infrastructure.config import load_settings  # noqa: E402
from infrastructure.cv_repo import PostgresCvRepository  # noqa: E402

LOCAL_HOSTS = {"127.0.0.1", "localhost"}

BUCKETS = {
    "plant-images": {"public": False, "allowed_mime_types": ["image/jpeg", "image/png"], "file_size_limit": 10 * 1024 * 1024},
    "mrv-evidence": {"public": False, "file_size_limit": 50 * 1024 * 1024},
    "mrv-exports": {"public": False, "file_size_limit": 50 * 1024 * 1024},
    # RAG V1.3-C controlled artifact copies (ST1): no storage.objects policy, service role only.
    "knowledge-artifacts": {"public": False, "allowed_mime_types": ["text/markdown", "text/plain", "application/pdf"],
                            "file_size_limit": 50 * 1024 * 1024},
}


def password() -> str:
    return f"Ci-{secrets.token_urlsafe(18)}"


def run(script: str, env: dict[str, str] | None = None, args: tuple[str, ...] = ()) -> None:
    print(f"-- {script} {' '.join(args)}".rstrip(), flush=True)
    subprocess.run([sys.executable, f"scripts/{script}", *args], cwd=BACKEND,
                   env={**os.environ, **(env or {})}, check=True)


def main() -> int:
    settings = load_settings()
    url, service_key = settings.require_supabase()
    # BOTH connections must be local: the API URL (supabase-py, Auth admin,
    # Storage) and the direct Postgres URL (factor import, CV repository).
    # A missing DB URL is refused too -- never "probably fine".
    targets = {"SUPABASE_URL": url, "SUPABASE_DB_URL": settings.supabase_db_url or ""}
    for name, value in targets.items():
        host = urlparse(value).hostname
        if host not in LOCAL_HOSTS:
            sys.exit(f"refusing to seed: {name} host {host!r} is not local; this script only provisions a local CI stack")

    run("import_factor_set.py", args=("--apply", "--publish"))
    run("import_factor_set.py", args=("--verify",))
    run("seed_demo_data.py", {"MANAGER_PASSWORD": password(), "ENTERPRISE_PASSWORD": password()})
    run("create_farmer_qa_identity.py", {"QA_FARMER_EMAIL": "ci-farmer@agricarbon-ci.invalid", "QA_FARMER_PASSWORD": password()})

    admin = create_client(url, service_key)
    existing = {b.id for b in admin.storage.list_buckets()}
    for name, options in BUCKETS.items():
        if name not in existing:
            admin.storage.create_bucket(name, options=options)
    print(f"-- private buckets: {', '.join(BUCKETS)}")

    admin.auth.admin.create_user({"email": "ci-outsider@agricarbon-ci.invalid", "password": password(), "email_confirm": True})
    print("-- one user with no organization membership")

    PostgresCvRepository(settings).get_or_create_model_version(
        version_code="ci-fixture", model_name="CI fixture (not a trained model)",
        test_dataset_name="none", test_dataset_version=None, test_sample_count=None,
        accuracy=0.0, confusion_matrix={}, confidence_threshold=0.5,
        source_reference="scripts/ci/seed_ci_db.py",
    )
    print("-- CV model version 'ci-fixture'")
    return 0


if __name__ == "__main__":
    sys.exit(main())

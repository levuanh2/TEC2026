"""Session-wide test safety: LOCAL database / Supabase only (tests/_db_target.py).

Runs at conftest import -- before pytest imports any test module, i.e. before any module-level
load_settings() can pull the HOSTED project from backend/.env. A non-local target from .env is
neutralized (the CI no-DB state); one set explicitly in the environment aborts the session;
only ALLOW_HOSTED_DB_TESTS + AGRICARBON_HOSTED_TEST_PROJECT_REF with matching targets passes.
"""

from __future__ import annotations

import pytest

from tests._db_target import enforce

try:
    _DECISION = enforce()
except RuntimeError as exc:
    pytest.exit(str(exc), returncode=4)


def pytest_report_header(config):
    if _DECISION.action == "neutralize":
        return ["DB target guard: hosted values from backend/.env IGNORED for this session "
                f"({', '.join(_DECISION.neutralize)}); DB tests run only against a LOCAL stack"]
    if _DECISION.action == "allow-hosted":
        return ["DB target guard: " + "; ".join(_DECISION.reasons)]
    return ["DB target guard: local targets only"]

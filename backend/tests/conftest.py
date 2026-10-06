"""Session-wide test safety: LOCAL database / Supabase only (tests/_db_target.py).

The guard itself runs in tests/__init__.py, which pytest imports before this file and before any
test module, so it also holds under --noconftest / --confcutdir. Here: a clean exit (code 4) when
it refused the session, and a report header saying what it decided.
"""

from __future__ import annotations

import pytest

try:
    from tests import GUARD_DECISION as _DECISION
except RuntimeError as exc:                           # tests/__init__.py refused the session
    pytest.exit(str(exc), returncode=4)


def pytest_report_header(config):
    if _DECISION.action == "neutralize":
        return ["DB target guard: hosted values from backend/.env IGNORED for this session "
                f"({', '.join(_DECISION.neutralize)}); DB tests run only against a LOCAL stack"]
    if _DECISION.action == "allow-hosted":
        return ["DB target guard: " + "; ".join(_DECISION.reasons)]
    return ["DB target guard: local targets only (connections to any other host are refused)"]

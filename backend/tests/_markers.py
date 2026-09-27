"""Shared pytest gates. Skip reasons are matched EXACTLY by the CI skip budget
(scripts/ci/policy/policy.json), so they live in one place."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infrastructure.config import load_settings  # noqa: E402

# Drives the CONFIGURED `main.app`: without Supabase settings every read/write
# route answers 503 `backend_not_configured` before validation or auth. CI runs
# these in backend-db-integration against its local Supabase stack, where no
# skip is allowed.
requires_supabase_config = pytest.mark.skipif(
    not load_settings().auth_configured,
    reason="SUPABASE_URL/SUPABASE_PUBLISHABLE_KEY are not configured; needs the configured main.app.",
)

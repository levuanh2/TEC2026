"""The `Server-Timing` diagnostic: opt-in, and numbers only.

It exists so a latency claim can be checked from the browser instead of
estimated. That makes it a development/QA aid, not a production response
header, and it must never carry anything but counts and durations.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infrastructure import profiling  # noqa: E402

def _app(server_timing: bool):
    from fastapi import FastAPI
    from infrastructure.request_context import RequestIdMiddleware

    app = FastAPI()
    app.add_middleware(RequestIdMiddleware, server_timing=server_timing)

    @app.get("/probe")
    def probe() -> dict:
        profile = profiling.current()
        if profile is not None:
            profile.record('select farms; desc="injected", evil', 12.0)
        return {"ok": True}

    return app


def test_server_timing_is_absent_unless_explicitly_enabled():
    """It is a development/QA diagnostic. Production default is off."""
    from fastapi.testclient import TestClient

    response = TestClient(_app(server_timing=False)).get("/probe")
    assert response.status_code == 200
    assert "server-timing" not in {k.lower() for k in response.headers}


def test_server_timing_carries_only_counts_and_durations():
    from fastapi.testclient import TestClient

    header = TestClient(_app(server_timing=True)).get("/probe").headers["server-timing"]

    # Shape: total, an aggregate db entry, then one entry per label.
    assert header.startswith("total;dur=")
    assert 'db;dur=' in header and 'desc="1 calls"' in header
    # A label can never break out of the header grammar, even though labels are
    # built from code constants today and never from request input.
    assert 'desc="injected"' not in header
    assert header.count('"') % 2 == 0
    # Nothing resembling a token, a row id, or SQL.
    assert "Bearer" not in header and "select *" not in header.lower()
    assert "eyJ" not in header  # a JWT's leading base64


def test_default_settings_keep_server_timing_off(monkeypatch):
    from infrastructure.config import load_settings

    monkeypatch.delenv("AGRICARBON_SERVER_TIMING", raising=False)
    assert load_settings().server_timing is False
    monkeypatch.setenv("AGRICARBON_SERVER_TIMING", "0")
    assert load_settings().server_timing is False
    monkeypatch.setenv("AGRICARBON_SERVER_TIMING", "1")
    assert load_settings().server_timing is True

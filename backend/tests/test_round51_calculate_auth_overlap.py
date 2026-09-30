"""Round 5.1: the calculate route overlaps the Auth identity lookup with the
RLS read check — and nothing else.

Invariants kept from B4: the write rule (`private.user_can_write_crop`) is only
evaluated after the read check passed, an out-of-scope caller gets the read
check's 404, and the engine never runs without both checks passing. New: the
Auth server is asked who the JWT belongs to once, not once per check.
"""
from __future__ import annotations

import sys
import threading
from contextlib import nullcontext
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api  # noqa: E402
from infrastructure.persist_access import PostgresCropPersistChecker  # noqa: E402
from tests.test_carbon_persist_authorization import OTHER, SEASON, Readers, RecordingCarbon  # noqa: E402


class ScriptedCursor:
    def __init__(self, allowed: bool):
        self.allowed, self.statements = allowed, []

    def execute(self, sql, params=None):
        self.statements.append((" ".join(sql.split()), list(params or [])))

    def fetchone(self):
        return {"allowed": self.allowed}


class SlowReaders(Readers):
    """Read check that only answers once the identity lookup has started."""

    def __init__(self, readable, started: threading.Event):
        super().__init__(readable)
        self.started = started

    def assert_can_access(self, token, crop_season_id):
        assert self.started.wait(5), "identity lookup did not run alongside the read check"
        super().assert_can_access(token, crop_season_id)


def client_for(*, readable, allowed=True, overlap_probe=False):
    cursor, carbon, lookups, started = ScriptedCursor(allowed), RecordingCarbon(), [], threading.Event()

    def user_id_for(token):
        lookups.append(token)
        started.set()
        return "user-1"

    connection = type("Conn", (), {"cursor": lambda self: nullcontext(cursor)})()
    checker = PostgresCropPersistChecker(settings=None, user_id_for=user_id_for, connect=lambda: nullcontext(connection))
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api._service] = lambda: carbon
    app.dependency_overrides[api._access_checker] = (
        (lambda: SlowReaders(readable, started)) if overlap_probe else (lambda: Readers(readable))
    )
    app.dependency_overrides[api._persist_checker] = lambda: checker
    return TestClient(app, headers={"Authorization": "Bearer jwt"}), carbon, cursor, lookups


def post(client, season=SEASON):
    return client.post("/v1/carbon/calculate", json={"crop_season_id": season, "water_regime_scenario": "as_recorded"})


def test_identity_lookup_runs_while_the_read_check_is_in_flight():
    client, carbon, cursor, lookups = client_for(readable={SEASON}, overlap_probe=True)
    assert post(client).status_code == 200
    assert lookups == ["jwt"] and carbon.calculated == [SEASON]


def test_writer_is_checked_once_with_the_verified_identity():
    client, carbon, cursor, lookups = client_for(readable={SEASON})
    response = post(client)
    assert response.status_code == 200 and response.json()["calculation_id"] == "calc-1"
    assert lookups == ["jwt"]  # one Auth round trip, shared by both checks
    claims = [params for sql, params in cursor.statements if "set_config('request.jwt.claims', %s" in sql]
    assert claims and '"sub": "user-1"' in claims[0][0]
    assert any("private.user_can_write_crop" in sql for sql, _ in cursor.statements)


def test_out_of_scope_caller_never_reaches_the_write_rule():
    client, carbon, cursor, _ = client_for(readable={SEASON})
    response = post(client, OTHER)
    assert response.status_code == 404
    assert response.json()["detail"]["error"]["code"] == "crop_not_found"
    assert cursor.statements == [] and carbon.calculated == []


def test_reader_without_write_authority_is_404_and_nothing_is_calculated():
    client, carbon, cursor, _ = client_for(readable={SEASON}, allowed=False)
    response = post(client)
    assert response.status_code == 404
    assert response.json()["detail"]["error"]["code"] == "crop_not_found"
    assert carbon.calculated == []


def test_missing_header_is_401_before_any_lookup():
    client, carbon, cursor, lookups = client_for(readable={SEASON})
    response = client.post("/v1/carbon/calculate", headers={"Authorization": ""},
                           json={"crop_season_id": SEASON, "water_regime_scenario": "as_recorded"})
    assert response.status_code == 401
    assert lookups == [] and cursor.statements == [] and carbon.calculated == []

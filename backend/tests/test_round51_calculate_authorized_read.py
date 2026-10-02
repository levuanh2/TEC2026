"""Round 5.1: the calculate route's one-trip path (identity, then an authorized read).

When the service's repository can enforce the caller's read AND write rules in
the same round trip as its read (`get_crop_bundle_as`), the route asks Auth who
the caller is — overlapped with the pool checkout — and hands the verified id
to the service. The error contract is unchanged:

* no token -> 401 `missing_authorization`; a token Auth rejects -> 401;
* refused by either rule, unknown season, or no user -> 404 `crop_not_found`,
  and the engine never ran;
* allowed -> 200, and the service received exactly the verified user id.
"""
from __future__ import annotations

import sys
import threading
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api  # noqa: E402
import main  # noqa: E402
from infrastructure.auth import CropAccessError, InvalidTokenError  # noqa: E402
from infrastructure.persist_access import PostgresCropPersistChecker  # noqa: E402
from tests.test_carbon_persist_authorization import SEASON, Readers, RecordingCarbon  # noqa: E402


class AuthorizingCarbon(RecordingCarbon):
    """A service whose repository authorizes while it reads."""

    def __init__(self, allowed_users: set[str]):
        super().__init__()
        self.allowed_users, self.callers, self.sessions = allowed_users, [], 0

    def can_authorize_reads(self) -> bool:
        return True

    @contextmanager
    def session(self):
        self.sessions += 1
        yield

    def calculate(self, crop_season_id, scenario="as_recorded", *, persist=True, prepare=None, caller=None):
        self.callers.append(caller)
        if caller not in self.allowed_users:
            raise CropAccessError(f"'{crop_season_id}' không tồn tại hoặc không thuộc phạm vi truy cập.")
        return super().calculate(crop_season_id, scenario, persist=persist, prepare=prepare)


class NoReads(Readers):
    def assert_can_access(self, token, crop_season_id):  # the old PostgREST check must not run
        raise AssertionError("the PostgREST read check ran on the one-trip path")


def client(identity, allowed_users=frozenset({"user-1"}), headers={"Authorization": "Bearer jwt"}):
    carbon, lookups = AuthorizingCarbon(set(allowed_users)), []

    def user_id_for(token):
        lookups.append((token, threading.current_thread().name))
        if isinstance(identity, Exception):
            raise identity
        return identity

    main.app.dependency_overrides[api._service] = lambda: carbon
    main.app.dependency_overrides[api._access_checker] = lambda: NoReads(set())
    main.app.dependency_overrides[api._persist_checker] = lambda: PostgresCropPersistChecker(
        settings=None, user_id_for=user_id_for, connect=lambda: None)
    return TestClient(main.app, headers=headers), carbon, lookups


def post(c):
    return c.post("/v1/carbon/calculate", json={"crop_season_id": SEASON, "water_regime_scenario": "as_recorded"})


# `main` wires the configured repositories into `main.app.dependency_overrides`
# at import. Restore exactly that wiring after each test -- clearing it would
# leave every later `main.app` test in the process on 503 `backend_not_configured`.
_MAIN_OVERRIDES = dict(main.app.dependency_overrides)


def teardown_function():
    main.app.dependency_overrides.clear()
    main.app.dependency_overrides.update(_MAIN_OVERRIDES)


def test_allowed_caller_gets_the_result_and_the_service_gets_the_verified_id():
    c, carbon, lookups = client("user-1")
    r = post(c)
    assert r.status_code == 200 and r.json()["calculation_id"] == "calc-1"
    assert carbon.callers == ["user-1"] and carbon.calculated == [SEASON]
    assert len(lookups) == 1 and lookups[0][0] == "jwt"
    assert lookups[0][1] != threading.current_thread().name  # asked off the request thread (overlapped)


def test_refused_caller_is_the_same_404_and_the_engine_never_ran():
    c, carbon, _ = client("user-2")
    r = post(c)
    assert r.status_code == 404 and r.json()["detail"]["error"]["code"] == "crop_not_found"
    assert carbon.calculated == []


def test_no_user_behind_the_token_is_404_without_calling_the_service():
    c, carbon, _ = client(None)
    r = post(c)
    assert r.status_code == 404 and r.json()["detail"]["error"]["code"] == "crop_not_found"
    assert carbon.callers == []


def test_rejected_token_is_401_and_nothing_is_read():
    c, carbon, _ = client(InvalidTokenError("Token không hợp lệ hoặc đã hết hạn."))
    r = post(c)
    assert r.status_code == 401
    assert carbon.callers == []


def test_missing_token_is_the_standard_401():
    c, carbon, lookups = client("user-1", headers={})
    r = post(c)
    assert r.status_code == 401 and r.json()["detail"]["error"]["code"] == "missing_authorization"
    assert carbon.callers == [] and lookups == []

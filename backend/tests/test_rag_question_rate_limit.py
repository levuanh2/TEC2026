"""Per-user question rate limit for POST /v1/crop-seasons/{id}/questions (A12).

Unit + route tests with in-memory stand-ins; the durable store is proven on a local
Supabase stack in test_rag_question_rate_limit_db.py. The limits used here (10/min,
100/day) are the PROPOSED pilot defaults, not owner-approved values.
"""
from __future__ import annotations

import logging
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api  # noqa: E402
import rag_qa  # noqa: E402
from infrastructure import question_rate_limit as qrl  # noqa: E402
from infrastructure.auth import InvalidTokenError  # noqa: E402
from rag_qa import RagQuestionService  # noqa: E402
from tests.fixtures.rag_fakes import SEASON_ID  # noqa: E402
from tests.test_rag_qa import Carbon, Reader, gate  # noqa: E402

URL = f"/v1/crop-seasons/{SEASON_ID}/questions"
OTHER_TENANT_SEASON = "00000000-0000-4000-8000-0000000000aa"
TOKEN = "header.payload.signature-not-a-real-jwt"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
LIMITED_MESSAGE = "Bạn đã hỏi quá nhiều câu trong thời gian ngắn. Vui lòng thử lại sau."
USER_A = "11111111-1111-4111-8111-111111111111"
USER_B = "22222222-2222-4222-8222-222222222222"


class Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def limiter(per_minute=10, per_day=100, clock=None, store=None):
    store = store or qrl.InProcessQuestionRateStore(clock=clock or Clock())
    return qrl.QuestionRateLimiter(qrl.QuestionRatePolicy(per_minute, per_day), store, store_kind="memory")


@dataclass
class CountingReader(Reader):
    """Records every Core V1 read; `user` is what Supabase Auth verified for the token."""

    user: str = USER_A
    reject_token: bool = False
    used: list = field(default_factory=list)

    def __getattribute__(self, name):
        attr = object.__getattribute__(self, name)
        if callable(attr) and not name.startswith("_") and name not in {"used"}:
            object.__getattribute__(self, "used").append(name)
        return attr

    def user_id(self):
        if self.reject_token:
            raise InvalidTokenError("Token không hợp lệ hoặc đã hết hạn.")
        return self.user


def app_client(service, reader) -> TestClient:
    from main import invalid_token_exception_handler

    app = FastAPI()
    app.include_router(api.router)
    app.add_exception_handler(InvalidTokenError, invalid_token_exception_handler)
    app.dependency_overrides[api._read_repo] = lambda: reader
    app.dependency_overrides[api._rag_question_service] = lambda: service
    return TestClient(app)


def service_with(rate_limiter, carbon=None):
    return RagQuestionService(carbon_service=carbon or Carbon(), write_gate=gate(), action_tier_enabled=False,
                              rate_limiter=rate_limiter)


def ask(client, season=SEASON_ID, intent="explain", **extra):
    return client.post(f"/v1/crop-seasons/{season}/questions",
                       json={"question": "Vì sao phát thải cao?", "intent": intent, **extra}, headers=AUTH)


def error_code(response):
    return response.json()["detail"]["error"]["code"]


# -- policy / configuration ------------------------------------------------------

def test_defaults_are_the_proposed_pilot_values():
    policy = qrl.load_question_rate_policy({})
    assert (policy.per_minute, policy.per_day) == (10, 100)
    assert qrl.store_kind_from_env({}) == "postgres"


def test_limits_come_from_server_env():
    policy = qrl.load_question_rate_policy({qrl.PER_MINUTE_ENV: "3", qrl.PER_DAY_ENV: "7"})
    assert (policy.per_minute, policy.per_day) == (3, 7)


@pytest.mark.parametrize("value", ["0", "-1", "abc", "off", "1.5", "none"])
def test_there_is_no_off_or_zero_limit(value):
    with pytest.raises(qrl.QuestionRateConfigError):
        qrl.load_question_rate_policy({qrl.PER_MINUTE_ENV: value})
    with pytest.raises(qrl.QuestionRateConfigError):
        qrl.load_question_rate_policy({qrl.PER_DAY_ENV: value})


@pytest.mark.parametrize("value", ["redis", "off", "none", "disabled"])
def test_unknown_store_fails_start_up(value):
    with pytest.raises(qrl.QuestionRateConfigError):
        qrl.store_kind_from_env({qrl.STORE_ENV: value})


def test_postgres_store_needs_the_backend_db_url():
    with pytest.raises(qrl.QuestionRateConfigError):
        qrl.build_question_rate_limiter(db_url=None, env={})


def test_memory_store_is_explicit_opt_in(caplog):
    with caplog.at_level(logging.INFO, logger=qrl.logger.name):
        built = qrl.build_question_rate_limiter(db_url=None, env={qrl.STORE_ENV: "memory"})
    assert built.store_kind == "memory" and "store=memory per_minute=10 per_day=100" in caplog.text


def test_main_always_passes_a_rate_limiter_to_the_question_service():
    source = (Path(__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8")
    call = source[source.index("rag_qa.build_question_service("):]
    call = call[:call.index("\n    app.dependency_overrides")]
    assert "rate_limiter=build_question_rate_limiter(db_url=settings.supabase_db_url)" in call


# -- the in-process store ----------------------------------------------------------

def test_tenth_allowed_eleventh_refused_then_the_minute_window_slides():
    clock = Clock()
    gate_ = limiter(clock=clock)
    for _ in range(10):
        gate_.consume(USER_A)
    with pytest.raises(qrl.QuestionRateLimited) as refused:
        gate_.consume(USER_A)
    assert refused.value.window == "minute" and refused.value.retry_after_seconds == 60
    clock.now += 59.5
    with pytest.raises(qrl.QuestionRateLimited) as still:
        gate_.consume(USER_A)
    assert still.value.retry_after_seconds == 1
    clock.now += 0.5
    gate_.consume(USER_A)  # the first question left the 60 s window


def test_refused_questions_are_not_counted():
    clock = Clock()
    gate_ = limiter(per_minute=2, clock=clock)
    gate_.consume(USER_A)
    gate_.consume(USER_A)
    for _ in range(50):
        with pytest.raises(qrl.QuestionRateLimited):
            gate_.consume(USER_A)
    clock.now += 60
    gate_.consume(USER_A)
    gate_.consume(USER_A)


def test_daily_limit_and_its_reset():
    clock = Clock()
    gate_ = limiter(per_minute=1000, per_day=100, clock=clock)
    for _ in range(100):
        gate_.consume(USER_A)
        clock.now += 10
    with pytest.raises(qrl.QuestionRateLimited) as refused:
        gate_.consume(USER_A)
    assert refused.value.window == "day"
    assert refused.value.retry_after_seconds == 86_400 - 1000
    clock.now += 86_400 - 1000
    gate_.consume(USER_A)  # the first question of the day expired


def test_day_limit_spread_over_minutes_is_still_enforced():
    clock = Clock()
    gate_ = limiter(per_minute=10, per_day=25, clock=clock)
    for _ in range(25):
        gate_.consume(USER_A)
        clock.now += 61
    with pytest.raises(qrl.QuestionRateLimited) as refused:
        gate_.consume(USER_A)
    assert refused.value.window == "day"


def test_two_users_have_independent_limits():
    gate_ = limiter(per_minute=3)
    for _ in range(3):
        gate_.consume(USER_A)
    with pytest.raises(qrl.QuestionRateLimited):
        gate_.consume(USER_A)
    for _ in range(3):
        gate_.consume(USER_B)


def test_concurrent_requests_never_exceed_the_limit():
    gate_ = limiter(per_minute=10, per_day=100)
    allowed, refused = [], []
    start = threading.Barrier(40)

    def one():
        start.wait()
        try:
            gate_.consume(USER_A)
            allowed.append(1)
        except qrl.QuestionRateLimited:
            refused.append(1)
    threads = [threading.Thread(target=one) for _ in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert (len(allowed), len(refused)) == (10, 30)


def test_an_empty_user_id_is_refused_not_counted_as_anonymous():
    with pytest.raises(qrl.QuestionRateLimitUnavailable):
        limiter().consume("")


# -- the postgres store adapter (no database) ---------------------------------------

class FakeCursor:
    def __init__(self, row, fail):
        self.row, self.fail, self.executed = row, fail, []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        if self.fail:
            raise self.fail
        self.executed.append((sql, params))

    def fetchone(self):
        return self.row


class FakeConnection:
    def __init__(self, row=None, fail=None):
        self.cursor_ = FakeCursor(row, fail)

    def __call__(self, conninfo):
        assert conninfo == "postgresql://backend-only"
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def cursor(self):
        return self.cursor_


def test_postgres_store_passes_only_server_values_to_the_function():
    conn = FakeConnection(row={"allowed": False, "limit_window": "minute", "retry_after_seconds": 42})
    store = qrl.PostgresQuestionRateStore("postgresql://backend-only", connection=conn)
    decision = store.consume(USER_A, qrl.QuestionRatePolicy(10, 100))
    assert decision == qrl.QuestionRateDecision(False, "minute", 42)
    sql, params = conn.cursor_.executed[0]
    assert "private.consume_rag_question_quota" in sql and params == (USER_A, 10, 100)


@pytest.mark.parametrize("failure", [RuntimeError("function does not exist"), OSError("connection refused")])
def test_postgres_store_failure_refuses_the_question(failure, caplog):
    store = qrl.PostgresQuestionRateStore("postgresql://backend-only", connection=FakeConnection(fail=failure))
    with caplog.at_level(logging.ERROR, logger=qrl.logger.name), pytest.raises(qrl.QuestionRateLimitUnavailable):
        store.consume(USER_A, qrl.QuestionRatePolicy())
    assert "backend-only" not in caplog.text and "does not exist" not in caplog.text


def test_postgres_store_with_no_row_refuses():
    store = qrl.PostgresQuestionRateStore("postgresql://backend-only", connection=FakeConnection(row=None))
    with pytest.raises(qrl.QuestionRateLimitUnavailable):
        store.consume(USER_A, qrl.QuestionRatePolicy())


# -- the route ------------------------------------------------------------------------

def test_ten_questions_answer_and_the_eleventh_is_429_before_any_read():
    reader = CountingReader()
    client = app_client(service_with(limiter()), reader)
    for _ in range(10):
        response = ask(client)
        assert response.status_code == 200, response.text
        assert response.json()["provenance"]["llm_calls"] == 0
    reader.used.clear()
    response = ask(client)
    assert response.status_code == 429
    assert error_code(response) == "question_rate_limited"
    assert response.json()["detail"]["error"]["message"] == LIMITED_MESSAGE
    assert response.headers["Retry-After"] == "60"
    assert reader.used == ["user_id"]  # Auth verification only: no season/Carbon/knowledge read


def test_over_the_limit_is_identical_for_every_season_id():
    reader = CountingReader()
    client = app_client(service_with(limiter(per_minute=1)), reader)
    assert ask(client).status_code == 200
    bodies = []
    for season in (SEASON_ID, OTHER_TENANT_SEASON, "00000000-0000-4000-8000-00000000dead"):
        reader.used.clear()
        response = ask(client, season=season)
        assert response.status_code == 429 and reader.used == ["user_id"]
        bodies.append(response.json())
    assert bodies[0] == bodies[1] == bodies[2]


def test_changing_the_season_id_does_not_reset_the_quota():
    reader = CountingReader(visible=False)  # every season is out of scope -> 404
    client = app_client(service_with(limiter(per_minute=3)), reader)
    statuses = [ask(client, season=f"00000000-0000-4000-8000-00000000000{i}").status_code for i in range(5)]
    assert statuses == [404, 404, 404, 429, 429]


def test_two_users_through_the_route_are_independent():
    shared = limiter(per_minute=2)
    a, b = CountingReader(user=USER_A), CountingReader(user=USER_B)
    service = service_with(shared)
    client_a, client_b = app_client(service, a), app_client(service, b)
    assert [ask(client_a).status_code for _ in range(3)] == [200, 200, 429]
    assert [ask(client_b).status_code for _ in range(2)] == [200, 200]


class SpyStore:
    def __init__(self):
        self.calls = []

    def consume(self, user_id, policy):
        self.calls.append(user_id)
        return qrl.QuestionRateDecision(True)


def test_invalid_expired_or_revoked_jwt_is_401_and_never_counted():
    spy = SpyStore()
    client = app_client(service_with(limiter(store=spy)), CountingReader(reject_token=True))
    response = ask(client)
    assert response.status_code == 401 and error_code(response) == "unauthenticated"
    assert spy.calls == []


def test_missing_token_is_401_before_the_service():
    spy = SpyStore()
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api._rag_question_service] = lambda: service_with(limiter(store=spy))
    response = TestClient(app).post(URL, json={"question": "?", "intent": "explain"})
    assert response.status_code == 401 and spy.calls == []


def test_the_quota_key_is_the_verified_user_not_anything_in_the_request():
    spy = SpyStore()
    client = app_client(service_with(limiter(store=spy)), CountingReader(user=USER_B))
    response = client.post(URL, json={"question": "?", "intent": "explain"},
                           headers={**AUTH, "X-User-Id": USER_A, "X-Forwarded-For": "10.0.0.1",
                                    "X-RateLimit-Limit": "100000"})
    assert response.status_code == 200 and spy.calls == [USER_B]


@pytest.mark.parametrize("extra", [{"user_id": USER_A}, {"rate_limit": 1000}, {"quota": {"per_minute": 999}}])
def test_the_body_cannot_name_a_user_or_change_the_quota(extra):
    spy = SpyStore()
    client = app_client(service_with(limiter(store=spy)), CountingReader())
    response = ask(client, **extra)
    assert response.status_code == 422 and spy.calls == []


@pytest.mark.parametrize("intent", ["recommend", "what_if"])
def test_action_tier_lock_still_refuses_first_and_costs_no_quota(intent):
    spy = SpyStore()
    reader = CountingReader()
    client = app_client(service_with(limiter(store=spy)), reader)
    extra = {"what_if_scenario": "awd"} if intent == "what_if" else {}
    response = ask(client, intent=intent, **extra)
    assert response.status_code == 503 and error_code(response) == "action_tier_disabled"
    assert spy.calls == [] and reader.used == []


def test_store_unavailable_is_503_and_reads_nothing():
    class Broken:
        def consume(self, user_id, policy):
            raise qrl.QuestionRateLimitUnavailable("down")
    reader = CountingReader()
    client = app_client(service_with(limiter(store=Broken())), reader)
    response = ask(client)
    assert response.status_code == 503 and error_code(response) == "question_rate_limit_unavailable"
    assert "Retry-After" not in response.headers
    assert reader.used == ["user_id"]


def test_rate_limit_logs_carry_no_token_user_or_question(caplog):
    client = app_client(service_with(limiter(per_minute=1)), CountingReader())
    with caplog.at_level(logging.INFO):
        ask(client)
        ask(client)
    assert "rag_question_rate_limited" in caplog.text and "window=minute" in caplog.text
    for secret in (TOKEN, USER_A, "Vì sao phát thải cao?"):
        assert secret not in caplog.text


def test_other_routes_are_not_rate_limited():
    """The limiter lives in the Q&A service only; Carbon, MRV and journal routes never see it."""
    source = (Path(__file__).resolve().parent.parent / "api.py").read_text(encoding="utf-8")
    assert "question_rate_limit" not in source and "rate_limiter" not in source


def test_http_mapping():
    assert rag_qa.HTTP_STATUS["question_rate_limited"] == 429
    assert rag_qa.HTTP_STATUS["question_rate_limit_unavailable"] == 503

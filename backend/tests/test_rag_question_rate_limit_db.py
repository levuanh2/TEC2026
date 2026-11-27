"""private.consume_rag_question_quota on a LOCAL Supabase stack (migration 20261106090000).

Proves the durable store: atomic under concurrency, sliding minute/day windows, per-user
isolation, backend-only access, and the real route with real Supabase Auth JWTs (an
over-limit request and a revoked token). Users are synthetic and removed afterwards.
"""
from __future__ import annotations

import sys
import threading
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.test_rag_retrieval_db import _DB_URL, _SETTINGS, env, pytestmark, run_token  # noqa: E402,F401

FN = "select allowed, limit_window, retry_after_seconds from private.consume_rag_question_quota(%s, %s, %s)"


@pytest.fixture(scope="module")
def users():
    from supabase import create_client

    url, service = _SETTINGS.require_supabase()
    admin = create_client(url, service)
    run = uuid.uuid4().hex[:8]
    made = []
    try:
        for name in ("a", "b", "c", "d", "e"):
            made.append(str(admin.auth.admin.create_user(
                {"email": f"rl-{run}-{name}@agricarbon-ci.invalid", "password": f"Rl-{uuid.uuid4().hex}!9",
                 "email_confirm": True}).user.id))
        yield made
    finally:
        for user_id in made:
            admin.auth.admin.delete_user(user_id)


def consume(user_id, per_minute=10, per_day=100):
    import psycopg

    with psycopg.connect(_DB_URL) as conn:
        return conn.execute(FN, (user_id, per_minute, per_day)).fetchone()


def events(user_id):
    import psycopg

    with psycopg.connect(_DB_URL) as conn:
        return conn.execute("select count(*) from private.rag_question_events where user_id = %s",
                            (user_id,)).fetchone()[0]


def backdate(user_id, *ages_seconds):
    import psycopg

    with psycopg.connect(_DB_URL) as conn:
        conn.execute("delete from private.rag_question_events where user_id = %s", (user_id,))
        for age in ages_seconds:
            conn.execute("insert into private.rag_question_events (user_id, asked_at)"
                         " values (%s, clock_timestamp() - make_interval(secs => %s))", (user_id, age))


def test_ten_allowed_then_refused_for_the_minute(users):
    user = users[0]
    assert [consume(user)[0] for _ in range(10)] == [True] * 10
    allowed, window, retry = consume(user)
    assert (allowed, window) == (False, "minute") and 1 <= retry <= 60
    assert events(user) == 10  # the refused question was not recorded


def test_minute_window_slides(users):
    user = users[1]
    backdate(user, *([61] * 10))
    assert consume(user)[0] is True
    backdate(user, *([30] * 10))
    allowed, window, retry = consume(user)
    assert (allowed, window) == (False, "minute") and 29 <= retry <= 31


def test_day_limit_retry_after_and_cleanup(users):
    user = users[2]
    backdate(user, *([7200] * 100), 90_000, 90_000)  # 100 within 24 h, 2 older than 24 h
    allowed, window, retry = consume(user)
    assert (allowed, window) == (False, "day")
    assert 86_400 - 7200 - 5 <= retry <= 86_400 - 7200 + 1
    assert events(user) == 100  # the >24 h rows were deleted


def test_users_are_independent(users):
    a, b = users[3], users[4]
    backdate(a)
    backdate(b)
    for _ in range(2):
        assert consume(a, per_minute=2)[0] is True
    assert consume(a, per_minute=2)[0] is False
    assert consume(b, per_minute=2)[0] is True


def test_concurrent_questions_never_exceed_the_limit(users):
    import psycopg

    user = users[4]
    backdate(user)
    results, errors = [], []
    start = threading.Barrier(30)

    def one():
        try:
            with psycopg.connect(_DB_URL) as conn:
                start.wait()
                results.append(conn.execute(FN, (user, 10, 100)).fetchone()[0])
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
    threads = [threading.Thread(target=one) for _ in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert results.count(True) == 10 and results.count(False) == 20
    assert events(user) == 10


@pytest.mark.parametrize("args", [(None, 10, 100), ("u", 0, 100), ("u", 10, 0), ("u", -1, 100), ("u", 10, None)])
def test_invalid_arguments_are_refused(users, args):
    import psycopg

    user = users[0] if args[0] == "u" else None
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        consume(user, args[1], args[2])


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_client_roles_cannot_call_the_function_or_read_the_table(users, role):
    import psycopg

    for statement, params in ((FN, (users[0], 1000, 1000)),
                              ("select count(*) from private.rag_question_events", None),
                              ("insert into private.rag_question_events values (%s, now())", (users[0],))):
        with psycopg.connect(_DB_URL) as conn:
            conn.execute(f"set role {role}")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(statement, params)


# -- the real route: real JWTs, real Auth verification, the durable store --------------

@pytest.fixture(scope="module")
def http(env):  # noqa: F811
    from fastapi.testclient import TestClient

    import api
    import main
    from infrastructure.question_rate_limit import (PostgresQuestionRateStore, QuestionRateLimiter,
                                                    QuestionRatePolicy)
    from infrastructure.recommendation_repo import PostgresRecommendationRepository
    from rag_qa import RagQuestionService

    limiter = QuestionRateLimiter(QuestionRatePolicy(per_minute=2, per_day=100),
                                  PostgresQuestionRateStore(_DB_URL), store_kind="postgres")
    service = RagQuestionService(carbon_service=main._service_singleton, action_tier_enabled=False,
                                 write_gate=PostgresRecommendationRepository(_SETTINGS).assert_can_write,
                                 rate_limiter=limiter)
    previous = main.app.dependency_overrides.get(api._rag_question_service)
    main.app.dependency_overrides[api._rag_question_service] = lambda: service
    try:
        client = TestClient(main.app)

        def ask(token, season, intent="explain"):
            return client.post(f"/v1/crop-seasons/{season}/questions",
                               json={"question": f"awd {run_token(env)}", "intent": intent},
                               headers={"Authorization": f"Bearer {token}"})
        yield ask
    finally:
        if previous is None:
            main.app.dependency_overrides.pop(api._rag_question_service, None)
        else:
            main.app.dependency_overrides[api._rag_question_service] = previous


def test_route_limits_the_verified_user_across_season_ids(http, env):
    token = env["tokens"]["member"]
    backdate(str(env["users"]["member"]))
    first = [http(token, env["season_member"]).status_code for _ in range(2)]
    over_own = http(token, env["season_member"])
    over_foreign = http(token, env["season_outsider"])
    assert first == [200, 200]
    assert over_own.status_code == over_foreign.status_code == 429
    assert over_own.json() == over_foreign.json()
    assert over_own.json()["detail"]["error"]["code"] == "question_rate_limited"
    assert int(over_own.headers["Retry-After"]) >= 1
    # another user is unaffected
    backdate(str(env["users"]["outsider"]))
    assert http(env["tokens"]["outsider"], env["season_outsider"]).status_code == 200


def test_route_action_tier_stays_locked_and_uncounted(http, env):
    user = str(env["users"]["viewer"])
    backdate(user)
    response = http(env["tokens"]["viewer"], env["season_member"], intent="recommend")
    assert response.status_code == 503 and response.json()["detail"]["error"]["code"] == "action_tier_disabled"
    assert events(user) == 0


def test_route_revoked_token_is_401_and_not_counted(http, env):
    import httpx

    url, _ = _SETTINGS.require_supabase()
    _, publishable = _SETTINGS.require_publishable()
    token = env["tokens"]["leaver"]
    user = str(env["users"]["leaver"])
    backdate(user)
    httpx.post(f"{url}/auth/v1/logout?scope=global", headers={"apikey": publishable,
               "Authorization": f"Bearer {token}"}, timeout=30).raise_for_status()
    response = http(token, env["season_member"])
    assert response.status_code == 401
    assert events(user) == 0


# -- which database role runs the quota function (release preflight evidence) ----------
#
# The API calls the function over SUPABASE_DB_URL (infrastructure/pg_pool.py: no SET ROLE, no
# PostgREST), so the login in that URL executes it. The function is SECURITY INVOKER and the table
# forces RLS with no policy, so that login needs BYPASSRLS (or superuser) plus EXECUTE, USAGE on
# schema private and select/insert/delete on the table. RAG_QA_PILOT_SAFEGUARDS.md §5 checks the
# same facts read-only on the target database before the migration and before the deploy.

QUOTA_FN = "private.consume_rag_question_quota(uuid,integer,integer)"
EVENTS = "private.rag_question_events"


def test_the_backend_login_runs_the_function_and_meets_its_requirements(users):
    import psycopg

    with psycopg.connect(_DB_URL) as conn:
        login = conn.execute("select current_user").fetchone()[0]
        superuser, bypassrls = conn.execute(
            "select rolsuper, rolbypassrls from pg_roles where rolname = current_user").fetchone()
        grants = conn.execute(
            "select has_function_privilege(current_user, %s, 'execute'),"
            " has_schema_privilege(current_user, 'private', 'usage'),"
            " has_table_privilege(current_user, %s, 'select'), has_table_privilege(current_user, %s, 'insert'),"
            " has_table_privilege(current_user, %s, 'delete')", (QUOTA_FN, EVENTS, EVENTS, EVENTS)).fetchone()
        rls = conn.execute("select relrowsecurity, relforcerowsecurity from pg_class where oid = %s::regclass",
                           (EVENTS,)).fetchone()
        policies = conn.execute("select count(*) from pg_policies"
                                " where schemaname = 'private' and tablename = 'rag_question_events'").fetchone()[0]
        security_definer = conn.execute("select prosecdef from pg_proc where oid = %s::regprocedure",
                                        (QUOTA_FN,)).fetchone()[0]
    assert rls == (True, True) and policies == 0 and security_definer is False
    assert superuser or bypassrls, f"{login} would hit the forced RLS on every question (503)"
    assert all(grants), (login, grants)


def test_the_postgrest_service_role_is_not_the_role_that_runs_it(users):
    """service_role holds the migration's EXECUTE grant but no table privilege: under SECURITY INVOKER
    a call as service_role fails. The API never calls the function as service_role."""
    import psycopg

    with psycopg.connect(_DB_URL) as conn:
        conn.execute("set role service_role")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute(FN, (users[0], 1000, 1000))


@contextmanager
def _login_without_bypassrls(conninfo):
    """A connection acting as a fresh role that has every grant but NOT BYPASSRLS. Everything runs in
    one transaction that is rolled back, so the role never exists outside this block."""
    import psycopg

    role = f"rl_nobypass_{uuid.uuid4().hex[:8]}"
    conn = psycopg.connect(conninfo)
    try:
        conn.execute(f"create role {role} nologin nobypassrls")
        conn.execute(f"grant usage on schema private to {role}")
        conn.execute(f"grant execute on function {QUOTA_FN} to {role}")
        conn.execute(f"grant select, insert, delete on {EVENTS} to {role}")
        conn.execute(f"grant {role} to current_user")
        conn.execute(f"set local role {role}")
        yield conn
    finally:
        conn.rollback()
        conn.close()


def test_a_login_without_bypassrls_fails_closed_before_any_read(users):
    import psycopg

    import rag_qa
    from infrastructure.question_rate_limit import (PostgresQuestionRateStore, QuestionRateLimiter,
                                                    QuestionRateLimitUnavailable, QuestionRatePolicy)
    from recommendation.rag import RagIntent

    user = users[1]
    backdate(user)
    store = PostgresQuestionRateStore(_DB_URL, connection=_login_without_bypassrls)
    with pytest.raises(QuestionRateLimitUnavailable) as unavailable:
        store.consume(user, QuestionRatePolicy())
    cause = unavailable.value.__cause__
    assert isinstance(cause, psycopg.errors.InsufficientPrivilege) and "row-level security" in str(cause)

    class Reader:
        def user_id(self):
            return user

        def __getattr__(self, name):
            raise AssertionError(f"read before the quota: {name}")

    service = rag_qa.RagQuestionService(carbon_service=None, action_tier_enabled=False, rate_limiter=QuestionRateLimiter(
        QuestionRatePolicy(), store, store_kind="postgres"))
    with pytest.raises(rag_qa.QuestionRefused) as refused:
        rag_qa.respond(service, reader=Reader(), crop_season_id=str(uuid.uuid4()),
                       question=rag_qa.QuestionInput(question="Vụ này phát thải bao nhiêu?", intent=RagIntent.EXPLAIN))
    assert (refused.value.status, refused.value.code) == (503, "question_rate_limit_unavailable")
    assert events(user) == 0
    with psycopg.connect(_DB_URL) as conn:
        assert conn.execute("select count(*) from pg_roles where rolname like 'rl_nobypass_%'").fetchone()[0] == 0

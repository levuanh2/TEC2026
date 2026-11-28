"""L1 #103 A1: the Q&A request deadline, the Q&A share of the pg pool, and the stage log line.

Context: a local concurrency soak (2026-11-28) hung a question for 70 s. The thread dump at the
time shows no lock, pool or executor wait: every read was blocked in `_receive_response_headers`
of an HTTP call already sent, while the network path in front of PostgREST was frozen. Without a
deadline any such upstream stall became the request's duration (up to 120 s x 3 transport tries).
These tests pin the contract: a question ends at its deadline as 503 `question_timeout`, a late
worker is never joined, every DB / HTTP wait is cut at the deadline, the Q&A share of the pool is
bounded and always given back, and routes without a deadline are unchanged.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import rag_qa  # noqa: E402
from infrastructure import pg_pool, request_deadline, supabase_clients  # noqa: E402
from infrastructure.pg_carbon_repo import PostgresCarbonRepository  # noqa: E402
from infrastructure.question_rate_limit import PostgresQuestionRateStore, QuestionRatePolicy  # noqa: E402
from infrastructure.read_repo import SupabaseReadRepository  # noqa: E402
from recommendation.rag import RagIntent, RagMode, TenantIsolationViolation  # noqa: E402
from tests.test_rag_qa import SEASON_ID, Carbon, Reader  # noqa: E402
from tests.test_read_performance import SETTINGS, _Client, _patch_factory  # noqa: E402


def _ask(service, reader, question="Vụ này thế nào?"):
    return rag_qa.respond(service, reader=reader, crop_season_id=SEASON_ID,
                          question=rag_qa.QuestionInput(question=question, intent=RagIntent.EXPLAIN,
                                                        mode=RagMode.ASK))


class HangingReader(Reader):
    """`metrics` blocks until released: an HTTP call whose response never comes."""

    def __init__(self):
        super().__init__()
        self.release = threading.Event()
        self.entered = threading.Event()

    def metrics(self, season_id):
        self.entered.set()
        self.release.wait(30)
        return super().metrics(season_id)


# -- the whole question ---------------------------------------------------------

def test_a_hung_read_ends_the_question_at_its_deadline_as_503_question_timeout():
    reader = HangingReader()
    service = rag_qa.RagQuestionService(carbon_service=Carbon(), deadline_seconds=0.6)
    started = time.monotonic()
    try:
        with pytest.raises(rag_qa.QuestionRefused) as refused:
            _ask(service, reader)
        elapsed = time.monotonic() - started
    finally:
        reader.release.set()
    assert reader.entered.is_set()
    assert (refused.value.status, refused.value.code) == (503, "question_timeout")
    assert refused.value.message == rag_qa.PUBLIC_MESSAGES["question_timeout"]
    # ends at the deadline: the hung worker is NOT joined (it would hold the request for 30 s)
    assert 0.5 <= elapsed < 2.0, elapsed


def test_the_same_question_without_a_stall_is_unchanged():
    fast = rag_qa.RagQuestionService(carbon_service=Carbon(), deadline_seconds=5.0)
    no_limit = rag_qa.RagQuestionService(carbon_service=Carbon(), deadline_seconds=3600.0)
    assert _ask(fast, Reader()) == _ask(no_limit, Reader())


def test_a_tenant_isolation_violation_is_never_relabelled_as_a_timeout():
    with request_deadline.bound(time.monotonic() - 1):
        exc = TenantIsolationViolation("chunk of another org")
        exc.__cause__ = TimeoutError("late")
        assert rag_qa._deadline_failure(exc) is False
        assert rag_qa._deadline_failure(RuntimeError("x")) is False  # not a timeout
        wrapped = RuntimeError("adapter")
        wrapped.__cause__ = request_deadline.DeadlineExceeded("late")
        assert rag_qa._deadline_failure(wrapped) is True


def test_a_timeout_before_the_deadline_keeps_its_own_error():
    with request_deadline.bound(time.monotonic() + 30):
        assert rag_qa._deadline_failure(TimeoutError("the server's own statement_timeout")) is False
    assert rag_qa._deadline_failure(TimeoutError("no deadline at all")) is False


def test_the_stage_line_has_timings_only(caplog):
    caplog.set_level(logging.INFO, logger="agricarbon.rag")
    secret = "Câu hỏi riêng của nông hộ Trần Thị B"
    _ask(rag_qa.RagQuestionService(carbon_service=Carbon()), Reader(), question=secret)
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("rag_question_stages ")]
    assert len(lines) == 1
    line = lines[0]
    for field in ("timed_out=False", "deadline_ms=20000", "pg_acquire_n=", "http_n=", "facts_queue_ms_max=",
                  "facts_worker_ms_max=", "facts_wait_ms=", "facts_shutdown_ms=", "facts_pending=0"):
        assert field in line, field
    assert secret not in line and SEASON_ID not in line
    # the monitoring parser keys on "rag_question " (with the space): the stage line is not a question
    assert not line.startswith("rag_question ")


# -- the facts executor -----------------------------------------------------------

def test_late_fact_reads_become_errors_and_are_never_rerun():
    reader = HangingReader()
    source = rag_qa.CallerSeasonFactsSource(reader, Carbon())
    try:
        with request_deadline.bound(time.monotonic() + 0.3):
            assert source.season(SEASON_ID)["id"] == SEASON_ID  # finished in time: its own value
            with pytest.raises(request_deadline.DeadlineExceeded):
                source.metrics(SEASON_ID)
            assert source.stages["pending"] >= 1
            calls_before = len(source._outcomes)
            with pytest.raises(request_deadline.DeadlineExceeded):
                source.metrics(SEASON_ID)  # served from the stored outcome
            assert len(source._outcomes) == calls_before
    finally:
        reader.release.set()


def test_workers_get_the_deadline_and_the_budget_but_nothing_else():
    seen = {}
    sem = threading.BoundedSemaphore(2)

    class Probe(Reader):
        def season(self, season_id):
            seen["deadline"] = request_deadline.at()
            seen["budget"] = pg_pool.current_budget()
            seen["bound"] = pg_pool._bound.get()
            return super().season(season_id)

    token = pg_pool._bound.set({"dsn": object()})  # a caller inside pg_pool.bound(): must not cross
    try:
        with request_deadline.bound(123456.0), pg_pool.budget(sem):
            rag_qa.CallerSeasonFactsSource(Probe(), Carbon()).season(SEASON_ID)
    finally:
        pg_pool._bound.reset(token)
    assert seen == {"deadline": 123456.0, "budget": sem, "bound": None}


# -- pg pool: budget, checkout, release -----------------------------------------------

class _FakePool:
    def __init__(self):
        self.timeouts: list[float] = []
        self.out = 0

    def connection(self, timeout):
        pool = self
        pool.timeouts.append(timeout)

        class _Cm:
            def __enter__(self):
                pool.out += 1
                return object()

            def __exit__(self, *exc):
                pool.out -= 1
                return False
        return _Cm()


@pytest.fixture
def fake_pool(monkeypatch):
    pool = _FakePool()
    monkeypatch.setattr(pg_pool, "_pool_for", lambda conninfo: pool)
    return pool


def test_without_deadline_or_budget_the_checkout_is_unchanged(fake_pool):
    with pg_pool.connection("dsn"):
        pass
    assert fake_pool.timeouts == [pg_pool.TIMEOUT_SECONDS] and fake_pool.out == 0


def test_the_checkout_wait_ends_at_the_deadline(fake_pool):
    with request_deadline.bound(time.monotonic() + 2.0), pg_pool.connection("dsn"):
        pass
    assert 0 < fake_pool.timeouts[0] <= 2.0


def test_the_budget_refuses_at_the_deadline_and_is_always_given_back(fake_pool):
    from psycopg_pool import PoolTimeout

    sem = threading.BoundedSemaphore(1)
    with pg_pool.budget(sem), request_deadline.bound(time.monotonic() + 0.3):
        with pg_pool.connection("dsn"):
            started = time.monotonic()
            with pytest.raises(PoolTimeout):  # -> 503 database_unavailable / question_timeout
                with pg_pool.connection("dsn"):
                    pass
            assert time.monotonic() - started < 1.0
        # the slot came back after the first checkout, also when the body raises
        with pytest.raises(ZeroDivisionError):
            with pg_pool.connection("dsn"):
                1 / 0
    assert sem.acquire(blocking=False), "budget slot leaked"
    sem.release()
    assert fake_pool.out == 0, "connection leaked"


def test_the_budget_caps_concurrent_qa_checkouts(fake_pool):
    sem = threading.BoundedSemaphore(rag_qa.QA_PG_BUDGET)
    peak, lock, inside = [0], threading.Lock(), [0]

    def one():
        with pg_pool.budget(sem), pg_pool.connection("dsn"):
            with lock:
                inside[0] += 1
                peak[0] = max(peak[0], inside[0])
            time.sleep(0.05)
            with lock:
                inside[0] -= 1

    threads = [threading.Thread(target=one) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert peak[0] <= rag_qa.QA_PG_BUDGET < pg_pool.MAX_SIZE
    assert fake_pool.out == 0


# -- Postgres statements -------------------------------------------------------------------

class _Cursor:
    def __init__(self, log, rows):
        self.log, self.rows, self.description = log, rows, [("r",)]

    def execute(self, sql, params=None):
        self.log.append((sql, list(params or [])))

    def fetchall(self):
        return [{"r": r} for r in self.rows]

    def fetchone(self):
        return {"allowed": True, "limit_window": None, "retry_after_seconds": 0}

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _Conn:
    """No `pipeline`: `_stage` runs statements one by one (as on a test savepoint)."""

    def __init__(self):
        self.log: list = []

    def cursor(self):
        return _Cursor(self.log, ["row"])


def test_stage_sends_a_transaction_local_statement_timeout_only_under_a_deadline():
    conn = _Conn()
    assert PostgresCarbonRepository._stage(conn, "t", [("select 1 as r", [])]) == [["row"]]
    assert [sql for sql, _ in conn.log] == ["select 1 as r"]

    conn = _Conn()
    with request_deadline.bound(time.monotonic() + 5):
        assert PostgresCarbonRepository._stage(conn, "t", [("select 1 as r", [])]) == [["row"]]
    (first, params), (second, _) = conn.log
    assert first == "select set_config('statement_timeout', %s, true) as r" and second == "select 1 as r"
    assert 0 < int(params[0]) <= 5000


def test_the_rate_limit_statement_is_bounded_in_the_same_round_trip_and_still_fails_closed():
    class _Pipe:
        def __enter__(self):
            log.append(("pipeline", []))

        def __exit__(self, *exc):
            return False

    log: list = []

    class _PConn(_Conn):
        def pipeline(self):
            return _Pipe()

        def execute(self, sql, params=None):
            log.append((sql, list(params or [])))

        def cursor(self):
            return _Cursor(log, [])

    from contextlib import contextmanager

    @contextmanager
    def connection(_conninfo):
        yield _PConn()

    store = PostgresQuestionRateStore("dsn", connection=connection)
    policy = QuestionRatePolicy(per_minute=5, per_day=50)
    assert store.consume("u", policy).allowed
    assert [s for s, _ in log if "set_config" in s] == []  # no deadline: unchanged

    log.clear()
    with request_deadline.bound(time.monotonic() + 5):
        assert store.consume("u", policy).allowed
    assert log[0][0] == "pipeline" and "statement_timeout" in log[1][0] and "consume_rag_question_quota" in log[2][0]


# -- HTTP (PostgREST / Auth) -------------------------------------------------------------------

def test_http_timeouts_are_cut_to_what_is_left_and_untouched_without_a_deadline():
    hook = supabase_clients._apply_request_deadline
    request = httpx.Request("GET", "http://x/rest/v1/t")
    request.extensions["timeout"] = httpx.Timeout(120.0).as_dict()
    hook(request)
    assert request.extensions["timeout"]["read"] == 120.0

    with request_deadline.bound(time.monotonic() + 2.0):
        hook(request)
    assert all(0 < v <= 2.0 for v in request.extensions["timeout"].values())

    with request_deadline.bound(time.monotonic() - 0.1), pytest.raises(request_deadline.DeadlineExceeded):
        hook(request)


def test_the_pooled_client_carries_the_deadline_hook():
    transport = supabase_clients._transport()
    try:
        assert supabase_clients._apply_request_deadline in transport.event_hooks["request"]
    finally:
        transport.close()


def test_no_transport_retry_or_client_swap_once_the_deadline_has_passed(monkeypatch):
    clients: list[_Client] = []

    def make(url, key, **_kw):
        client = _Client(rows={"farms": [{"id": "f1"}]}, fail_times=1 if not clients else 0)
        clients.append(client)
        return client

    _patch_factory(monkeypatch, make)
    repo = SupabaseReadRepository(SETTINGS, "token-a")
    with request_deadline.bound(time.monotonic() - 1), pytest.raises(httpx.TransportError):
        repo._many("farms")
    assert len(clients) == 1 and repo.client is clients[0], "a timed-out request must not renew the client"

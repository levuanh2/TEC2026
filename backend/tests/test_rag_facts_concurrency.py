"""`CallerSeasonFactsSource`: the season's independent fact reads overlap, and nothing else changes.

Latency fix from the L1 production profile (2026-11-27): the 7 reads ran one after another.
Contract kept: same values, each read once, nothing read before the first call (which the
orchestrator makes only after the scope resolver authorized the season), and an error raised
at the same call that raised it before.
"""

from __future__ import annotations

import contextvars
import threading

import pytest

import rag_qa
from infrastructure.read_repo import ReadNotFoundError
from recommendation.rag import RagAccessDenied

SID = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
ORG = "33333333-3333-4333-8333-333333333333"


REQUEST = contextvars.ContextVar("request", default=None)


class FakeReader:
    def __init__(self, barrier: threading.Barrier | None = None, fail: dict[str, Exception] | None = None):
        self.calls: list[tuple[str, str]] = []
        self.seen_request: set[object] = set()
        self._barrier = barrier
        self._fail = fail or {}
        self._lock = threading.Lock()

    def _hit(self, name: str, sid: str) -> None:
        with self._lock:
            self.calls.append((name, sid))
            self.seen_request.add(REQUEST.get())
        if name in self._fail:
            raise self._fail[name]

    def season(self, sid):
        self._hit("season", sid)
        return {"id": sid, "plot_id": "plot-1", "season_code": "S", "planting_date": "2026-01-01"}

    def activity_summary(self, sid):
        self._hit("activity_summary", sid)
        return {"crop_season_id": sid, "total": 3}

    def metrics(self, sid):
        self._hit("metrics", sid)
        return {"yield_kg": 100.0 if sid == SID else 90.0}

    def recommendations(self, sid):
        self._hit("recommendations", sid)
        return [{"rule_code": "R1"}]

    def season_lineage(self, sid):
        self._hit("season_lineage", sid)
        return {"organization_id": ORG}

    def seasons_for_plot(self, plot_id):
        self._hit("seasons_for_plot", plot_id)
        return [{"id": SID, "planting_date": "2026-01-01"}, {"id": OTHER, "planting_date": "2025-06-01", "season_code": "OLD"}]


class FakeCarbon:
    def __init__(self, reader: FakeReader):
        self._reader = reader

    def stored(self, sid, scenario):
        assert scenario == "as_recorded"
        self._reader._hit("carbon_actual", sid)
        return {"total_co2e_kg": 12.0}

    def readiness(self, sid):
        self._reader._hit("carbon_readiness", sid)
        return {"ready": True}


def _all(source: rag_qa.CallerSeasonFactsSource) -> dict[str, object]:
    return {
        "carbon_actual": source.carbon_actual(SID), "carbon_readiness": source.carbon_readiness(SID),
        "season": source.season(SID), "activity_summary": source.activity_summary(SID),
        "metrics": source.metrics(SID), "signals": source.recommendation_signals(SID, fresh=False),
        "comparison": source.comparison_seasons(SID),
    }


class BarrierReader(FakeReader):
    """Some top-level reads wait on a barrier: they only pass if they run at the same time."""

    def activity_summary(self, sid):
        self._wait(); return super().activity_summary(sid)

    def metrics(self, sid):
        if sid == SID: self._wait()
        return super().metrics(sid)

    def recommendations(self, sid):
        self._wait(); return super().recommendations(sid)

    def _wait(self):
        self._barrier.wait()


def test_concurrent_and_sequential_give_identical_facts():
    r1, r2 = FakeReader(), FakeReader()
    assert _all(rag_qa.CallerSeasonFactsSource(r1, FakeCarbon(r1))) == \
        _all(rag_qa.CallerSeasonFactsSource(r2, FakeCarbon(r2), concurrent=False))
    assert sorted(r1.calls) == sorted(r2.calls)


def test_comparison_keeps_its_shape_and_skips_the_current_season():
    reader = FakeReader()
    out = rag_qa.CallerSeasonFactsSource(reader, FakeCarbon(reader)).comparison_seasons(SID)
    assert out == [{"crop_season_id": OTHER, "organization_id": ORG, "season_code": "OLD",
                    "planting_date": "2025-06-01", "metrics": {"yield_kg": 90.0}}]


def test_the_top_level_reads_overlap():
    barrier = threading.Barrier(5, timeout=5)  # activity_summary, metrics, recommendations, stored, readiness

    class Carbon(FakeCarbon):
        def stored(self, sid, scenario):
            barrier.wait(); return super().stored(sid, scenario)

        def readiness(self, sid):
            barrier.wait(); return super().readiness(sid)

    reader = BarrierReader(barrier=barrier)
    facts = _all(rag_qa.CallerSeasonFactsSource(reader, Carbon(reader)))
    assert facts["metrics"] == {"yield_kg": 100.0}  # a sequential run would have broken the barrier


def test_sequential_mode_really_is_sequential():
    barrier = threading.Barrier(2, timeout=0.5)
    reader = BarrierReader(barrier=barrier)
    with pytest.raises(threading.BrokenBarrierError):
        rag_qa.CallerSeasonFactsSource(reader, FakeCarbon(reader), concurrent=False).activity_summary(SID)


def test_each_read_runs_once_per_season_however_often_it_is_asked():
    reader = FakeReader()
    source = rag_qa.CallerSeasonFactsSource(reader, FakeCarbon(reader))
    _all(source); _all(source); source.metrics(SID); source.season(SID)
    top = [c for c in reader.calls if c[1] == SID and c[0] in
           {"activity_summary", "carbon_actual", "carbon_readiness", "recommendations"}]
    assert sorted(top) == sorted({c for c in top}) and len(top) == 4
    assert reader.calls.count(("metrics", SID)) == 1
    assert reader.calls.count(("metrics", OTHER)) == 1
    assert reader.calls.count(("season", SID)) == 2  # the season read itself + the comparison's own season read


def test_nothing_is_read_before_the_first_call():
    reader = FakeReader()
    rag_qa.CallerSeasonFactsSource(reader, FakeCarbon(reader))
    assert reader.calls == []


@pytest.mark.parametrize("failing,call", [
    ("carbon_actual", lambda s: s.carbon_actual(SID)),
    ("carbon_readiness", lambda s: s.carbon_readiness(SID)),
    ("activity_summary", lambda s: s.activity_summary(SID)),
    ("metrics", lambda s: s.metrics(SID)),
    ("recommendations", lambda s: s.recommendation_signals(SID, fresh=False)),
])
def test_an_error_surfaces_at_its_own_call_and_nowhere_else(failing, call):
    boom = ReadNotFoundError(failing)
    reader = FakeReader(fail={failing: boom})
    source = rag_qa.CallerSeasonFactsSource(reader, FakeCarbon(reader))
    with pytest.raises(ReadNotFoundError) as caught:
        call(source)
    assert caught.value is boom
    with pytest.raises(ReadNotFoundError):  # asked again: the same verdict, not a re-read
        call(source)
    assert source.season(SID)["id"] == SID  # the other reads are unaffected


def test_the_first_error_in_call_order_is_the_one_the_orchestrator_sees():
    # build_season_context asks carbon_actual first: with carbon_actual AND season failing,
    # the caller still sees carbon_actual's error first, exactly as when the reads were sequential.
    first, later = RuntimeError("carbon"), ReadNotFoundError("crop_seasons")
    reader = FakeReader(fail={"carbon_actual": first, "season": later})
    source = rag_qa.CallerSeasonFactsSource(reader, FakeCarbon(reader))
    with pytest.raises(RuntimeError) as caught:
        source.carbon_actual(SID)
    assert caught.value is first


def test_preview_is_still_refused_without_reading():
    reader = FakeReader()
    with pytest.raises(RagAccessDenied):
        rag_qa.CallerSeasonFactsSource(reader, FakeCarbon(reader)).recommendation_signals(SID, fresh=True)
    assert reader.calls == []


def test_request_context_reaches_every_worker():
    reader = FakeReader()
    token = REQUEST.set("request-42")
    try:
        _all(rag_qa.CallerSeasonFactsSource(reader, FakeCarbon(reader)))
    finally:
        REQUEST.reset(token)
    assert reader.seen_request == {"request-42"}

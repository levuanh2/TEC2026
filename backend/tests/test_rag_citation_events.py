"""RAG V1.5 M6.1 citation events, offline half: the event model, the retrieved/cited/response_emitted
distinction, privacy (no content field), and the wiring (no sink = nothing recorded, a failing sink never
changes the answer). Pure: no database, no network. Every value is a SYNTHETIC TEST FIXTURE."""

from __future__ import annotations

import dataclasses
import uuid
from types import SimpleNamespace

import pytest

import rag_citation_events as ce

SEASON = str(uuid.uuid4())
REQUEST = str(uuid.uuid4())
SECRET_QUESTION = "TEST FIXTURE question text that must never be stored"


def result(status="generated", cited=("c1",), rejection=None):
    return SimpleNamespace(status=status, evidence=tuple(SimpleNamespace(chunk_id=c) for c in cited),
                           policy_rejection=rejection)


def recorder(ids):
    r = ce.RecordingRetriever(SimpleNamespace(retrieve=lambda q: [SimpleNamespace(chunk_id=i) for i in ids]))
    r.retrieve(SimpleNamespace(text=SECRET_QUESTION))
    return r


def test_the_event_has_no_field_for_content_or_identity():
    names = {f.name for f in dataclasses.fields(ce.CitationEvent)}
    assert names == {"request_id", "crop_season_id", "retrieval_mode", "outcome", "response_emitted", "trace_completeness",
                     "retrieved", "cited"}
    event = ce.build_event(request_id=REQUEST, crop_season_id=SEASON, recorder=recorder(["c1", "c2"]),
                           result=result(), response_emitted=True)
    assert SECRET_QUESTION not in repr(event)


def test_retrieved_cited_and_response_emitted_are_distinct():
    event = ce.build_event(request_id=REQUEST, crop_season_id=SEASON, recorder=recorder(["c1", "c2", "c1"]),
                           result=result(cited=("c1",)), response_emitted=True)
    assert (event.retrieved, event.cited, event.response_emitted, event.trace_completeness) == (("c1", "c2"), ("c1",), True,
                                                                                          "complete")
    declined = ce.build_event(request_id=REQUEST, crop_season_id=SEASON, recorder=recorder(["c3"]),
                              result=result("insufficient_evidence", cited=()), response_emitted=True)
    assert (declined.outcome, declined.retrieved, declined.cited) == ("insufficient_evidence", ("c3",), ())
    rejected = ce.build_event(request_id=REQUEST, crop_season_id=SEASON, recorder=recorder(["c3"]),
                              result=result("insufficient_evidence", cited=(), rejection="advice"), response_emitted=True)
    assert rejected.outcome == "policy_rejected"


def test_trace_completeness():
    no_retrieval = ce.RecordingRetriever(SimpleNamespace(retrieve=lambda q: []))
    assert ce.build_event(request_id=REQUEST, crop_season_id=SEASON, recorder=no_retrieval, result=result(cited=()),
                          response_emitted=True).trace_completeness == "not_reached"
    assert ce.build_event(request_id=REQUEST, crop_season_id=SEASON, recorder=no_retrieval, result=None,
                          response_emitted=False, retrieval_failed=True).trace_completeness == "retrieval_unavailable"


def test_a_cited_chunk_must_have_been_retrieved_and_an_error_emits_nothing():
    with pytest.raises(ValueError):
        ce.CitationEvent(REQUEST, SEASON, "production", "generated", True, "complete", ("c1",), ("c2",))
    with pytest.raises(ValueError):
        ce.CitationEvent(REQUEST, SEASON, "production", "error", True, "not_reached", (), ())
    with pytest.raises(ValueError):
        ce.CitationEvent("not-a-uuid", SEASON, "production", "generated", True, "complete", (), ())


def test_no_sink_records_nothing_and_a_failing_sink_never_raises():
    calls = []
    ce.record_safely(None, lambda: calls.append("built"))
    assert calls == []

    class Broken:
        def record(self, event):
            raise RuntimeError("TEST FIXTURE sink down")
    ce.record_safely(Broken(), lambda: ce.build_event(request_id=REQUEST, crop_season_id=SEASON, recorder=None,
                                                      result=result(cited=()), response_emitted=True))


def test_the_question_service_records_only_with_a_sink(monkeypatch):
    import rag_qa
    assert "citation_sink" in rag_qa.RagQuestionService.__init__.__code__.co_varnames
    service = rag_qa.RagQuestionService(carbon_service=None)
    assert service._citations is None                                # the default (and production) is off


def test_the_request_id_becomes_a_uuid():
    import rag_qa
    assert rag_qa._event_id(REQUEST) == REQUEST
    assert uuid.UUID(rag_qa._event_id("not-a-uuid"))
    assert uuid.UUID(rag_qa._event_id(None))

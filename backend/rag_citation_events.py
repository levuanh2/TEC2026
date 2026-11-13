"""RAG V1.5 M6.1: metadata-only citation events, a LOCAL/CI PROTOTYPE
(docs/rag/RAG_V15_M6_1_CITATION_EVENTS.md).

`RagQuestionService` records one event per question ONLY when it is constructed with a
`citation_sink` (default: none, so production behaviour is unchanged). The database refuses to record
on any database that does not pass the H-a isolation gate, so even a configured sink cannot log on the
shared hosted project.

An event never carries the question, the answer, a prompt, a user id, an email, a key or a secret:
`CitationEvent` has no field for any of them. It distinguishes
  * the chunks RETRIEVED for the request (candidates; retrieval alone is not exposure),
  * the chunks actually CITED in the returned answer,
  * whether the backend EMITTED a response body (`response_emitted`): the log cannot prove that the caller
    received or read it (a dropped connection or a client error is invisible here).
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

logger = logging.getLogger(__name__)

#: `evidence_refused` (M7 E5): the answer-time check refused a cited chunk and the model answer was discarded.
Outcome = Literal["generated", "insufficient_evidence", "policy_rejected", "evidence_refused", "error"]
Trace = Literal["complete", "retrieval_unavailable", "not_reached"]
Mode = Literal["production", "demo"]


@dataclass(frozen=True)
class CitationEvent:
    request_id: str
    crop_season_id: str
    retrieval_mode: Mode
    outcome: Outcome
    response_emitted: bool
    trace_completeness: Trace
    retrieved: tuple[str, ...]
    cited: tuple[str, ...]

    def __post_init__(self) -> None:
        uuid.UUID(self.request_id)
        uuid.UUID(self.crop_season_id)
        if not set(self.cited) <= set(self.retrieved):
            raise ValueError("a cited chunk must be one retrieved for this request")
        if self.response_emitted and self.outcome == "error":
            raise ValueError("an error emits no answer")


class CitationSink(Protocol):
    def record(self, event: CitationEvent) -> None: ...


class RecordingRetriever:
    """Wraps the request's retriever and keeps the chunk ids it returned (before any relevance filter)."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.retrieved: list[str] | None = None
        #: M7 E5: the EvidenceChunks themselves, for the answer-time re-validation (never recorded).
        self.chunks: tuple[Any, ...] | None = None

    def retrieve(self, query: Any) -> Sequence[Any]:
        rows = self._inner.retrieve(query)
        self.retrieved = list(dict.fromkeys(chunk.chunk_id for chunk in rows))
        self.chunks = tuple(rows)
        return rows


def build_event(*, request_id: str, crop_season_id: str, recorder: RecordingRetriever | None, result: Any | None,
                response_emitted: bool, retrieval_failed: bool = False, retrieval_mode: Mode = "production") -> CitationEvent:
    """`result` is the trusted RagAnswerResult (None when the request failed before one existed).
    Trace: `complete` when retrieval ran and its chunk ids are known; `retrieval_unavailable` when it
    failed; `not_reached` when the request never retrieved (a deterministic answer or an earlier stop)."""
    if result is None:
        outcome: Outcome = "error"
    elif getattr(result, "policy_rejection", None) is not None:
        outcome = "policy_rejected"
    elif getattr(result, "insufficient_reason", None) == "evidence_no_longer_admissible":
        outcome = "evidence_refused"
    else:
        outcome = "generated" if result.status == "generated" else "insufficient_evidence"
    retrieved: tuple[str, ...] = ()
    if retrieval_failed:
        trace: Trace = "retrieval_unavailable"
    elif recorder is not None and recorder.retrieved is not None:
        trace, retrieved = "complete", tuple(recorder.retrieved)
    else:
        trace = "not_reached"
    cited = tuple(dict.fromkeys(c.chunk_id for c in (result.evidence if result is not None else ())))
    return CitationEvent(request_id=request_id, crop_season_id=crop_season_id, retrieval_mode=retrieval_mode,
                         outcome=outcome, response_emitted=response_emitted and outcome != "error", trace_completeness=trace,
                         retrieved=retrieved, cited=cited)


class PostgresCitationSink:
    """Writes through private.knowledge_record_citation_event with a SERVICE connection factory
    (`connect()` returns a psycopg connection). The database derives scope, document versions and
    assurance, and refuses on a shared database."""

    SQL = "select private.knowledge_record_citation_event(%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)"

    def __init__(self, connect: Callable[[], Any]) -> None:
        self._connect = connect

    def record(self, event: CitationEvent) -> None:
        with self._connect() as conn:
            conn.execute(self.SQL, (event.request_id, event.crop_season_id, event.retrieval_mode, event.outcome,
                                    event.response_emitted, event.trace_completeness, json.dumps(list(event.retrieved)),
                                    json.dumps(list(event.cited))))


def record_safely(sink: CitationSink | None, event_factory: Callable[[], CitationEvent]) -> None:
    """Recording never changes the answer: a failure is logged (without content) and swallowed."""
    if sink is None:
        return
    try:
        sink.record(event_factory())
    except Exception as exc:  # noqa: BLE001 - audit side channel, fail open for the answer only
        logger.warning("rag_citation_event_not_recorded error=%s", type(exc).__name__)

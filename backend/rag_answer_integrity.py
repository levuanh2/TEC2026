"""RAG V1.5 M7 E5: answer-time re-validation of cited evidence (docs/rag/RAG_V15_M7_E5_ANSWER_TIME_CONTROL.md).

Runs in `RagQuestionService.answer` AFTER the orchestrator built a trusted, grounded result and BEFORE the
response body is built. It never makes the model an authority and never changes a status:

* C1  every citation names a chunk RETRIEVED for this request (the orchestrator already enforces it; re-asserted
      here on the exact (source_id, chunk_id) pairs, so a later change cannot widen it);
* C2  the database, under the CALLER'S JWT, says which cited chunks are still admissible for this crop season
      (`public.knowledge_cited_evidence_state`: the retrieval predicate, re-evaluated now);
* C3  the same source, document and version, and a content hash equal to the sha256 of the text retrieval
      returned and consistent with the stored text;
* C4  verified assurance only (demo assurance only in the isolated demo mode, labelled);
* C5  every recommendation keeps at least one admissible citation; integrity findings an expert resolved as
      false_positive / contextual_difference are SURFACED as a caveat (finding types only), never hidden;
* C6  one failing citation discards the whole model answer (fail closed); a failing recheck is an error, not a pass.

Consistency boundary: the database statement's snapshot. A change committed after it is not seen here.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

from recommendation.rag import RetrievalUnavailable
from recommendation.rag.answers import INSUFFICIENT_MESSAGES

logger = logging.getLogger("agricarbon.rag")

Refusal = Literal["not_retrieved", "no_longer_admissible", "version_changed", "content_changed",
                  "content_hash_inconsistent", "assurance_not_verified", "recommendation_without_citation"]

#: Trusted copy for a caveat (finding types are codes from the E2 report, not document text).
CAVEAT_TEXT = ("Lưu ý: tài liệu được dẫn có phát hiện kiểm tra tính toàn vẹn mà chuyên gia đã đánh giá là báo động"
               " nhầm hoặc khác biệt theo ngữ cảnh ({types}). Hệ thống không tự xác minh nội dung khoa học.")


class EvidenceStateReader(Protocol):
    def knowledge_evidence_state(self, season_id: str, chunk_ids: Sequence[str], *, demo: bool) -> Sequence[Mapping[str, Any]]: ...


@dataclass(frozen=True)
class EvidenceCheck:
    refused: tuple[tuple[str, Refusal], ...] = ()
    caveats: tuple[tuple[str, tuple[str, ...]], ...] = ()
    checked: tuple[str, ...] = field(default_factory=tuple)

    @property
    def admissible(self) -> bool:
        return not self.refused


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def recheck_cited_evidence(reader: Any, *, crop_season_id: str, result: Any, retrieved: Sequence[Any],
                           demo: bool) -> EvidenceCheck:
    """`result` is the trusted RagAnswerResult, `retrieved` the EvidenceChunks this request's retrieval returned.
    Raises RetrievalUnavailable when the database cannot answer (the caller refuses the answer)."""
    cited = list(result.evidence)
    if not cited:
        return EvidenceCheck()
    by_key = {(c.source_id, c.chunk_id): c for c in retrieved}
    refused: list[tuple[str, Refusal]] = []
    for c in cited:                                                                   # C1
        if (c.source_id, c.chunk_id) not in by_key:
            refused.append((c.chunk_id, "not_retrieved"))
    cited_ids = {c.chunk_id for c in cited}
    for rec in getattr(result, "recommendations", ()):                               # C5 (structure)
        refs = {r.chunk_id for r in getattr(rec, "evidence_refs", ())}
        if not refs & cited_ids:
            refused.append((getattr(rec, "rule_code", "?"), "recommendation_without_citation"))
    lookup = getattr(reader, "knowledge_evidence_state", None)
    if lookup is None:
        raise RetrievalUnavailable("this reader cannot re-validate cited evidence")
    ids = sorted(cited_ids)
    try:
        rows = list(lookup(crop_season_id, ids, demo=demo))
    except Exception as exc:  # noqa: BLE001 - adapter boundary: fail closed, cause chained
        raise RetrievalUnavailable("final evidence recheck failed") from exc
    state = {(r["source_id"], r["chunk_id"]): r for r in rows}
    caveats: list[tuple[str, tuple[str, ...]]] = []
    for c in cited:
        key = (c.source_id, c.chunk_id)
        if key not in by_key:
            continue                                                                  # already refused (C1)
        row, chunk = state.get(key), by_key[key]
        if row is None:                                                               # C2
            refused.append((c.chunk_id, "no_longer_admissible"))
        elif (row["document_id"], row["document_version"]) != (chunk.document_id, chunk.document_version):
            refused.append((c.chunk_id, "version_changed"))                           # C3
        elif row["content_sha256"] != _sha(chunk.content):
            refused.append((c.chunk_id, "content_changed"))
        elif row.get("content_hash_consistent") is not True:
            refused.append((c.chunk_id, "content_hash_inconsistent"))
        elif row.get("approval_assurance") != "verified" and not (demo and row.get("approval_assurance")
                                                                    == "demo_unverified"):
            refused.append((c.chunk_id, "assurance_not_verified"))                    # C4
        elif row.get("resolved_finding_types"):
            caveats.append((c.chunk_id, tuple(row["resolved_finding_types"])))       # C5 (caveat)
    return EvidenceCheck(refused=tuple(refused), caveats=tuple(caveats), checked=tuple(ids))


def caveat_limitations(check: EvidenceCheck) -> tuple[str, ...]:
    types = sorted({t for _, ts in check.caveats for t in ts})
    return (CAVEAT_TEXT.format(types=", ".join(types)),) if types else ()


def answer_time_evidence_gate(reader: Any, *, crop_season_id: str, result: Any, retrieved: Sequence[Any],
                              demo: bool) -> tuple[Any, tuple[tuple[str, Refusal], ...]]:
    """(result to emit, refusals). A generated answer with any refused citation becomes the trusted
    `insufficient_evidence` / `evidence_no_longer_admissible` state: no model text, no recommendation, no
    citation, no model-referenced fact survives; the deterministic signals, what-if numbers and basis stay
    (they never depended on the documents). An admissible answer gains the trusted caveat, if any."""
    if result.status != "generated" or not result.evidence:
        return result, ()
    check = recheck_cited_evidence(reader, crop_season_id=crop_season_id, result=result, retrieved=retrieved,
                                   demo=demo)
    if not check.admissible:
        logger.warning("rag_answer_evidence_refused crop_season_id=%s reasons=%s", crop_season_id,
                       sorted({reason for _, reason in check.refused}))
        return result.model_copy(update={
            "status": "insufficient_evidence", "insufficient_reason": "evidence_no_longer_admissible",
            "answer": INSUFFICIENT_MESSAGES["evidence_no_longer_admissible"], "answer_template": None,
            "rationale": None, "recommendations": (), "evidence": (), "facts": (), "limitations": (),
            "confidence": None}), check.refused
    extra = caveat_limitations(check)
    if extra:
        result = result.model_copy(update={"limitations": tuple(result.limitations) + extra})
    return result, ()


def fixture_evidence_state(rows: Sequence[Mapping[str, Any]], chunk_ids: Sequence[str]) -> list[dict[str, Any]]:
    """For OFFLINE fixtures and the benchmark only: retrieval-shaped rows of a fixture corpus that stands for
    approved, verified knowledge that stays admissible for the whole request. The answer-time controls
    themselves are tested against the database (test_rag_knowledge_m7_e5_answer_time.py)."""
    wanted = set(chunk_ids)
    return [{"source_id": r["source_id"], "document_id": r["document_id"], "document_version": r.get("document_version"),
             "chunk_id": r["chunk_id"], "content_sha256": _sha(r["content"]), "content_hash_consistent": True,
             "approval_assurance": r.get("approval_assurance", "verified"), "resolved_finding_types": []}
            for r in rows if r["chunk_id"] in wanted]

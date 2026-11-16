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
* C6  one failing citation discards the whole model answer (fail closed); a failing recheck is an error, not a pass;
* E3  (owner decisions D-E3-1 B / D-E3-2 / D-E3-3, docs/rag/RAG_V15_M7_E3_ACTION_CONTAINMENT.md) an ACTION-producing answer
      (a recommendation, or the RECOMMEND / WHAT_IF capability) may not rest on a chunk whose SCIENTIFIC-CONFLICT
      finding (`ACTION_CONTAINED_FINDING_TYPES`) an expert dismissed: a dismissal is a recorded human judgement,
      not proof that the source claim is correct. Such an answer is discarded whole (`evidence_integrity_contested`);
      a READ-tier answer keeps the C5 caveat. Nothing is quarantined, no review record is touched and the approval
      policy is unchanged: this is answer-time admissibility only.

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
from recommendation.rag.intents import INTENT_POLICIES, GenerationCapability

logger = logging.getLogger("agricarbon.rag")

Refusal = Literal["not_retrieved", "no_longer_admissible", "version_changed", "content_changed",
                  "content_hash_inconsistent", "assurance_not_verified", "recommendation_without_citation",
                  "integrity_conflict_dismissed"]

#: E3: finding types that state a detected CONFLICT of a source claim with a trusted reference, another approved
#: claim or a reference number (E2's blocking set minus the temporal types M3 governs and `unsupported_assertion`,
#: which mostly reflects the incomplete reference registry, E1). Owner decision D-E3-2 may widen or narrow it.
ACTION_CONTAINED_FINDING_TYPES = frozenset({"reference_conflict", "claim_conflict", "numeric_reference_mismatch"})

#: E3 refusals only (every other refusal means the evidence itself is no longer admissible, C1-C5).
_CONTAINMENT_REFUSALS = frozenset({"integrity_conflict_dismissed"})

#: Trusted copy (owner decision D-E3-3). `{labels}` are FINDING_TYPE_LABELS, never the internal codes, which stay in
#: the E2 report / disposition records and the developer log. A dismissed finding of a non-conflict type:
CAVEAT_TEXT = ("Lưu ý: tài liệu được dẫn có phát hiện kiểm tra tính toàn vẹn ({labels}) mà chuyên gia đã đánh giá là"
               " báo động nhầm hoặc khác biệt theo ngữ cảnh. Hệ thống không tự xác minh nội dung khoa học.")
#: A dismissed SCIENTIFIC CONFLICT (ACTION_CONTAINED_FINDING_TYPES) on a citation a READ-tier answer may still show:
CONFLICT_CAVEAT_TEXT = ("Cảnh báo: tài liệu được dẫn có mâu thuẫn khoa học ({labels}) và cần được xác minh lại. Chuyên"
                        " gia đã đánh giá là báo động nhầm hoặc khác biệt theo ngữ cảnh, nhưng điều đó chưa được xác minh"
                        " độc lập; nội dung tài liệu này không phải là hướng dẫn canh tác đã được xác lập.")
#: Shown ON the citation itself (RagCitationResponse.integrity_warning), next to the document it is about.
CITATION_CONFLICT_WARNING = ("Cảnh báo: tài liệu này có mâu thuẫn khoa học ({labels}) và cần được xác minh lại;"
                             " không dùng làm hướng dẫn canh tác.")
CITATION_CAVEAT = ("Lưu ý: tài liệu này có phát hiện kiểm tra ({labels}) đã được chuyên gia đánh giá là báo động nhầm"
                   " hoặc khác biệt theo ngữ cảnh; hệ thống không tự xác minh nội dung khoa học.")
#: Appended to a READ-tier (system-composed) answer that cites a contested document.
ANSWER_CONFLICT_NOTE = ("Một số tài liệu được dẫn có mâu thuẫn khoa học và cần được xác minh lại; đó không phải hướng"
                        " dẫn canh tác đã được xác lập.")


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


def is_action_answer(result: Any) -> bool:
    """An answer that advises an action: it carries a recommendation, or its intent has the ACTION_PRODUCING
    capability (RECOMMEND, WHAT_IF). Decided by trusted code from the trusted result, never by the model's text."""
    if getattr(result, "recommendations", ()):
        return True
    policy = INTENT_POLICIES.get(getattr(result, "intent", None))
    return policy is not None and policy.capability is GenerationCapability.ACTION_PRODUCING


def recheck_cited_evidence(reader: Any, *, crop_season_id: str, result: Any, retrieved: Sequence[Any],
                           demo: bool) -> EvidenceCheck:
    """`result` is the trusted RagAnswerResult, `retrieved` the EvidenceChunks this request's retrieval returned.
    Raises RetrievalUnavailable when the database cannot answer (the caller refuses the answer)."""
    action = is_action_answer(result)
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
    for r in rows:
        # E3 cannot fail open: a row that does not say which findings were dismissed is not "no findings".
        if not isinstance(r.get("resolved_finding_types"), (list, tuple)):
            raise RetrievalUnavailable("final evidence recheck returned no integrity finding state")
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
        elif action and ACTION_CONTAINED_FINDING_TYPES & set(row.get("resolved_finding_types") or ()):
            refused.append((c.chunk_id, "integrity_conflict_dismissed"))             # E3 (action tier)
        elif row.get("resolved_finding_types"):
            caveats.append((c.chunk_id, tuple(row["resolved_finding_types"])))       # C5 (caveat)
    return EvidenceCheck(refused=tuple(refused), caveats=tuple(caveats), checked=tuple(ids))


#: Trusted Vietnamese labels for farmer-facing copy (D-E3-3: no internal code is shown).
FINDING_TYPE_LABELS = {
    "reference_conflict": "mâu thuẫn với tài liệu tham chiếu",
    "claim_conflict": "mâu thuẫn với nội dung của tài liệu đã duyệt khác",
    "numeric_reference_mismatch": "số liệu khác với tài liệu tham chiếu",
    "unsupported_assertion": "nhận định chưa có tài liệu tham chiếu hỗ trợ",
    "expired_guidance": "hướng dẫn đã hết hiệu lực",
    "not_yet_effective": "hướng dẫn chưa có hiệu lực",
    "superseded_guidance": "hướng dẫn đã được thay thế",
}


_OTHER_FINDING_LABEL = "phát hiện kiểm tra khác"


def finding_labels(types) -> str:
    """Vietnamese labels, de-duplicated, in a stable order; an unknown code is never echoed."""
    return "; ".join(dict.fromkeys(FINDING_TYPE_LABELS.get(t, _OTHER_FINDING_LABEL) for t in sorted(types)))


def is_conflict(types) -> bool:
    return bool(ACTION_CONTAINED_FINDING_TYPES & set(types))


def caveat_limitations(check: EvidenceCheck) -> tuple[str, ...]:
    """At most one conflict warning and one plain caveat, each naming the labels of its own findings."""
    conflict = {t for _, ts in check.caveats if is_conflict(ts) for t in ts}
    plain = {t for _, ts in check.caveats if not is_conflict(ts) for t in ts}
    out = []
    if conflict:
        out.append(CONFLICT_CAVEAT_TEXT.format(labels=finding_labels(conflict)))
    if plain:
        out.append(CAVEAT_TEXT.format(labels=finding_labels(plain)))
    return tuple(out)


def citation_warning(types) -> str:
    template = CITATION_CONFLICT_WARNING if is_conflict(types) else CITATION_CAVEAT
    return template.format(labels=finding_labels(types))


def answer_time_evidence_gate(reader: Any, *, crop_season_id: str, result: Any, retrieved: Sequence[Any],
                              demo: bool) -> tuple[Any, tuple[tuple[str, Refusal], ...]]:
    """(result to emit, refusals). A generated answer with any refused citation becomes the trusted
    `insufficient_evidence` / `evidence_no_longer_admissible` (or, for E3 alone, `evidence_integrity_contested`)
    state: no model text, no recommendation, no citation, no model-referenced fact survives; the deterministic
    signals, what-if numbers and basis stay (they never depended on the documents). An admissible answer that cites
    a document with dismissed findings gains the trusted caveat, a warning on that citation and, in the READ tier
    for a scientific conflict, a sentence in the answer saying the source is not established guidance."""
    if result.status != "generated" or not result.evidence:
        return result, ()
    check = recheck_cited_evidence(reader, crop_season_id=crop_season_id, result=result, retrieved=retrieved,
                                   demo=demo)
    if not check.admissible:
        reasons = {reason for _, reason in check.refused}
        logger.warning("rag_answer_evidence_refused crop_season_id=%s reasons=%s", crop_season_id, sorted(reasons))
        # Inadmissible evidence (C1-C5) takes precedence over E3 containment: the copy must not claim a reviewed
        # conflict when the document is in fact withdrawn, changed or unverified.
        why = "evidence_integrity_contested" if reasons <= _CONTAINMENT_REFUSALS else "evidence_no_longer_admissible"
        return result.model_copy(update={
            "status": "insufficient_evidence", "insufficient_reason": why,
            "answer": INSUFFICIENT_MESSAGES[why], "answer_template": None,
            "rationale": None, "recommendations": (), "evidence": (), "facts": (), "limitations": (),
            "confidence": None}), check.refused
    if not check.caveats:
        return result, ()
    # Codes for developers only (the immutable E2 records hold the audit trail); farmers see labels.
    logger.info("rag_answer_evidence_caveat crop_season_id=%s findings=%s", crop_season_id,
                [(chunk, sorted(types)) for chunk, types in check.caveats])
    warnings = dict(check.caveats)
    update: dict[str, Any] = {
        "limitations": tuple(result.limitations) + caveat_limitations(check),
        "evidence": tuple(c.model_copy(update={"integrity_warning": citation_warning(warnings[c.chunk_id])})
                          if c.chunk_id in warnings else c for c in result.evidence),
    }
    if not is_action_answer(result) and any(is_conflict(ts) for ts in warnings.values()) and result.answer:
        # READ tier (trusted composer text): the answer itself says the contested source is not guidance.
        update["answer"] = f"{result.answer} {ANSWER_CONFLICT_NOTE}"
        if getattr(result, "answer_template", None):
            update["answer_template"] = f"{result.answer_template} {ANSWER_CONFLICT_NOTE}"
    return result.model_copy(update=update), ()


def fixture_evidence_state(rows: Sequence[Mapping[str, Any]], chunk_ids: Sequence[str]) -> list[dict[str, Any]]:
    """For OFFLINE fixtures and the benchmark only: retrieval-shaped rows of a fixture corpus that stands for
    approved, verified knowledge that stays admissible for the whole request. The answer-time controls
    themselves are tested against the database (test_rag_knowledge_m7_e5_answer_time.py)."""
    wanted = set(chunk_ids)
    return [{"source_id": r["source_id"], "document_id": r["document_id"], "document_version": r.get("document_version"),
             "chunk_id": r["chunk_id"], "content_sha256": _sha(r["content"]), "content_hash_consistent": True,
             "approval_assurance": r.get("approval_assurance", "verified"), "resolved_finding_types": []}
            for r in rows if r["chunk_id"] in wanted]

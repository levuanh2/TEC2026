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

E5.1 (owner decision D-E5-PIN, docs/rag/RAG_V15_M7_E5_1_PIN_AWARE_ADMISSION.md) a verified version is admissible only
      while its integrity report and independent verification are under the CURRENT integrity pin
      (`integrity_status` = current). Gate 1 (`AdmittedEvidenceRetriever`) applies it to the retrieved chunks BEFORE the
      model sees them; gate 2 (this recheck) applies it again to the cited chunks at answer time.

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
                  "integrity_conflict_dismissed", "integrity_not_current"]

#: E5.1 (owner decision D-E5-PIN): the values `knowledge_cited_evidence_state.integrity_status` may take. Anything
#: else, or a missing value, is a broken recheck (fail closed), never "current".
INTEGRITY_STATUSES = frozenset({"current", "not_current", "demo_unverified"})

#: E5.1: refusals that mean "admissible except that its integrity evidence is not under the current pin".
_PIN_REFUSALS = frozenset({"integrity_not_current"})

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
#: Shown ON the citation itself (RagCitationResponse.integrity_warning), directly after its title. A dismissed
#: SCIENTIFIC CONFLICT gets the owner's sentence verbatim (2026-11-16, docs/rag/RAG_V15_E1_E4_SOURCE_EXPERT_GOVERNANCE_PLAN.md
#: §3): no label or other text is ever added to it. The finding description goes in `integrity_detail`.
CITATION_CONFLICT_WARNING = ("Tài liệu đang có nội dung khoa học cần xác minh lại; không sử dụng làm căn cứ hướng dẫn"
                             " canh tác.")
#: Any other dismissed finding: an integrity caveat, NOT a scientific contradiction.
CITATION_CAVEAT = ("Lưu ý: tài liệu này có phát hiện kiểm tra đã được chuyên gia đánh giá là báo động nhầm hoặc khác biệt"
                   " theo ngữ cảnh; hệ thống không tự xác minh nội dung khoa học.")
#: RagCitationResponse.integrity_detail: the trusted labels of the citation's own findings, shown separately.
CITATION_FINDINGS_DETAIL = "Phát hiện kiểm tra: {labels}."
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
    state = _validated_state(rows, "final evidence recheck")
    caveats: list[tuple[str, tuple[str, ...]]] = []
    for c in cited:
        key = (c.source_id, c.chunk_id)
        if key not in by_key:
            continue                                                                  # already refused (C1)
        row = state.get(key)
        why = _evidence_refusal(row, by_key[key], demo=demo)                          # C2-C4, E5.1
        if why is not None:
            refused.append((c.chunk_id, why))
        elif action and ACTION_CONTAINED_FINDING_TYPES & set(row.get("resolved_finding_types") or ()):
            refused.append((c.chunk_id, "integrity_conflict_dismissed"))             # E3 (action tier)
        elif row.get("resolved_finding_types"):
            caveats.append((c.chunk_id, tuple(row["resolved_finding_types"])))       # C5 (caveat)
    return EvidenceCheck(refused=tuple(refused), caveats=tuple(caveats), checked=tuple(ids))


def _validated_state(rows: Sequence[Mapping[str, Any]], what: str) -> dict[tuple[str, str], Mapping[str, Any]]:
    """Index the recheck rows; a row that does not state its finding types (E3) or its integrity status (E5.1) is a
    broken recheck, never "no findings" or "current": the request fails closed (503)."""
    for r in rows:
        if not isinstance(r.get("resolved_finding_types"), (list, tuple)):
            raise RetrievalUnavailable(f"{what} returned no integrity finding state")
        if r.get("integrity_status") not in INTEGRITY_STATUSES:
            raise RetrievalUnavailable(f"{what} returned no integrity status (E5.1 not installed?)")
    return {(r["source_id"], r["chunk_id"]): r for r in rows}


def _evidence_refusal(row: Mapping[str, Any] | None, chunk: Any, *, demo: bool) -> Refusal | None:
    """Why the retrieved `chunk` is not admissible evidence now (C2-C4 and the E5.1 pin), or None. Shared by the
    before-model admission (gate 1) and the answer-time recheck (gate 2), so both apply exactly one policy."""
    if row is None:                                                                   # C2
        return "no_longer_admissible"
    if (row["document_id"], row["document_version"]) != (chunk.document_id, chunk.document_version):
        return "version_changed"                                                      # C3
    if row["content_sha256"] != _sha(chunk.content):
        return "content_changed"
    if row.get("content_hash_consistent") is not True:
        return "content_hash_inconsistent"
    assurance = row.get("approval_assurance")
    if assurance != "verified" and not (demo and assurance == "demo_unverified"):
        return "assurance_not_verified"                                               # C4
    # E5.1 (D-E5-PIN): a verified version is admissible only while its integrity report and independent
    # verification are under the CURRENT pin; a demo approval only as what it is, in the labelled demo mode.
    expected = "current" if assurance == "verified" else "demo_unverified"
    if row.get("integrity_status") != expected:
        return "integrity_not_current"
    return None


@dataclass(frozen=True)
class EvidenceAdmission:
    """Gate 1 result: the retrieved chunks admitted into the model context, and the excluded ones with why."""
    admitted: tuple[Any, ...]
    excluded: tuple[tuple[str, Refusal], ...] = ()

    @property
    def pin_excluded(self) -> bool:
        return any(reason in _PIN_REFUSALS for _, reason in self.excluded)


def admit_retrieved_evidence(reader: Any, *, crop_season_id: str, retrieved: Sequence[Any],
                             demo: bool) -> EvidenceAdmission:
    """M7 E5.1 gate 1, BEFORE any provider call: only retrieved chunks that are admissible now under the current
    integrity pin (`_evidence_refusal`) may enter the model context. The check runs in the database under the
    CALLER'S JWT (`knowledge_evidence_admission`); a reader that cannot run it, or a failing check, refuses the
    request (RetrievalUnavailable), it never passes the chunks through. E3 containment is NOT applied here: a
    dismissed conflict stays an answer-time decision (gate 2), exactly as owner decisions D-E3-1..3 define it."""
    chunks = list(retrieved)
    if not chunks:
        return EvidenceAdmission(admitted=())
    lookup = getattr(reader, "knowledge_evidence_admission", None)
    if lookup is None:
        raise RetrievalUnavailable("this reader cannot check evidence admission")
    ids = sorted({c.chunk_id for c in chunks})
    try:
        rows = list(lookup(crop_season_id, ids, demo=demo))
    except Exception as exc:  # noqa: BLE001 - adapter boundary: fail closed, cause chained
        raise RetrievalUnavailable("evidence admission check failed") from exc
    state = _validated_state(rows, "evidence admission check")
    admitted, excluded = [], []
    for c in chunks:
        why = _evidence_refusal(state.get((c.source_id, c.chunk_id)), c, demo=demo)
        if why is None:
            admitted.append(c)
        else:
            excluded.append((c.chunk_id, why))
    return EvidenceAdmission(admitted=tuple(admitted), excluded=tuple(excluded))


class AdmittedEvidenceRetriever:
    """Wraps the request's retriever: the orchestrator (and so the model) only ever sees gate-1-admitted chunks.
    `admission` keeps the last result for the answer's explanation and the developer log (never the response)."""

    def __init__(self, inner: Any, reader: Any, *, demo: bool) -> None:
        self._inner, self._reader, self._demo = inner, reader, demo
        self.admission: EvidenceAdmission | None = None

    def retrieve(self, query: Any) -> tuple[Any, ...]:
        rows = tuple(self._inner.retrieve(query))
        season_id = query.tenant.crop_season_id
        if season_id is None:
            raise RetrievalUnavailable("evidence admission needs the authorized crop season")
        self.admission = admit_retrieved_evidence(self._reader, crop_season_id=season_id, retrieved=rows,
                                                  demo=self._demo)
        if self.admission.excluded:
            logger.warning("rag_evidence_not_admitted crop_season_id=%s reasons=%s", season_id,
                           sorted({reason for _, reason in self.admission.excluded}))
        return self.admission.admitted


def explain_unadmitted_evidence(result: Any, admission: EvidenceAdmission | None) -> Any:
    """A request that found no usable document only because gate 1 excluded documents whose integrity evidence is
    not current says so (trusted copy), instead of the generic "no approved document" message."""
    if (admission is None or not admission.pin_excluded or result.status != "insufficient_evidence"
            or result.insufficient_reason != "no_evidence_retrieved"):
        return result
    return result.model_copy(update={"insufficient_reason": "no_integrity_current_evidence",
                                     "answer": INSUFFICIENT_MESSAGES["no_integrity_current_evidence"],
                                     "answer_template": None})


#: Trusted Vietnamese labels for farmer-facing copy (D-E3-3: no internal code is shown).
FINDING_TYPE_LABELS = {
    "reference_conflict": "mâu thuẫn với tài liệu tham chiếu",
    "claim_conflict": "mâu thuẫn với nội dung của một tài liệu khác trong kho tri thức",
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
    """The citation's headline warning: chosen by trusted code from the finding TYPES, never from any text."""
    return CITATION_CONFLICT_WARNING if is_conflict(types) else CITATION_CAVEAT


def citation_detail(types) -> str:
    """The citation's finding description (labels only; an unknown code is never echoed)."""
    return CITATION_FINDINGS_DETAIL.format(labels=finding_labels(types))


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
        # E5.1: a document whose integrity evidence is not under the current pin is not admissible either; it
        # takes precedence over E3 (the conflict review it would rest on is itself out of date).
        if reasons <= _CONTAINMENT_REFUSALS:
            why = "evidence_integrity_contested"
        elif reasons <= _CONTAINMENT_REFUSALS | _PIN_REFUSALS:
            why = "evidence_integrity_not_current"
        else:
            why = "evidence_no_longer_admissible"
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
        # A warned citation keeps its authorized title but never carries a navigable URL, for every client
        # (owner decision 2026-11-16, READ-tier citation UX): decided from the finding TYPES, never from text.
        "evidence": tuple(c.model_copy(update={"integrity_warning": citation_warning(warnings[c.chunk_id]),
                                               "integrity_detail": citation_detail(warnings[c.chunk_id]),
                                               "url": None})
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
    out = []
    for r in rows:
        if r["chunk_id"] not in wanted:
            continue
        assurance = r.get("approval_assurance", "verified")
        out.append({"source_id": r["source_id"], "document_id": r["document_id"],
                    "document_version": r.get("document_version"), "chunk_id": r["chunk_id"],
                    "content_sha256": _sha(r["content"]), "content_hash_consistent": True,
                    "approval_assurance": assurance, "resolved_finding_types": [],
                    "integrity_status": "current" if assurance == "verified" else "demo_unverified"})
    return out

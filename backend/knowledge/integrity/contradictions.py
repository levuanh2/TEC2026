"""Deterministic contradiction CANDIDATES between stored claims of different chunks and documents
(RAG V1.5 M4, docs/rag/RAG_V15_M4_CLAIMS_CONTRADICTIONS.md).

Pure: stdlib only, no database. The caller supplies claim records and the context of their
documents (scope, validity window, supersession, evidence state) exactly as the database holds
them, and gets back candidate pairs for a HUMAN reviewer. A candidate is a review aid, never a
factual verdict, and nothing here approves, rejects or quarantines anything.

Two claims are compared only when that is meaningful:
- same comparison key (one parameter in one canonical unit), both extracted unambiguously;
- different chunks (one chunk listing several values is a dose split or a stage sequence);
- inside one data boundary: public with public, a tenant with itself or with public, never one
  tenant with another, and never two different farms of one tenant;
- not two different, stated crop stages;
- at least one side is usable evidence (see below);
- their value ranges do NOT overlap, after widening by an explicit tolerance if one was supplied
  for that parameter. No tolerance is assumed: without one, only disjoint ranges are reported.

Classification of a reported pair, first match wins:
- insufficient_evidence   one side is not active approved evidence (rejected, quarantined, archived,
                          expired, not yet in force, or its source is not approved). It can never
                          count as a contradiction of current guidance.
- apparent_contradiction  an ordinary explanation is on record: one version supersedes the other
                          (directly or through a chain), their validity windows do not overlap,
                          or they are two versions of one document.
- missing_context         one side states a crop stage or a practice tag (e.g. AWD) and the other
                          does not, so it is unknown whether they describe the same situation.
- contradiction           none of the above: same parameter, same stated context, both usable.

Evidence state of a document (decided by the database, passed in):
- active     approved, its source approved, in force today (M3)
- candidate  review_required or expert_review (the version under review)
- inactive   everything else
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from knowledge.integrity.claims import Claim

ANALYSIS_VERSION = "kn-contradictions-1"

Classification = Literal["contradiction", "apparent_contradiction", "missing_context", "insufficient_evidence"]
CLASSIFICATIONS: tuple[str, ...] = ("contradiction", "apparent_contradiction", "missing_context",
                                    "insufficient_evidence")
EVIDENCE_STATES: tuple[str, ...] = ("active", "candidate", "inactive")
Independence = Literal["same_document", "same_source", "independent_source"]


@dataclass(frozen=True)
class DocumentRecord:
    document_pk: str
    source_id: str
    document_id: str
    document_version: str
    visibility: str                          # "public" | "tenant"
    organization_id: str | None
    farm_id: str | None
    evidence_state: str                      # EVIDENCE_STATES
    state_reason: str                        # e.g. "approved_in_force", "quarantined", "not_in_force"
    effective_from: date | None = None
    effective_to: date | None = None
    supersedes_document_pk: str | None = None


@dataclass(frozen=True)
class ClaimRecord:
    record_id: int                           # the stored claim's id (orders a pair)
    document_pk: str
    chunk_id: str
    claim_id: str
    comparison_key: str | None               # parameter|unit; None = not comparable
    value_min: float | None
    value_max: float | None
    stage: str | None = None
    scope_tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Tolerance:
    """An explicit, justified widening for one comparison key. Never defaulted."""
    comparison_key: str
    absolute: float
    rationale: str

    def __post_init__(self) -> None:
        if not self.comparison_key or self.absolute < 0 or self.absolute != self.absolute \
                or self.absolute == float("inf") or not self.rationale.strip():
            raise ValueError("a tolerance needs a comparison key, a finite value >= 0 and a rationale")


@dataclass(frozen=True)
class Candidate:
    claim_a: int                             # record ids, claim_a < claim_b
    claim_b: int
    comparison_key: str
    classification: str
    reasons: tuple[str, ...]
    independence: str
    tolerance: float = 0.0
    tolerance_rationale: str = ""


@dataclass(frozen=True)
class Analysis:
    analysis_version: str
    candidates: tuple[Candidate, ...]
    compared: int                            # pairs that reached the value comparison
    skipped: tuple[tuple[str, int], ...]     # (reason, pairs) for pairs never compared
    decision: Literal["none"] = "none"       # this report never approves, rejects or quarantines

    def of(self, classification: str) -> tuple[Candidate, ...]:
        return tuple(c for c in self.candidates if c.classification == classification)


def comparison_key(claim: Claim) -> str | None:
    """`parameter|unit` for an unambiguous quantity with a parameter and a range; else None."""
    if (claim.kind == "quantity" and claim.status == "extracted" and claim.parameter and claim.unit
            and claim.value_min is not None and claim.value_max is not None):
        return f"{claim.parameter}|{claim.unit}"
    return None


def claim_payload(claim: Claim) -> dict:
    """The stored form of one extracted claim (private.knowledge_record_claims). Nothing is added:
    an ambiguous or unsupported claim keeps its status and has no comparison key."""
    return {
        "claim_id": claim.claim_id, "chunk_id": claim.chunk_id, "span_start": claim.start, "span_end": claim.end,
        "raw_text": claim.text, "kind": claim.kind, "status": claim.status, "parameter": claim.parameter,
        "value_min": claim.value_min, "value_max": claim.value_max, "unit": claim.unit, "dimension": claim.dimension,
        "date_iso": claim.date_iso, "stage": claim.stage, "scope_tags": list(claim.scope), "note": claim.note,
    }


def same_boundary(a: DocumentRecord, b: DocumentRecord) -> bool:
    """Public with public; a tenant with itself (not two different farms) or with public."""
    if a.visibility == "public" or b.visibility == "public":
        return True
    if a.organization_id is None or a.organization_id != b.organization_id:
        return False
    return a.farm_id is None or b.farm_id is None or a.farm_id == b.farm_id


def _ancestors(document_pk: str, supersedes: dict[str, str | None]) -> set[str]:
    seen: set[str] = set()
    current = supersedes.get(document_pk)
    while current and current not in seen:
        seen.add(current)
        current = supersedes.get(current)
    return seen


def _periods_disjoint(a: DocumentRecord, b: DocumentRecord) -> bool:
    if a.effective_to and b.effective_from and a.effective_to < b.effective_from:
        return True
    return bool(b.effective_to and a.effective_from and b.effective_to < a.effective_from)


def _independence(a: DocumentRecord, b: DocumentRecord) -> str:
    if a.document_pk == b.document_pk:
        return "same_document"
    return "same_source" if a.source_id == b.source_id else "independent_source"


def _classify(a: ClaimRecord, b: ClaimRecord, doc_a: DocumentRecord, doc_b: DocumentRecord,
              supersedes: dict[str, str | None]) -> tuple[str, tuple[str, ...]]:
    inactive = [f"inactive_evidence:{d.state_reason}" for d in (doc_a, doc_b) if d.evidence_state == "inactive"]
    explained = []
    if doc_a.document_pk != doc_b.document_pk:
        if doc_b.document_pk in _ancestors(doc_a.document_pk, supersedes) \
                or doc_a.document_pk in _ancestors(doc_b.document_pk, supersedes):
            explained.append("superseded_version")
        if _periods_disjoint(doc_a, doc_b):
            explained.append("disjoint_validity")
        if (doc_a.source_id, doc_a.document_id) == (doc_b.source_id, doc_b.document_id):
            explained.append("other_version_of_document")
    context = []
    if (a.stage is None) != (b.stage is None):
        context.append("stage_unstated")
    if set(a.scope_tags) != set(b.scope_tags):
        context.append("scope_tag_differs")
    reasons = tuple(dict.fromkeys(inactive)) + tuple(explained) + tuple(context)
    if inactive:
        return "insufficient_evidence", reasons
    if explained:
        return "apparent_contradiction", reasons
    if context:
        return "missing_context", reasons
    return "contradiction", reasons or ("same_parameter_same_context",)


def analyze(claims: Iterable[ClaimRecord], documents: Iterable[DocumentRecord], *,
            tolerances: Sequence[Tolerance] = (), subject_document_pk: str | None = None) -> Analysis:
    """Candidate pairs among `claims`. With `subject_document_pk`, only pairs that involve a claim of
    that document. Deterministic: the result does not depend on the input order."""
    docs = {d.document_pk: d for d in documents}
    for d in docs.values():
        if d.evidence_state not in EVIDENCE_STATES:
            raise ValueError(f"unknown evidence state {d.evidence_state!r}")
    supersedes = {d.document_pk: d.supersedes_document_pk for d in docs.values()}
    widen: dict[str, Tolerance] = {}
    for t in tolerances:
        if t.comparison_key in widen:
            raise ValueError(f"two tolerances for {t.comparison_key!r}")
        widen[t.comparison_key] = t
    by_key: dict[str, list[ClaimRecord]] = {}
    for c in sorted(claims, key=lambda c: c.record_id):
        if c.comparison_key and c.value_min is not None and c.value_max is not None and c.document_pk in docs:
            by_key.setdefault(c.comparison_key, []).append(c)
    skipped: dict[str, int] = {}
    candidates: list[Candidate] = []
    compared = 0
    for key in sorted(by_key):
        group = by_key[key]
        tolerance = widen.get(key)
        margin = tolerance.absolute if tolerance else 0.0
        for i, a in enumerate(group):
            for b in group[i + 1:]:
                if a.record_id == b.record_id:
                    continue
                if subject_document_pk and subject_document_pk not in (a.document_pk, b.document_pk):
                    continue
                doc_a, doc_b = docs[a.document_pk], docs[b.document_pk]
                reason = None
                if (a.document_pk, a.chunk_id) == (b.document_pk, b.chunk_id):
                    reason = "same_chunk"
                elif not same_boundary(doc_a, doc_b):
                    reason = "scope_boundary"
                elif a.stage is not None and b.stage is not None and a.stage != b.stage:
                    reason = "different_stage"
                elif doc_a.evidence_state == "inactive" and doc_b.evidence_state == "inactive":
                    reason = "both_inactive"
                if reason:
                    skipped[reason] = skipped.get(reason, 0) + 1
                    continue
                compared += 1
                if a.value_min <= b.value_max + margin and b.value_min <= a.value_max + margin:
                    continue                                    # the ranges agree
                classification, reasons = _classify(a, b, doc_a, doc_b, supersedes)
                candidates.append(Candidate(a.record_id, b.record_id, key, classification, reasons,
                                            _independence(doc_a, doc_b), margin,
                                            tolerance.rationale if tolerance else ""))
    return Analysis(ANALYSIS_VERSION, tuple(candidates), compared, tuple(sorted(skipped.items())))


def candidate_payload(candidate: Candidate) -> dict:
    """The stored form of one candidate (private.knowledge_record_contradiction_candidates)."""
    return {"claim_a": candidate.claim_a, "claim_b": candidate.claim_b, "classification": candidate.classification,
            "reasons": list(candidate.reasons), "independence": candidate.independence,
            "tolerance": candidate.tolerance, "tolerance_rationale": candidate.tolerance_rationale}

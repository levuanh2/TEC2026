"""Offline integrity review: claims vs claims, claims vs the trusted-reference registry, and
document validity periods. The output is a list of findings for a HUMAN expert.

The report never decides anything. `decision` is always "none": no approval, rejection,
quarantine or status change follows from it, and nothing in the RAG answer path reads it.
A finding marked needs_expert_review means "a person must resolve this before approval". It
does not mean the document is false. An empty report does not mean the document is true.

Comparison rules (conservative: compare only when it is meaningful):
- Only claims with status "extracted" and a parameter are compared.
- Quantities are compared only within one parameter, which implies one dimension. Units are
  already canonical (claims.py), and a registry entry of another dimension is refused at load
  time, so incompatible units are never compared.
- Stage scope must agree: a claim scoped to a stage is compared with an unscoped claim or a
  claim of the same stage, never with a claim of another stage.
- Two documents with disjoint validity periods, or where one supersedes the other, are not
  compared with each other.
- Two claims from the same chunk are never compared with each other (split doses, stage
  sequences). Each is still compared with the registry.
- Ranges conflict only when they do not overlap. A registry entry widens its range by its
  tolerance.
- Every registry entry can raise a conflict, whatever its verification status. The finding names
  that status, and the expert decides how much weight it carries.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

from knowledge.integrity.claims import ASSERTIONS, CLAIM_EXTRACTOR_VERSION, Claim, ClaimSource, extract_claims
from knowledge.integrity import reference_numeric as rn
from knowledge.integrity.conditions import CONDITION_EXTRACTOR_VERSION, NumericComparison, compare_claims
from knowledge.integrity.references import ReferenceEntry, ReferenceRegistry

REVIEW_VERSION = "kn-integrity-review-1"

FindingType = Literal[
    "reference_conflict",      # claim contradicts a registry entry
    "claim_conflict",          # two claims of the same parameter and scope disagree
    "unsupported_assertion",   # an absolute qualitative statement with no registry entry
    "expired_guidance",        # document validity ended before as_of
    "not_yet_effective",       # document validity starts after as_of
    "superseded_guidance",     # another document in the review declares that it replaces this one
    "unresolved_claim",        # ambiguous / unsupported extraction (info)
    "unreferenced_claim",      # a quantity with a parameter but no registry entry (info)
    # M5 follow-up (numeric_registry given): against HUMAN-VERIFIED numeric entries only
    "numeric_reference_mismatch",   # outside the printed range / differs from the printed value
    "numeric_unresolved",           # out_of_scope, not_comparable, reference_unverified or no entry (info)
]
_NEEDS_REVIEW = frozenset({"reference_conflict", "claim_conflict", "unsupported_assertion", "expired_guidance",
                           "not_yet_effective", "superseded_guidance", "numeric_reference_mismatch"})
_EVIDENCE = {
    "reference_conflict": "the publisher's primary text for this statement, or a recorded expert justification "
                          "for deviating from the reference",
    "claim_conflict": "which source governs for this scope and period (effective dates, supersession, expert note)",
    "unsupported_assertion": "a primary source stating this explicitly, or removal/exclusion of the chunk",
    "expired_guidance": "a current version of the document, or confirmation from the publisher that it still applies",
    "not_yet_effective": "the effective date from the publisher; the version must not be used before it",
    "superseded_guidance": "archive the superseded version, or a publisher statement that both apply",
    "unresolved_claim": "a reviewer reads the span; no automatic comparison was possible",
    "unreferenced_claim": "optional: a registry entry with a primary source for this parameter",
    "numeric_reference_mismatch": "the publisher's primary text for this value and its conditions, or a recorded "
                                  "expert justification; the comparison lists units, conversion and conditions",
    "numeric_unresolved": "a reviewer decides whether the reference applies; no mismatch was concluded",
}


@dataclass(frozen=True)
class DocumentContext:
    document_ref: str
    effective_from: date | None = None
    effective_to: date | None = None
    supersedes: tuple[str, ...] = ()           # document_refs this document replaces


@dataclass(frozen=True)
class Finding:
    finding_type: str
    needs_expert_review: bool
    document_refs: tuple[str, ...]
    claim_ids: tuple[str, ...]
    reference_ids: tuple[str, ...]
    detail: str
    evidence_needed: str


@dataclass(frozen=True)
class IntegrityReview:
    review_version: str
    extractor_version: str
    registry_version: str
    registry_digest: str
    as_of: str
    claims: tuple[Claim, ...]
    findings: tuple[Finding, ...]
    decision: Literal["none"] = "none"         # this report never approves, rejects or quarantines
    #: M5 follow-up: one row per (claim, numeric entry) with the full reasoning; empty without a registry
    numeric_comparisons: tuple[NumericComparison, ...] = ()
    numeric_registry_version: str | None = None
    numeric_registry_digest: str | None = None
    condition_extractor_version: str | None = None

    @property
    def requires_expert_review(self) -> bool:
        return any(f.needs_expert_review for f in self.findings)

    def of_type(self, finding_type: str) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.finding_type == finding_type)


def _finding(kind: str, claims: Sequence[Claim] = (), refs: Sequence[ReferenceEntry] = (), docs: Sequence[str] = (),
             detail: str = "") -> Finding:
    doc_refs = tuple(sorted(set(docs) | {c.document_ref for c in claims}))
    return Finding(kind, kind in _NEEDS_REVIEW, doc_refs, tuple(c.claim_id for c in claims),
                   tuple(r.reference_id for r in refs), detail, _EVIDENCE[kind])


def _overlap(a_low: float, a_high: float, b_low: float, b_high: float) -> bool:
    return a_low <= b_high and b_low <= a_high


def _stage_ok(a: str | None, b: str | None) -> bool:
    return a is None or b is None or a == b


def _fmt(low: float | None, high: float | None, unit: str | None) -> str:
    value = f"{low:g}" if low == high else f"{low:g}-{high:g}"
    return f"{value} {unit}"


def _periods_disjoint(a: DocumentContext | None, b: DocumentContext | None) -> bool:
    if a is None or b is None:
        return False
    if a.effective_to and b.effective_from and a.effective_to < b.effective_from:
        return True
    return bool(b.effective_to and a.effective_from and b.effective_to < a.effective_from)


def review(sources: Sequence[ClaimSource], *, registry: ReferenceRegistry, as_of: date,
           documents: Sequence[DocumentContext] = (),
           numeric_registry: rn.NumericRegistry | None = None) -> IntegrityReview:
    claims = tuple(c for source in sources for c in extract_claims(source))
    contexts = {d.document_ref: d for d in documents}
    replaced: dict[str, set[str]] = {}
    for d in documents:
        for old in d.supersedes:
            replaced.setdefault(old, set()).add(d.document_ref)
    findings: list[Finding] = []

    # Validity periods and supersession (needs DocumentContext; documents without one are not judged).
    for d in documents:
        if d.effective_to and d.effective_to < as_of:
            findings.append(_finding("expired_guidance", docs=[d.document_ref],
                                     detail=f"effective_to {d.effective_to.isoformat()} < as_of {as_of.isoformat()}"))
        if d.effective_from and d.effective_from > as_of:
            findings.append(_finding("not_yet_effective", docs=[d.document_ref],
                                     detail=f"effective_from {d.effective_from.isoformat()} > as_of {as_of.isoformat()}"))
    for old, newer in sorted(replaced.items()):
        findings.append(_finding("superseded_guidance", docs=[old, *sorted(newer)],
                                 detail=f"{old} is superseded by {', '.join(sorted(newer))}"))

    usable = [c for c in claims if c.status == "extracted" and c.parameter]
    for c in claims:
        if c.status != "extracted" or (c.kind == "quantity" and not c.parameter):
            findings.append(_finding("unresolved_claim", [c], detail=f"{c.status}: {c.text!r} {c.note}".strip()))

    # Claims vs the registry.
    for c in usable:
        if c.kind == "assertion":
            entries = [e for e in registry.for_parameter(c.parameter) if e.kind == "qualitative"]
            if not entries:
                findings.append(_finding("unsupported_assertion", [c],
                                         detail=f"{ASSERTIONS[c.parameter]}: no registry entry"))
            for e in entries:
                if e.assertion_holds is False:
                    findings.append(_finding("reference_conflict", [c], [e],
                                             detail=f"claims '{ASSERTIONS[c.parameter]}'; reference says it does not "
                                                    f"hold ({e.verification_status})"))
        elif c.kind == "quantity":
            entries = [e for e in registry.for_parameter(c.parameter)
                       if e.kind == "quantity" and _stage_ok(e.stage, c.stage)]
            if not entries:
                findings.append(_finding("unreferenced_claim", [c], detail=f"{c.parameter}: no registry entry"))
            for e in entries:
                if not _overlap(c.value_min, c.value_max, e.value_min - e.tolerance, e.value_max + e.tolerance):
                    findings.append(_finding("reference_conflict", [c], [e],
                                             detail=f"{c.parameter}: {_fmt(c.value_min, c.value_max, c.unit)} outside "
                                                    f"{_fmt(e.value_min, e.value_max, e.unit)} ± {e.tolerance:g} "
                                                    f"({e.verification_status})"))

    # Claims vs claims (quantities of one parameter and compatible stage).
    quantities = [c for c in usable if c.kind == "quantity"]
    pairs = [(a, b) for i, a in enumerate(quantities) for b in quantities[i + 1:]]
    for a, b in pairs:
        if a.parameter != b.parameter or not _stage_ok(a.stage, b.stage):
            continue
        if (a.document_ref, a.chunk_id) == (b.document_ref, b.chunk_id):
            continue        # one chunk listing several values (split doses, stage sequences) is not a contradiction
        if a.document_ref != b.document_ref:
            if _periods_disjoint(contexts.get(a.document_ref), contexts.get(b.document_ref)):
                continue
            if a.document_ref in replaced.get(b.document_ref, ()) or b.document_ref in replaced.get(a.document_ref, ()):
                continue
        if not _overlap(a.value_min, a.value_max, b.value_min, b.value_max):
            findings.append(_finding("claim_conflict", [a, b],
                                     detail=f"{a.parameter}: {_fmt(a.value_min, a.value_max, a.unit)} vs "
                                            f"{_fmt(b.value_min, b.value_max, b.unit)}"))

    # M5 follow-up: claims vs the human-verified numeric registry (non-blocking analysis aid).
    comparisons: tuple[NumericComparison, ...] = ()
    if numeric_registry is not None:
        contents = {(s.document_ref, s.chunk_id): s.content for s in sources}
        comparisons = compare_claims(claims, contents, numeric_registry)
        for c in comparisons:
            tags = ", ".join(t.tag for t in c.conditions) or "none stated"
            detail = (f"{c.parameter}: claimed {c.claimed_min}..{c.claimed_max} {c.claim_unit} [conditions: {tags};"
                      f" region: {c.region or 'none stated'}] vs {c.reference_id or 'no entry'}: {c.outcome}."
                      f" {c.rationale}")
            refs = [c.reference_id] if c.reference_id else []
            findings.append(Finding("numeric_reference_mismatch" if c.is_mismatch else "numeric_unresolved",
                                    c.is_mismatch, (c.document_ref,), (c.claim_id,), tuple(refs), detail,
                                    _EVIDENCE["numeric_reference_mismatch" if c.is_mismatch else "numeric_unresolved"]))

    findings.sort(key=lambda f: (not f.needs_expert_review, f.finding_type, f.document_refs, f.claim_ids,
                                 f.reference_ids))
    return IntegrityReview(REVIEW_VERSION, CLAIM_EXTRACTOR_VERSION, registry.registry_version, registry.digest,
                           as_of.isoformat(), claims, tuple(findings), numeric_comparisons=comparisons,
                           numeric_registry_version=numeric_registry.registry_version if numeric_registry else None,
                           numeric_registry_digest=numeric_registry.digest if numeric_registry else None,
                           condition_extractor_version=CONDITION_EXTRACTOR_VERSION if numeric_registry else None)

"""RAG V1.5 M7 E2: the integrity report payload the database records for one document version
(private.knowledge_record_integrity_report). Pure: no database, no network.

The database re-derives what it can (snapshot hashes, claim spans from the stored M4 claims, whether a
finding needs expert review) and refuses a report that omits a stored assertion or unreadable claim. This
module only turns the deterministic offline review into that payload and states its limitations honestly:
an empty or unverified registry is never presented as verified content.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from knowledge.integrity.claims import CLAIM_EXTRACTOR_VERSION, Claim
from knowledge.integrity.references import ReferenceRegistry
from knowledge.integrity.review import REVIEW_VERSION, IntegrityReview

#: Finding types that describe the document as a whole (they need DocumentContext and name no claim).
_DOCUMENT_LEVEL = frozenset({"expired_guidance", "not_yet_effective", "superseded_guidance"})


def report_payload(result: IntegrityReview, registry: ReferenceRegistry) -> dict[str, Any]:
    """{extractor_version, review_version, registry_version, registry_digest, findings, supported, limitations}."""
    findings = [{"finding_type": f.finding_type, "claim_ids": sorted(set(f.claim_ids)),
                 "reference_ids": sorted(set(f.reference_ids)), "detail": f.detail[:2000] or f.finding_type}
                for f in result.findings if f.claim_ids or f.finding_type not in _DOCUMENT_LEVEL]
    flagged = {cid for f in result.findings if f.needs_expert_review for cid in f.claim_ids}
    supported = []
    for claim in _assertions(result.claims):
        if claim.claim_id in flagged:
            continue
        holding = [e.reference_id for e in registry.for_parameter(claim.parameter)
                   if e.kind == "qualitative" and e.assertion_holds is True]
        if holding:          # otherwise the claim stays uncovered and the database refuses the report
            supported.append({"claim_id": claim.claim_id, "reference_id": holding[0]})
    return {"extractor_version": result.extractor_version, "review_version": result.review_version,
            "registry_version": result.registry_version, "registry_digest": result.registry_digest,
            "findings": findings, "supported": supported, "limitations": limitations(result, registry)}


def _assertions(claims: Sequence[Claim]) -> list[Claim]:
    return [c for c in claims if c.kind == "assertion" and c.status == "extracted" and c.parameter]


def limitations(result: IntegrityReview, registry: ReferenceRegistry) -> list[str]:
    out = [f"deterministic extractor {CLAIM_EXTRACTOR_VERSION} and review {REVIEW_VERSION}: only the claim patterns"
           " they know are read; absence of a finding is not evidence that the text is correct"]
    if not result.claims:
        out.append("no claim was extracted from this version: nothing was compared, the text is unchecked")
    statuses = sorted({e.verification_status for e in registry.entries})
    if not any(e.independently_verified for e in registry.entries):
        out.append("no registry entry is human-verified against a primary source (statuses: "
                   + ", ".join(statuses or ["none"]) + ")")
    unresolved = [c for c in result.claims if c.status != "extracted"]
    if unresolved:
        out.append(f"{len(unresolved)} claim(s) could not be read (ambiguous or unsupported) and were not compared")
    out.append("numeric reference comparison: the numeric registry holds no human-verified entry")
    return out

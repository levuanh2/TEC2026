"""RAG V1.5 M7 E7: the deterministic, independently re-runnable part of integrity verification
(docs/rag/RAG_V15_M7_E7_INDEPENDENT_VERIFICATION.md). Pure: no database, no network, no key.

The verifier re-reads the stored chunk text (never the operator's submitted claims), runs the pinned
extractor, and states the canonical digest of the claim set it found. The database computes the same digest
over the claims the operator stored (`private.knowledge_claim_set_digest`) and accepts a verification only
when they are equal and the statement is signed by a registered verifier key.

Canonical form (identical in SQL): one line per claim, sorted by claim_id, fields joined by "|":
claim_id, chunk_id, chunk_content_sha256, span_start, span_end, kind, status, parameter, value_min,
value_max, unit, dimension, date_iso, stage, sorted scope tags joined by ","; numbers without trailing zeros
(Decimal.normalize / trim_scale), a null as the empty string; lines joined by "\\n"; sha256 hex of UTF-8.
Independent of filesystem order, locale, DateStyle, timezone and JSON key order.

A matching digest shows the claim set is REPRODUCIBLE under the pinned extractor. It does not show that
every scientific claim in the document was found.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from typing import Any

from knowledge.ids import sha256_hex
from knowledge.integrity.claims import CLAIM_EXTRACTOR_VERSION, Claim, ClaimSource, extract_claims

VERIFICATION_FORMAT = "kn-integrity-verification-1"
#: The code that determines the verifier's claim set and verdict, relative to the `knowledge` package: the
#: extractor, the claim-id derivation it imports, and this module (canonical form and comparison). Its digest
#: is pinned by the owner and signed by the verifier; a change to any of them needs a re-pin.
EXTRACTOR_SOURCES = ("integrity/claims.py", "ids.py", "integrity/verifier.py")


def _num(value: Any) -> str:
    if value is None:
        return ""
    text = format(Decimal(repr(value) if isinstance(value, float) else str(value)).normalize(), "f")
    return "0" if text in ("-0", "") else text


def canonical_line(c: Mapping[str, Any]) -> str:
    tags = ",".join(sorted(c.get("scope_tags") or ()))
    fields = (c["claim_id"], c["chunk_id"], c["chunk_content_sha256"], str(int(c["span_start"])),
              str(int(c["span_end"])), c["kind"], c["status"], c.get("parameter") or "", _num(c.get("value_min")),
              _num(c.get("value_max")), c.get("unit") or "", c.get("dimension") or "", c.get("date_iso") or "",
              c.get("stage") or "", tags)
    return "|".join(fields)


def claim_set_digest(claims: Iterable[Mapping[str, Any]]) -> str:
    lines = sorted((canonical_line(c) for c in claims), key=lambda line: line.split("|", 1)[0])
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def claim_record(claim: Claim, chunk_content_sha256: str) -> dict[str, Any]:
    return {"claim_id": claim.claim_id, "chunk_id": claim.chunk_id, "chunk_content_sha256": chunk_content_sha256,
            "span_start": claim.start, "span_end": claim.end, "kind": claim.kind, "status": claim.status,
            "parameter": claim.parameter, "value_min": claim.value_min, "value_max": claim.value_max,
            "unit": claim.unit, "dimension": claim.dimension, "date_iso": claim.date_iso, "stage": claim.stage,
            "scope_tags": list(claim.scope)}


def code_digest(sources: Sequence[tuple[str, bytes]]) -> str:
    """sha256 over (name, LF-normalized source bytes) of the extractor modules, in the given fixed order."""
    h = hashlib.sha256()
    for name, data in sources:
        h.update(name.encode() + b"\0" + data.replace(b"\r\n", b"\n") + b"\0")
    return h.hexdigest()


def reextract(document_ref: str, chunks: Sequence[tuple[str, str, str]]) -> list[dict[str, Any]]:
    """Re-run the pinned extractor over (chunk_id, content, content_sha256) read from the stored snapshot."""
    out: list[dict[str, Any]] = []
    for chunk_id, content, content_sha256 in chunks:
        out.extend(claim_record(c, content_sha256) for c in extract_claims(ClaimSource(document_ref, chunk_id, content)))
    return out


def coverage(chunks: Sequence[tuple[str, str, str]], recomputed: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """What the re-extraction did and did not cover, per stored chunk (chunk_id, content, content_sha256).

    Recorded in the signed statement as evidence; it does NOT change the verdict, which is about the claim
    set only. `chunk_hash_mismatch` names chunks whose stored text does not hash to their stored
    content_sha256: the database does not bind the two (an ingestion-level gap, documented), and the claims
    are bound to the stored hash. `chunks_without_claims` are chunks in which the pinned extractor found
    nothing: either no claim it recognises, or a claim outside its patterns (NOT evidence of clean content)."""
    with_claims = {c["chunk_id"] for c in recomputed}
    return {"chunks_read": len(chunks),
            "chunks_with_claims": sum(1 for cid, _, _ in chunks if cid in with_claims),
            "chunks_without_claims": sorted(cid for cid, _, _ in chunks if cid not in with_claims),
            "empty_chunks": sorted(cid for cid, text, _ in chunks if not (text or "").strip()),
            "chunk_hash_mismatch": sorted(cid for cid, text, digest in chunks if sha256_hex(text or "") != digest)}


def compare(recomputed: Sequence[Mapping[str, Any]], stored: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    """Missing (recomputed, not stored), extra (stored, not recomputed) and altered claim ids."""
    a = {c["claim_id"]: canonical_line(c) for c in recomputed}
    b = {c["claim_id"]: canonical_line(c) for c in stored}
    return {"missing": sorted(set(a) - set(b)), "extra": sorted(set(b) - set(a)),
            "altered": sorted(k for k in set(a) & set(b) if a[k] != b[k])}


def statement(*, report: Mapping[str, Any], key_id: str, recomputed: Sequence[Mapping[str, Any]],
              stored: Sequence[Mapping[str, Any]], chunks_read: int, registry_digest: str,
              extractor_code_digest: str, chunk_coverage: Mapping[str, Any] | None = None) -> str:
    """The exact text the verifier signs (canonical JSON: sorted keys, no whitespace, ASCII)."""
    diff = compare(recomputed, stored)
    verdict = "reproduced" if not any(diff.values()) and chunks_read == report["chunk_count"] else "mismatch"
    body = {
        "format": VERIFICATION_FORMAT, "key_id": key_id, "verdict": verdict,
        "report_id": str(report["id"]), "report_sha256": report["report_sha256"],
        "document_pk": str(report["document_pk"]), "document_snapshot_sha256": report["document_snapshot_sha256"],
        "source_snapshot_sha256": report["source_snapshot_sha256"],
        "extractor_version": CLAIM_EXTRACTOR_VERSION, "extractor_code_digest": extractor_code_digest,
        "registry_digest": registry_digest, "claim_set_digest": claim_set_digest(recomputed),
        "claim_count": len(recomputed), "chunks_read": chunks_read,
        "missing": diff["missing"], "extra": diff["extra"], "altered": diff["altered"],
        "limitations": ["reproducibility of the claim set under the pinned extractor only; claims the extractor"
                        " does not recognise are not found by either run"],
    }
    if chunk_coverage is not None:
        body["coverage"] = dict(chunk_coverage)
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

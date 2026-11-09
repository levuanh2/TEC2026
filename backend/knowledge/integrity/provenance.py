"""Provenance evaluation of one artifact: is there independent evidence of WHO published these
exact bytes, and is the declared metadata complete and consistent?

Every check yields one outcome:
  verified              -- independent evidence (or the bytes themselves) establishes it
  missing               -- the information or evidence is absent
  mismatch              -- the evidence contradicts the claim (wrong hash, foreign host, ...)
  unverified_assertion  -- a well-formed claim that nothing independent backs up

A URL, an HTTPS origin, a matching hash or a claimed publisher name is never treated as proof
of factual correctness: `content_correctness` is always "not_assessed". Content goes through
claims.py + review.py and, in the end, a human domain expert.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from knowledge.ids import sha256_hex
from knowledge.models import LICENSE_BASES, LICENSE_NEEDS_REFERENCE

PROVENANCE_CHECKER_VERSION = "kn-provenance-1"

Outcome = Literal["verified", "missing", "mismatch", "unverified_assertion"]
EvidenceMethod = Literal["pki_signature", "second_channel_sha256", "operator_assertion"]

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_HTTPS_HOST = re.compile(r"^https://([A-Za-z0-9.-]+)(?::\d+)?(?:[/?#]\S*)?$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_METHODS = frozenset({"pki_signature", "second_channel_sha256", "operator_assertion"})


@dataclass(frozen=True)
class TrustedPublisher:
    """An allowlist entry supplied by the caller (owner-maintained). Nothing is built in."""

    publisher_id: str
    hosts: frozenset[str]          # official HTTPS hosts (lowercase, exact match)
    signers: frozenset[str] = frozenset()   # accepted certificate subjects for PKI signatures


@dataclass(frozen=True)
class VerificationEvidence:
    """One piece of evidence recorded by a person or tool.

    pki_signature:          attested_by = the signer subject of a signature verified against
                            an official trust anchor; artifact_sha256 = the bytes it covers.
    second_channel_sha256:  attested_by = the https URL where the publisher lists the hash,
                            reached independently of the artifact download.
    operator_assertion:     someone says so. Never counts as verification.
    """

    method: str
    attested_by: str
    artifact_sha256: str | None = None
    independent: bool = False
    evidence_ref: str | None = None    # sha256 of the stored evidence file (signature report, page capture)


@dataclass(frozen=True)
class ProvenanceClaim:
    publisher_id: str | None
    official_url: str | None
    declared_sha256: str | None
    document_version: str | None
    license_basis: str | None
    license_reference: str | None = None
    evidence: tuple[VerificationEvidence, ...] = ()


@dataclass(frozen=True)
class ProvenanceCheck:
    name: str
    outcome: Outcome
    detail: str


@dataclass(frozen=True)
class ProvenanceReport:
    checker_version: str
    artifact_sha256: str
    status: Literal["verified", "mismatch", "incomplete", "unverified"]
    checks: tuple[ProvenanceCheck, ...]
    content_correctness: Literal["not_assessed"] = "not_assessed"

    def outcome(self, name: str) -> Outcome:
        return next(c.outcome for c in self.checks if c.name == name)


def _host(url: str | None) -> str | None:
    match = _HTTPS_HOST.match(url or "")
    return match.group(1).lower() if match else None


def _usable(ev: VerificationEvidence, publisher: TrustedPublisher | None, official_url: str | None,
            actual_sha256: str) -> bool:
    """Evidence that can count as independent: it attests THESE bytes, is flagged independent, has a
    stored evidence file, comes from a channel the allowlist accepts, and is not the artifact's own
    download URL."""
    if ev.method not in ("pki_signature", "second_channel_sha256") or not ev.independent:
        return False
    if not _SHA256.match(ev.evidence_ref or "") or ev.artifact_sha256 != actual_sha256:
        return False
    if publisher is None:
        return False
    if ev.method == "pki_signature":
        return ev.attested_by in publisher.signers
    return _host(ev.attested_by) in publisher.hosts and ev.attested_by != official_url


def evaluate_provenance(artifact: bytes, claim: ProvenanceClaim, *,
                        publishers: dict[str, TrustedPublisher], expected_version: str | None = None) -> ProvenanceReport:
    """Pure: no network. `expected_version` is the version declared elsewhere (ingestion spec)."""
    actual = sha256_hex(artifact)
    publisher = publishers.get(claim.publisher_id or "")
    checks: list[ProvenanceCheck] = []

    def add(name: str, outcome: Outcome, detail: str) -> None:
        checks.append(ProvenanceCheck(name, outcome, detail))

    # 1. Declared hash vs the bytes in hand (local consistency only).
    if not claim.declared_sha256:
        add("artifact_sha256", "missing", "no declared SHA-256")
    elif not _SHA256.match(claim.declared_sha256):
        add("artifact_sha256", "mismatch", "declared SHA-256 is not 64 lowercase hex characters")
    elif claim.declared_sha256 != actual:
        add("artifact_sha256", "mismatch", "declared SHA-256 differs from the artifact bytes")
    else:
        add("artifact_sha256", "verified", "declared SHA-256 equals the artifact bytes")

    # 2. Independent binding of these bytes to the publisher (authenticity).
    malformed = [e for e in claim.evidence if e.method not in _METHODS]
    usable = [e for e in claim.evidence if _usable(e, publisher, claim.official_url, actual)]
    contradicting = [e for e in claim.evidence
                     if e.method in ("pki_signature", "second_channel_sha256") and e.artifact_sha256
                     and e.artifact_sha256 != actual]
    if malformed:
        add("authenticity", "mismatch", f"unknown evidence method(s): {sorted({e.method for e in malformed})}")
    elif contradicting:
        add("authenticity", "mismatch", "evidence attests a different SHA-256: forged, altered or wrong artifact")
    elif usable:
        add("authenticity", "verified", f"{len(usable)} independent evidence item(s) bind the bytes to the publisher")
    elif claim.evidence:
        add("authenticity", "unverified_assertion",
            "evidence exists but none is independent, stored, and from an allowlisted channel")
    else:
        add("authenticity", "missing", "no verification evidence")

    # 3. Publisher identity.
    if not claim.publisher_id:
        add("publisher", "missing", "no publisher declared")
    elif publisher is None:
        add("publisher", "mismatch", "publisher is not on the trusted-publisher allowlist")
    elif usable:
        add("publisher", "verified", "identity established by independent evidence")
    else:
        add("publisher", "unverified_assertion", "allowlisted name, but only claimed")

    # 4. Official origin.
    host = _host(claim.official_url)
    if not claim.official_url:
        add("origin", "missing", "no official URL")
    elif host is None:
        add("origin", "mismatch", "official URL is not an https:// URL")
    elif publisher is not None and host not in publisher.hosts:
        add("origin", "mismatch", f"host {host} is not an official host of the publisher")
    elif publisher is not None and usable:
        add("origin", "verified", "official host, and the bytes are independently bound to the publisher")
    else:
        add("origin", "unverified_assertion", "a URL is a claim; nothing independent ties these bytes to it")

    # 5. Document version: declared and consistent with the ingestion declaration.
    if not claim.document_version:
        add("document_version", "missing", "no document version")
    elif not _VERSION.match(claim.document_version):
        add("document_version", "mismatch", "document version is not a short printable token")
    elif expected_version is not None and claim.document_version != expected_version:
        add("document_version", "mismatch", "claimed version differs from the declared ingestion version")
    elif expected_version is None:
        add("document_version", "unverified_assertion", "no second declaration to compare with")
    else:
        add("document_version", "verified", "claimed version equals the declared ingestion version")

    # 6. License basis (RAG_V1_SOURCE_POLICY): known, with a reference where one is required.
    basis = claim.license_basis
    if basis is None or basis == "unknown":
        add("license", "missing", "license basis unknown")
    elif basis not in LICENSE_BASES:
        add("license", "mismatch", f"license basis {basis!r} is not a known value")
    elif basis in LICENSE_NEEDS_REFERENCE and not (claim.license_reference or "").strip():
        add("license", "missing", f"license basis {basis!r} needs a license reference")
    else:
        add("license", "verified", "license basis documented")

    outcomes = {c.outcome for c in checks}
    status = ("mismatch" if "mismatch" in outcomes else "incomplete" if "missing" in outcomes
              else "unverified" if "unverified_assertion" in outcomes else "verified")
    return ProvenanceReport(PROVENANCE_CHECKER_VERSION, actual, status, tuple(checks))

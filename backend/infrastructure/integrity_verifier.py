"""RAG V1.5 M7 E7 / E7.1: the independent integrity verifier (docs/rag/RAG_V15_M7_E7_INDEPENDENT_VERIFICATION.md,
docs/rag/RAG_V15_M7_E7_1_PORTABLE_ATTESTATION.md).

Runs OUTSIDE the report producer's trust domain, with two things the producer never has:

* its own DATABASE LOGIN, a member of the NOLOGIN group `knowledge_integrity_verifier`
  (KNOWLEDGE_VERIFIER_DB_URL). The producer's credential (service_role / SUPABASE_DB_URL) is never read here.
* its own Ed25519 PRIVATE KEY (KNOWLEDGE_VERIFIER_KEY_FILE, a PEM file of the verifier's account; never the
  repository, a log, CI output or a shared secret) and its key id (KNOWLEDGE_VERIFIER_KEY_ID).

It reads the version under review ONLY through `knowledge_verifier.verification_input` (that report's chunk text,
stored claims and the owner's pin), re-runs the pinned extractor, refuses to sign when its own extractor digest
is not the pinned one, signs a canonical statement and submits it through `knowledge_verifier.record_verification`.

    python -m infrastructure.integrity_verifier --report-id <uuid>   # local / CI only
    python -m infrastructure.integrity_verifier --audit              # offline signature audit
                                                                     # (KNOWLEDGE_AUDIT_DB_URL: owner / auditor)

It never approves, rejects or quarantines anything. An unavailable verifier blocks approval only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from knowledge.integrity import verifier
from knowledge.integrity.claims import CLAIM_EXTRACTOR_VERSION

RECORD = "select knowledge_verifier.record_verification(%s, %s)"
INPUT = "select knowledge_verifier.verification_input(%s)"


class PinMismatch(RuntimeError):
    """This process does not run the extractor the owner pinned: it must not sign anything."""


def extractor_sources() -> list[tuple[str, bytes]]:
    base = Path(verifier.__file__).resolve().parent.parent                    # the `knowledge` package
    return [(name, (base / name).read_bytes()) for name in verifier.EXTRACTOR_SOURCES]


def extractor_code_digest() -> str:
    """The manifest digest of the extractor THIS process runs: files, extractor version and runtime (E7.1)."""
    return verifier.manifest_digest(extractor_sources(), verifier.runtime_fingerprint(), CLAIM_EXTRACTOR_VERSION)


def load_key(path: str | None = None) -> Ed25519PrivateKey:
    path = path or os.environ.get("KNOWLEDGE_VERIFIER_KEY_FILE")
    if not path:
        raise RuntimeError("KNOWLEDGE_VERIFIER_KEY_FILE is not set: the verifier has no key of its own")
    with open(path, "rb") as fh:
        key = serialization.load_pem_private_key(fh.read(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise RuntimeError("the verifier key must be Ed25519")
    return key


def public_key_bytes(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def build_statement(read: Any, report_id: str, key_id: str) -> str:
    """Everything the statement says comes from `verification_input` (run as the verifier role)."""
    data = read.execute(INPUT, (report_id,)).fetchone()[0]
    if isinstance(data, str):
        data = json.loads(data)
    own = extractor_code_digest()
    pin = data["pin"]
    if pin.get("extractor_code_digest") != own or pin.get("extractor_version") != CLAIM_EXTRACTOR_VERSION:
        raise PinMismatch(f"this verifier runs extractor {CLAIM_EXTRACTOR_VERSION} / {own}, the owner pinned"
                          f" {pin.get('extractor_version')} / {pin.get('extractor_code_digest')}: not signing")
    report = data["report"]
    triples = [(c["chunk_id"], c["content"], c["content_sha256"]) for c in data["chunks"]]
    recomputed = verifier.reextract(data["document_ref"], triples)
    return verifier.statement(report=report, key_id=key_id, recomputed=recomputed, stored=data["claims"],
                              chunks_read=len(triples), registry_digest=report["registry_digest"],
                              extractor_code_digest=own, chunk_coverage=verifier.coverage(triples, recomputed))


def verify(read: Any, submit: Any, report_id: str, key: Ed25519PrivateKey, key_id: str) -> int:
    """Build, sign and submit one statement; returns the verification id (the database may refuse it)."""
    text = build_statement(read, report_id, key_id)
    return submit.execute(RECORD, (text, key.sign(text.encode("utf-8")))).fetchone()[0]


def audit(read: Any) -> list[tuple[int, str]]:
    """Offline signature audit: every stored statement re-verified against its registered public key (needed in
    `offline_signature_audit` mode, where the database could not check it). Returns (verification id, problem)."""
    rows = read.execute("select v.id, v.statement, v.signature, k.public_key, k.status from"
                        " public.knowledge_integrity_verifications v join public.knowledge_integrity_verifier_keys k"
                        " on k.key_id = v.key_id order by v.id").fetchall()
    problems = []
    for vid, text, sig, public, status in rows:
        try:
            Ed25519PublicKey.from_public_bytes(bytes(public)).verify(bytes(sig), text.encode("utf-8"))
        except InvalidSignature:
            problems.append((vid, "signature does not verify"))
            continue
        if status != "active":
            problems.append((vid, f"signed by a {status} key"))
    return problems


def main(argv: list[str] | None = None) -> int:
    import psycopg                                                    # the runner's only database dependency

    parser = argparse.ArgumentParser(prog="integrity_verifier")
    parser.add_argument("--report-id")
    parser.add_argument("--audit", action="store_true")
    args = parser.parse_args(argv)
    # the audit reads the evidence tables (an owner / auditor login); the verifier login cannot read them
    var = "KNOWLEDGE_AUDIT_DB_URL" if args.audit else "KNOWLEDGE_VERIFIER_DB_URL"
    url = os.environ.get(var)
    if not url:
        print(f"{var} is not set: this step needs a database login of its own", file=sys.stderr)
        return 2
    with psycopg.connect(url) as conn:
        if args.audit:
            problems = audit(conn)
            print(json.dumps({"problems": problems}))
            return 1 if problems else 0
        if not args.report_id:
            parser.error("--report-id is required")
        key_id = os.environ.get("KNOWLEDGE_VERIFIER_KEY_ID")
        if not key_id:
            print("KNOWLEDGE_VERIFIER_KEY_ID is not set", file=sys.stderr)
            return 2
        try:
            vid = verify(conn, conn, args.report_id, load_key(), key_id)
        except PinMismatch as exc:
            print(str(exc), file=sys.stderr)
            return 3
        conn.commit()
        print(json.dumps({"verification_id": vid}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

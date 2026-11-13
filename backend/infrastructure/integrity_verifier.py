"""RAG V1.5 M7 E7: the independent integrity verifier (docs/rag/RAG_V15_M7_E7_INDEPENDENT_VERIFICATION.md).

Runs OUTSIDE the report producer's trust domain: it holds an Ed25519 private key the producer never has
(loaded from KNOWLEDGE_VERIFIER_KEY_FILE, a PEM file owned by the verifier's own account; never from the
repository, a log or a shared secret). It re-reads the STORED chunk text, re-runs the pinned extractor,
compares with the stored claims, signs a canonical statement and submits it. The database verifies the
signature against the owner-registered public key and recomputes the stored digest itself.

    python -m infrastructure.integrity_verifier --report-id <uuid>     # local / CI only

It never approves, rejects or quarantines anything.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from knowledge.integrity import verifier

RECORD = "select private.knowledge_record_integrity_verification(%s, %s)"


def extractor_code_digest() -> str:
    """The digest of the extractor code THIS process runs (the owner pins the expected value)."""
    base = Path(verifier.__file__).resolve().parent.parent                    # the `knowledge` package
    return verifier.code_digest([(name, (base / name).read_bytes()) for name in verifier.EXTRACTOR_SOURCES])


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
    """Everything the statement says is read here, from the stored snapshot (`read`: a SELECT-only cursor
    or connection)."""
    cols = ("id", "document_pk", "report_sha256", "document_snapshot_sha256", "source_snapshot_sha256", "chunk_count",
            "extractor_version", "registry_digest")
    row = read.execute(f"select {', '.join(cols)} from public.knowledge_integrity_reports where id = %s",
                       (report_id,)).fetchone()
    if row is None:
        raise LookupError(report_id)
    report = dict(zip(cols, row))
    ref = read.execute("select source_id || '/' || document_id || '@' || document_version from public.knowledge_documents"
                       " where id = %s", (report["document_pk"],)).fetchone()[0]
    chunks = read.execute("select chunk_id, content, content_sha256 from public.knowledge_chunks where document_pk = %s"
                          " order by ordinal, chunk_id", (report["document_pk"],)).fetchall()
    stored_cols = ("claim_id", "chunk_id", "chunk_content_sha256", "span_start", "span_end", "kind", "status",
                   "parameter", "value_min", "value_max", "unit", "dimension", "date_iso", "stage", "scope_tags")
    stored = [dict(zip(stored_cols, r)) for r in read.execute(
        "select claim_id, chunk_id, chunk_content_sha256, span_start, span_end, kind, status, parameter, value_min,"
        " value_max, unit, dimension, to_char(date_iso, 'YYYY-MM-DD'), stage, scope_tags from public.knowledge_claims"
        " where document_pk = %s and extractor_version = %s", (report["document_pk"], report["extractor_version"])).fetchall()]
    triples = [(c, t, h) for c, t, h in chunks]
    recomputed = verifier.reextract(ref, triples)
    return verifier.statement(report=report, key_id=key_id, recomputed=recomputed, stored=stored,
                              chunks_read=len(chunks), registry_digest=report["registry_digest"],
                              extractor_code_digest=extractor_code_digest(),
                              chunk_coverage=verifier.coverage(triples, recomputed))


def verify(read: Any, submit: Any, report_id: str, key: Ed25519PrivateKey, key_id: str) -> int:
    """Build, sign and submit one statement; returns the verification id (the database may refuse it)."""
    text = build_statement(read, report_id, key_id)
    return submit.execute(RECORD, (text, key.sign(text.encode("utf-8")))).fetchone()[0]

"""RAG V1.5 M7 E7: the verifier's canonical claim-set digest (knowledge/integrity/verifier.py). Pure: no
database (the database half, private.knowledge_claim_set_digest, is exercised by every DB approval test:
a single byte of difference would refuse the verification). Synthetic values only."""

from __future__ import annotations

import hashlib

from knowledge.integrity import verifier as vf

BASE = {"claim_id": "cl-0000000000000001", "chunk_id": "c1", "chunk_content_sha256": "a" * 64, "span_start": 3,
        "span_end": 9, "kind": "quantity", "status": "extracted", "parameter": "p", "value_min": 5.0,
        "value_max": 5.0, "unit": "cm", "dimension": "length", "date_iso": None, "stage": None, "scope_tags": ["b", "a"]}


def test_numbers_are_written_like_postgres_trim_scale():
    assert [vf._num(v) for v in (5.0, 2.2, 1e-05, 1000.0, 0.0, None, -1.5)] == ["5", "2.2", "0.00001", "1000", "0", "",
                                                                             "-1.5"]


def test_the_digest_is_order_independent_and_sensitive_to_every_field():
    other = {**BASE, "claim_id": "cl-0000000000000002", "scope_tags": ["a", "b"]}
    d = vf.claim_set_digest([BASE, other])
    assert d == vf.claim_set_digest([other, BASE])
    for field, value in (("span_start", 4), ("value_max", 5.5), ("chunk_content_sha256", "b" * 64), ("unit", "mm"),
                         ("status", "ambiguous"), ("scope_tags", ["a"])):
        assert vf.claim_set_digest([{**BASE, field: value}, other]) != d, field
    assert vf.claim_set_digest([]) == hashlib.sha256(b"").hexdigest()


def test_compare_names_missing_extra_and_altered_claims():
    other = {**BASE, "claim_id": "cl-0000000000000002"}
    diff = vf.compare([BASE, other], [{**BASE, "value_min": 6.0}, {**BASE, "claim_id": "cl-0000000000000003"}])
    assert diff == {"missing": ["cl-0000000000000002"], "extra": ["cl-0000000000000003"], "altered": ["cl-0000000000000001"]}


def test_the_statement_is_canonical_json_and_says_mismatch_on_any_difference():
    report = {"id": "r", "report_sha256": "x", "document_pk": "d", "document_snapshot_sha256": "s",
              "source_snapshot_sha256": "t", "chunk_count": 1}
    kw = {"report": report, "key_id": "k", "registry_digest": "g", "extractor_code_digest": "c" * 64}
    ok = vf.statement(recomputed=[BASE], stored=[BASE], chunks_read=1, **kw)
    assert '"verdict":"reproduced"' in ok and ok == vf.statement(recomputed=[BASE], stored=[BASE], chunks_read=1, **kw)
    assert '"verdict":"mismatch"' in vf.statement(recomputed=[BASE], stored=[], chunks_read=1, **kw)
    assert '"verdict":"mismatch"' in vf.statement(recomputed=[BASE], stored=[BASE], chunks_read=0, **kw)
    crlf, lf = bytes([120, 13, 10, 121]), bytes([120, 10, 121])                # "x CR LF y" and "x LF y"
    assert vf.code_digest([("a.py", crlf)]) == vf.code_digest([("a.py", lf)])   # CRLF-independent


def test_coverage_names_unprocessed_and_hash_inconsistent_chunks_without_changing_the_verdict():
    from knowledge.ids import sha256_hex
    chunks = [("c1", "awd text", sha256_hex("awd text")), ("c2", "  ", sha256_hex("  ")), ("c3", "edited", "f" * 64)]
    cov = vf.coverage(chunks, [BASE])                                        # BASE is a claim of chunk c1
    assert cov == {"chunks_read": 3, "chunks_with_claims": 1, "chunks_without_claims": ["c2", "c3"],
                   "empty_chunks": ["c2"], "chunk_hash_mismatch": ["c3"]}
    report = {"id": "r", "report_sha256": "x", "document_pk": "d", "document_snapshot_sha256": "s",
              "source_snapshot_sha256": "t", "chunk_count": 3}
    text = vf.statement(report=report, key_id="k", recomputed=[BASE], stored=[BASE], chunks_read=3, registry_digest="g",
                        extractor_code_digest="c" * 64, chunk_coverage=cov)
    assert '"verdict":"reproduced"' in text and '"chunk_hash_mismatch":["c3"]' in text   # evidence, not a verdict

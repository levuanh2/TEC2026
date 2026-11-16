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


REPORT3 = {"id": "r", "report_sha256": "x", "document_pk": "d", "document_snapshot_sha256": "s",
           "source_snapshot_sha256": "t", "chunk_count": 3}


def _statement(cov, recomputed=(BASE,), stored=(BASE,), chunks_read=3):
    return vf.statement(report=REPORT3, key_id="k", recomputed=list(recomputed), stored=list(stored),
                        chunks_read=chunks_read, registry_digest="g", extractor_code_digest="c" * 64, chunk_coverage=cov)


def test_coverage_names_unprocessed_chunks_and_a_hash_mismatch_fails_the_verdict():
    """E7.1: a chunk whose text does not hash to its stored content_sha256 turns the verdict into mismatch
    (E7 only recorded it); chunks without claims are recorded and do not change the verdict."""
    from knowledge.ids import sha256_hex
    chunks = [("c1", "awd text", sha256_hex("awd text")), ("c2", "  ", sha256_hex("  ")), ("c3", "edited", "f" * 64)]
    cov = vf.coverage(chunks, [BASE])                                        # BASE is a claim of chunk c1
    assert cov == {"chunks_read": 3, "chunks_with_claims": 1, "chunks_without_claims": ["c2", "c3"],
                   "empty_chunks": ["c2"], "chunk_hash_mismatch": ["c3"]}
    assert '"verdict":"mismatch"' in _statement(cov) and '"chunk_hash_mismatch":["c3"]' in _statement(cov)
    clean = vf.coverage(chunks[:2], [BASE])
    assert clean["chunk_hash_mismatch"] == [] and '"verdict":"reproduced"' in _statement(clean, chunks_read=3)


def test_hashes_are_of_the_exact_utf8_bytes_without_unicode_normalization():
    import unicodedata

    from knowledge.ids import sha256_hex
    nfc = unicodedata.normalize("NFC", "tưới ngập khô xen kẽ")
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfc != nfd
    assert vf.coverage([("c1", nfd, sha256_hex(nfc))], [])["chunk_hash_mismatch"] == ["c1"]
    assert vf.coverage([("c1", nfc, sha256_hex(nfc))], [])["chunk_hash_mismatch"] == []
    lone_surrogate = "awd " + chr(0xD800)                                      # not encodable as UTF-8
    assert vf.coverage([("c1", lone_surrogate, "0" * 64)], [])["chunk_hash_mismatch"] == ["c1"]   # no crash
    assert vf.coverage([("c1", None, sha256_hex(""))], [])["chunk_hash_mismatch"] == ["c1"]       # not text


def test_chunk_order_does_not_change_the_claims_digest_or_the_statement():
    from knowledge.ids import sha256_hex
    texts = ["AWD giảm phát thải mê-tan 30%.", "Rơm rạ không được đốt ngoài đồng."]
    chunks = [(f"{n:020x}", t, sha256_hex(t)) for n, t in enumerate(texts)]
    a = vf.reextract("s/d@v1", chunks)
    b = vf.reextract("s/d@v1", list(reversed(chunks)))
    assert vf.claim_set_digest(a) == vf.claim_set_digest(b)
    report = {**REPORT3, "chunk_count": 2}
    kw = {"report": report, "key_id": "k", "chunks_read": 2, "registry_digest": "g", "extractor_code_digest": "c" * 64}
    assert vf.statement(recomputed=a, stored=b, chunk_coverage=vf.coverage(chunks, a), **kw) == \
        vf.statement(recomputed=b, stored=a, chunk_coverage=vf.coverage(list(reversed(chunks)), b), **kw)


# ================================================================== E7.1: the pinned extractor manifest

def _imports(path):
    import ast
    out = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            out.add(node.module)
            out |= {f"{node.module}.{a.name}" for a in node.names}          # `from pkg import submodule`
        elif isinstance(node, ast.ImportFrom):
            raise AssertionError("relative imports are not allowed in the pinned extractor")
        elif isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
    return out


def test_the_pinned_sources_are_exactly_the_project_import_closure_of_the_extractor_and_verifier():
    """A new project import, or a non-allowlisted outside import, in the code that produces the claim set fails
    here, so it cannot change extraction while keeping the pinned digest."""
    from pathlib import Path
    pkg = Path(vf.__file__).resolve().parent.parent                          # backend/knowledge
    todo, seen, outside = ["integrity/claims.py", "integrity/verifier.py"], set(), set()
    while todo:
        rel = todo.pop()
        if rel in seen:
            continue
        seen.add(rel)
        parts = rel.split("/")
        for init in ("__init__.py", *("/".join(parts[:i]) + "/__init__.py" for i in range(1, len(parts)))):
            if init not in seen:
                todo.append(init)
        for mod in _imports(pkg / rel):
            if mod == "knowledge" or mod.startswith("knowledge."):
                sub = mod.split(".")[1:]
                if sub and pkg.joinpath(*sub).with_suffix(".py").exists():
                    todo.append("/".join(sub) + ".py")
                elif pkg.joinpath(*sub, "__init__.py").exists():
                    todo.append("/".join([*sub, "__init__.py"]))
                # else: `from knowledge.x import name` where name is an attribute, not a module
            elif "." in mod and mod.rsplit(".", 1)[0] in vf.STDLIB_IMPORTS | {"collections"}:
                outside.add(mod.rsplit(".", 1)[0] if mod.rsplit(".", 1)[0] != "collections" else mod)
            else:
                outside.add(mod)
    assert seen == set(vf.EXTRACTOR_SOURCES)
    assert outside <= vf.STDLIB_IMPORTS, outside - vf.STDLIB_IMPORTS


def test_the_manifest_digest_moves_with_any_file_runtime_or_extractor_version_and_ignores_line_ends():
    files = [("integrity/claims.py", b"x = 1\n"), ("ids.py", b"y = 2\n")]
    rt = {"implementation": "CPython", "python": "3.11", "unicodedata": "14.0.0"}
    base = vf.manifest_digest(files, rt, "kn-claims-1")
    assert vf.manifest_digest(list(reversed(files)), rt, "kn-claims-1") == base          # order-independent
    crlf = [(n, d.replace(b"\n", bytes([13, 10]))) for n, d in files]
    assert vf.manifest_digest(crlf, rt, "kn-claims-1") == base                            # CRLF checkout
    assert vf.manifest_digest([files[0], ("ids.py", b"y = 3\n")], rt, "kn-claims-1") != base
    assert vf.manifest_digest(files, {**rt, "unicodedata": "15.0.0"}, "kn-claims-1") != base
    assert vf.manifest_digest(files, {**rt, "python": "3.12"}, "kn-claims-1") != base
    assert vf.manifest_digest(files, rt, "kn-claims-2") != base
    assert set(vf.runtime_fingerprint()) == {"implementation", "python", "unicodedata"}


def test_canonical_numbers_ignore_the_process_global_decimal_context():
    import decimal
    with decimal.localcontext() as ctx:
        ctx.prec = 2                                                       # another module lowering precision
        assert vf._num(1234.5678) == "1234.5678" and vf._num("0.000012345") == "0.000012345"

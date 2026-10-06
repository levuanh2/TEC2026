"""RAG V1.3-C ingestion pipeline, pure layer: parsers, normalizer, chunker, stable ids,
metadata validation. No database, no network. Fixtures are synthetic
(TEST FIXTURE — NOT A REAL APPROVED SOURCE); PDFs are generated at test time.
"""

from __future__ import annotations

import sys
import unicodedata
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from knowledge.chunking import CHUNKER_VERSION, MAX_TOKENS, TARGET_TOKENS, chunk  # noqa: E402
from knowledge.ids import artifact_key, chunk_id, safe_artifact_name, sha256_hex  # noqa: E402
from knowledge.ingest import plan  # noqa: E402
from knowledge.models import (Block, DocumentSpec, MetadataError, NormalizedDocument, ParseError,  # noqa: E402
                              SourceSpec, UnsupportedFormatError, validate_document, validate_source)
from knowledge.normalize import NORMALIZER_VERSION, normalize, normalize_block  # noqa: E402
from knowledge.parsers import detect  # noqa: E402
from knowledge.parsers import markdown, pdf, text  # noqa: E402
from tests.fixtures.knowledge import FIXTURE, make_pdf, read  # noqa: E402

SOURCE = SourceSpec("test-fixture-src", "TEST FIXTURE source", "Test publisher", "guideline", "official")


def doc(version="v1", **kw) -> DocumentSpec:
    return DocumentSpec("test-fixture-src", kw.pop("document_id", "awd-guide"), version, "TEST FIXTURE doc", "vi", **kw)


def plan_of(data: bytes, filename="awd_guide.md", version="v1", **kw):
    return plan(data=data, filename=filename, source=SOURCE, document=doc(version, **kw))


def _norm(blocks) -> NormalizedDocument:
    return NormalizedDocument(NORMALIZER_VERSION, tuple(blocks), "", sha256_hex(""))


# ------------------------------------------------------------------ formats

@pytest.mark.parametrize(("name", "data", "expected"), [
    ("a.md", b"# x", "markdown"), ("a.MD", b"x", "markdown"), ("a.txt", b"x", "text"), ("a.pdf", b"%PDF-1.4", "pdf"),
])
def test_supported_formats(name, data, expected):
    assert detect(name, data).name == expected


@pytest.mark.parametrize(("name", "data"), [
    ("a.docx", b"PK\x03\x04"), ("a.html", b"<html>"), ("a.xlsx", b"PK"), ("a.csv", b"a,b"), ("noext", b"x"),
    ("a.pdf", b"not a pdf"), ("a.txt", b"%PDF-1.7 renamed"), ("a.md", b"PK\x03\x04 renamed docx"),
    ("a.txt", b"\x89PNG\r\n"),
])
def test_unsupported_or_mislabelled_input_is_refused(name, data):
    with pytest.raises(UnsupportedFormatError):
        detect(name, data)


@pytest.mark.parametrize(("data", "code"), [(b"\xff\xfe bad", "encoding"), (b"a\x00b", "binary_content")])
def test_text_decoding_fails_explicitly(data, code):
    with pytest.raises(ParseError) as err:
        text.parse(data)
    assert err.value.code == code


# ------------------------------------------------------------------ markdown parser

def test_markdown_structure_is_preserved():
    parsed = markdown.parse(read("awd_guide.md"))
    kinds = [(b.kind, b.level) for b in parsed.blocks]
    assert parsed.warnings == ("front_matter_ignored",)
    assert kinds == [("heading", 1), ("paragraph", 0), ("heading", 2), ("paragraph", 0), ("list", 0), ("heading", 2),
                     ("table", 0), ("heading", 3), ("paragraph", 0), ("code", 0)]
    lists = [b for b in parsed.blocks if b.kind == "list"][0].text.split("\n")
    assert len(lists) == 3 and lists[1].endswith("Dòng tiếp nối vẫn thuộc mục danh sách này.")
    table = [b for b in parsed.blocks if b.kind == "table"][0].text
    assert "---" not in table and table.count("\n") == 2 and "table_uncertain" not in [b for b in parsed.blocks if b.kind == "table"][0].flags


def test_markdown_setext_thematic_quote_and_unclosed_fence():
    parsed = markdown.parse("Title\n=====\n\nSub\n---\n\n***\n\n> quoted line\n\n```\ncode".encode())
    assert [(b.kind, b.level, b.text) for b in parsed.blocks] == [
        ("heading", 1, "Title"), ("heading", 2, "Sub"), ("paragraph", 0, "quoted line"), ("code", 0, "code")]
    assert parsed.warnings == ("unclosed_code_fence",)


def test_markdown_empty_atx_heading_is_dropped():
    assert markdown.parse(b"#   \n\ntext").blocks == (Block(kind="paragraph", text="text"),)


# ------------------------------------------------------------------ text parser

def test_text_structure_detection():
    blocks = text.parse(read("straw_notes.txt")).blocks
    assert [(b.kind, b.level) for b in blocks] == [("heading", 1), ("paragraph", 0), ("heading", 2), ("paragraph", 0),
                                                   ("list", 0), ("table", 0), ("heading", 3), ("paragraph", 0)]
    table = [b for b in blocks if b.kind == "table"][0]
    assert table.flags == ("table_uncertain",)


def test_text_structure_is_identical_for_nfc_and_nfd_input():
    source = "\n".join(["Điều 2. Phạm vi áp dụng", "Nội dung.", "", "Chương II", "– mục danh sách", ""])
    nfc, nfd = text.parse(source.encode()), text.parse(unicodedata.normalize("NFD", source).encode())
    assert nfc.blocks == nfd.blocks and [b.kind for b in nfc.blocks] == ["heading", "paragraph", "heading", "list"]


@pytest.mark.parametrize(("line", "level"), [
    ("1.2 Thu gom rơm", 2), ("1.2.3 Mực nước", 3), ("Chương II", 1), ("Mục 1. Phạm vi", 2), ("Điều 5. Đối tượng", 3),
    ("QUẢN LÝ RƠM RẠ", 1), ("1. Bước một", 0), ("Một câu văn bình thường.", 0), ("1.2 kết thúc bằng dấu chấm.", 0),
    ("AWD", 0), ("1.2 10 kg", 0),
])
def test_heading_rules(line, level):
    assert text.heading_level(line) == level


# ------------------------------------------------------------------ PDF parser

PDF_PAGES = [["BÁO CÁO KIỂM THỬ", FIXTURE, "1.2 Mực nước", "Tưới ướt khô xen kẽ giúp giảm phát thải mê-",
              "tan trong ruộng lúa.", "Giai đoạn    Mực nước    Ghi chú", f"Trang {i}"] for i in range(1, 5)]


def test_pdf_text_layer_pages_headings_and_tables():
    parsed = pdf.parse(make_pdf(PDF_PAGES))
    assert parsed.page_count == 4 and parsed.parser_version.startswith("kn-pdf-1+pypdf-")
    assert {b.page for b in parsed.blocks} == {1, 2, 3, 4}
    assert parsed.blocks[0].kind == "heading" and parsed.blocks[0].flags == ("page_first",)
    assert any(b.kind == "heading" and b.text == "1.2 Mực nước" for b in parsed.blocks)
    tables = [b for b in parsed.blocks if b.kind == "table"]
    assert tables and all("table_uncertain" in b.flags for b in tables)


def test_pdf_without_text_layer_is_refused():
    with pytest.raises(ParseError) as err:
        pdf.parse(make_pdf([[], [], ["only one page has text " * 2]]))
    assert err.value.code == "no_text_layer"


def test_pdf_with_some_blank_pages_warns():
    parsed = pdf.parse(make_pdf([["Trang có nội dung kiểm thử đầy đủ."], [], ["Trang ba có nội dung kiểm thử."]]))
    assert parsed.warnings == ("page 2 has no extractable text",)


@pytest.mark.parametrize(("data", "code"), [
    (b"%PDF-1.4\n%garbage that is not a pdf", "malformed"), (b"plain", "malformed"),
])
def test_malformed_pdf_fails_explicitly(data, code):
    with pytest.raises(ParseError) as err:
        pdf.parse(data)
    assert err.value.code == code


def test_encrypted_pdf_is_refused():
    import io

    import pypdf

    writer = pypdf.PdfWriter(clone_from=pypdf.PdfReader(io.BytesIO(make_pdf([["Nội dung kiểm thử bí mật đủ dài."]]))))
    writer.encrypt("secret")
    buf = io.BytesIO()
    writer.write(buf)
    with pytest.raises(ParseError) as err:
        pdf.parse(buf.getvalue())
    assert err.value.code == "encrypted"


# ------------------------------------------------------------------ normalizer

def test_normalizer_unicode_whitespace_hyphen_rules():
    nfd = unicodedata.normalize("NFD", "tưới")
    block = Block(kind="paragraph", text=f"  {nfd} ướt​ khô­   mê-\ntan\tvà\nkhí\x07 ")
    assert normalize_block(block).text == "tưới ướt khô mê-tan và khí"
    assert normalize_block(Block(kind="paragraph", text="giá 10-\n20 kg")).text == "giá 10- 20 kg"   # digit: no join
    assert normalize_block(Block(kind="table", text="a    b  c\n\n d e ")).text == "a  b  c\nd e"
    assert normalize_block(Block(kind="list", text="- a   b\n- c")).text == "- a b\n- c"
    assert normalize_block(Block(kind="code", text="  x = 1   \n    y\n")).text == "  x = 1\n    y"
    assert normalize_block(Block(kind="heading", text="Tiêu\n đề", level=1)).text == "Tiêu đề"
    assert normalize_block(Block(kind="paragraph", text=" ​ ")) is None


def test_nfc_and_nfd_inputs_normalize_identically_keeping_diacritics():
    md = read("awd_guide.md").decode()
    a, b = plan_of(md.encode()), plan_of(unicodedata.normalize("NFD", md).encode())
    assert a.file_sha256 != b.file_sha256
    assert a.normalized_sha256 == b.normalized_sha256 and [c.chunk_id for c in a.chunks] == [c.chunk_id for c in b.chunks]
    assert "tưới ướt khô xen kẽ" in a.chunks[0].section_path.lower()


def test_repeated_pdf_headers_and_footers_are_removed_by_the_rule():
    n = normalize(pdf.parse(make_pdf(PDF_PAGES)))
    assert "BÁO CÁO KIỂM THỬ" not in n.text and "Trang" not in n.text
    assert n.warnings == ("removed 8 repeated page header/footer line(s)",)
    assert "mê-tan trong ruộng lúa" in n.text


def test_page_edges_repeated_on_too_few_pages_are_kept():
    pages = [["TIÊU ĐỀ RIÊNG", "Nội dung trang một kiểm thử.", "Thêm dòng", "Chân trang"],
             ["TIÊU ĐỀ RIÊNG", "Nội dung trang hai kiểm thử.", "Thêm dòng", "Chân trang"]]
    n = normalize(pdf.parse(make_pdf(pages)))
    assert n.text.count("Chân trang") == 2 and not n.warnings      # 2 pages < EDGE_MIN_PAGES


def test_normalization_and_hash_are_deterministic():
    data = read("awd_guide.md")
    first = normalize(markdown.parse(data))
    assert all(normalize(markdown.parse(data)) == first for _ in range(3))
    assert first.sha256 == sha256_hex(first.text) and first.normalizer_version == NORMALIZER_VERSION


# ------------------------------------------------------------------ chunker

def _para(n: int, prefix="từ") -> Block:
    sentences = [" ".join(f"{prefix}{i}_{j}" for j in range(20)) + "." for i in range(n // 20)]
    return Block(kind="paragraph", text=" ".join(sentences))


def test_sections_paragraphs_and_packing():
    blocks = [Block("heading", "A", 1), Block("paragraph", "một hai ba"), Block("paragraph", "bốn năm"),
              Block("heading", "B", 2), Block("list", "- x\n- y"), Block("heading", "C", 1), Block("paragraph", "z")]
    chunks = chunk(_norm(blocks), source_id="s1", document_id="d1", document_version="v1")
    assert [(c.section_path, c.content) for c in chunks] == [
        ("A", "một hai ba\n\nbốn năm"), ("A > B", "- x\n- y"), ("C", "z")]
    assert [c.ordinal for c in chunks] == [0, 1, 2] and all(c.ordinal_in_section == 0 for c in chunks)


def test_target_is_respected_between_blocks():
    blocks = [Block("heading", "S", 1)] + [_para(200, f"p{k}") for k in range(3)]
    chunks = chunk(_norm(blocks), source_id="s1", document_id="d1", document_version="v1")
    assert [c.tokens for c in chunks] == [200, 200, 200]
    assert [c.ordinal_in_section for c in chunks] == [0, 1, 2] and all(c.tokens <= TARGET_TOKENS for c in chunks)


def test_long_paragraph_is_split_at_sentences_with_one_sentence_overlap():
    chunks = chunk(_norm([_para(1000)]), source_id="s1", document_id="d1", document_version="v1")
    assert len(chunks) == 3 and all(c.tokens <= MAX_TOKENS for c in chunks)
    assert chunks[0].metadata == {"block_kinds": ["paragraph"], "split": "sentence"}
    assert chunks[1].metadata["overlap_sentence"] is True
    last_sentence = chunks[0].content.rsplit(". ", 1)[-1]
    assert chunks[1].content.startswith(last_sentence.rstrip("."))
    assert chunks[0].section_path is None and len({c.chunk_id for c in chunks}) == 3


def test_long_table_splits_at_lines_without_overlap_and_huge_line_is_windowed():
    table = Block("table", "\n".join(" ".join(f"c{i}_{j}" for j in range(40)) for i in range(20)), flags=("table_uncertain",))
    chunks = chunk(_norm([table]), source_id="s1", document_id="d1", document_version="v1")
    assert [c.tokens for c in chunks] == [440, 360]
    assert chunks[0].metadata == {"block_kinds": ["table"], "table": True, "table_uncertain": True, "split": "line"}
    huge = Block("paragraph", " ".join(f"w{i}" for i in range(1000)))
    assert [c.tokens for c in chunk(_norm([huge]), source_id="s", document_id="d1", document_version="v")] == [450, 450, 100]


def test_chunk_pages_come_from_their_blocks():
    blocks = [Block("paragraph", "a", page=2), Block("paragraph", "b", page=3)]
    (c,) = chunk(_norm(blocks), source_id="s1", document_id="d1", document_version="v1")
    assert (c.page_from, c.page_to) == (2, 3)


# ------------------------------------------------------------------ stable ids

def test_chunk_id_formula_is_the_adr_contract():
    expected = sha256_hex("s|d|v|A > B|2|" + "f" * 64)[:20]
    assert chunk_id(source_id="s", document_id="d", document_version="v", section_path="A > B",
                    ordinal_in_section=2, content_sha256="f" * 64) == expected


def test_rerun_gives_identical_ids_and_new_version_gives_new_ids():
    data = read("awd_guide.md")
    v1, again, v2 = plan_of(data), plan_of(data), plan_of(data, version="v2")
    assert [c.chunk_id for c in v1.chunks] == [c.chunk_id for c in again.chunks]
    assert not {c.chunk_id for c in v1.chunks} & {c.chunk_id for c in v2.chunks}
    other_doc = plan_of(data, document_id="awd-guide-copy")
    assert not {c.chunk_id for c in v1.chunks} & {c.chunk_id for c in other_doc.chunks}
    assert v1.parser_version == markdown.PARSER_VERSION and v1.chunker_version == CHUNKER_VERSION


@pytest.mark.parametrize(("filename", "ext", "expected"), [
    ("../../etc/passwd.md", ".md", "passwd.md"), ("..\\..\\boot.ini.txt", ".txt", "boot.ini.txt"),
    ("Hướng dẫn tưới.PDF", ".pdf", "Huong-dan-tuoi.pdf"), (".hidden.md", ".md", "hidden.md"),
    ("....md", ".md", "artifact.md"), ("a" * 300 + ".md", ".md", "a" * 97 + ".md"), ("x.md.exe", ".md", "x.md.md"),
])
def test_safe_artifact_names(filename, ext, expected):
    assert safe_artifact_name(filename, ext) == expected


def test_artifact_key_is_content_addressed_and_refuses_unsafe_parts():
    sha = sha256_hex(b"x")
    assert artifact_key(sha, "a.md") == f"{sha}/a.md"
    for bad_sha, name in ((sha.upper(), "a.md"), ("abc", "a.md"), (sha, "../a.md"), (sha, "a/b.md"), (sha, "a..b.md"),
                          (sha, ".a.md"), (sha, "noext")):
        with pytest.raises(ValueError):
            artifact_key(bad_sha, name)


# ------------------------------------------------------------------ metadata validation

@pytest.mark.parametrize("change", [
    {"source_id": "Bad_ID"}, {"title": " "}, {"owner": ""}, {"source_type": "blog"}, {"authority": "random"},
    {"visibility": "secret"}, {"visibility": "tenant"}, {"organization_id": "00000000-0000-0000-0000-000000000001"},
    {"visibility": "tenant", "organization_id": "not-a-uuid"},
])
def test_invalid_source_metadata(change):
    spec = SourceSpec(**{**SOURCE.__dict__, **change})
    with pytest.raises(MetadataError):
        validate_source(spec)


def test_valid_tenant_source():
    validate_source(SourceSpec(**{**SOURCE.__dict__, "visibility": "tenant", "source_type": "tenant_document",
                                  "organization_id": "00000000-0000-0000-0000-000000000001"}))


@pytest.mark.parametrize("change", [
    {"document_id": "Doc"}, {"document_version": "v 1"}, {"document_version": "../v1"}, {"title": ""},
    {"language": "vie"}, {"official_url": "http://example.invalid/x"}, {"official_url": "https://a b"},
    {"license_basis": "proprietary"},
])
def test_invalid_document_metadata(change):
    with pytest.raises(MetadataError):
        validate_document(DocumentSpec(**{**doc().__dict__, **change}))


def test_license_gaps_warn_without_blocking():
    assert validate_document(doc()) == ["license_basis is 'unknown': this version cannot be approved until it is known"]
    assert validate_document(doc(license_basis="open_license")) == [
        "license_basis 'open_license' needs a license_reference before approval"]
    assert validate_document(doc(license_basis="official_publication", official_url="https://example.invalid/a")) == []


def test_plan_refuses_empty_oversized_mismatched_and_contentless_input(monkeypatch):
    with pytest.raises(ParseError):
        plan_of(b"")
    with pytest.raises(ParseError) as err:
        plan_of(b"#  \n\n# \n", filename="x.md")
    assert err.value.code == "no_content"
    with pytest.raises(MetadataError):
        plan(data=b"x", filename="x.md", source=SOURCE, document=DocumentSpec("other-src", "awd-guide", "v1", "t", "vi"))
    import knowledge.ingest as ingest_mod
    monkeypatch.setattr(ingest_mod, "MAX_FILE_BYTES", 3)
    with pytest.raises(ParseError) as err:
        plan_of(b"abcd", filename="x.txt")
    assert err.value.code == "too_large"


def test_a_huge_run_without_spaces_is_refused_not_stored():
    with pytest.raises(ParseError) as err:
        plan_of(("Tiêu đề" + "\n\n" + "A" * 2_000_000).encode(), filename="x.txt")
    assert err.value.code == "unsplittable_text"


def test_indexed_size_counts_the_heading_path_with_exact_boundaries():
    def md(heading_len, body_len):
        return ("# " + "H" * heading_len + "\n\n" + "a" * body_len).encode()

    plan_of(md(1000, 1), filename="x.md")
    with pytest.raises(ParseError) as err:
        plan_of(md(1001, 1), filename="x.md")
    assert err.value.code == "heading_too_long"
    plan_of(md(1000, 19_000), filename="x.md")                 # 1000 + 19000 = 20000 indexed characters
    with pytest.raises(ParseError) as err:
        plan_of(md(1000, 19_001), filename="x.md")
    assert err.value.code == "unsplittable_text"
    plan_of(("a" * 20_000).encode(), filename="x.txt")
    with pytest.raises(ParseError):
        plan_of(("a" * 20_001).encode(), filename="x.txt")


@pytest.mark.parametrize("fmt", ["md", "txt", "pdf"])
def test_fragmented_input_stops_at_the_block_limit(monkeypatch, fmt):
    import knowledge.models as models

    monkeypatch.setattr(models, "MAX_BLOCKS", 5)
    if fmt == "pdf":
        data = make_pdf([[f"1.{i} Mục {i}", f"Nội dung kiểm thử số {i} đủ dài.", "Dòng ba", "Dòng bốn"]
                         for i in range(1, 5)])
    else:
        data = "\n\n".join(f"# Mục {i}" if fmt == "md" else f"Đoạn {i}." for i in range(20)).encode()
    with pytest.raises(ParseError) as err:
        plan_of(data, filename=f"x.{fmt}")
    assert err.value.code == "too_many_blocks"


def test_chunk_count_is_bounded(monkeypatch):
    import knowledge.ingest as ingest_mod

    monkeypatch.setattr(ingest_mod, "MAX_CHUNKS", 2)
    with pytest.raises(ParseError) as err:
        plan_of(read("awd_guide.md"))
    assert err.value.code == "too_many_chunks"


def test_plan_reports_everything_a_write_would_persist():
    p = plan_of(read("awd_guide.md"), filename="dir/AWD guide.md")
    assert p.format == "markdown" and p.content_type == "text/markdown" and p.artifact_name == "AWD-guide.md"
    assert p.file_sha256 == sha256_hex(read("awd_guide.md")) and len(p.chunks) == 4
    assert p.warnings == ("license_basis is 'unknown': this version cannot be approved until it is known",
                          "front_matter_ignored")
    assert FIXTURE in p.chunks[0].content

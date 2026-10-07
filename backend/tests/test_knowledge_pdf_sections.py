"""RAG V1.3-C: top-level numbered section headings in born-digital PDFs (kn-pdf-2).

Single-level `2. Title` lines are list items for the line classifier (a line alone cannot tell a
section heading from a numbered list). The PDF parser promotes one only with document context:
the 1, 2, 3 sequence across pages, no list numbering continuing through it, not a wrapped
sentence. Fixtures are synthetic (TEST FIXTURE — NOT A REAL APPROVED SOURCE); PDFs are generated
at test time.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from knowledge.chunking import chunk  # noqa: E402
from knowledge.models import Block  # noqa: E402
from knowledge.normalize import normalize  # noqa: E402
from knowledge.parsers import pdf, text  # noqa: E402
from tests.fixtures.knowledge import FIXTURE, make_pdf  # noqa: E402

# Shape of a Vietnamese technical procedure: ALL-CAPS chapter headings, top-level `1.`/`2.`/`3.`
# sections, `1.1`-`1.6` subsections, plus numbered PROSE and a numbered LIST that must stay lists.
PROCEDURE = [
    ["QUY TRÌNH KIỂM THỬ", FIXTURE, "I. GIỚI THIỆU CHUNG",
     "1. Quy trình gồm ba nhóm nội dung chính:",
     "2. Đối tượng áp dụng: các hộ sản xuất tham gia thí điểm.",
     "II. NỘI DUNG QUY TRÌNH", "1. Kỹ thuật canh tác", "Kỹ thuật canh tác gồm các bước chính.",
     "1.1. Làm đất", "Cày và phơi ải sau thu hoạch vụ Đông Xuân.", "Trang 1"],
    ["1.6. Phòng chống sinh vật gây hại", "Thăm đồng thường xuyên và áp dụng IPM.", "Các bước xử lý ruộng:",
     "1. Rút nước khỏi ruộng", "2. Chờ ba ngày", "3. Bơm nước trở lại",
     "2. Quản lý thu hoạch và bảo quản", "Thu hoạch khi lúa chín khoảng 85 - 90%.", "Trang 2"],
    ["3. Quản lý rơm rạ", "a) Rơm", "- Không đốt rơm trên ruộng.",
     "III. PHỤ LỤC KIỂM THỬ", "1. Phạm vi áp dụng gồm vùng chuyên canh lúa chất lượng cao",
     "thuộc đề án thí điểm.", "Trang 3"],
]


def _chunks(pages):
    return chunk(normalize(pdf.parse(make_pdf(pages))), source_id="test-fixture-src",
                 document_id="procedure", document_version="v1")


def _path_of(chunks, needle: str) -> str | None:
    """section_path of the one chunk whose content contains `needle`."""
    found = [c.section_path for c in chunks if needle in c.content]
    assert len(found) == 1, (needle, found)
    return found[0]


def test_top_level_numbered_sections_end_the_previous_subsection():
    chunks = _chunks(PROCEDURE)
    assert _path_of(chunks, "Thu hoạch khi lúa chín") == "II. NỘI DUNG QUY TRÌNH > 2. Quản lý thu hoạch và bảo quản"
    assert _path_of(chunks, "Không đốt rơm") == "II. NỘI DUNG QUY TRÌNH > 3. Quản lý rơm rạ"
    assert _path_of(chunks, "IPM") == ("II. NỘI DUNG QUY TRÌNH > 1. Kỹ thuật canh tác"
                                        " > 1.6. Phòng chống sinh vật gây hại")
    assert _path_of(chunks, "phơi ải") == "II. NỘI DUNG QUY TRÌNH > 1. Kỹ thuật canh tác > 1.1. Làm đất"


def test_numbered_prose_lists_and_wrapped_items_stay_lists():
    chunks = _chunks(PROCEDURE)
    assert _path_of(chunks, "Đối tượng áp dụng") == "I. GIỚI THIỆU CHUNG"            # `1.`/`2.` prose with `:`
    assert _path_of(chunks, "Chờ ba ngày").endswith("1.6. Phòng chống sinh vật gây hại")   # a 1-2-3 list
    assert _path_of(chunks, "thuộc đề án thí điểm") == "III. PHỤ LỤC KIỂM THỬ"            # wrapped `1.` item


# ------------------------------------------------- the promotion rule on parsed blocks


def H(text_, level, page=1, flags=()):
    return Block(kind="heading", text=text_, level=level, page=page, flags=flags)


def P(text_, page=1, flags=()):
    return Block(kind="paragraph", text=text_, page=page, flags=flags)


def L(*lines, page=1):
    return Block(kind="list", text="\n".join(lines), page=page)


def headings(blocks):
    return [(b.text, b.level) for b in pdf._top_level_sections(blocks) if b.kind == "heading"]


@pytest.mark.parametrize("line", [
    "1. Kỹ thuật canh tác", "2. Quản lý thu hoạch, sấy và bảo quản", "3. Quản lý rơm rạ", "12. Tổng hợp kết quả",
])
def test_the_heading_shape_accepts_top_level_numbered_titles(line):          # A, B, H
    assert pdf._section_number(line) == int(line.split(".")[0])


@pytest.mark.parametrize("line", [
    "2.5 kg/ha cho ô thí nghiệm",            # E decimal
    "2.10.2025 Bắt đầu vụ Đông Xuân",        # F date / version-like
    "2.", "2. Rơm",                           # G bare number, one-word title
    "1.6. Phòng chống sinh vật gây hại",      # C nested numbering stays the line classifier's job
    "2. Đối tượng áp dụng: các hộ sản xuất",  # a `label: content` item
    "2. Quản lý thu hoạch; bảo quản",
    "2. Bón phân theo khuyến cáo.",           # a sentence
    "2. quản lý thu hoạch",                   # lower-case title
    "0. Mở đầu tài liệu kiểm thử",
    "100. Quản lý thu hoạch",
    "2) Quản lý thu hoạch",
    "2. " + "Quản lý thu hoạch " * 6,        # over 100 characters
])
def test_the_heading_shape_rejects_everything_else(line):                    # E, F, G
    assert pdf._section_number(line.strip()) is None


def test_a_numbered_list_is_not_promoted_even_when_the_sequence_matches():   # D
    blocks = [H("II. NỘI DUNG", 1), L("1. Kỹ thuật canh tác"), P("Nội dung phần một."),
              L("1. Thêm nước vào ruộng", "2. Chờ ba ngày", "3. Bơm nước trở lại"), P("Kết thúc.")]
    assert headings(blocks) == [("II. NỘI DUNG", 1), ("1. Kỹ thuật canh tác", 2)]


def test_a_short_list_without_a_section_sequence_stays_a_list():             # D
    blocks = [P("Các bước:"), L("1. Thêm nước vào ruộng", "2. Chờ ba ngày"), P("Sau đó tiếp tục.")]
    assert headings(blocks) == []


def test_a_wrapped_item_breaks_the_sequence_for_the_items_after_it():        # D
    blocks = [L("1. Thêm nước vào ruộng cho"), P("ngập năm phân."), L("2. Chờ ba ngày"), P("Sau đó tiếp tục.")]
    assert headings(blocks) == []


def test_a_heading_right_after_a_numbered_list_is_still_a_heading():
    blocks = [H("II. NỘI DUNG", 1), L("1. Kỹ thuật canh tác"), H("1.6. Sâu bệnh", 2),
              L("1. Rút nước khỏi ruộng", "2. Chờ ba ngày", "3. Bơm nước trở lại", "2. Quản lý thu hoạch")]
    assert headings(blocks) == [("II. NỘI DUNG", 1), ("1. Kỹ thuật canh tác", 2), ("1.6. Sâu bệnh", 3),
                                ("2. Quản lý thu hoạch", 2)]


def test_sections_nest_under_an_open_level_one_heading_and_subsections_follow():   # C
    blocks = [H("II. NỘI DUNG", 1), L("1. Kỹ thuật canh tác"), H("1.1. Làm đất", 2), P("Cày ải."),
              H("1.6. Sâu bệnh", 2), P("IPM."), L("2. Quản lý thu hoạch"), P("Thu hoạch."),
              H("III. PHỤ LỤC", 1), H("1.1. Ghi chú", 2)]
    assert headings(blocks) == [("II. NỘI DUNG", 1), ("1. Kỹ thuật canh tác", 2), ("1.1. Làm đất", 3),
                                ("1.6. Sâu bệnh", 3), ("2. Quản lý thu hoạch", 2), ("III. PHỤ LỤC", 1),
                                ("1.1. Ghi chú", 2)]        # a new level-1 heading closes the section


def test_a_subsection_of_another_number_does_not_nest_in_the_open_section():
    nested = [H("MỤC LỤC", 1), L("1. Quản lý dịch hại"), H("1.1. Nguyên tắc", 2), P("A."),
              H("3.1. Phủ cho cây trồng", 2), P("B."), H("3.1.1. Rơm khô", 3), P("C.")]
    assert headings(nested) == [("MỤC LỤC", 1), ("1. Quản lý dịch hại", 2), ("1.1. Nguyên tắc", 3),
                                ("3.1. Phủ cho cây trồng", 2), ("3.1.1. Rơm khô", 3)]
    flat = [L("1. Quản lý dịch hại"), H("1.1. Nguyên tắc", 2), P("A."), H("3.1. Phủ cho cây trồng", 2), P("B."),
            H("3.1.1. Rơm khô", 3), P("C.")]
    assert headings(flat) == [("1. Quản lý dịch hại", 1), ("1.1. Nguyên tắc", 2), ("3.1. Phủ cho cây trồng", 1),
                              ("3.1.1. Rơm khô", 2)]


def test_without_a_level_one_heading_sections_are_level_one_and_subsections_unchanged():
    blocks = [L("1. Kỹ thuật canh tác"), H("1.1. Làm đất", 2), P("Cày ải."), L("2. Quản lý thu hoạch"), P("Thu.")]
    assert headings(blocks) == [("1. Kỹ thuật canh tác", 1), ("1.1. Làm đất", 2), ("2. Quản lý thu hoạch", 1)]


def test_a_new_level_one_heading_starts_a_new_sequence():
    blocks = [H("I. MỘT", 1), L("1. Phần thứ nhất"), P("A."), L("2. Phần thứ hai"), P("B."),
              H("II. HAI", 1), L("2. Không phải mở đầu"), P("C."), L("1. Phần mở đầu mới"), P("D.")]
    assert [t for t, _ in headings(blocks)] == ["I. MỘT", "1. Phần thứ nhất", "2. Phần thứ hai", "II. HAI",
                                                "1. Phần mở đầu mới"]


def test_running_edge_headers_neither_reset_nor_open_a_sequence():
    header = "TÀI LIỆU KIỂM THỬ"
    blocks = [H(header, 1, page=1, flags=("page_first",)), L("1. Phần thứ nhất", page=1), P("A.", page=1),
              H(header, 1, page=2, flags=("page_first",)), L("2. Phần thứ hai", page=2), P("B.", page=2),
              H(header, 1, page=3, flags=("page_first",)), L("3. Phần thứ ba", page=3), P("C.", page=3)]
    assert [(t, lvl) for t, lvl in headings(blocks) if t != header] == [
        ("1. Phần thứ nhất", 1), ("2. Phần thứ hai", 1), ("3. Phần thứ ba", 1)]


def test_a_page_edge_section_line_keeps_its_edge_flag_for_header_detection():
    blocks = [L("1. Phần thứ nhất"), P("A."), P("2. Phần thứ hai", page=2, flags=("page_first",)), P("B.", page=2)]
    promoted = [b for b in pdf._top_level_sections(blocks) if b.kind == "heading"]
    assert [(b.text, b.flags) for b in promoted] == [("1. Phần thứ nhất", ()), ("2. Phần thứ hai", ("page_first",))]


def test_lines_around_a_promoted_heading_keep_their_block_kind():
    out = pdf._top_level_sections([H("II. NỘI DUNG", 1), L("1. Kỹ thuật canh tác"), P("X."),
                                   L("- mục một", "2. Quản lý rơm rạ", "a) Rơm", "- không đốt rơm")])
    assert [(b.kind, b.text) for b in out[-3:]] == [("list", "- mục một"), ("heading", "2. Quản lý rơm rạ"),
                                                    ("list", "a) Rơm\n- không đốt rơm")]


def test_promotion_is_deterministic_and_keeps_vietnamese_text():             # H, I
    data = make_pdf(PROCEDURE)
    first, second = pdf.parse(data), pdf.parse(data)
    assert first == second
    assert any(b.kind == "heading" and b.text == "3. Quản lý rơm rạ" for b in first.blocks)
    a, b = _chunks(PROCEDURE), _chunks(PROCEDURE)
    assert [(c.chunk_id, c.section_path) for c in a] == [(c.chunk_id, c.section_path) for c in b]


def test_the_text_parser_still_treats_single_level_numbers_as_list_items():
    parsed = text.parse("II. NỘI DUNG\n1. Kỹ thuật canh tác\nNội dung.\n2. Quản lý thu hoạch\n".encode())
    assert [b.kind for b in parsed.blocks] == ["heading", "list", "paragraph", "list"]
    assert parsed.parser_version == "kn-text-1"

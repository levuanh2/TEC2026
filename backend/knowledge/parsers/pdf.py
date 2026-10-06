"""PDF parser: the existing text layer only (pypdf, already pinned). Never OCR.

- Encrypted, malformed or oversized PDFs fail explicitly (`encrypted`, `malformed`, `too_large`).
- A page "has text" with >= MIN_PAGE_CHARS non-space characters. Fewer than half the pages with
  text -- or none -- is `no_text_layer` (a scan/image-only PDF): the artifact is refused rather
  than indexed. Individual empty pages are reported as warnings.
- Each page's text goes through the shared line classifier (knowledge.parsers.text). The first and
  last line of a page become their own blocks flagged `page_first` / `page_last`, so the
  normalizer can drop repeated headers/footers by its documented rule; they are never merged.
- pypdf cannot reliably reconstruct tables: table-like lines stay verbatim with `table_uncertain`.
The pypdf version is part of PARSER_VERSION because extraction output may change between releases.
"""

from __future__ import annotations

import io
import unicodedata

import pypdf
from pypdf.errors import PyPdfError

from knowledge.models import Block, ParsedDocument, ParseError, check_block_count
from knowledge.parsers.text import heading_level, segment_lines

PARSER_VERSION = f"kn-pdf-1+pypdf-{pypdf.__version__}"
MIN_PAGE_CHARS = 20
MAX_PAGES = 2000
MAX_TEXT_CHARS = 20_000_000
_EDGE_MAX_CHARS = 100


def _edge(line: str, page: int, flag: str) -> Block:
    level = heading_level(line)
    return Block(kind="heading" if level else "paragraph", text=line, level=level, page=page, flags=(flag,))


def _page_blocks(text: str, page: int) -> list[Block]:
    lines = [line for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    content = [i for i, line in enumerate(lines) if line.strip()]
    if len(content) < 3:
        return segment_lines(lines, page)
    first, last = content[0], content[-1]
    blocks: list[Block] = []
    if len(lines[first].strip()) <= _EDGE_MAX_CHARS:
        blocks.append(_edge(lines[first].strip(), page, "page_first"))
        start = first + 1
    else:
        start = first
    end_block = None
    if len(lines[last].strip()) <= _EDGE_MAX_CHARS:
        end_block = _edge(lines[last].strip(), page, "page_last")
        stop = last
    else:
        stop = last + 1
    blocks.extend(segment_lines(lines[start:stop], page))
    if end_block:
        blocks.append(end_block)
    return blocks


def parse(data: bytes) -> ParsedDocument:
    if not data.startswith(b"%PDF-"):
        raise ParseError("not a PDF file (missing %PDF- header)", code="malformed")
    try:
        reader = pypdf.PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise ParseError("encrypted PDFs are not supported", code="encrypted")
        page_count = len(reader.pages)
        if page_count == 0:
            raise ParseError("the PDF has no pages", code="no_text_layer")
        if page_count > MAX_PAGES:
            raise ParseError(f"the PDF has {page_count} pages (limit {MAX_PAGES})", code="too_large")
        texts, total = [], 0
        for page in reader.pages:
            text = unicodedata.normalize("NFC", page.extract_text() or "")   # before structure rules
            total += len(text)
            if total > MAX_TEXT_CHARS:
                raise ParseError(f"extracted text exceeds {MAX_TEXT_CHARS} characters", code="too_large")
            texts.append(text)
    except ParseError:
        raise
    except (PyPdfError, ValueError, KeyError, TypeError, AttributeError, IndexError, RecursionError,
            OSError, ZeroDivisionError) as exc:
        raise ParseError(f"the PDF could not be read ({type(exc).__name__})", code="malformed") from exc

    with_text = [i for i, t in enumerate(texts, start=1) if sum(not c.isspace() for c in t) >= MIN_PAGE_CHARS]
    if len(with_text) * 2 < page_count or not with_text:
        raise ParseError(f"no usable text layer: {len(with_text)} of {page_count} pages have text "
                         f"(scanned/image-only PDFs need OCR, which is unsupported)", code="no_text_layer")
    warnings = [f"page {i} has no extractable text" for i in range(1, page_count + 1) if i not in with_text]
    blocks: list[Block] = []
    for number, text in enumerate(texts, start=1):
        if number in with_text:
            blocks.extend(_page_blocks(text, number))
            check_block_count(len(blocks))
    return ParsedDocument(format="pdf", parser_version=PARSER_VERSION, blocks=tuple(blocks),
                          page_count=page_count, warnings=tuple(warnings))

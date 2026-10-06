"""Content normalization (ADR §4.2), deterministic and versioned as NORMALIZER_VERSION.

This is what users will see as chunk `content`; SEARCH normalization (unaccent/lower) is the
database's job (private.knowledge_search_text) and is never re-implemented here.

Rules, in order, per block:
1. Unicode NFC. Diacritics are kept (Vietnamese `tưới` stays `tưới`; NFD input becomes NFC).
2. Remove zero-width space, word joiner, BOM and soft hyphen; map NBSP and the other Unicode
   space characters to a plain space; drop other control characters; tab -> space.
3. Paragraph line-break repair: a line break inside a paragraph becomes one space. A line that
   ends with `-` right after a letter is joined to the next line WITHOUT a space and the hyphen
   is KEPT (`mê-\\ntan` -> `mê-tan`); no word is ever reconstructed or rewritten.
4. Whitespace: runs of spaces collapse to one, lines are stripped. Lists keep one line per item;
   tables keep their lines and mark column gaps (2+ spaces) as exactly two spaces; code keeps
   its lines and indentation (trailing spaces stripped).
5. PDF only -- repeated page headers/footers: a block flagged `page_first`/`page_last` is removed
   when the same text (digits ignored, case-insensitive) sits on that page edge on at least
   max(3, ceil(50% of the PDF's pages)) pages. Page-number lines (`12`, `Trang 3`, `Page 3 of 9`)
   fall under the same rule. Nothing else is ever dropped.
Empty blocks are dropped. The normalized text is the blocks joined by blank lines (headings as
`#`-prefixed lines) and `sha256` is its UTF-8 digest: same bytes + same parser/normalizer
version => same text and digest.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter

from knowledge.ids import sha256_hex
from knowledge.models import Block, NormalizedDocument, ParsedDocument

NORMALIZER_VERSION = "kn-normalize-1"
EDGE_MIN_PAGES = 3
EDGE_MIN_SHARE = 0.5

_REMOVE = dict.fromkeys(map(ord, "​⁠﻿­"))
_SPACES = re.compile(r"[   -   　\t]")
_RUN = re.compile(r" {2,}")
_HYPHEN_END = re.compile(r"(?<=[^\W\d_])-$")


def _clean(text: str) -> str:
    text = unicodedata.normalize("NFC", text).translate(_REMOVE)
    text = _SPACES.sub(" ", text)
    return "".join(c for c in text if c == "\n" or unicodedata.category(c) != "Cc")


def _paragraph(text: str) -> str:
    out = ""
    for line in (part.strip() for part in text.split("\n")):
        if not line:
            continue
        if not out:
            out = line
        elif _HYPHEN_END.search(out):
            out += line
        else:
            out += " " + line
    return _RUN.sub(" ", out)


def _lines(text: str, *, table: bool) -> str:
    lines = []
    for line in text.split("\n"):
        line = line.strip()
        if line:
            lines.append(re.sub(r" {2,}", "  ", line) if table else _RUN.sub(" ", line))
    return "\n".join(lines)


def normalize_block(block: Block) -> Block | None:
    text = _clean(block.text)
    if block.kind == "paragraph":
        text = _paragraph(text)
    elif block.kind == "heading":
        text = _RUN.sub(" ", " ".join(text.split("\n")).strip())
    elif block.kind == "code":
        text = "\n".join(line.rstrip() for line in text.split("\n")).strip("\n")
    else:
        text = _lines(text, table=block.kind == "table")
    if not text.strip():
        return None
    return Block(kind=block.kind, text=text, level=block.level, page=block.page, flags=block.flags)


def _edge_key(block: Block) -> tuple[str, str] | None:
    edge = "first" if "page_first" in block.flags else "last" if "page_last" in block.flags else None
    return (edge, re.sub(r"\d+", "#", block.text.lower())) if edge else None


def normalize(parsed: ParsedDocument) -> NormalizedDocument:
    blocks = [b for b in (normalize_block(b) for b in parsed.blocks) if b is not None]
    warnings: list[str] = []
    if parsed.format == "pdf" and parsed.page_count:
        threshold = max(EDGE_MIN_PAGES, math.ceil(EDGE_MIN_SHARE * parsed.page_count))
        pages = Counter()
        for key, page in {(_edge_key(b), b.page) for b in blocks if _edge_key(b)}:
            pages[key] += 1
        repeated = {key for key, n in pages.items() if n >= threshold}
        kept = [b for b in blocks if _edge_key(b) not in repeated]
        if len(kept) != len(blocks):
            warnings.append(f"removed {len(blocks) - len(kept)} repeated page header/footer line(s)")
        blocks = kept
    text = "\n\n".join(f"{'#' * b.level} {b.text}" if b.kind == "heading" else b.text for b in blocks)
    return NormalizedDocument(normalizer_version=NORMALIZER_VERSION, blocks=tuple(blocks), text=text,
                              sha256=sha256_hex(text), warnings=tuple(warnings))

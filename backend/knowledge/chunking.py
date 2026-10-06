"""Structure-aware lexical chunker (ADR §4.3), versioned as CHUNKER_VERSION.

Split priority: heading/section -> paragraph -> list/table/code block -> deterministic split of
an over-long block. Sizes are whitespace-token heuristics for lexical retrieval, NOT model
tokens: blocks of one section are packed in order while the chunk stays <= TARGET_TOKENS; a
block that alone exceeds MAX_TOKENS is split:
- paragraph: at sentence ends (`.`, `!`, `?`, `…` + space), pieces <= MAX_TOKENS; each piece after
  the first repeats the previous piece's last sentence (the only overlap, ADR §4.3) when that
  sentence is short enough to keep the piece within MAX_TOKENS;
- list/table/code: at line boundaries, no overlap;
- any single sentence/line still over MAX_TOKENS: fixed MAX_TOKENS token windows, no overlap.
Headings are not repeated in `content`; they are the chunk's `section_path` (`A > B > C`),
which the database also indexes. Parameters are frozen for V1.3-C (no tuning here).
"""

from __future__ import annotations

import re

from knowledge.ids import chunk_id, sha256_hex
from knowledge.models import Block, Chunk, NormalizedDocument

CHUNKER_VERSION = "kn-chunk-1"
TARGET_TOKENS = 300
MAX_TOKENS = 450

_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")


def tokens(text: str) -> int:
    return len(text.split())


def _windows(text: str) -> list[str]:
    words = text.split()
    return [" ".join(words[i:i + MAX_TOKENS]) for i in range(0, len(words), MAX_TOKENS)]


def _pack(units: list[str], sep: str, overlap: bool) -> list[tuple[str, bool]]:
    """Greedy, order-preserving packing of units into pieces <= MAX_TOKENS.
    Returns (text, starts_with_overlap)."""
    pieces: list[tuple[str, bool]] = []
    current: list[str] = []
    lead = False
    for unit in units:
        if tokens(unit) > MAX_TOKENS:
            if current:
                pieces.append((sep.join(current), lead))
            pieces.extend((w, False) for w in _windows(unit))
            current, lead = [], False
            continue
        if current and tokens(sep.join(current + [unit])) > MAX_TOKENS:
            pieces.append((sep.join(current), lead))
            last = current[-1]
            if overlap and len(current) > 1 and tokens(last) + tokens(unit) <= MAX_TOKENS:
                current, lead = [last, unit], True
            else:
                current, lead = [unit], False
        else:
            current.append(unit)
    if current:
        pieces.append((sep.join(current), lead))
    return pieces


def _split_block(block: Block) -> list[tuple[str, dict]]:
    if block.kind == "paragraph":
        sentences = [s for s in _SENTENCE_END.split(block.text) if s.strip()]
        return [(text, {"split": "sentence", **({"overlap_sentence": True} if lead else {})})
                for text, lead in _pack(sentences, " ", overlap=True)]
    lines = [line for line in block.text.split("\n") if line.strip()]
    return [(text, {"split": "line"}) for text, _ in _pack(lines, "\n", overlap=False)]


def _metadata(blocks: list[Block], extra: dict | None = None) -> dict:
    kinds = sorted({b.kind for b in blocks})
    meta: dict = {"block_kinds": kinds}
    if "table" in kinds:
        meta["table"] = True
    if any("table_uncertain" in b.flags for b in blocks):
        meta["table_uncertain"] = True
    return {**meta, **(extra or {})}


def chunk(document: NormalizedDocument, *, source_id: str, document_id: str, document_version: str) -> tuple[Chunk, ...]:
    out: list[Chunk] = []
    per_section: dict[str | None, int] = {}

    def emit(section: str | None, content: str, blocks: list[Block], extra: dict | None = None):
        pages = [b.page for b in blocks if b.page is not None]
        n = per_section.get(section, 0)
        per_section[section] = n + 1
        digest = sha256_hex(content)
        out.append(Chunk(
            chunk_id=chunk_id(source_id=source_id, document_id=document_id, document_version=document_version,
                              section_path=section, ordinal_in_section=n, content_sha256=digest),
            ordinal=len(out), ordinal_in_section=n, section_path=section, content=content, content_sha256=digest,
            page_from=min(pages) if pages else None, page_to=max(pages) if pages else None,
            tokens=tokens(content), metadata=_metadata(blocks, extra)))

    stack: list[tuple[int, str]] = []
    section: str | None = None
    current: list[Block] = []

    def flush():
        nonlocal current
        if current:
            emit(section, "\n\n".join(b.text for b in current), current)
        current = []

    for block in document.blocks:
        if block.kind == "heading":
            flush()
            stack = [(lvl, text) for lvl, text in stack if lvl < block.level] + [(block.level, block.text)]
            section = " > ".join(text for _, text in stack)
            continue
        size = tokens(block.text)
        if size > MAX_TOKENS:
            flush()
            for text, extra in _split_block(block):
                emit(section, text, [block], extra)
            continue
        if current and tokens("\n\n".join(b.text for b in current)) + size > TARGET_TOKENS:
            flush()
        current.append(block)
    flush()
    return tuple(out)

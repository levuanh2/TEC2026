"""Quantitative claim policy (docs/rag/RAG_V1_ARCHITECTURE.md §13).

Structural rule: a generator never writes a business number. It writes a
`{{fact:<fact_id>}}` placeholder, lists the id in `fact_refs`, and the trusted
result carries the referenced `GroundedFact` whose value the client renders.

Backstop (deliberately narrow, not NLP): after removing placeholders, a digit
run followed by a business unit — %, kg, tấn, CO2/CO2e, m3/m³, lít, đ/đồng/
VND, triệu/nghìn — fails grounding. Harmless numbers ("1 phải 5 giảm",
"15 cm", "3 lần") pass. Numbers spelled out in words are not detected; the
placeholder rule and the provider prompt cover those.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence

from .errors import FactReferenceMismatch, GroundingFailed
from .models import FactRef, GroundedFact

FACT_PLACEHOLDER = re.compile(r"\{\{fact:([A-Za-z0-9_.:\-]+)\}\}")
_BUSINESS_QUANTITY = re.compile(
    r"\d(?:[\d.,]*\d)?\s*(?:%|phần\s*trăm|kg\b|kilogram|tấn\b|co2|m3\b|m³|lít\b|đồng\b|đ\b|vnđ\b|vnd\b|"
    r"triệu\b|nghìn\b|ngàn\b)",
    re.IGNORECASE,
)


def placeholder_ids(text: str) -> list[str]:
    return FACT_PLACEHOLDER.findall(text)


def unreferenced_quantities(text: str) -> list[str]:
    return [m.group(0) for m in _BUSINESS_QUANTITY.finditer(FACT_PLACEHOLDER.sub(" ", text))]


def validate_fact_refs(refs: Sequence[FactRef], catalog: Mapping[str, GroundedFact]) -> None:
    """One fact-reference list (an answer's, or one recommendation's)."""
    seen: set[str] = set()
    for ref in refs:
        if ref.fact_id in seen:
            raise FactReferenceMismatch(f"duplicate fact reference {ref.fact_id}")
        if ref.fact_id not in catalog:
            raise FactReferenceMismatch(f"unknown fact {ref.fact_id}")
        seen.add(ref.fact_id)


def validate_quantitative_claims(texts: Iterable[str], declared: set[str], catalog: Mapping[str, GroundedFact]) -> None:
    """Every placeholder names a declared, existing fact; no business number
    appears outside a placeholder."""
    for text in texts:
        for fact_id in placeholder_ids(text):
            if fact_id not in catalog:
                raise FactReferenceMismatch(f"placeholder names an unknown fact {fact_id}")
            if fact_id not in declared:
                raise FactReferenceMismatch(f"placeholder {fact_id} is not listed in fact_refs")
        loose = unreferenced_quantities(text)
        if loose:
            raise GroundingFailed(f"quantitative claim without a system fact: {loose[0]!r}")

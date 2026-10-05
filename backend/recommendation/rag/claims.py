"""Fact-reference policy (docs/rag/RAG_V1_ARCHITECTURE.md §13).

Structural rule: a generator never writes a business number. It writes a
`{{fact:<fact_id>}}` placeholder, lists the id in `fact_refs`, and the trusted
result carries the referenced `GroundedFact`, whose value the trusted renderer
substitutes. That no raw number, link or malformed placeholder appears in the
prose itself is the generated-prose policy (prose.py).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence

from .errors import FactReferenceMismatch
from .models import FactRef, GroundedFact

FACT_PLACEHOLDER = re.compile(r"\{\{fact:([A-Za-z0-9_.:\-]+)\}\}")


def placeholder_ids(text: str) -> list[str]:
    return FACT_PLACEHOLDER.findall(text)


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
    """Every placeholder names a declared, existing fact."""
    for text in texts:
        for fact_id in placeholder_ids(text):
            if fact_id not in catalog:
                raise FactReferenceMismatch(f"placeholder names an unknown fact {fact_id}")
            if fact_id not in declared:
                raise FactReferenceMismatch(f"placeholder {fact_id} is not listed in fact_refs")

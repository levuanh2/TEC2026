"""Generated prose policy (docs/rag/RAG_V1_ARCHITECTURE.md §13): what UNTRUSTED
generator text may contain.

Applies only to generator-controlled prose (`GeneratedAnswer.texts()`), never
to `GroundedFact` values, `EvidenceChunk` content or trusted metadata. Each
rule fails closed; none guesses whether a token is harmless. Outside the
canonical `{{fact:<fact_id>}}` placeholders, prose has:

  * no other placeholder-like syntax — no brace of any width (NFKC);
  * no number — no numeric character of any script (digits, numerals,
    superscripts, fractions): an authoritative number is a placeholder backed
    by a `FactRef` and a `GroundedFact`;
  * no link — scheme, `www.`, dotted domain, Markdown link or HTML (on NFKC
    text): a source URL reaches a client only as trusted `CitedEvidence.url`;
  * only allowlisted characters — letters, combining marks, whitespace and
    plain sentence punctuation; any other symbol (↊, %, $, @, emoji, …) is
    rejected rather than enumerated.

Not covered: numbers spelled out in words (known gap) and numbers quoted
from cited documents (D6, not supported — rejected by the number rule).
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from .claims import FACT_PLACEHOLDER
from .errors import FactReferenceMismatch, GroundingFailed

_LINK = re.compile(
    r"[a-z][a-z0-9+.\-]*://"                                    # any scheme://
    r"|\bwww\."
    r"|\b(?:mailto|javascript|data|file|tel):"
    r"|[^\W_]\.[^\W\d_]{2,}"                                    # dotted domain (any TLD, IDN)
    r"|\]\s*\("                                                 # Markdown [text](target)
    r"|<\s*/?\s*[a-z!]|\bhref\b",                               # HTML
    re.IGNORECASE,
)
#: Sentence punctuation prose may use besides letters, marks and whitespace.
_PUNCTUATION = frozenset(" .,;:!?'\"()-–—/…“”‘’«»")


def _outside_placeholders(text: str) -> str:
    return FACT_PLACEHOLDER.sub(" ", text)


def validate_placeholder_syntax(text: str) -> None:
    if any(brace in unicodedata.normalize("NFKC", _outside_placeholders(text)) for brace in "{}"):
        raise FactReferenceMismatch("malformed fact placeholder: only {{fact:<fact_id>}} is allowed")


def validate_no_raw_numbers(text: str) -> None:
    for token in _outside_placeholders(text).split():
        if any(char.isnumeric() for char in token):
            raise GroundingFailed(f"number without a system fact: {token!r}")


def validate_no_raw_links(text: str) -> None:
    match = _LINK.search(unicodedata.normalize("NFKC", _outside_placeholders(text)))
    if match:
        raise GroundingFailed(f"link in generated text: {match.group(0)!r}")


def validate_supported_characters(text: str) -> None:
    for char in _outside_placeholders(text):
        if not (char.isspace() or char in _PUNCTUATION or unicodedata.category(char)[0] in "LM"):
            raise GroundingFailed(f"unsupported character in generated text: U+{ord(char):04X}")


def validate_generated_prose(texts: Iterable[str]) -> None:
    for text in texts:
        validate_placeholder_syntax(text)
        validate_no_raw_numbers(text)
        validate_no_raw_links(text)
        validate_supported_characters(text)

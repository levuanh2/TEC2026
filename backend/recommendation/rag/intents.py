"""RAG V1 vocabulary: intents, modes, access levels and the evidence policy.

The only place that decides which intents need external evidence and which
access level a request needs — the route and the orchestrator never branch on
an intent's name (docs/rag/RAG_V1_ARCHITECTURE.md §6, §11).
"""

from __future__ import annotations

from enum import StrEnum


class RagIntent(StrEnum):
    EXPLAIN = "explain"
    COMPARE = "compare"
    RECOMMEND = "recommend"
    WHAT_IF = "what_if"
    EVIDENCE = "evidence"
    DATA_GAP = "data_gap"
    UNKNOWN = "unknown"


class RagMode(StrEnum):
    #: Answer from the stored deterministic recommendations.
    ASK = "ask"
    #: Answer from freshly evaluated deterministic rules (`persist=False`).
    PREVIEW = "preview"


class AccessLevel(StrEnum):
    READ = "read"
    WRITE = "write"


#: Intents whose answer is a claim beyond the season's own authoritative data,
#: so it must cite retrieved evidence. COMPARE is here because no benchmark
#: exists in the database (docs/modules/05-ai-recommendation.md, R2): a
#: benchmark can only come from a cited source. UNKNOWN is treated
#: conservatively.
EVIDENCE_REQUIRED_INTENTS: frozenset[RagIntent] = frozenset({
    RagIntent.COMPARE, RagIntent.RECOMMEND, RagIntent.EVIDENCE, RagIntent.UNKNOWN,
})


def required_access(intent: RagIntent, mode: RagMode) -> AccessLevel:
    """Access level a question needs. Every V1 mode is read-only.

    Open decision D1 (docs/rag/RAG_V1_ARCHITECTURE.md): Core V1 only runs
    `persist=False` engine calls for farmers with write authority. If the
    product owner keeps that rule for WHAT_IF/PREVIEW, this is the one line
    to change.
    """
    del intent, mode
    return AccessLevel.READ

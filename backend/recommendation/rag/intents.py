"""RAG V1 vocabulary and the per-intent policy table.

The only place that decides, per intent, which Core V1 access level is needed,
whether retrieved documents are required and whether the answer may contain
recommendations. The route and the orchestrator never branch on an intent's
name for policy (docs/rag/RAG_V1_ARCHITECTURE.md §6, §11).
"""

from __future__ import annotations

from dataclasses import dataclass
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
    #: Core V1 read scope of the season (RLS `user_can_read_crop`).
    READ = "read"
    #: Core V1 recommendation/CV write authority: an active `farmer` membership
    #: in the season's organization AND `private.user_can_write_crop`
    #: (`infrastructure/crop_write_authz.py`).
    WRITE = "write"


@dataclass(frozen=True)
class IntentPolicy:
    access: AccessLevel
    #: An answer must cite at least one retrieved document.
    needs_documents: bool
    #: The answer may contain recommendations (action-producing intent).
    may_recommend: bool


#: Decision D1 (closed): action-producing intents keep Core V1 write
#: semantics even though nothing is persisted — no new access for viewers,
#: managers, former owners or other organizations. UNKNOWN never reaches
#: generation (the orchestrator asks for clarification), so it is read-only.
INTENT_POLICIES: dict[RagIntent, IntentPolicy] = {
    RagIntent.EXPLAIN: IntentPolicy(AccessLevel.READ, needs_documents=False, may_recommend=False),
    RagIntent.COMPARE: IntentPolicy(AccessLevel.READ, needs_documents=False, may_recommend=False),
    RagIntent.EVIDENCE: IntentPolicy(AccessLevel.READ, needs_documents=True, may_recommend=False),
    RagIntent.DATA_GAP: IntentPolicy(AccessLevel.READ, needs_documents=False, may_recommend=False),
    RagIntent.RECOMMEND: IntentPolicy(AccessLevel.WRITE, needs_documents=True, may_recommend=True),
    RagIntent.WHAT_IF: IntentPolicy(AccessLevel.WRITE, needs_documents=False, may_recommend=True),
    RagIntent.UNKNOWN: IntentPolicy(AccessLevel.READ, needs_documents=False, may_recommend=False),
}


def required_access(intent: RagIntent, mode: RagMode) -> AccessLevel:
    """PREVIEW re-runs the deterministic rules, i.e. Carbon what-ifs, which
    Core V1 only runs for writers (`RecommendationService.generate`)."""
    if mode is RagMode.PREVIEW:
        return AccessLevel.WRITE
    return INTENT_POLICIES[intent].access

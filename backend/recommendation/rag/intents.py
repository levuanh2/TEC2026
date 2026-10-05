"""RAG V1 vocabulary and the per-intent policy table.

The only place that decides, per intent, what a generator may produce (its
`GenerationCapability`), which Core V1 access level that needs and whether
retrieved documents are required. Access follows the capability, not the
intent's name: READ buys informational answers only, never advice. The route
and the orchestrator never branch on an intent's name for policy
(docs/rag/RAG_V1_ARCHITECTURE.md §6, §11).
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


class GenerationCapability(StrEnum):
    #: Describe, explain, compare or summarize authorized facts, evidence,
    #: data gaps and provenance. Never recommend an action, give steps, say
    #: what the farmer should do or propose a change: the output schema has
    #: no recommendation slot (`InformationalAnswer`).
    INFORMATIONAL = "informational"
    #: May recommend actions (structured `recommendations`) and simulate an
    #: intervention.
    ACTION_PRODUCING = "action_producing"


#: Decision D1 (closed): action-producing generation keeps Core V1 write
#: semantics even though nothing is persisted — no new access for viewers,
#: managers, former owners or other organizations. Free text of an
#: INFORMATIONAL answer can still phrase advice; detecting that is D8, a
#: required gate before any real generator serves READ-tier requests.
CAPABILITY_ACCESS: dict[GenerationCapability, AccessLevel] = {
    GenerationCapability.INFORMATIONAL: AccessLevel.READ,
    GenerationCapability.ACTION_PRODUCING: AccessLevel.WRITE,
}


@dataclass(frozen=True)
class IntentPolicy:
    #: What the generator may produce; None = no generation at all.
    capability: GenerationCapability | None
    #: An answer must cite at least one retrieved document.
    needs_documents: bool

    @property
    def access(self) -> AccessLevel:
        # No generation still reads the season (after a READ check).
        return AccessLevel.READ if self.capability is None else CAPABILITY_ACCESS[self.capability]

    @property
    def may_recommend(self) -> bool:
        return self.capability is GenerationCapability.ACTION_PRODUCING


_INFORMATIONAL, _ACTION = GenerationCapability.INFORMATIONAL, GenerationCapability.ACTION_PRODUCING

#: UNKNOWN never reaches generation: the orchestrator asks for clarification.
INTENT_POLICIES: dict[RagIntent, IntentPolicy] = {
    RagIntent.EXPLAIN: IntentPolicy(_INFORMATIONAL, needs_documents=False),
    RagIntent.COMPARE: IntentPolicy(_INFORMATIONAL, needs_documents=False),
    RagIntent.EVIDENCE: IntentPolicy(_INFORMATIONAL, needs_documents=True),
    RagIntent.DATA_GAP: IntentPolicy(_INFORMATIONAL, needs_documents=False),
    RagIntent.RECOMMEND: IntentPolicy(_ACTION, needs_documents=True),
    RagIntent.WHAT_IF: IntentPolicy(_ACTION, needs_documents=False),
    RagIntent.UNKNOWN: IntentPolicy(None, needs_documents=False),
}


def required_access(intent: RagIntent, mode: RagMode) -> AccessLevel:
    """The capability's access level. PREVIEW re-runs the deterministic
    rules, i.e. Carbon what-ifs, which Core V1 only runs for writers
    (`RecommendationService.generate`), so it needs WRITE whatever the intent."""
    if mode is RagMode.PREVIEW:
        return AccessLevel.WRITE
    return INTENT_POLICIES[intent].access

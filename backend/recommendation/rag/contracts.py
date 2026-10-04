"""Ports of the RAG core — structural Protocols, like `rules.CarbonCalculator`.

Each one is a real boundary: the caller's authorization (`SeasonAccessGate`),
existing Core V1 reads (`SeasonFactsSource`), a knowledge store
(`KnowledgeRetriever`), a model provider (`AnswerGenerator`) and the Carbon
service (`WhatIfSimulator`). Concrete adapters live outside this package
(docs/rag/RAG_V1_ARCHITECTURE.md §4) and none exists in V1 except
`what_if.CarbonScenarioWhatIf`, which only wraps an injected CarbonService.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Protocol

from .intents import AccessLevel
from .models import AuthorizedSeasonScope, EvidenceChunk, HypotheticalChange, RetrievalQuery, WhatIfResult

if TYPE_CHECKING:
    from .answers import GenerationInput


class SeasonAccessGate(Protocol):
    """Bound to one caller (like `SupabaseReadRepository` is bound to a JWT).

    Must reuse Core V1 checks — RLS read for READ, `crop_write_authz` for
    WRITE — and raise `RagAccessDenied` for an unknown or out-of-scope season.
    """

    def authorize(self, crop_season_id: str, level: AccessLevel) -> AuthorizedSeasonScope: ...


class SeasonFactsSource(Protocol):
    """Rows from EXISTING Core V1 reads, already scoped to the caller.

    Each method maps 1:1 to a Core V1 method (RAG_V1_DATA_CONTRACT.md §9);
    an adapter composes them, it never queries business tables itself.
    """

    def season(self, crop_season_id: str) -> Mapping[str, Any]: ...

    def activity_summary(self, crop_season_id: str) -> Mapping[str, Any]: ...

    def metrics(self, crop_season_id: str) -> Mapping[str, Any]: ...

    def carbon_actual(self, crop_season_id: str) -> Mapping[str, Any] | None: ...

    def carbon_readiness(self, crop_season_id: str) -> Mapping[str, Any] | None: ...

    def recommendation_signals(self, crop_season_id: str, *, fresh: bool) -> Sequence[Mapping[str, Any]]: ...

    def cv_signals(self, crop_season_id: str) -> Sequence[Mapping[str, Any]]: ...


class KnowledgeRetriever(Protocol):
    """Read-only search. Applies `query.tenant` inside the store query, never
    persists, never calls Carbon. Raises `RetrievalUnavailable` on failure."""

    def retrieve(self, query: RetrievalQuery) -> Sequence[EvidenceChunk]: ...


class AnswerGenerator(Protocol):
    """Model provider adapter. Returns the provider's STRUCTURED output as a
    mapping; the orchestrator validates it against `GeneratedAnswer`. Owns
    the policy prompt; has no DB access and no tools."""

    def generate(self, request: GenerationInput) -> Mapping[str, Any]: ...


class WhatIfSimulator(Protocol):
    def simulate(self, scope: AuthorizedSeasonScope, change: HypotheticalChange) -> WhatIfResult: ...

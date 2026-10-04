"""Retrieval query building and the tenant-isolation backstop.

The retriever adapter enforces `RetrievalQuery.tenant` inside the store
query; `assert_tenant_isolation` re-checks what came back, so a buggy or
misconfigured store fails closed instead of leaking another tenant's
evidence into generation. Isolation is never left to the prompt.
"""

from __future__ import annotations

from collections.abc import Sequence

from .errors import TenantIsolationViolation
from .intents import RagIntent
from .models import AuthorizedSeasonScope, EvidenceChunk, RetrievalQuery, TenantScope


def build_retrieval_query(question: str, intent: RagIntent, scope: AuthorizedSeasonScope) -> RetrievalQuery:
    return RetrievalQuery(
        text=question,
        intent=intent,
        tenant=TenantScope(
            organization_id=scope.organization_id, farm_id=scope.farm_id, crop_season_id=scope.crop_season_id,
        ),
    )


def assert_tenant_isolation(evidence: Sequence[EvidenceChunk], scope: AuthorizedSeasonScope) -> None:
    for chunk in evidence:
        if chunk.visibility != "tenant":
            continue
        if chunk.organization_id != scope.organization_id or chunk.farm_id not in (None, scope.farm_id):
            # Ids of the offending chunk only — never the other tenant's ids.
            raise TenantIsolationViolation(
                f"retrieved tenant evidence outside the caller's scope: source={chunk.source_id} chunk={chunk.chunk_id}"
            )

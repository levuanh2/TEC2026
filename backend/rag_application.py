"""RAG V1.3 application adapters: caller-bound scope and real lexical retrieval.

This module joins the provider-neutral RAG core (`recommendation/rag/`) to Core V1
(docs/rag/RAG_V1_RETRIEVAL_ADR.md §3, §8). It is deliberately NOT in `service.py`
(architecture debt, docs/rag/RAG_V1_ARCHITECTURE.md §1) and NOT in `infrastructure/`,
which stays free of `recommendation.rag`: the infrastructure layer only offers two plain
RLS-bound reads (`SupabaseReadRepository.season_lineage` and `.knowledge_matches`), and the
mapping into RAG contracts happens here.

What is here:

* `CallerSeasonScopeResolver` -- decision D3. READ = the caller's own JWT through RLS
  (season -> plot -> farm -> organization); WRITE = additionally the Core V1 write gate
  (`crop_write_authz.assert_can_write_crop` via the recommendation repository: an active
  `farmer` membership in the season's organization AND `private.user_can_write_crop`).
  Nothing is taken from the request; every refusal is `RagAccessDenied` (-> 404).
* `LexicalKnowledgeRetriever` -- `KnowledgeRetriever` over the SECURITY INVOKER RPC
  `match_knowledge_chunks_lexical`, called with the caller's JWT. Tenant scope is derived in
  the database from the season; this adapter adds a configurable relevance cutoff and maps
  rows to `EvidenceChunk`s. Chunk text stays UNTRUSTED data.
* `RagEvidenceService` -- question -> authorized scope -> retrieval query -> evidence ->
  `assert_tenant_isolation`. Retrieval only.

What is NOT here (and must not be, until D8 is closed): `AnswerGenerator`,
`GenerationInput`, `RagOrchestrator` or any generated answer. `test_rag_architecture.py`
enforces that for every production module.
"""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

from pydantic import ValidationError

from infrastructure.crop_write_authz import CropWriteDeniedError
from infrastructure.read_repo import ReadNotFoundError
from recommendation.rag import (
    AccessLevel,
    AuthorizedSeasonScope,
    EvidenceChunk,
    RagAccessDenied,
    RagIntent,
    RagMode,
    RetrievalQuery,
    RetrievalUnavailable,
    assert_tenant_isolation,
    build_retrieval_query,
    required_access,
)

#: ADR §6: no cutoff is calibrated yet (that needs the approved corpus and the DEV split
#: of the eval plan). 0.0 keeps every row the RPC ranked; a deployment sets the DEV value.
DEFAULT_MIN_FUSED_SCORE = 0.0
#: `ShortText` bound of the RAG contracts; `section_path` may be up to 1 000 characters.
_SHORT_TEXT = 500
_ELLIPSIS = "…"


class LineageReader(Protocol):
    """The two caller-bound reads this module needs (`SupabaseReadRepository`)."""

    def user_id(self) -> str: ...

    def season_lineage(self, season_id: str) -> Mapping[str, str]: ...


class KnowledgeSearch(Protocol):
    def knowledge_matches(self, season_id: str, query: str, top_k: int) -> Sequence[Mapping[str, Any]]: ...


#: `PostgresRecommendationRepository.assert_can_write` -- raises `CropWriteDeniedError`.
WriteGate = Callable[..., None]


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return False
    return True


class CallerSeasonScopeResolver:
    """`SeasonScopeResolver` bound to ONE caller (D3).

    `write_gate` is the Core V1 recommendation write check. Without one, WRITE is refused:
    a deployment that cannot evaluate write authority never grants it.
    """

    def __init__(self, reader: LineageReader, *, write_gate: WriteGate | None = None) -> None:
        self._reader = reader
        self._write_gate = write_gate

    def resolve(self, crop_season_id: str, level: AccessLevel) -> AuthorizedSeasonScope:
        # A malformed id would surface as a PostgREST 400; refuse it before any read.
        if not _is_uuid(crop_season_id):
            raise RagAccessDenied("not a crop season id")
        try:
            lineage = self._reader.season_lineage(crop_season_id)
            actor_id = self._reader.user_id()
        except ReadNotFoundError as exc:
            raise RagAccessDenied("season not visible to the caller") from exc
        if lineage.get("crop_season_id") != str(uuid.UUID(crop_season_id)):
            raise RagAccessDenied("lineage of another season")
        if level is AccessLevel.WRITE:
            if self._write_gate is None:
                raise RagAccessDenied("write authority cannot be evaluated")
            try:
                self._write_gate(crop_season_id=lineage["crop_season_id"], actor_id=actor_id)
            except CropWriteDeniedError as exc:
                raise RagAccessDenied("caller may not write this season") from exc
        try:
            return AuthorizedSeasonScope(
                actor_id=actor_id, organization_id=lineage["organization_id"], farm_id=lineage["farm_id"],
                plot_id=lineage["plot_id"], crop_season_id=lineage["crop_season_id"], access=level,
            )
        except (KeyError, ValidationError) as exc:
            raise RagAccessDenied("incomplete season lineage") from exc


@dataclass(frozen=True)
class RetrievalSettings:
    #: Rows whose RRF fused score is below this are dropped (DEV-calibrated, ADR §6).
    min_fused_score: float = DEFAULT_MIN_FUSED_SCORE

    def __post_init__(self) -> None:
        if not math.isfinite(self.min_fused_score) or self.min_fused_score < 0:
            raise ValueError("min_fused_score must be a finite, non-negative number")


def _short(text: Any) -> str | None:
    if text is None:
        return None
    text = str(text).strip()
    if not text:
        return None
    return text if len(text) <= _SHORT_TEXT else text[: _SHORT_TEXT - 1].rstrip() + _ELLIPSIS


def _scalar_metadata(row: Mapping[str, Any]) -> dict[str, str | int | float | bool | None]:
    """Chunk metadata (scalars only; nested values are dropped, never stringified) plus the
    retrieval provenance a citation panel and the eval runner need."""
    out: dict[str, str | int | float | bool | None] = {}
    raw = row.get("metadata")
    if isinstance(raw, Mapping):
        for key, value in raw.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                out[f"chunk.{key}"] = value
    for key in ("page_from", "page_to", "ordinal", "fts_rank", "trgm_rank"):
        if row.get(key) is not None:
            out[key] = int(row[key])
    if row.get("fused_score") is not None:
        out["fused_score"] = float(row["fused_score"])
    return out


def evidence_from_row(row: Mapping[str, Any]) -> EvidenceChunk:
    """One RPC row -> `EvidenceChunk`. Every display field is trusted ingestion metadata;
    `content` is untrusted document text and is passed through verbatim."""
    published = row.get("published_at")
    return EvidenceChunk(
        source_id=row["source_id"], document_id=row["document_id"], document_version=row.get("document_version"),
        chunk_id=row["chunk_id"], title=_short(row.get("title")) or row["document_id"],
        section=_short(row.get("section_path")), content=row["content"], source_type=row["source_type"],
        visibility=row["visibility"],
        organization_id=str(row["organization_id"]) if row.get("organization_id") else None,
        farm_id=str(row["farm_id"]) if row.get("farm_id") else None,
        url=row.get("official_url"), authority=row.get("authority"),
        published_at=date.fromisoformat(published) if isinstance(published, str) else published,
        metadata=_scalar_metadata(row),
    )


class LexicalKnowledgeRetriever:
    """`KnowledgeRetriever` over the lexical RPC, bound to one caller's JWT.

    The tenant filter is applied INSIDE the store query: the RPC derives organization and
    farm from `query.tenant.crop_season_id` under RLS and has no other scope input. The
    organization/farm in `query.tenant` are therefore not sent anywhere; the RAG core's
    `assert_tenant_isolation` re-checks every returned row against them (backstop).
    """

    def __init__(self, search: KnowledgeSearch, settings: RetrievalSettings | None = None) -> None:
        self._search = search
        self._settings = settings or RetrievalSettings()

    def retrieve(self, query: RetrievalQuery) -> tuple[EvidenceChunk, ...]:
        season_id = query.tenant.crop_season_id
        if season_id is None:
            raise RetrievalUnavailable("retrieval needs the authorized crop season")
        try:
            rows = self._search.knowledge_matches(season_id, query.text, query.top_k)
        except Exception as exc:  # noqa: BLE001 - adapter boundary: fail closed, cause chained
            raise RetrievalUnavailable(type(exc).__name__) from exc
        evidence: list[EvidenceChunk] = []
        seen: set[tuple[str, str]] = set()
        for row in rows[: query.top_k]:
            score = row.get("fused_score")
            if score is None or not math.isfinite(float(score)) or float(score) < self._settings.min_fused_score:
                continue
            if not query.include_public and row.get("visibility") == "public":
                continue
            try:
                chunk = evidence_from_row(row)
            except (KeyError, ValueError, ValidationError) as exc:
                raise RetrievalUnavailable("knowledge row failed the evidence contract") from exc
            if (chunk.source_id, chunk.chunk_id) in seen:
                continue
            seen.add((chunk.source_id, chunk.chunk_id))
            evidence.append(chunk)
        return tuple(evidence)


@dataclass(frozen=True)
class EvidenceResult:
    """Retrieval output for one authorized question. Nothing is persisted (D4)."""

    scope: AuthorizedSeasonScope
    query: RetrievalQuery
    evidence: tuple[EvidenceChunk, ...]


class RagEvidenceService:
    """Authorize first, then retrieve; no generation (D8 stays closed here)."""

    def __init__(self, settings: RetrievalSettings | None = None, *, write_gate: WriteGate | None = None) -> None:
        self._settings = settings or RetrievalSettings()
        self._write_gate = write_gate

    def evidence(self, *, reader: Any, crop_season_id: str, question: str, intent: RagIntent,
                 mode: RagMode = RagMode.ASK, top_k: int | None = None) -> EvidenceResult:
        """`reader` is the caller's `SupabaseReadRepository` (lineage + RPC, same JWT)."""
        if intent is RagIntent.UNKNOWN:
            raise ValueError("an unknown intent has no retrieval")
        resolver = CallerSeasonScopeResolver(reader, write_gate=self._write_gate)
        scope = resolver.resolve(crop_season_id, required_access(intent, mode))
        query = build_retrieval_query(question, intent, scope)
        if top_k is not None:  # validated again: the contract bounds top_k to 1..50
            query = RetrievalQuery(text=query.text, intent=query.intent, tenant=query.tenant,
                                   include_public=query.include_public, top_k=top_k)
        evidence = LexicalKnowledgeRetriever(reader, self._settings).retrieve(query)
        assert_tenant_isolation(evidence, scope)
        return EvidenceResult(scope=scope, query=query, evidence=evidence)

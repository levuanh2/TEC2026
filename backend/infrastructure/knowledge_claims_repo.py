"""Operator-side claim pipeline of RAG V1.5 M4 (docs/rag/RAG_V15_M4_CLAIMS_CONTRADICTIONS.md).

PsycopgClaimStore reads the chunks of one stored document version, hands the deterministic
extractor's claims to private.knowledge_record_claims, reads stored claims back with the context
of their documents, and hands the analysis' candidate pairs to
private.knowledge_record_contradiction_candidates. The database re-checks every span against the
chunk and classifies every pair itself, so nothing here can store a label the database does not
share.

It is a privileged OPERATOR path (a direct Postgres connection as service_role or the table
owner), never a user JWT and never reachable from an API route. It only SELECTs and calls those
two functions: it never writes a status, never approves, rejects or quarantines, and the answer
path does not read what it stores. A candidate is a review aid for a human, never a verdict.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from knowledge.integrity.claims import CLAIM_EXTRACTOR_VERSION, Claim, ClaimSource, extract_claims
from knowledge.integrity.contradictions import (ANALYSIS_VERSION, Analysis, ClaimRecord, DocumentRecord, Tolerance,
                                                analyze, candidate_payload, claim_payload)


class UnknownDocument(LookupError):
    """No document version with this primary key."""


@dataclass(frozen=True)
class ExtractionResult:
    document_pk: str
    extractor_version: str
    chunks: int
    claims: int               # claims the extractor produced
    inserted: int             # rows new in the database (0 on a repeated run)
    unresolved: int           # ambiguous or unsupported claims (stored, never compared)
    decision: str = "none"


@dataclass(frozen=True)
class AnalysisResult:
    document_pk: str
    analysis: Analysis
    inserted: int
    decision: str = "none"


class PsycopgClaimStore:
    """`conn` is a psycopg 3 connection owned by the caller. Each write is one `conn.transaction()`."""

    def __init__(self, conn: Any):
        self._conn = conn

    def chunk_sources(self, document_pk: str) -> list[ClaimSource]:
        """The chunks of one version as extractor input, in document order."""
        with self._conn.cursor() as cur:
            cur.execute("select d.source_id || '/' || d.document_id || '@' || d.document_version"
                        " from public.knowledge_documents d where d.id = %s", (document_pk,))
            row = cur.fetchone()
            if row is None:
                raise UnknownDocument(document_pk)
            cur.execute("select c.chunk_id, c.content from public.knowledge_chunks c where c.document_pk = %s"
                        " order by c.ordinal", (document_pk,))
            return [ClaimSource(row[0], chunk_id, content) for chunk_id, content in cur.fetchall()]

    def record_claims(self, document_pk: str, claims: Sequence[Claim], extractor_version: str) -> int:
        payload = json.dumps([claim_payload(c) for c in claims], ensure_ascii=False)
        with self._conn.transaction(), self._conn.cursor() as cur:
            cur.execute("select private.knowledge_record_claims(%s, %s, %s::jsonb)",
                        (document_pk, extractor_version, payload))
            return cur.fetchone()[0]

    def comparable_claims(self, document_pk: str, extractor_version: str) -> tuple[list[ClaimRecord],
                                                                                    list[DocumentRecord]]:
        """Every stored comparable claim (this extractor version) that shares a comparison key with a
        claim of `document_pk`, and the documents they belong to, with the database's evidence state."""
        with self._conn.cursor() as cur:
            cur.execute(
                "select c.id, c.document_pk::text, c.chunk_id, c.claim_id, c.comparison_key, c.value_min::float8,"
                "       c.value_max::float8, c.stage, c.scope_tags"
                "  from public.knowledge_claims c"
                " where c.extractor_version = %s and c.comparison_key in ("
                "       select s.comparison_key from public.knowledge_claims s"
                "        where s.document_pk = %s and s.extractor_version = %s and s.comparison_key is not null)"
                " order by c.id", (extractor_version, document_pk, extractor_version))
            claims = [ClaimRecord(r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], tuple(r[8])) for r in cur.fetchall()]
            pks = sorted({c.document_pk for c in claims})
            cur.execute(
                "select d.id::text, d.source_id, d.document_id, d.document_version, s.visibility,"
                "       s.organization_id::text, s.farm_id::text, e.state, e.reason, d.effective_from, d.effective_to,"
                "       d.supersedes_document_pk::text"
                "  from public.knowledge_documents d"
                "  join public.knowledge_sources s on s.source_id = d.source_id"
                " cross join lateral private.knowledge_document_evidence_state(d.id) e"
                # the documents of the claims and every version they supersede, through the whole chain
                # (the same bounded walk as private.knowledge_classify_claim_pair)
                " where d.id in ("
                "       with recursive chain(id, depth) as ("
                "         select x.id, 0 from public.knowledge_documents x where x.id::text = any(%s)"
                "         union"
                "         select x.supersedes_document_pk, chain.depth + 1 from chain"
                "           join public.knowledge_documents x on x.id = chain.id"
                "          where x.supersedes_document_pk is not null and chain.depth < 64)"
                "       select chain.id from chain)", (pks,))
            documents = [DocumentRecord(*r) for r in cur.fetchall()]
        return claims, documents

    def record_candidates(self, analysis: Analysis) -> int:
        payload = json.dumps([candidate_payload(c) for c in analysis.candidates])
        with self._conn.transaction(), self._conn.cursor() as cur:
            cur.execute("select private.knowledge_record_contradiction_candidates(%s, %s::jsonb)",
                        (analysis.analysis_version, payload))
            return cur.fetchone()[0]


def extract_document_claims(store: PsycopgClaimStore, document_pk: str) -> ExtractionResult:
    """Extract and store the claims of one document version. Deterministic and idempotent."""
    sources = store.chunk_sources(document_pk)
    claims = [claim for source in sources for claim in extract_claims(source)]
    inserted = store.record_claims(document_pk, claims, CLAIM_EXTRACTOR_VERSION)
    return ExtractionResult(document_pk, CLAIM_EXTRACTOR_VERSION, len(sources), len(claims), inserted,
                            sum(1 for c in claims if c.status != "extracted"))


def analyze_document(store: PsycopgClaimStore, document_pk: str, *,
                     tolerances: Sequence[Tolerance] = ()) -> AnalysisResult:
    """Compare the stored claims of one document version with every comparable stored claim and
    store the candidate pairs. No tolerance unless the caller supplies a justified one."""
    claims, documents = store.comparable_claims(document_pk, CLAIM_EXTRACTOR_VERSION)
    analysis = analyze(claims, documents, tolerances=tolerances, subject_document_pk=document_pk)
    inserted = store.record_candidates(analysis) if analysis.candidates else 0
    return AnalysisResult(document_pk, analysis, inserted)


__all__ = ["ANALYSIS_VERSION", "AnalysisResult", "ExtractionResult", "PsycopgClaimStore", "UnknownDocument",
           "analyze_document", "extract_document_claims"]

"""L2 Scientific RAG evaluation framework (docs/rag/RAG_L2_EVALUATION_FRAMEWORK.md) — pure computation.

Three things on top of the retrieval metrics in `rag_eval.py` (P/R/F1/nDCG@k, MRR, hit@k, latency):

1. Label provenance. A label set is either `draft_unvalidated` (machine or agent candidates, a person
   has not confirmed them) or `expert_validated` (every query carries `validated_by` and a
   `label_set_id`). `official_report` refuses to call a result a benchmark unless EVERY query of the
   split is expert-validated, and a comparison over draft labels never names a winner.
2. Method comparison. The same queries go through several retrievers (lexical, dense, hybrid,
   hybrid + rerank, ...). A retriever is any callable `query -> ranked chunks`; this module never loads
   a model, calls a provider or reads a database, so a method that is not configured simply is not run.
3. Answer-level metrics from judged answers: citation accuracy (a citation counts only if it points at
   a chunk that was served as evidence for THAT question, is approved, and has the cited version),
   hallucinated-citation rate, and unsupported-claim rate (claims that no cited chunk supports,
   according to the judge's `supported_by`).

No number here is produced without its inputs: an empty or draft set yields `None` / "no conclusion",
never a default score.
"""
from __future__ import annotations

import json
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rag_eval import EvalQuery, EvalSetError, judge, score

DRAFT, VALIDATED = "draft_unvalidated", "expert_validated"
LABEL_STATUSES = frozenset({DRAFT, VALIDATED})

Retriever = Callable[[EvalQuery], Sequence[Mapping[str, Any]]]


# -- 1. label provenance -----------------------------------------------------------------------

@dataclass(frozen=True)
class LabelProvenance:
    status: str
    label_set_id: str | None = None
    validated_by: tuple[str, ...] = ()
    validated_at: str | None = None


def load_provenance(path: Path) -> dict[str, LabelProvenance]:
    """{query id: provenance} from the same JSONL as `rag_eval.load_eval_set`. A row without
    `label_status` is a DRAFT: nothing becomes official by omission."""
    out: dict[str, LabelProvenance] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        where = f"{path.name}:{number}"
        status = row.get("label_status", DRAFT)
        if status not in LABEL_STATUSES:
            raise EvalSetError(f"{where}: unknown label_status {status!r}")
        validators = tuple(v for v in (row.get("validated_by") or []) if isinstance(v, str) and v.strip())
        if status == VALIDATED and (not validators or not row.get("label_set_id") or not row.get("validated_at")):
            raise EvalSetError(f"{where}: expert_validated needs validated_by, label_set_id and validated_at")
        out[row["id"]] = LabelProvenance(status, row.get("label_set_id"), validators, row.get("validated_at"))
    return out


def label_status(queries: Iterable[EvalQuery], provenance: Mapping[str, LabelProvenance]) -> dict[str, Any]:
    queries = list(queries)
    validated = [q.id for q in queries if provenance.get(q.id, LabelProvenance(DRAFT)).status == VALIDATED]
    set_ids = sorted({provenance[q].label_set_id for q in validated if provenance[q].label_set_id})
    official = bool(queries) and len(validated) == len(queries) and len(set_ids) == 1
    return {"queries": len(queries), "expert_validated": len(validated), "official": official,
            "label_set_id": set_ids[0] if official else None,
            "status": VALIDATED if official else DRAFT}


# -- 2. method comparison ---------------------------------------------------------------------------

def run_method(queries: Sequence[EvalQuery], retriever: Retriever) -> dict[str, Any]:
    """Score one retriever on one split. Latency is measured here, around the retriever call only."""
    outcomes = []
    for query in queries:
        started = time.perf_counter()
        ranked = list(retriever(query))
        outcomes.append(judge(query, ranked, (time.perf_counter() - started) * 1000))
    return score(queries, outcomes)


COMPARED = ("ndcg@10", "recall@10", "precision@5", "f1@5", "mrr@10")


def compare_methods(queries: Sequence[EvalQuery], retrievers: Mapping[str, Retriever | None],
                    provenance: Mapping[str, LabelProvenance]) -> dict[str, Any]:
    """Every configured method on the same queries. `None` = not configured (e.g. dense without an
    approved embedding model): reported as `not_run`, never scored. A winner is named only on an
    official (fully expert-validated) label set; on draft labels the numbers are a pipeline check."""
    status = label_status(queries, provenance)
    results: dict[str, Any] = {}
    for name, retriever in retrievers.items():
        results[name] = {"not_run": "retriever not configured"} if retriever is None else run_method(queries, retriever)
    scored = {n: r for n, r in results.items() if "not_run" not in r}
    best: dict[str, Any] = {}
    if status["official"] and len(scored) >= 2:
        for metric in COMPARED:
            values = {n: r.get(metric) for n, r in scored.items() if r.get(metric) is not None}
            if values:
                top = max(values.values())
                best[metric] = sorted(n for n, v in values.items() if v == top)
    return {"label_status": status, "methods": results,
            "best_by_metric": best if status["official"] else None,
            "conclusion": ("compare on the official label set" if status["official"]
                           else "NO CONCLUSION: labels are not expert-validated (pipeline check only)")}


# -- 3. answer-level metrics --------------------------------------------------------------------------

@dataclass(frozen=True)
class Citation:
    source_id: str
    chunk_id: str
    version_id: str | None = None


@dataclass(frozen=True)
class Claim:
    claim_id: str
    #: chunk ids the JUDGE found support the claim (empty = unsupported); set by a person, not a model
    supported_by: tuple[str, ...] = ()


@dataclass
class JudgedAnswer:
    query_id: str
    citations: tuple[Citation, ...]
    #: chunk id -> version id of every chunk the retriever served as evidence for this question
    served: Mapping[str, str | None]
    #: chunk ids that were approved (and current) at answer time
    approved: frozenset[str]
    claims: tuple[Claim, ...] = ()
    judged_by: str | None = None
    notes: dict[str, Any] = field(default_factory=dict)


def _citation_ok(c: Citation, a: JudgedAnswer) -> bool:
    if c.chunk_id not in a.served or c.chunk_id not in a.approved:
        return False
    return c.version_id is None or a.served[c.chunk_id] is None or c.version_id == a.served[c.chunk_id]


def answer_metrics(answers: Iterable[JudgedAnswer]) -> dict[str, Any]:
    answers = list(answers)
    unjudged = [a.query_id for a in answers if not a.judged_by]
    if unjudged:
        raise EvalSetError(f"answers without a judge: {unjudged[:5]}")
    citations = [(c, a) for a in answers for c in a.citations]
    claims = [(cl, a) for a in answers for cl in a.claims]

    def rate(n: int, d: int) -> dict[str, Any]:
        return {"count": n, "of": d, "rate": (n / d) if d else None}

    hallucinated = sum(1 for c, a in citations if c.chunk_id not in a.served)
    unapproved = sum(1 for c, a in citations if c.chunk_id in a.served and c.chunk_id not in a.approved)
    version_mismatch = sum(1 for c, a in citations if c.chunk_id in a.served and c.chunk_id in a.approved
                           and not _citation_ok(c, a))
    unsupported = sum(1 for cl, a in claims
                      if not set(cl.supported_by) & {c.chunk_id for c in a.citations if _citation_ok(c, a)})
    return {
        "answers": len(answers),
        "citation_accuracy": rate(sum(1 for c, a in citations if _citation_ok(c, a)), len(citations)),
        "hallucinated_citation_rate": rate(hallucinated, len(citations)),
        "unapproved_citation_rate": rate(unapproved, len(citations)),
        "version_mismatch_rate": rate(version_mismatch, len(citations)),
        "unsupported_claim_rate": rate(unsupported, len(claims)),
        "answers_without_citation": [a.query_id for a in answers if not a.citations],
    }

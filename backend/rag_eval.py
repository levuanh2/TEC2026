"""Retrieval evaluation for RAG V1 (docs/rag/RAG_V1_RETRIEVAL_EVAL_PLAN.md) — pure metrics.

Labels name document SECTIONS (and optionally chunk ids), never numbers. A query hits at rank r
when the r-th retrieved chunk matches an `expected` (or `acceptable`) label. Negative queries
have `negative: true` and an empty `expected`; any returned chunk is a false positive.

This module computes; it does not retrieve. The runner (`scripts/eval_retrieval.py`) feeds it
the ranked results of the REAL retriever. HOLDOUT is only ever scored, never used to choose a
parameter: `score()` refuses to mix splits.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HIT_KS = (1, 3, 5, 8)
RECALL_KS = (5, 8)
MRR_K = 10
SPLITS = frozenset({"dev", "holdout", "fixture"})


class EvalSetError(ValueError):
    pass


@dataclass(frozen=True)
class Label:
    source_id: str
    document_id: str
    section_path: str | None = None
    chunk_ids: tuple[str, ...] = ()

    def matches(self, chunk: Mapping[str, Any]) -> bool:
        if chunk.get("source_id") != self.source_id or chunk.get("document_id") != self.document_id:
            return False
        if self.chunk_ids:
            return chunk.get("chunk_id") in self.chunk_ids
        if self.section_path is None:
            return True
        section = chunk.get("section") or ""
        return section == self.section_path or section.startswith(self.section_path + " > ")


@dataclass(frozen=True)
class EvalQuery:
    id: str
    split: str
    group: str
    category: str
    intent: str
    question: str
    negative: bool
    expected: tuple[Label, ...]
    acceptable: tuple[Label, ...] = ()
    set_version: int = 1


def _labels(rows: Any, where: str) -> tuple[Label, ...]:
    if not isinstance(rows, list):
        raise EvalSetError(f"{where}: must be a list")
    out = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("source_id") or not row.get("document_id"):
            raise EvalSetError(f"{where}: every label needs source_id and document_id")
        out.append(Label(row["source_id"], row["document_id"], row.get("section_path"), tuple(row.get("chunk_ids") or ())))
    return tuple(out)


def load_eval_set(path: Path) -> list[EvalQuery]:
    queries, seen, groups = [], set(), {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        where = f"{path.name}:{number}"
        for key in ("id", "split", "group", "category", "intent", "question"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                raise EvalSetError(f"{where}: missing {key}")
        if row["split"] not in SPLITS:
            raise EvalSetError(f"{where}: unknown split {row['split']!r}")
        if row["id"] in seen:
            raise EvalSetError(f"{where}: duplicate id {row['id']}")
        seen.add(row["id"])
        # Anti-leakage (eval plan §3): a topic group lives in exactly one split.
        if groups.setdefault(row["group"], row["split"]) != row["split"]:
            raise EvalSetError(f"{where}: group {row['group']!r} appears in two splits")
        negative = bool(row.get("negative", False))
        expected = _labels(row.get("expected", []), where)
        if negative and expected:
            raise EvalSetError(f"{where}: a negative query has no expected label")
        if not negative and not expected:
            raise EvalSetError(f"{where}: a positive query needs an expected label")
        queries.append(EvalQuery(row["id"], row["split"], row["group"], row["category"], row["intent"],
                                 row["question"], negative, expected, _labels(row.get("acceptable", []), where),
                                 int(row.get("set_version", 1))))
    if not queries:
        raise EvalSetError(f"{path.name}: empty")
    return queries


@dataclass
class QueryOutcome:
    id: str
    category: str
    negative: bool
    returned: int
    first_rank: int | None
    expected_found: int
    expected_total: int
    latency_ms: float
    top: list[dict[str, Any]] = field(default_factory=list)


def judge(query: EvalQuery, ranked: Sequence[Mapping[str, Any]], latency_ms: float) -> QueryOutcome:
    labels = query.expected + query.acceptable
    first = next((rank for rank, chunk in enumerate(ranked, 1) if any(l.matches(chunk) for l in labels)), None)
    found = sum(1 for label in query.expected if any(label.matches(chunk) for chunk in ranked[:max(RECALL_KS)]))
    top = [{"rank": rank, "source_id": c.get("source_id"), "document_id": c.get("document_id"),
            "section": c.get("section"), "chunk_id": c.get("chunk_id"), "score": c.get("score")}
           for rank, c in enumerate(ranked[:MRR_K], 1)]
    return QueryOutcome(query.id, query.category, query.negative, len(ranked), first, found,
                        len(query.expected), latency_ms, top)


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))]


def score(queries: Iterable[EvalQuery], outcomes: Iterable[QueryOutcome]) -> dict[str, Any]:
    queries, outcomes = list(queries), list(outcomes)
    splits = {q.split for q in queries}
    if len(splits) != 1:
        raise EvalSetError(f"score one split at a time, got {sorted(splits)}")
    by_id = {o.id: o for o in outcomes}
    positives = [by_id[q.id] for q in queries if not q.negative]
    negatives = [by_id[q.id] for q in queries if q.negative]

    def frac(n: int, d: int) -> dict[str, Any]:
        return {"count": n, "of": d, "rate": (n / d) if d else None}

    hit = {f"hit@{k}": frac(sum(1 for o in positives if o.first_rank and o.first_rank <= k), len(positives)) for k in HIT_KS}
    recall = {}
    for k in RECALL_KS:
        values = [o.expected_found / o.expected_total for o in positives if o.expected_total]
        recall[f"recall@{k}"] = (sum(values) / len(values)) if values else None
    mrr = (sum(1 / o.first_rank for o in positives if o.first_rank and o.first_rank <= MRR_K) / len(positives)
           if positives else None)
    latencies = [o.latency_ms for o in outcomes]
    categories: dict[str, dict[str, Any]] = {}
    for q in queries:
        o = by_id[q.id]
        cat = categories.setdefault(q.category, {"queries": 0, "hit@5": 0, "negative_false_positive": 0})
        cat["queries"] += 1
        if not q.negative and o.first_rank and o.first_rank <= 5:
            cat["hit@5"] += 1
        if q.negative and o.returned:
            cat["negative_false_positive"] += 1
    return {
        "split": splits.pop(),
        "set_version": max(q.set_version for q in queries),
        "queries": len(queries), "positives": len(positives), "negatives": len(negatives),
        **hit, **recall, "mrr@10": mrr,
        "negative_fpr": frac(sum(1 for o in negatives if o.returned), len(negatives)),
        "empty_result_rate": frac(sum(1 for o in positives if o.returned == 0), len(positives)),
        "latency_ms": {"p50": _percentile(latencies, 0.5), "p95": _percentile(latencies, 0.95)},
        "categories": categories,
        "failed_queries": [o.id for o in positives if not o.first_rank or o.first_rank > 5]
                          + [o.id for o in negatives if o.returned],
    }

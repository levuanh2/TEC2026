"""Run the RAG V1 retrieval evaluation against a REAL store, through the production retriever.

Each query goes through `RagEvidenceService` exactly as a request would: the caller's JWT
(RLS), the D3 scope resolver, the SECURITY INVOKER lexical RPC and the relevance cutoff. The
report records the configuration, per-query ranks and the metrics of
docs/rag/RAG_V1_RETRIEVAL_EVAL_PLAN.md §5. One split per run; HOLDOUT is scored, never tuned on.

  EVAL_ACCESS_TOKEN=<JWT of a user who can read the season> \\
  python backend/scripts/eval_retrieval.py --set backend/tests/fixtures/rag_eval/<set>.jsonl \\
      --season-id <uuid> --min-fused-score 0.0 --top-k 8 --out report.json

The token is read from the environment only and never written to the report.
Exit 0 = evaluated, 2 = usage / configuration error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infrastructure.config import load_settings  # noqa: E402
from infrastructure.read_repo import SupabaseReadRepository  # noqa: E402
from rag_application import RagEvidenceService, RetrievalSettings  # noqa: E402
from rag_eval import EvalSetError, judge, load_eval_set, score  # noqa: E402
from recommendation.rag import RagIntent  # noqa: E402


def evaluate(*, reader, season_id: str, set_path: Path, min_fused_score: float, top_k: int) -> dict:
    queries = load_eval_set(set_path)
    service = RagEvidenceService(RetrievalSettings(min_fused_score=min_fused_score))
    outcomes = []
    for query in queries:
        started = time.perf_counter()
        # Retrieval is the same for every intent; READ access is enough to measure it.
        result = service.evidence(reader=reader, crop_season_id=season_id, question=query.question,
                                  intent=RagIntent.EVIDENCE, top_k=top_k)
        elapsed = (time.perf_counter() - started) * 1000
        ranked = [{"source_id": c.source_id, "document_id": c.document_id, "section": c.section,
                   "chunk_id": c.chunk_id, "score": c.metadata.get("fused_score")} for c in result.evidence]
        outcomes.append(judge(query, ranked, elapsed))
    report = score(queries, outcomes)
    report["config"] = {"method": "lexical", "rpc": "match_knowledge_chunks_lexical",
                        "min_fused_score": min_fused_score, "top_k": top_k, "set": set_path.name}
    report["per_query"] = [o.__dict__ for o in outcomes]
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--set", type=Path, required=True)
    parser.add_argument("--season-id", required=True)
    parser.add_argument("--min-fused-score", type=float, default=0.0)
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    token = (os.environ.get("EVAL_ACCESS_TOKEN") or "").strip()
    if not token:
        print("EVAL_ACCESS_TOKEN is not set", file=sys.stderr)
        return 2
    try:
        reader = SupabaseReadRepository(load_settings(), token)
        report = evaluate(reader=reader, season_id=args.season_id, set_path=args.set,
                          min_fused_score=args.min_fused_score, top_k=args.top_k)
    except (EvalSetError, ValueError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    text = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

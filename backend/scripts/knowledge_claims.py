"""Operator CLI of RAG V1.5 M4: store the deterministic claims of ONE document version and the
contradiction candidates they raise against the stored claims of other versions.

    python backend/scripts/knowledge_claims.py --document-pk <uuid> --target local

LOCAL ONLY in M4: the destination must be a 127.0.0.1/localhost stack (`--target local` is
required and a hosted project is refused, exit 2). The M4 migration is not applied to hosted
Supabase, and applying it needs an owner decision.

What it does, in two transactions: extract (claims.py) and store the claims; compare them with
every comparable stored claim (contradictions.py) and store the candidate pairs. Both steps are
idempotent. It never changes a status and never approves, rejects or quarantines anything.

The output is a REVIEW AID for a human expert. `decision = none`, always. A candidate does not
mean a document is false, and no candidate does not mean it is true.

Exit codes: 0 done, 1 refused by the database or unknown document, 2 usage/target.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ingest_knowledge import target_of  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Store claims and contradiction candidates of ONE document version.")
    ap.add_argument("--document-pk", required=True, type=uuid.UUID, help="public.knowledge_documents.id")
    ap.add_argument("--target", required=True, choices=["local"], help="M4 runs against a local stack only")
    return ap


def report(extraction, result) -> str:
    counts = Counter(c.classification for c in result.analysis.candidates)
    lines = [
        "claim extraction and contradiction candidates (REVIEW AID, not a verdict)",
        f"document_pk        {extraction.document_pk}",
        f"extractor_version  {extraction.extractor_version}",
        f"analysis_version   {result.analysis.analysis_version}",
        f"chunks             {extraction.chunks}",
        f"claims             {extraction.claims} ({extraction.inserted} new, {extraction.unresolved} unresolved)",
        f"pairs compared     {result.analysis.compared}",
        "pairs not compared " + (", ".join(f"{reason}={n}" for reason, n in result.analysis.skipped) or "none"),
        f"candidates         {len(result.analysis.candidates)} ({result.inserted} new)",
    ]
    lines += [f"  {name:<24}{counts.get(name, 0)}" for name in
              ("contradiction", "apparent_contradiction", "missing_context", "insufficient_evidence")]
    lines += ["content_correctness = not_assessed", "decision = none"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    import psycopg

    from infrastructure.config import load_settings
    from infrastructure.knowledge_claims_repo import (PsycopgClaimStore, UnknownDocument, analyze_document,
                                                      extract_document_claims)

    settings = load_settings()
    url, _ = settings.require_supabase()
    db_url = settings.supabase_db_url or ""
    actual = target_of(url, db_url)
    if actual != "local":
        print(f"refused: M4 runs against a local stack only (configured destination: "
              f"{actual or 'SUPABASE_URL and SUPABASE_DB_URL disagree'})", file=sys.stderr)
        return 2
    try:
        with psycopg.connect(db_url, autocommit=True) as conn:
            store = PsycopgClaimStore(conn)
            extraction = extract_document_claims(store, str(args.document_pk))
            result = analyze_document(store, str(args.document_pk))
    except UnknownDocument:
        print(f"refused [unknown_document]: {args.document_pk}", file=sys.stderr)
        return 1
    except psycopg.Error as exc:
        print(f"refused [db {exc.sqlstate}]: {str(exc).splitlines()[0] if str(exc) else type(exc).__name__}",
              file=sys.stderr)
        return 1
    print(report(extraction, result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

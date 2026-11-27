"""Operator CLI of RAG V1.5 M7 E5.2: the impact of a re-pin on the AI-admissible corpus, BEFORE the owner re-pins
(docs/rag/RAG_V15_M7_E5_2_PIN_GENERATION.md §6).

    python backend/scripts/knowledge_repin_impact.py --target local [--rows]

READ-ONLY and LOCAL ONLY (owner decision D-ROLLOUT, 2026-11-20): a 127.0.0.1/localhost stack, one read-only
transaction, rolled back. It writes no claim, report, verification or status. It connects with SUPABASE_DB_URL
because the inventory function is owner-only (private review state of every tenant). The output names document ids
and counts only, never a title or any chunk text.

Under E5.2 EVERY pin change is a new generation, so a re-pin suspends every approval made before it, whatever the
claims. The offline columns say what a NEW VERSION reviewed under the new pin would face: its claim set compared with
the stored one (`claim_set_changed` / `claim_set_unchanged`) and whether the current review raises findings an expert
must disposition (`needs_expert_review`).

Local or synthetic data never measures production scale: the summary says which database it read.

Exit codes: 0 done, 1 refused by the database, 2 usage/target.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.ingest_knowledge import target_of  # noqa: E402

INVENTORY = ("select document_pk::text, source_id, document_status, approval_assurance, source_status, source_assurance,"
             " visibility, current_generation, report_id::text, report_extractor_version, report_generation,"
             " verified_in_generation, approved_in_generation, open_blocking_findings, admission_problem"
             " from private.knowledge_corpus_integrity_inventory()")
COLUMNS = ("document_pk", "source_id", "document_status", "approval_assurance", "source_status", "source_assurance",
           "visibility", "current_generation", "report_id", "report_extractor_version", "report_generation",
           "verified_in_generation", "approved_in_generation", "open_blocking_findings", "admission_problem")

#: Categories (a version can carry several).
CATEGORIES = ("current_under_existing_pin", "will_become_stale", "not_current_now", "claim_set_unchanged",
              "claim_set_changed", "missing_evidence", "missing_verifier", "needs_expert_review", "demo_only",
              "inaccessible_or_blocked", "in_review")

_MISSING_EVIDENCE = {"no_report", "generation_missing", "report_not_under_current_pin", "report_from_earlier_generation",
                     "report_stale", "approval_not_bound_to_report", "approval_from_earlier_generation"}
_MISSING_VERIFIER = {"not_verified_under_current_pin", "verification_mismatch"}
_IN_REVIEW = {"review_required", "expert_review"}


def _offline(cur: Any, document_pk: str, stored_version: str | None, registry: Any) -> dict[str, Any]:
    """What the CURRENT code would extract and flag for this version's stored chunks (no write)."""
    from infrastructure.knowledge_claims_repo import PsycopgClaimStore
    from knowledge.integrity.claims import extract_claims
    from knowledge.integrity.review import review

    store = PsycopgClaimStore(getattr(cur, "connection", cur))
    sources = store.chunk_sources(document_pk)
    now = {c.claim_id for s in sources for c in extract_claims(s)}
    cur.execute("select claim_id from public.knowledge_claims where document_pk = %s and extractor_version = %s",
                (document_pk, stored_version))
    stored = {r[0] for r in cur.fetchall()}
    flagged = (any(f.needs_expert_review for f in review(sources, registry=registry, as_of=date.today()).findings)
               if registry is not None else None)
    return {"claims_changed": now != stored, "claims_added": len(now - stored), "claims_removed": len(stored - now),
            "needs_expert_review": flagged}


def classify(row: Mapping[str, Any], offline: Mapping[str, Any] | None) -> list[str]:
    cats: list[str] = []
    status, assurance = row["document_status"], row["approval_assurance"]
    if assurance == "demo_unverified":
        return ["demo_only"]
    if status in _IN_REVIEW:
        return ["in_review"]
    if status != "approved" or row["source_status"] != "approved" or row["source_assurance"] != "verified" \
            or assurance != "verified":
        return ["inaccessible_or_blocked"]
    problem = row["admission_problem"]                    # approved + verified: null means admitted now
    if problem is None:
        cats += ["current_under_existing_pin", "will_become_stale"]        # any re-pin is a new generation
    else:
        cats.append("not_current_now")
        if problem in _MISSING_EVIDENCE:
            cats.append("missing_evidence")
        if problem in _MISSING_VERIFIER or row["verified_in_generation"] is None:
            cats.append("missing_verifier")
    if offline is not None:
        cats.append("claim_set_changed" if offline["claims_changed"] else "claim_set_unchanged")
        if offline["needs_expert_review"]:
            cats.append("needs_expert_review")
    return cats


def assess(cur: Any, *, registry: Any = None, database: str = "local") -> dict[str, Any]:
    """The impact report over every document version. `cur` is an OWNER cursor; nothing is written."""
    cur.execute(INVENTORY)
    rows = [dict(zip(COLUMNS, r)) for r in cur.fetchall()]
    out_rows = []
    for row in rows:
        offline = None
        if row["document_status"] == "approved" and row["approval_assurance"] == "verified" and row["report_id"]:
            offline = _offline(cur, row["document_pk"], row["report_extractor_version"], registry)
        out_rows.append({"document_pk": row["document_pk"], "source_id": row["source_id"],
                         "admission_problem": row["admission_problem"], "categories": classify(row, offline),
                         **({"offline": offline} if offline else {})})
    return {"summary": summarize(rows, out_rows, database), "rows": out_rows}


def summarize(rows: Iterable[Mapping[str, Any]], out_rows: list[Mapping[str, Any]], database: str) -> dict[str, Any]:
    rows = list(rows)
    count = Counter(c for r in out_rows for c in r["categories"])
    current = count["current_under_existing_pin"]
    generation = rows[0]["current_generation"] if rows else None
    return {
        "database": database,
        "scale_note": "local/synthetic data: not a production-scale estimate" if database != "production" else None,
        "current_generation": generation,
        "documents_total": len(rows),
        "approved_verified": sum(1 for r in rows if r["document_status"] == "approved"
                                 and r["approval_assurance"] == "verified"),
        **{c: count[c] for c in CATEGORIES},
        "admissible_after_any_re_pin": 0,
        "intent_impact": {
            "RECOMMEND": f"{current} admissible version(s) today -> 0 after a re-pin: answers fall back to"
                         " insufficient_evidence until new versions are reviewed (stored M05 rule outcomes stay)",
            "EVIDENCE (READ)": f"{current} -> 0 citable version(s): document questions answer 'no approved document'",
            "WHAT_IF": "Carbon Engine numbers unaffected; the answer loses its document citations",
            "EXPLAIN / COMPARE / DATA_GAP (READ)": "unaffected (built from crop-season data, no document needed)",
        },
    }


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Read-only re-pin impact assessment of the AI-admissible corpus.")
    ap.add_argument("--target", required=True, choices=["local"], help="E5.2 runs against a local stack only")
    ap.add_argument("--rows", action="store_true", help="also print one JSON line per document version (ids only)")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    import psycopg

    from infrastructure.config import load_settings
    from knowledge.integrity.references import load_registry

    registry_path = Path(__file__).resolve().parent.parent / "knowledge" / "integrity" / "reference_registry.json"

    settings = load_settings()
    url, _ = settings.require_supabase()
    db_url = settings.supabase_db_url or ""
    actual = target_of(url, db_url)
    if actual != "local":
        print(f"refused: the E5.2 impact assessment runs against a local stack only (configured destination: "
              f"{actual or 'SUPABASE_URL and SUPABASE_DB_URL disagree'})", file=sys.stderr)
        return 2
    try:
        with psycopg.connect(db_url) as conn, conn.cursor() as cur:
            cur.execute("set transaction read only")
            report = assess(cur, registry=load_registry(json.loads(registry_path.read_text(encoding="utf-8"))),
                            database="local")
            conn.rollback()
    except psycopg.Error as exc:
        print(f"refused [db {exc.sqlstate}]: {str(exc).splitlines()[0] if str(exc) else type(exc).__name__}",
              file=sys.stderr)
        return 1
    if args.rows:
        for row in report["rows"]:
            print(json.dumps(row, ensure_ascii=False))
    print(json.dumps(report["summary"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

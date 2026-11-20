"""Operator CLI of RAG V1.5 M7 E5.1: which approved versions are no longer integrity-current under the owner's pin,
and which of them the CURRENT extractor reads differently (docs/rag/RAG_V15_M7_E5_1_PIN_AWARE_ADMISSION.md §6).

    python backend/scripts/knowledge_pin_reextraction_inventory.py --target local

READ-ONLY and LOCAL ONLY (owner decision D-ROLLOUT, 2026-11-20): the destination must be a 127.0.0.1/localhost
stack and the session is a read-only transaction. It writes no claim, report, verification or status; it never
approves, quarantines or re-reviews anything. It connects with SUPABASE_DB_URL because the inventory function is
owner-only (it names private review state).

For every approved version: its latest report's extractor version and why it is not admissible now (or `current`).
For every verified version that is not current: the claim ids the current extractor (`CLAIM_EXTRACTOR_VERSION`)
extracts from the stored chunks, compared with the claim ids stored under the report's extractor version. Claim ids
do not depend on the extractor version, so the difference is exactly what a re-extraction would change:
`claims_changed` (a new version needs a fresh review with the new findings) or `claims_unchanged` (the new version
would carry the same claims; under D-E5-PIN it still needs a new version and review, see §6 decision E5.1-b).

Exit codes: 0 done, 1 refused by the database, 2 usage/target.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.ingest_knowledge import target_of  # noqa: E402

INVENTORY = ("select document_pk::text, source_id, document_id, document_version, approval_assurance,"
             " report_extractor_version, coalesce(admission_problem, 'current')"
             " from private.knowledge_integrity_admission_inventory()")


def classify(cur: Any, document_pks: Sequence[str]) -> list[dict[str, Any]]:
    """Offline impact of the current extractor on each version (no write): stored claim ids of the latest report's
    extractor version vs. the claim ids `extract_claims` yields now from the stored chunk text."""
    from infrastructure.knowledge_claims_repo import PsycopgClaimStore
    from knowledge.integrity.claims import CLAIM_EXTRACTOR_VERSION, extract_claims

    store = PsycopgClaimStore(getattr(cur, "connection", cur))
    out = []
    for pk in document_pks:
        cur.execute("select r.extractor_version from private.knowledge_integrity_current_report(%s) r"
                    " where r.id is not null", (pk,))
        row = cur.fetchone()
        stored_version = row[0] if row else None
        cur.execute("select claim_id, kind from public.knowledge_claims where document_pk = %s"
                    " and extractor_version = %s", (pk, stored_version))
        stored = dict(cur.fetchall())
        now = {c.claim_id: c.kind for s in store.chunk_sources(pk) for c in extract_claims(s)}
        added, removed = sorted(set(now) - set(stored)), sorted(set(stored) - set(now))
        out.append({"document_pk": pk, "stored_extractor_version": stored_version,
                    "current_extractor_version": CLAIM_EXTRACTOR_VERSION,
                    "impact": "claims_changed" if added or removed else "claims_unchanged",
                    "added": len(added), "removed": len(removed),
                    "added_assertions": sum(1 for c in added if now[c] == "assertion")})
    return out


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Read-only inventory of approved versions that are not integrity-current.")
    ap.add_argument("--target", required=True, choices=["local"], help="E5.1 runs against a local stack only")
    return ap


def main(argv: list[str] | None = None) -> int:
    build_parser().parse_args(argv)
    import psycopg

    from infrastructure.config import load_settings

    settings = load_settings()
    url, _ = settings.require_supabase()
    db_url = settings.supabase_db_url or ""
    actual = target_of(url, db_url)
    if actual != "local":
        print(f"refused: the E5.1 inventory runs against a local stack only (configured destination: "
              f"{actual or 'SUPABASE_URL and SUPABASE_DB_URL disagree'})", file=sys.stderr)
        return 2
    try:
        with psycopg.connect(db_url) as conn, conn.cursor() as cur:
            cur.execute("set transaction read only")
            cur.execute(INVENTORY)
            rows = cur.fetchall()
            stale = [r[0] for r in rows if r[4] == "verified" and r[6] != "current"]
            impact = {r["document_pk"]: r for r in classify(cur, stale)}
            conn.rollback()
    except psycopg.Error as exc:
        print(f"refused [db {exc.sqlstate}]: {str(exc).splitlines()[0] if str(exc) else type(exc).__name__}",
              file=sys.stderr)
        return 1
    for pk, source_id, document_id, version, assurance, report_version, state in rows:
        print(json.dumps({"document_pk": pk, "source_id": source_id, "document_id": document_id,
                          "document_version": version, "approval_assurance": assurance,
                          "report_extractor_version": report_version, "admission": state,
                          **({"impact": impact[pk]} if pk in impact else {})}, ensure_ascii=False))
    print(json.dumps({"approved": len(rows), "not_current": sum(1 for r in rows if r[6] != "current"),
                      "claims_changed": sum(1 for r in impact.values() if r["impact"] == "claims_changed")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

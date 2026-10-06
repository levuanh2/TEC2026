"""Operator CLI: ingest ONE knowledge document version (RAG V1.3-C).

    python backend/scripts/ingest_knowledge.py --file guide.md \\
        --source-id mard-awd --source-title "..." --source-owner "..." --source-type guideline \\
        --document-id awd-guide --document-version 2024-01 --title "..." --language vi --dry-run

    ... same arguments, without --dry-run, plus --target local | --target <hosted-project-ref>

--dry-run   parses, normalizes and chunks and prints hashes, pipeline versions, stable chunk
            ids and warnings. NO database, NO Storage call, no credentials needed.
write mode  stores the original bytes as a controlled artifact (private bucket, content
            addressed, SHA-256 verified -- ST1), then writes source + version + chunks in ONE
            transaction, all `review_required`. --target must name the destination: `local`
            for a 127.0.0.1/localhost stack, else the project ref of SUPABASE_URL/SUPABASE_DB_URL.
There is no approve flag: approval is a separate explicit operator action
(docs/rag/RAG_V1_INGESTION.md). One file per run; directories are refused. Credentials come
from the backend settings and are never printed.
Exit codes: 0 created / unchanged / dry run, 1 refused (conflict, parse, integrity), 2 usage/target.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from knowledge.ingest import MAX_FILE_BYTES, ingest, plan  # noqa: E402
from knowledge.models import DocumentSpec, KnowledgeIngestionError, SourceSpec  # noqa: E402

_LOCAL = {"127.0.0.1", "localhost"}


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Ingest ONE knowledge document version as review_required.")
    ap.add_argument("--file", required=True, help="one .md, .txt or text-layer .pdf file")
    ap.add_argument("--source-id", required=True)
    ap.add_argument("--source-title", required=True)
    ap.add_argument("--source-owner", required=True, help="publisher / owner")
    ap.add_argument("--source-type", required=True)
    ap.add_argument("--authority")
    ap.add_argument("--visibility", default="public", choices=("public", "tenant"))
    ap.add_argument("--organization-id")
    ap.add_argument("--farm-id")
    ap.add_argument("--document-id", required=True)
    ap.add_argument("--document-version", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--language", required=True)
    ap.add_argument("--official-url")
    ap.add_argument("--published-at", type=date.fromisoformat, help="YYYY-MM-DD")
    ap.add_argument("--license-basis", default="unknown")
    ap.add_argument("--license-reference")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="no database or Storage access")
    mode.add_argument("--target", help="`local` or the hosted project ref the settings point at")
    return ap


def target_of(supabase_url: str, db_url: str) -> str | None:
    """`local`, the project ref both URLs name exactly, or None when they disagree.
    The DB URL names a project only through its pooler user `postgres.<ref>` or its direct host
    `db.<ref>.supabase.co` -- never by a substring (a password may contain anything) -- and a
    pooler user is only accepted on a Supabase pooler host."""
    api = urlparse(supabase_url).hostname or ""
    db = urlparse(db_url)
    if api in _LOCAL and (db.hostname or "") in _LOCAL:
        return "local"
    if not api.endswith(".supabase.co") or api.count(".") != 2:
        return None
    ref = api.split(".")[0]
    host = db.hostname or ""
    pooler = db.username == f"postgres.{ref}" and (host == "pooler.supabase.com" or host.endswith(".pooler.supabase.com"))
    direct = db.username == "postgres" and host == f"db.{ref}.supabase.co"
    return ref if pooler or direct else None


def pinned_pypdf() -> str | None:
    """The pypdf version backend/constraints.txt pins (the tested extraction)."""
    pins = Path(__file__).resolve().parent.parent / "constraints.txt"
    for line in pins.read_text(encoding="utf-8").splitlines() if pins.is_file() else []:
        if line.lower().startswith("pypdf=="):
            return line.split("==", 1)[1].split()[0]
    return None


def environment_warnings(p) -> list[str]:
    if p.format != "pdf":
        return []
    running = p.parser_version.rsplit("pypdf-", 1)[-1]
    pin = pinned_pypdf()
    if pin and running != pin:
        return [f"pypdf {running} is not the pinned {pin}: run the dry run AND the write in the pinned backend "
                "environment, or chunk ids will differ"]
    return []


def _read(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise SystemExit(f"--file must be one regular file (not a directory or symlink): {path.name}")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise SystemExit(f"--file is larger than {MAX_FILE_BYTES} bytes")
    return path.read_bytes()


def summary(p, *, mode: str, target: str | None = None, result=None) -> str:
    d = p.document
    lines = [
        f"mode               {mode}" + (f" (target {target})" if target else ""),
        f"identity           {d.source_id}/{d.document_id}@{d.document_version}",
        f"format             {p.format} ({p.size_bytes} bytes)",
        f"file_sha256        {p.file_sha256}",
        f"normalized_sha256  {p.normalized_sha256}",
        f"parser_version     {p.parser_version}",
        f"normalizer_version {p.normalizer_version}",
        f"chunker_version    {p.chunker_version}",
        f"artifact name      {p.artifact_name}",
        f"chunks             {len(p.chunks)}",
    ]
    lines += [f"  {c.ordinal:>4}  {c.chunk_id}  {c.tokens:>4} tok  p{c.page_from or '-'}-{c.page_to or '-'}  "
              f"{c.section_path or '(no section)'}" for c in p.chunks]
    warnings = list(p.warnings) + environment_warnings(p)
    lines += [f"warning            {w}" for w in warnings] or ["warnings           none"]
    if result is not None:
        lines += [f"outcome            {result.outcome}", f"document status    {result.status}",
                  f"source status      {result.source_status}",
                  f"artifact           {result.artifact_ref} ({'stored now' if result.artifact_created else 'already stored'})"]
        lines += [f"note               {n}" for n in result.notes]
    if mode == "dry-run" or (result is not None and result.status == "review_required"):
        lines.append("approval           NOT approved -- review_required; approval is a separate operator action")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path = Path(args.file)
    data = _read(path)
    source = SourceSpec(args.source_id, args.source_title, args.source_owner, args.source_type, args.authority,
                        args.visibility, args.organization_id, args.farm_id)
    document = DocumentSpec(args.source_id, args.document_id, args.document_version, args.title, args.language,
                            args.official_url, args.published_at, args.license_basis, args.license_reference)
    try:
        p = plan(data=data, filename=path.name, source=source, document=document)
    except KnowledgeIngestionError as exc:
        print(f"refused [{exc.code}]: {exc}", file=sys.stderr)
        return 1
    if args.dry_run:
        print(summary(p, mode="dry-run"))
        return 0

    import psycopg
    from supabase import create_client

    from infrastructure.config import load_settings
    from infrastructure.knowledge_repo import PsycopgKnowledgeStore, SupabaseArtifactStore

    settings = load_settings()
    url, service_key = settings.require_supabase()
    db_url = settings.supabase_db_url or ""
    actual = target_of(url, db_url)
    if actual is None or actual != args.target:
        print(f"refused: --target {args.target!r} does not match the configured destination "
              f"({actual or 'SUPABASE_URL and SUPABASE_DB_URL disagree'})", file=sys.stderr)
        return 2
    try:
        with psycopg.connect(db_url, autocommit=True) as conn:
            result = ingest(p, data=data, store=PsycopgKnowledgeStore(conn),
                            artifacts=SupabaseArtifactStore(create_client(url, service_key)))
    except KnowledgeIngestionError as exc:
        print(f"refused [{exc.code}]: {exc}", file=sys.stderr)
        for note in getattr(exc, "__notes__", []):
            print(f"note: {note}", file=sys.stderr)
        return 1
    except psycopg.Error as exc:   # e.g. a Migration A trigger refusing the write: nothing committed
        print(f"refused [db {exc.sqlstate}]: {str(exc).splitlines()[0] if str(exc) else type(exc).__name__}",
              file=sys.stderr)
        for note in getattr(exc, "__notes__", []):
            print(f"note: {note}", file=sys.stderr)
        return 1
    print(summary(p, mode="write", target=actual, result=result))
    return 0


if __name__ == "__main__":
    sys.exit(main())

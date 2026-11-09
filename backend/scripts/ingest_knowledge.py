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
--integrity-review --as-of YYYY-MM-DD   (dry run only)
            also prints the OFFLINE source-integrity review aid (knowledge/integrity) for the
            planned chunks against the versioned reference registry: findings for a human
            expert, never a decision. It writes nothing, calls no provider and does not change
            the exit code. Provenance is reported as not_evaluated (this CLI has no publisher
            allowlist or independent evidence). docs/rag/RAG_V15_SOURCE_INTEGRITY_OFFLINE.md.
There is no approve flag: approval is a separate explicit operator action
(docs/rag/RAG_V1_INGESTION.md). One file per run; directories are refused. Credentials come
from the backend settings and are never printed.
Exit codes: 0 created / unchanged / dry run, 1 refused (conflict, parse, integrity, malformed
reference registry), 2 usage/target.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from knowledge.ingest import MAX_FILE_BYTES, ingest, plan  # noqa: E402
from knowledge.models import DocumentSpec, KnowledgeIngestionError, SourceSpec  # noqa: E402

_LOCAL = {"127.0.0.1", "localhost"}
REGISTRY_FILE = Path(__file__).resolve().parent.parent / "knowledge" / "integrity" / "reference_registry.json"
_EXCERPT_CHARS = 80


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
    ap.add_argument("--integrity-review", action="store_true",
                    help="dry run only: also print the offline source-integrity review aid (no decision)")
    ap.add_argument("--as-of", type=_iso_day, metavar="YYYY-MM-DD",
                    help="evaluation date of --integrity-review (required with it; never defaulted to today)")
    return ap


def _iso_day(value: str) -> date:
    """Strictly YYYY-MM-DD (date.fromisoformat alone also takes 20261109 and 2026-W45-1)."""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise argparse.ArgumentTypeError(f"{value!r} is not YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a calendar date") from None


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = build_parser()
    args = ap.parse_args(argv)
    if args.integrity_review and not args.dry_run:
        ap.error("--integrity-review is only valid with --dry-run")
    if args.integrity_review and args.as_of is None:
        ap.error("--integrity-review needs an explicit --as-of YYYY-MM-DD (the report records its evaluation date)")
    if args.as_of is not None and not args.integrity_review:
        ap.error("--as-of is only used by --integrity-review")
    return args


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


def section_labels(p) -> dict[str, str]:
    """How each chunk's section is printed. Public documents print the heading path as before.
    A tenant document's headings are tenant-private text (a farm, a household, a plot), so they
    are replaced by their position among the document's distinct sections. No hash: short
    headings are easy to guess from one. Only the printout changes; the plan, chunk ids and
    hashes are untouched."""
    paths = list(dict.fromkeys(c.section_path for c in p.chunks if c.section_path))
    if p.source.visibility == "public":
        return {s: s for s in paths}
    return {s: f"(section {i} of {len(paths)}, heading withheld: tenant document)" for i, s in enumerate(paths, 1)}


def summary(p, *, mode: str, target: str | None = None, result=None) -> str:
    d = p.document
    shown = section_labels(p)
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
              f"{shown[c.section_path] if c.section_path else '(no section)'}" for c in p.chunks]
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


class RegistryLoadError(Exception):
    """The reference registry could not be read or validated: the review is refused, never skipped."""


def load_reference_registry(path: Path | None = None):
    """The versioned production registry. Any defect fails closed (synthetic entries are refused)."""
    from knowledge.integrity.references import RegistryError, load_registry

    path = path or REGISTRY_FILE
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return load_registry(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RegistryError) as exc:
        raise RegistryLoadError(f"{path.name}: {exc}") from None


def claim_sources(p) -> list:
    """One ClaimSource per planned chunk, addressed by the plan's identity and stable chunk ids."""
    from knowledge.integrity.claims import ClaimSource

    d = p.document
    ref = f"{d.source_id}/{d.document_id}@{d.document_version}"
    return [ClaimSource(ref, c.chunk_id, c.content) for c in p.chunks]


def _shown(path: Path) -> str:
    backend = Path(__file__).resolve().parent.parent
    try:
        return path.resolve().relative_to(backend).as_posix()
    except ValueError:
        return path.name


def _excerpt(claim, show: bool) -> str:
    if not show:
        return "(excerpt withheld: tenant document)"
    text = " ".join(claim.text.split())
    return repr(text if len(text) <= _EXCERPT_CHARS else text[:_EXCERPT_CHARS - 1] + "…")


_LIMITATIONS = (
    "content_correctness is not assessed: a document with no detected conflicts can still be false",
    "assertions: a short fixed list of two absolute statements; any other false statement yields no claim",
    "numbers: compared only with a registry entry; the production registry holds no numeric entry, so a "
    "wrong number with no second source is at most an informational unreferenced_claim",
    "this run reviews ONE document version: contradictions with other documents are not checked; only "
    "chunks of this version are compared with each other",
    "registry entries are project pointers/policy, not independently verified primary sources",
    "conditional statements and quotations made to refute a claim can be flagged (false positives)",
    "dev3-01 remains OPEN: nothing here blocks retrieval or changes a knowledge status",
)


def integrity_report(p, *, registry, as_of: date) -> str:
    """The offline review aid for one plan. Prints identifiers, spans and short excerpts only:
    never a whole chunk, and no excerpt at all for a tenant document."""
    from knowledge.integrity.review import review

    result = review(claim_sources(p), registry=registry, as_of=as_of)
    by_id = {c.claim_id: c for c in result.claims}
    refs = {e.reference_id: e for e in registry.entries}
    show = p.source.visibility == "public"
    kinds = Counter(c.kind for c in result.claims)
    statuses = Counter(c.status for c in result.claims)
    types = Counter(f.finding_type for f in result.findings)
    needs = [f for f in result.findings if f.needs_expert_review]

    def counts(counter: Counter) -> str:
        return ", ".join(f"{k} {v}" for k, v in sorted(counter.items())) or "none"

    lines = [
        "",
        "== integrity review (offline review aid: findings for a human expert, NOT an approval) ==",
        f"review_version     {result.review_version}",
        f"claim_extractor    {result.extractor_version}",
        f"registry_version   {result.registry_version}",
        f"registry_digest    {result.registry_digest}",
        f"registry_file      {_shown(REGISTRY_FILE)} ({len(registry.entries)} entries)",
        f"as_of              {result.as_of}",
        "provenance         not_evaluated -- this CLI has no publisher allowlist, independent evidence or "
        "evidence files; --source-owner / --official-url are operator assertions, not verified authenticity",
        "validity_periods   not_evaluated -- no effective-period context is supplied; dates in the text are "
        "listed as claims, not applied",
        f"claims             {len(result.claims)} (kind: {counts(kinds)}; status: {counts(statuses)})",
        f"findings           {len(result.findings)} (needs_expert_review {len(needs)}; {counts(types)})",
    ]
    for e in registry.entries:
        used = sum(e.reference_id in f.reference_ids for f in result.findings)
        lines.append(f"reference          {e.reference_id}  verification {e.verification_status}  "
                     f"independently_verified {'yes' if e.independently_verified else 'no'}  findings {used}")
    for n, f in enumerate(result.findings, 1):
        claims = [by_id[i] for i in f.claim_ids]
        lines.append(f"finding {n:<10} {f.finding_type}  "
                     f"{'NEEDS EXPERT REVIEW' if f.needs_expert_review else 'informational'}")
        lines.append(f"  chunks           {', '.join(dict.fromkeys(c.chunk_id for c in claims)) or '-'}")
        lines += [f"  claim            {c.claim_id}  chunk {c.chunk_id} [{c.start}:{c.end}]  {c.kind}"
                  f"{'/' + c.parameter if c.parameter else ''}  {_excerpt(c, show)}" for c in claims]
        lines += [f"  reference        {r}  ({refs[r].verification_status}; independently verified: "
                  f"{'yes' if refs[r].independently_verified else 'no'})" for r in f.reference_ids]
        if f.finding_type == "unresolved_claim" and claims:      # review's detail quotes the span
            detail = f"{claims[0].status}: {claims[0].note or 'no comparison possible'}"
        elif not show and f.finding_type in ("claim_conflict", "reference_conflict") \
                and any(c.kind == "quantity" for c in claims):      # its detail prints values from the text
            detail = f"{claims[0].parameter}: values withheld (tenant document); read the spans above locally"
        else:
            detail = f.detail
        lines += [f"  detail           {detail}", f"  evidence_needed  {f.evidence_needed}"]
    if needs:
        lines.append(f"result             {len(needs)} finding(s) need expert review (this report makes no "
                     "decision; approval stays a separate operator action)")
    elif result.findings:
        lines.append(f"result             no detected conflicts ({len(result.findings)} informational finding(s) "
                     "above; not safe, not verified, not approved)")
    else:
        lines.append("result             no detected conflicts (not safe, not verified, not approved: these "
                     "deterministic checks produced no finding)")
    lines += [f"limitation         {text}" for text in _LIMITATIONS]
    lines += ["provenance = not_evaluated", "content_correctness = not_assessed", f"decision = {result.decision}"]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    path = Path(args.file)
    data = _read(path)
    registry = None
    if args.integrity_review:
        try:
            registry = load_reference_registry()
        except RegistryLoadError as exc:
            print(f"refused [registry_invalid]: {exc}", file=sys.stderr)
            return 1
    source = SourceSpec(args.source_id, args.source_title, args.source_owner, args.source_type, args.authority,
                        args.visibility, args.organization_id, args.farm_id)
    document = DocumentSpec(args.source_id, args.document_id, args.document_version, args.title, args.language,
                            args.official_url, args.published_at, args.license_basis, args.license_reference)
    from infrastructure.pdf_isolation import parse_pdf_isolated

    try:
        p = plan(data=data, filename=path.name, source=source, document=document, pdf_parser=parse_pdf_isolated)
    except KnowledgeIngestionError as exc:
        print(f"refused [{exc.code}]: {exc}", file=sys.stderr)
        return 1
    if args.dry_run:
        print(summary(p, mode="dry-run"))
        if registry is not None:
            print(integrity_report(p, registry=registry, as_of=args.as_of))
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

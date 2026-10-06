"""Value objects, errors and metadata validation of the ingestion pipeline.

Validation mirrors Migration A's CHECK constraints so an operator mistake fails before any
artifact upload or database write; the database still enforces every rule itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Literal

BlockKind = Literal["heading", "paragraph", "list", "table", "code"]

SOURCE_TYPES = frozenset({"guideline", "policy", "methodology", "research", "tenant_document"})
AUTHORITIES = frozenset({"official", "peer_reviewed", "extension", "internal"})
LICENSE_BASES = frozenset({"unknown", "official_publication", "public_domain", "open_license",
                           "written_permission", "tenant_owned"})
LICENSE_NEEDS_REFERENCE = frozenset({"open_license", "written_permission"})

_SOURCE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
_DOCUMENT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,127}$")
# Stricter than the database (non-blank): a version is part of citation identity and of
# the CLI summary, so it stays a short printable token.
_DOCUMENT_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_LANGUAGE = re.compile(r"^[a-z]{2}$")
_URL = re.compile(r"^https://\S+$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


# ------------------------------------------------------------------------------ errors

class KnowledgeIngestionError(Exception):
    """Base error; `code` is a stable machine-readable reason."""

    code = "ingestion_error"

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        if code:
            self.code = code


class MetadataError(KnowledgeIngestionError):
    code = "invalid_metadata"


class UnsupportedFormatError(KnowledgeIngestionError):
    code = "unsupported_format"


class ParseError(KnowledgeIngestionError):
    """The artifact cannot be parsed into text (malformed, encrypted, no text layer, ...)."""

    code = "parse_failed"


class IngestionConflict(KnowledgeIngestionError):
    """The declared identity already exists with different immutable provenance: fail closed."""

    code = "conflict"


class ArtifactIntegrityError(KnowledgeIngestionError):
    code = "artifact_integrity"


class StorageError(KnowledgeIngestionError):
    """Storage answered with something other than "not found" (auth, timeout, server error)."""

    code = "storage_error"


# Fail-fast structural bound shared by the parsers: a < 50 MiB file can still hold millions of
# one-line blocks; parsing stops as soon as this many blocks exist.
MAX_BLOCKS = 100_000


def check_block_count(count: int) -> None:
    if count > MAX_BLOCKS:
        raise ParseError(f"more than {MAX_BLOCKS} structural blocks: split the artifact", code="too_many_blocks")


# ------------------------------------------------------------------------------ pipeline values

@dataclass(frozen=True)
class Block:
    """One structural unit of a parsed artifact, in source order."""

    kind: BlockKind
    text: str
    level: int = 0                      # heading depth (1 = top); 0 for non-headings
    page: int | None = None             # 1-based PDF page; None for Markdown/text
    flags: tuple[str, ...] = ()         # e.g. "table_uncertain", "page_first", "page_last"


@dataclass(frozen=True)
class ParsedDocument:
    format: str                          # "markdown" | "text" | "pdf"
    parser_version: str
    blocks: tuple[Block, ...]
    page_count: int | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class NormalizedDocument:
    normalizer_version: str
    blocks: tuple[Block, ...]
    text: str                            # canonical normalized text (hashed)
    sha256: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    ordinal: int                         # position in the document version (0-based)
    ordinal_in_section: int
    section_path: str | None
    content: str
    content_sha256: str
    page_from: int | None
    page_to: int | None
    tokens: int
    metadata: dict = field(default_factory=dict)


# ------------------------------------------------------------------------------ declared metadata

@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    title: str
    owner: str
    source_type: str
    authority: str | None = None
    visibility: str = "public"
    organization_id: str | None = None
    farm_id: str | None = None


@dataclass(frozen=True)
class DocumentSpec:
    source_id: str
    document_id: str
    document_version: str
    title: str
    language: str
    official_url: str | None = None
    published_at: date | None = None
    license_basis: str = "unknown"
    license_reference: str | None = None


def _blank(value: str | None) -> bool:
    return value is None or not value.strip()


def validate_source(spec: SourceSpec) -> None:
    if not _SOURCE_ID.match(spec.source_id):
        raise MetadataError(f"source_id {spec.source_id!r} must match {_SOURCE_ID.pattern}")
    if _blank(spec.title) or _blank(spec.owner):
        raise MetadataError("source title and owner are required")
    if spec.source_type not in SOURCE_TYPES:
        raise MetadataError(f"source_type must be one of {sorted(SOURCE_TYPES)}")
    if spec.authority is not None and spec.authority not in AUTHORITIES:
        raise MetadataError(f"authority must be one of {sorted(AUTHORITIES)} or omitted")
    for name in ("organization_id", "farm_id"):
        value = getattr(spec, name)
        if value is not None and not _UUID.match(value):
            raise MetadataError(f"{name} must be a lowercase UUID")
    if spec.visibility == "public":
        if spec.organization_id or spec.farm_id:
            raise MetadataError("a public source names no organization or farm")
    elif spec.visibility == "tenant":
        if not spec.organization_id:
            raise MetadataError("a tenant source needs an organization_id")
    else:
        raise MetadataError("visibility must be 'public' or 'tenant'")


def validate_document(spec: DocumentSpec) -> list[str]:
    """Raises MetadataError on anything the database would refuse; returns warnings for
    gaps that do not block ingestion but will block a later approval."""
    if not _SOURCE_ID.match(spec.source_id):
        raise MetadataError(f"source_id {spec.source_id!r} must match {_SOURCE_ID.pattern}")
    if not _DOCUMENT_ID.match(spec.document_id):
        raise MetadataError(f"document_id {spec.document_id!r} must match {_DOCUMENT_ID.pattern}")
    if not _DOCUMENT_VERSION.match(spec.document_version):
        raise MetadataError(f"document_version {spec.document_version!r} must match {_DOCUMENT_VERSION.pattern}")
    if _blank(spec.title):
        raise MetadataError("document title is required")
    if not _LANGUAGE.match(spec.language):
        raise MetadataError("language must be a two-letter lowercase code (e.g. vi, en)")
    if spec.official_url is not None and not _URL.match(spec.official_url):
        raise MetadataError("official_url must be an https:// URL without spaces")
    if spec.license_basis not in LICENSE_BASES:
        raise MetadataError(f"license_basis must be one of {sorted(LICENSE_BASES)}")
    warnings = []
    if spec.license_basis == "unknown":
        warnings.append("license_basis is 'unknown': this version cannot be approved until it is known")
    if spec.license_basis in LICENSE_NEEDS_REFERENCE and _blank(spec.license_reference):
        warnings.append(f"license_basis {spec.license_basis!r} needs a license_reference before approval")
    return warnings


@dataclass(frozen=True)
class IngestionPlan:
    """Everything a write would persist, computed without any I/O (also the dry-run report)."""

    source: SourceSpec
    document: DocumentSpec
    format: str
    size_bytes: int
    file_sha256: str
    normalized_sha256: str
    parser_version: str
    normalizer_version: str
    chunker_version: str
    artifact_name: str
    content_type: str
    chunks: tuple[Chunk, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class StoredSource:
    source_id: str
    title: str
    owner: str
    source_type: str
    authority: str | None
    visibility: str
    organization_id: str | None
    farm_id: str | None
    status: str


@dataclass(frozen=True)
class StoredDocument:
    source_id: str
    document_id: str
    document_version: str
    title: str
    language: str
    official_url: str | None
    artifact_ref: str | None
    file_sha256: str
    normalized_sha256: str
    published_at: date | None
    parser_version: str
    normalizer_version: str
    chunker_version: str
    license_basis: str
    license_reference: str | None
    status: str
    chunks: tuple[tuple[str, str], ...]   # (chunk_id, content_sha256) in ordinal order


@dataclass(frozen=True)
class IngestionResult:
    outcome: Literal["created", "unchanged"]
    status: str                            # the stored document version's status
    artifact_ref: str | None
    artifact_created: bool
    source_status: str | None = None
    notes: tuple[str, ...] = ()

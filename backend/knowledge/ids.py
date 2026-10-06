"""Stable identities: content hashes, chunk ids, artifact object keys.

chunk_id (ADR §4.5) = sha256(source_id | document_id | document_version | section_path |
ordinal_in_section | content_sha256)[:20]. Unchanged input re-ingests to identical ids; a
new document_version always yields new ids. Storage row ids are never citation identity.

Artifacts are content-addressed (ST1): the object key is `<sha256>/<safe-name>`; the name
is only a human hint and never identity.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\.[a-z0-9]+$")
_MAX_NAME = 100


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def chunk_id(*, source_id: str, document_id: str, document_version: str, section_path: str | None,
             ordinal_in_section: int, content_sha256: str) -> str:
    parts = (source_id, document_id, document_version, section_path or "", str(ordinal_in_section), content_sha256)
    return sha256_hex("|".join(parts))[:20]


def safe_artifact_name(filename: str, extension: str) -> str:
    """A storage-safe display name: the basename only (no directory, no traversal), ASCII
    letters/digits/`._-`, no leading dot, bounded length, the canonical lowercase extension."""
    base = re.split(r"[\\/]", filename)[-1]
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode("ascii")
    stem = base[: -len(extension)] if base.lower().endswith(extension) else base.rsplit(".", 1)[0]
    stem = _UNSAFE.sub("-", stem).strip(".-_")
    stem = re.sub(r"\.{2,}", ".", stem)[: _MAX_NAME - len(extension)].strip(".-_")
    return f"{stem or 'artifact'}{extension}"


def artifact_key(file_sha256: str, name: str) -> str:
    if not _HEX64.match(file_sha256):
        raise ValueError("artifact key needs a lowercase hex SHA-256")
    if not _SAFE_NAME.match(name) or ".." in name or len(name) > _MAX_NAME:
        raise ValueError("artifact name must already be safe (see safe_artifact_name)")
    return f"{file_sha256}/{name}"

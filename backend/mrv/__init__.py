"""Module 07 — MRV evidence package generation.

`manifest` owns the versioned JSON contract, its canonical serialization and its
checksum. It holds no I/O: the service layer gathers data through the existing
repositories and hands it in, so the contract stays testable without a database
and the export never grows its own second copy of a domain query or formula.
"""

from .manifest import (
    MANIFEST_SCHEMA_VERSION,
    ManifestInputs,
    build_manifest,
    canonical_bytes,
    export_filename,
    manifest_checksum,
)

__all__ = [
    "MANIFEST_SCHEMA_VERSION",
    "ManifestInputs",
    "build_manifest",
    "canonical_bytes",
    "export_filename",
    "manifest_checksum",
]

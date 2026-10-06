"""Ports the pure pipeline drives; adapters live in infrastructure/knowledge_repo.py.

Neither port has an approval operation: ingestion writes `review_required` rows only, and
approving (or archiving, or republishing) is a separate explicit operator action outside V1.3-C.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol

from knowledge.models import IngestionPlan, StoredDocument, StoredSource


class IdentityExists(Exception):
    """The (source_id, document_id, document_version) row appeared concurrently."""


class KnowledgeStore(Protocol):
    def find_source(self, source_id: str) -> StoredSource | None: ...

    def find_document(self, source_id: str, document_id: str, document_version: str) -> StoredDocument | None: ...

    def create_version(self, plan: IngestionPlan, artifact_ref: str) -> StoredSource:
        """ONE transaction: insert the source if absent (an existing one must match the plan
        exactly, else IngestionConflict), insert the document version `review_required`, insert
        every chunk. All or nothing; raises IdentityExists if the version already exists."""
        ...

    def artifact_in_use(self, artifact_ref: str) -> bool: ...

    def artifact_lock(self, file_sha256: str) -> AbstractContextManager:
        """Serialize every ingestion of the same bytes (content address) across processes, so
        a failed run's compensation can never delete an object a concurrent run is adopting."""
        ...


class ArtifactStore(Protocol):
    def put(self, file_sha256: str, name: str, data: bytes, content_type: str) -> tuple[str, bool]:
        """Store the exact bytes under their content address (never overwriting) and return
        (artifact_ref, created_now). An existing object for this SHA-256 is reused only after its
        bytes are re-hashed and match."""
        ...

    def verify(self, artifact_ref: str, file_sha256: str) -> None:
        """Raise ArtifactIntegrityError unless `artifact_ref` is this SHA-256's content address
        and its stored bytes re-hash to it."""
        ...

    def discard(self, artifact_ref: str) -> None:
        """Compensation only: remove an object THIS run created when its DB write failed."""
        ...

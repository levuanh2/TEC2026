"""Operator-side adapters of the knowledge ingestion pipeline (V1.3-C).

PsycopgKnowledgeStore -- the privileged OPERATOR path: a direct Postgres connection (the
table owner, like the factor importer), never a browser/user JWT and never reachable from an
API route. It inserts sources/versions/chunks and reads metadata; it NEVER writes `status`,
`approved_by`, `approved_at` or `review_note`, never updates or deletes a row, so every row it
creates is `review_required` by the column default and Migration A's triggers (chunks only on a
never-approved version, lifecycle, immutability) stay the authority. Client reads of knowledge
keep going through RLS (PostgREST / the lexical RPC) and are not touched here.

SupabaseArtifactStore -- ST1 controlled copies, reusing the MRV-export pattern: the PRIVATE
bucket `knowledge-artifacts` (no storage.objects policy => every client operation is denied;
the service role is the only reader/writer), uploads with upsert=false (never overwrite),
SHA-256 verified on every write and reuse, no signed or public URL anywhere. Content address:
`<sha256>/<safe-name>`; `artifact_ref` = `knowledge-artifacts/<sha256>/<safe-name>`.
"""

from __future__ import annotations

import json
from typing import Any

from knowledge.ids import artifact_key, sha256_hex
from knowledge.models import ArtifactIntegrityError, IngestionConflict, IngestionPlan, StoredDocument, StoredSource
from knowledge.ports import IdentityExists

ARTIFACT_BUCKET = "knowledge-artifacts"
_SOURCE_COLUMNS = "source_id, title, owner, source_type, authority, visibility, organization_id::text, farm_id::text, status::text"
_DOCUMENT_COLUMNS = ("id, source_id, document_id, document_version, title, language, official_url, artifact_ref, "
                     "file_sha256, normalized_sha256, published_at, parser_version, normalizer_version, chunker_version, "
                     "license_basis::text, license_reference, status::text")


def _source(row) -> StoredSource:
    return StoredSource(*row)


class PsycopgKnowledgeStore:
    """`conn` is a psycopg 3 connection owned by the caller. Each write is one
    `conn.transaction()`: BEGIN/COMMIT on an autocommit connection (the CLI), a SAVEPOINT
    inside a caller's transaction (the DB tests, which roll everything back)."""

    def __init__(self, conn: Any):
        self._conn = conn

    def find_source(self, source_id: str) -> StoredSource | None:
        with self._conn.cursor() as cur:
            cur.execute(f"select {_SOURCE_COLUMNS} from public.knowledge_sources where source_id = %s", (source_id,))
            row = cur.fetchone()
        return _source(row) if row else None

    def find_document(self, source_id: str, document_id: str, document_version: str) -> StoredDocument | None:
        with self._conn.cursor() as cur:
            cur.execute(f"select {_DOCUMENT_COLUMNS} from public.knowledge_documents"
                        " where source_id = %s and document_id = %s and document_version = %s",
                        (source_id, document_id, document_version))
            row = cur.fetchone()
            if not row:
                return None
            cur.execute("select chunk_id, content_sha256 from public.knowledge_chunks where document_pk = %s"
                        " order by ordinal", (row[0],))
            chunks = tuple((c, h) for c, h in cur.fetchall())
        return StoredDocument(*row[1:], chunks=chunks)

    def artifact_in_use(self, artifact_ref: str) -> bool:
        with self._conn.cursor() as cur:
            cur.execute("select exists (select 1 from public.knowledge_documents where artifact_ref = %s)", (artifact_ref,))
            return bool(cur.fetchone()[0])

    def create_version(self, plan: IngestionPlan, artifact_ref: str) -> StoredSource:
        import psycopg

        s, d = plan.source, plan.document
        try:
            with self._conn.transaction(), self._conn.cursor() as cur:
                cur.execute(
                    "insert into public.knowledge_sources (source_id, title, owner, source_type, authority, visibility,"
                    " organization_id, farm_id) values (%s, %s, %s, %s, %s, %s, %s, %s) on conflict (source_id) do nothing",
                    (s.source_id, s.title, s.owner, s.source_type, s.authority, s.visibility, s.organization_id, s.farm_id))
                # Re-read under a lock: a source created concurrently must still match exactly.
                cur.execute(f"select {_SOURCE_COLUMNS} from public.knowledge_sources where source_id = %s for share",
                            (s.source_id,))
                source = _source(cur.fetchone())
                diffs = [f for f in ("title", "owner", "source_type", "authority", "visibility", "organization_id", "farm_id")
                         if getattr(source, f) != getattr(s, f)]
                if diffs:
                    raise IngestionConflict(f"source {s.source_id} exists with different {', '.join(diffs)}",
                                            code="source_mismatch")
                cur.execute(
                    "insert into public.knowledge_documents (source_id, document_id, document_version, title, language,"
                    " official_url, artifact_ref, file_sha256, normalized_sha256, published_at, parser_version,"
                    " normalizer_version, chunker_version, license_basis, license_reference)"
                    " values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id",
                    (d.source_id, d.document_id, d.document_version, d.title, d.language, d.official_url, artifact_ref,
                     plan.file_sha256, plan.normalized_sha256, d.published_at, plan.parser_version,
                     plan.normalizer_version, plan.chunker_version, d.license_basis, d.license_reference))
                document_pk = cur.fetchone()[0]
                cur.executemany(
                    "insert into public.knowledge_chunks (document_pk, chunk_id, ordinal, section_path, page_from, page_to,"
                    " content, content_sha256, metadata) values (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    [(document_pk, c.chunk_id, c.ordinal, c.section_path, c.page_from, c.page_to, c.content,
                      c.content_sha256, json.dumps(c.metadata, sort_keys=True)) for c in plan.chunks])
        except psycopg.errors.UniqueViolation as exc:
            if exc.diag.constraint_name == "knowledge_documents_identity_key":
                raise IdentityExists(str(exc.diag.constraint_name)) from exc
            raise
        return source


class SupabaseArtifactStore:
    def __init__(self, client: Any):
        self._bucket = client.storage.from_(ARTIFACT_BUCKET)

    def _download(self, key: str) -> bytes | None:
        try:
            data = self._bucket.download(key)
        except Exception:  # noqa: BLE001 -- the Storage client raises on a missing object
            return None
        return data or None

    def _existing_key(self, file_sha256: str) -> str | None:
        try:
            items = self._bucket.list(file_sha256)
        except Exception:  # noqa: BLE001
            return None
        names = sorted(i["name"] for i in items or [] if i.get("name") and i.get("id"))
        return f"{file_sha256}/{names[0]}" if names else None

    def _verified(self, key: str, file_sha256: str) -> bool:
        data = self._download(key)
        if data is None:
            return False
        if sha256_hex(data) != file_sha256:
            raise ArtifactIntegrityError(f"stored object {ARTIFACT_BUCKET}/{key} does not hash to {file_sha256}")
        return True

    def put(self, file_sha256: str, name: str, data: bytes, content_type: str) -> tuple[str, bool]:
        if sha256_hex(data) != file_sha256:
            raise ArtifactIntegrityError("artifact bytes do not match the declared SHA-256")
        existing = self._existing_key(file_sha256)
        if existing and self._verified(existing, file_sha256):
            return f"{ARTIFACT_BUCKET}/{existing}", False
        key = artifact_key(file_sha256, name)
        try:
            self._bucket.upload(key, data, {"content-type": content_type, "upsert": "false"})
            created = True
        except Exception as exc:  # noqa: BLE001 -- a concurrent upload of the same bytes is fine if it verifies
            if not self._verified(key, file_sha256):
                raise ArtifactIntegrityError(f"artifact upload failed ({type(exc).__name__})") from exc
            created = False
        if not self._verified(key, file_sha256):           # read-back: the reference must resolve to these bytes
            raise ArtifactIntegrityError(f"stored object {ARTIFACT_BUCKET}/{key} could not be read back")
        return f"{ARTIFACT_BUCKET}/{key}", created

    def discard(self, artifact_ref: str) -> None:
        prefix = f"{ARTIFACT_BUCKET}/"
        if not artifact_ref.startswith(prefix):
            raise ValueError("not a knowledge artifact reference")
        self._bucket.remove([artifact_ref[len(prefix):]])

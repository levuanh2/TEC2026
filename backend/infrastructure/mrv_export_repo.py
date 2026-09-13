"""Persistence for generated MRV export snapshots.

The snapshot is the point of the feature: once an export exists, downloading it
must return the bytes that were generated, not a fresh rebuild from data that
may have moved since. So the manifest is stored verbatim in
`mrv_exports.export_payload` and the download path only ever reads it back.

Writes use the backend's own database role, like every other write repository
here (`write_repo`, the recommendation and CV repositories): `authenticated` has
no INSERT grant on `mrv_exports` by design. Authorization happens before this
layer is reached, through an RLS-bound read of the case; this repository never
accepts an actor, organization or role from an HTTP payload.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from . import pg_pool
from .config import Settings

EXPORTS_BUCKET = "mrv-exports"


class MrvExportNotFoundError(Exception):
    pass


class MrvArtifactMissingError(Exception):
    """Metadata exists but the stored object does not.

    Deliberately its own error: the correct answer is a controlled failure, never
    a silent regeneration from live data -- that would hand back something that
    is not the snapshot the row promises.
    """


class MrvArtifactCorruptError(Exception):
    """Stored bytes do not match the recorded digest. Fail closed."""


_COLUMNS = (
    "id::text, mrv_case_id::text, format::text, factor_set_id::text, scope_description, "
    "data_as_of_at, contains_sample_data, is_finalized, warning_text, storage_bucket, "
    "storage_object_path, file_sha256, payload_sha256, "
    "source_snapshot_export_id::text, generated_by::text, generated_at"
)


class PostgresMrvExportRepository:
    def __init__(self, settings: Settings, connect: Any | None = None,
                 storage_client: Any | None = None):
        self._settings = settings
        self._connect = connect
        self._storage_client = storage_client

    def _connection(self):
        if self._connect is not None:
            return self._connect()
        return pg_pool.connection(self._settings.require_db())

    def create(
        self,
        *,
        export_id: str,
        mrv_case_id: str,
        organization_id: str,
        fmt: str,
        factor_set_id: str | None,
        scope_description: str,
        data_as_of_at: datetime,
        warning_text: str,
        storage_object_path: str,
        file_sha256: str,
        payload: dict[str, Any],
        generated_by: str,
        generated_at: datetime,
        calculation_ids: list[str],
        payload_sha256: str | None = None,
        source_snapshot_export_id: str | None = None,
    ) -> dict[str, Any]:
        """One transaction: the snapshot row and the calculations it covers.

        `is_finalized` stays false and `contains_sample_data` false, which is why
        `warning_text` is required by `mrv_export_warning_chk` -- a JSON data
        package is not a finalized report and the schema is what enforces saying
        so.
        """
        del organization_id  # part of the path, validated by a DB trigger
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""insert into public.mrv_exports
                      (id, mrv_case_id, format, factor_set_id, scope_description,
                       data_as_of_at, contains_sample_data, is_finalized, warning_text,
                       storage_object_path, file_sha256, payload_sha256,
                       source_snapshot_export_id, export_payload, generated_by,
                       generated_at)
                    values (%s, %s, %s::public.export_format, %s, %s, %s, false, false, %s,
                            %s, %s, %s, %s, %s::jsonb, %s, %s)
                    returning {_COLUMNS}""",
                [
                    export_id, mrv_case_id, fmt, factor_set_id, scope_description,
                    data_as_of_at, warning_text, storage_object_path, file_sha256,
                    payload_sha256, source_snapshot_export_id,
                    json.dumps(payload, sort_keys=True, ensure_ascii=False),
                    generated_by, generated_at,
                ],
            )
            row = cur.fetchone()
            for calculation_id in sorted(set(calculation_ids)):
                cur.execute(
                    """insert into public.mrv_export_calculations
                         (mrv_export_id, carbon_calculation_id) values (%s, %s)
                       on conflict do nothing""",
                    [export_id, calculation_id],
                )
            return dict(row)

    def payload(self, export_id: str, *, authorized_case_ids: list[str]) -> dict[str, Any]:
        """Read one stored snapshot back.

        `authorized_case_ids` comes from an RLS-bound read the caller already
        passed; this privileged connection must not be the thing that decides
        who may read an export, so the case filter is applied in SQL rather than
        trusted to the caller.
        """
        if not authorized_case_ids:
            raise MrvExportNotFoundError()
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""select {_COLUMNS}, export_payload
                    from public.mrv_exports
                    where id = %s and mrv_case_id = any(%s)""",
                [export_id, list(authorized_case_ids)],
            )
            row = cur.fetchone()
            if row is None:
                raise MrvExportNotFoundError()
            return dict(row)

    # -- artifact bytes: Supabase Storage, private bucket ------------------
    # The project already stores CV images this way (`cv_repo.upload_image`), the
    # `mrv-exports` bucket already exists and is NOT public, and the
    # `<organization>/<case>/<file>` path is already enforced by a DB trigger.
    # Retrieval goes through the backend after authorization -- no signed URL is
    # ever put into export metadata, so there is nothing to leak by holding a path.

    @property
    def _storage(self) -> Any:
        if self._storage_client is None:
            from supabase import create_client  # lazy, as in cv_repo/supabase_repo

            url, key = self._settings.require_supabase()
            self._storage_client = create_client(url, key)
        return self._storage_client

    def put_artifact(self, object_path: str, data: bytes, content_type: str) -> None:
        self._storage.storage.from_(EXPORTS_BUCKET).upload(
            object_path, data, {"content-type": content_type, "upsert": "false"},
        )

    def get_artifact(self, object_path: str) -> bytes:
        try:
            data = self._storage.storage.from_(EXPORTS_BUCKET).download(object_path)
        except Exception as exc:  # noqa: BLE001 - any storage miss is the same answer
            raise MrvArtifactMissingError(object_path) from exc
        if not data:
            raise MrvArtifactMissingError(object_path)
        return bytes(data)

    def delete_artifact(self, object_path: str) -> None:
        """Best-effort cleanup of an object whose metadata row was never written."""
        self._storage.storage.from_(EXPORTS_BUCKET).remove([object_path])

    def artifact_row(self, export_id: str, *, authorized_case_ids: list[str]) -> dict[str, Any]:
        """Metadata needed to serve an artifact, scoped in SQL to managed cases."""
        if not authorized_case_ids:
            raise MrvExportNotFoundError()
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                f"""select {_COLUMNS}, export_payload
                    from public.mrv_exports
                    where id = %s and mrv_case_id = any(%s)""",
                [export_id, list(authorized_case_ids)],
            )
            row = cur.fetchone()
            if row is None:
                raise MrvExportNotFoundError()
            return dict(row)

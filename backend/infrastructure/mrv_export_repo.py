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


class MrvExportNotFoundError(Exception):
    pass


_COLUMNS = (
    "id::text, mrv_case_id::text, format::text, factor_set_id::text, scope_description, "
    "data_as_of_at, contains_sample_data, is_finalized, warning_text, storage_bucket, "
    "storage_object_path, file_sha256, generated_by::text, generated_at"
)


class PostgresMrvExportRepository:
    def __init__(self, settings: Settings, connect: Any | None = None):
        self._settings = settings
        self._connect = connect

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
                       storage_object_path, file_sha256, export_payload, generated_by,
                       generated_at)
                    values (%s, %s, %s::public.export_format, %s, %s, %s, false, false, %s,
                            %s, %s, %s::jsonb, %s, %s)
                    returning {_COLUMNS}""",
                [
                    export_id, mrv_case_id, fmt, factor_set_id, scope_description,
                    data_as_of_at, warning_text, storage_object_path, file_sha256,
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

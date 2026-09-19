"""Trusted persistence + storage for M03 CV Farmer integration.

Same trust model as write_repo.py/recommendation_repo.py: authorization is
established by the caller (via SupabaseReadRepository, RLS) *before*
reaching this repository. `plant_images`/`cv_inferences`/`cv_model_versions`
writes use a service-role psycopg connection; the image bytes go to the
existing `plant-images` Supabase Storage bucket (already provisioned —
see baseline migration comment — not a second storage architecture).
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Callable

from . import pg_pool
from .config import Settings

STORAGE_BUCKET = "plant-images"


class CvNotFoundError(Exception):
    pass


class DuplicateImageError(Exception):
    """The exact same image bytes (sha256) are already attached to a
    *different* crop season — `plant_images_sha_uidx` is a global unique
    index, not scoped per season."""


def _normalize(row: dict[str, Any]) -> dict[str, Any]:
    """psycopg returns `uuid` columns as Python UUID objects; every response
    schema in this backend expects plain strings (see
    infrastructure/recommendation_repo.py for the same fix, found via a real
    M05 E2E — applying it here from the start instead of rediscovering it)."""
    for key in ("id", "crop_season_id", "image_id", "model_version_id"):
        if key in row and row[key] is not None:
            row[key] = str(row[key])
    return row


class PostgresCvRepository:
    def __init__(self, settings: Settings, connect: Any | None = None, storage_client: Any | None = None):
        self._settings = settings
        self._connect = connect
        self._storage_client = storage_client

    def _connection(self):
        if self._connect is not None:
            return self._connect()
        # Pooled: a fresh hosted-Postgres connection costs ~700ms, which
        # dwarfed the statements themselves (see infrastructure/pg_pool).
        return pg_pool.connection(self._settings.require_db())

    @property
    def _storage(self) -> Any:
        if self._storage_client is None:
            from supabase import create_client  # import lười, giống infrastructure/supabase_repo.py

            url, key = self._settings.require_supabase()
            self._storage_client = create_client(url, key)
        return self._storage_client

    def upload_image(self, *, farm_id: str, crop_season_id: str, file_bytes: bytes, mime_type: str, extension: str) -> str:
        """Object path MUST be `<farm_uuid>/<crop_season_uuid>/<file>` — enforced
        by `private.validate_plant_image_path()` trigger on insert."""
        object_path = f"{farm_id}/{crop_season_id}/{uuid.uuid4()}.{extension}"
        self._storage.storage.from_(STORAGE_BUCKET).upload(
            object_path, file_bytes, {"content-type": mime_type},
        )
        return object_path

    def delete_image_object(self, object_path: str) -> None:
        """Best-effort cleanup of an uploaded image whose row was never written."""
        self._storage.storage.from_(STORAGE_BUCKET).remove([object_path])

    def find_image_by_sha(self, *, crop_season_id: str, sha256: str) -> dict[str, Any] | None:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                """select id::text, crop_season_id::text from public.plant_images
                   where sha256 = %s and deleted_at is null""",
                [sha256],
            )
            row = cur.fetchone()
            if row is None:
                return None
            if row["crop_season_id"] != crop_season_id:
                raise DuplicateImageError()
            return row

    def get_or_create_model_version(
        self, *, version_code: str, model_name: str, test_dataset_name: str,
        test_dataset_version: str | None, test_sample_count: int | None, accuracy: float,
        confusion_matrix: dict[str, Any], confidence_threshold: float, source_reference: str | None,
    ) -> str:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute("select id::text from public.cv_model_versions where version_code = %s", [version_code])
            row = cur.fetchone()
            if row is not None:
                return row["id"]
            cur.execute(
                """insert into public.cv_model_versions
                   (model_name, version_code, test_dataset_name, test_dataset_version, test_sample_count,
                    accuracy, confusion_matrix, confidence_threshold, source_reference, status)
                   values (%s,%s,%s,%s,%s,%s,%s,%s,%s,'draft')
                   returning id::text""",
                [
                    model_name, version_code, test_dataset_name, test_dataset_version, test_sample_count,
                    accuracy, json.dumps(confusion_matrix), confidence_threshold, source_reference,
                ],
            )
            return cur.fetchone()["id"]

    def create_image(
        self, *, crop_season_id: str, uploaded_by: str, storage_object_path: str,
        mime_type: str, file_size_bytes: int, sha256: str,
    ) -> str:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                """insert into public.plant_images
                   (crop_season_id, storage_bucket, storage_object_path, mime_type, file_size_bytes, sha256, uploaded_by)
                   values (%s,%s,%s,%s,%s,%s,%s)
                   returning id::text""",
                [crop_season_id, STORAGE_BUCKET, storage_object_path, mime_type, file_size_bytes, sha256, uploaded_by],
            )
            return cur.fetchone()["id"]

    def find_inference(self, *, image_id: str, model_version_id: str) -> dict[str, Any] | None:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(self._inference_select_sql("where ci.image_id = %s and ci.model_version_id = %s"), [image_id, model_version_id])
            row = cur.fetchone()
            return _normalize(row) if row else None

    def create_inference(
        self, *, image_id: str, model_version_id: str, predicted_label: str, confidence: float, threshold_used: float,
        prepare: Callable[[dict[str, Any]], Any] | None = None,
    ) -> Any:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                """insert into public.cv_inferences (image_id, model_version_id, predicted_label, confidence, threshold_used)
                   values (%s,%s,%s,%s,%s) returning id::text""",
                [image_id, model_version_id, predicted_label, confidence, threshold_used],
            )
            inference_id = cur.fetchone()["id"]
            cur.execute(self._inference_select_sql("where ci.id = %s"), [inference_id])
            row = _normalize(cur.fetchone())
            # Before commit: an unrepresentable result rolls the row back.
            return prepare(row) if prepare is not None else row

    def get_inference(self, inference_id: str) -> dict[str, Any]:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(self._inference_select_sql("where ci.id = %s"), [inference_id])
            row = cur.fetchone()
            if row is None:
                raise CvNotFoundError()
            return _normalize(row)

    def list_inferences(self, crop_season_id: str) -> list[dict[str, Any]]:
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                self._inference_select_sql("where i.crop_season_id = %s order by ci.inferred_at desc"),
                [crop_season_id],
            )
            return [_normalize(row) for row in cur.fetchall()]

    @staticmethod
    def _inference_select_sql(where_clause: str) -> str:
        # noqa: S608 -- where_clause is one of the static literals passed by methods above, not request input
        return f"""
            select ci.id::text, i.crop_season_id::text, ci.image_id::text, ci.model_version_id::text,
                   ci.predicted_label::text, ci.confidence, ci.threshold_used, ci.is_uncertain,
                   ci.inferred_at, mv.version_code
            from public.cv_inferences ci
            join public.plant_images i on i.id = ci.image_id
            join public.cv_model_versions mv on mv.id = ci.model_version_id
            {where_clause}
        """

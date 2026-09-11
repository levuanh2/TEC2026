"""Lớp ứng dụng: nối Repository -> Carbon Engine -> Repository.

Đây là nơi DUY NHẤT biết cả hai phía. Carbon Engine không biết repository;
repository không biết Carbon Engine.
"""

from __future__ import annotations

import hashlib
import io
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from carbon import CarbonResult, ParameterSet, calculate_carbon
from infrastructure.mapping import (
    breakdown_rows,
    calculation_row,
    map_crop_activity_data,
)
from infrastructure.repository import CarbonRepository
from infrastructure.read_repo import ReadNotFoundError, SupabaseReadRepository
from infrastructure.cv_repo import CvNotFoundError, DuplicateImageError, PostgresCvRepository
from infrastructure.recommendation_repo import PostgresRecommendationRepository, RecommendationNotFoundError
from infrastructure.write_repo import ActivityNotFoundError, PostgresActivityWriteRepository
from recommendation import generate_recommendations
import schemas

# `ml/` lives at the repo root, a sibling of `backend/`, not a backend
# subpackage — add the repo root once so `import ml.*` below works
# regardless of the process's cwd (uvicorn from backend/, pytest from
# backend/ or repo root, ...).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from PIL import Image  # noqa: E402
from ml.class_mapping import LABEL_VI  # noqa: E402
from ml.infer import predict_with_model  # noqa: E402


@dataclass
class CalculationOutcome:
    result: CarbonResult
    calculation_id: str | None
    persisted: bool


class CarbonService:
    """Tính CO2e cho một vụ và lưu kết quả.

    `persist=False` cho phép chạy kịch bản giả định (What-if, giai đoạn 2) mà không ghi
    vào database — engine vốn là hàm thuần nên việc này không tốn gì thêm.
    """

    def __init__(self, repository: CarbonRepository, parameters: ParameterSet) -> None:
        self._repo = repository
        self._params = parameters

    @property
    def parameters(self) -> ParameterSet:
        return self._params

    def calculate(
        self, crop_season_id: str, scenario: str = "as_recorded", *, persist: bool = True
    ) -> CalculationOutcome:
        bundle = self._repo.get_crop_bundle(crop_season_id)
        activity_data = map_crop_activity_data(bundle)

        # Mọi lỗi phương pháp luận/thiếu hệ số nổ ra từ đây — fail closed, không nuốt.
        result = calculate_carbon(activity_data, scenario, self._params)

        if not persist:
            return CalculationOutcome(result=result, calculation_id=None, persisted=False)

        factor_set_id = self._repo.resolve_factor_set_id(result.ef_config_version)
        factor_ids = self._repo.factor_ids_by_code(factor_set_id)

        calculation_id = self._repo.save_calculation(
            calculation_row(
                result,
                crop_season_id=crop_season_id,
                factor_set_id=factor_set_id,
                area_ha=activity_data.area_ha,
                cultivation_days=activity_data.recorded_cultivation_days,
                pre_season_water_regime=activity_data.pre_season_water_regime,
            ),
            breakdown_rows(result, factor_ids),
        )
        return CalculationOutcome(
            result=result, calculation_id=calculation_id, persisted=True
        )

    def latest(self, crop_season_id: str, scenario: str | None = None) -> dict[str, Any] | None:
        return self._repo.latest_calculation(crop_season_id, scenario)


class ActivityWriteAccessError(Exception):
    """Normalized to 404 so write scope cannot enumerate other farmers' data."""


class InvalidCropSeasonStateError(Exception):
    pass


class ActivityWriteService:
    """Domain service for Farmer Web online journal writes.

    RLS-backed reads establish caller and crop scope before the trusted
    transaction repository writes base/detail rows with a backend DB role.
    """

    def __init__(self, write_repository: PostgresActivityWriteRepository):
        self._write_repository = write_repository

    @staticmethod
    def _actor_and_farmer_scope(read_repository: SupabaseReadRepository) -> str:
        me = read_repository.me()
        if "farmer" not in me["roles"]:
            raise ActivityWriteAccessError()
        return str(me["user_id"])

    @staticmethod
    def _write_batch(read_repository: SupabaseReadRepository, crop_season_id: str) -> str:
        try:
            season = read_repository.season(crop_season_id)
            # FW-2 does not revise crop lifecycle: its existing active state is
            # the only state accepting the three online journal activities.
            if season.get("status") != "active":
                raise InvalidCropSeasonStateError()
            batches = [
                batch for batch in read_repository.production_batches(crop_season_id)
                if batch.get("status") not in {"closed", "cancelled"}
            ]
        except ReadNotFoundError as exc:
            raise ActivityWriteAccessError() from exc
        if len(batches) != 1:
            raise InvalidCropSeasonStateError()
        return str(batches[0]["id"])

    @staticmethod
    def _response(row: dict[str, Any], *, replay: bool = False) -> dict[str, Any]:
        return {
            "id": row["id"], "crop_season_id": row["crop_season_id"],
            "activity_type": row["activity_type"], "occurred_at": row["occurred_at"],
            "note": row.get("note"), "data": row["data"],
            "created_by": row["created_by"], "created_at": row["created_at"],
            "updated_at": row["updated_at"], "idempotent_replay": replay,
        }

    def create(
        self, *, read_repository: SupabaseReadRepository, crop_season_id: str,
        request: schemas.ActivityCreateRequest,
    ) -> dict[str, Any]:
        actor_id = self._actor_and_farmer_scope(read_repository)
        batch_id = self._write_batch(read_repository, crop_season_id)
        data = schemas.validate_activity_data(request.activity_type, request.data).model_dump()
        row, replay = self._write_repository.create(
            crop_season_id=crop_season_id, production_batch_id=batch_id,
            actor_id=actor_id, idempotency_key=str(request.idempotency_key),
            activity_type=request.activity_type, occurred_at=request.occurred_at,
            note=request.note, data=data,
        )
        return self._response(row, replay=replay)

    def update(
        self, *, read_repository: SupabaseReadRepository, activity_id: str,
        request: schemas.ActivityUpdateRequest,
    ) -> dict[str, Any]:
        actor_id = self._actor_and_farmer_scope(read_repository)
        try:
            # RLS first: an out-of-scope ID and a nonexistent ID look identical.
            read_repository.activity(activity_id)
            existing = self._write_repository.get_for_actor(activity_id, actor_id)
            self._write_batch(read_repository, str(existing["crop_season_id"]))
        except (ReadNotFoundError, ActivityNotFoundError) as exc:
            raise ActivityWriteAccessError() from exc
        data = None
        if request.data is not None:
            data = schemas.validate_activity_data(
                existing["activity_type"], {**existing["data"], **request.data}
            ).model_dump()
        row = self._write_repository.update(
            activity_id=activity_id, actor_id=actor_id, occurred_at=request.occurred_at,
            note=request.note, update_note="note" in request.model_fields_set, data=data,
        )
        return self._response(row)

    def delete(self, *, read_repository: SupabaseReadRepository, activity_id: str) -> None:
        actor_id = self._actor_and_farmer_scope(read_repository)
        try:
            read_repository.activity(activity_id)
            existing = self._write_repository.get_for_actor(activity_id, actor_id)
            self._write_batch(read_repository, str(existing["crop_season_id"]))
            self._write_repository.soft_delete(activity_id=activity_id, actor_id=actor_id)
        except (ReadNotFoundError, ActivityNotFoundError) as exc:
            raise ActivityWriteAccessError() from exc


class RecommendationAccessError(Exception):
    """Normalized to 404 so scope cannot enumerate other farmers' seasons."""


class RecommendationService:
    """M05 domain service: generate deterministic recommendations for a crop
    season, and let the farmer accept/dismiss one.

    Carbon-impact evidence is always produced by calling back into the same
    `CarbonService` the `/v1/carbon/*` routes use (`persist=False` what-if
    calls) — this service never computes emissions itself.
    """

    def __init__(self, carbon_service: CarbonService, write_repository: PostgresRecommendationRepository):
        self._carbon = carbon_service
        self._write_repository = write_repository

    @staticmethod
    def _actor_and_farmer_scope(read_repository: SupabaseReadRepository) -> str:
        me = read_repository.me()
        if "farmer" not in me["roles"]:
            raise RecommendationAccessError()
        return str(me["user_id"])

    def generate(self, *, read_repository: SupabaseReadRepository, crop_season_id: str) -> list[dict[str, Any]]:
        self._actor_and_farmer_scope(read_repository)
        try:
            read_repository.season(crop_season_id)
            metrics = read_repository.metrics(crop_season_id)
        except ReadNotFoundError as exc:
            raise RecommendationAccessError() from exc

        candidates = generate_recommendations(crop_season_id, carbon=self._carbon, metrics=metrics)
        rows = [self._write_repository.upsert(crop_season_id=crop_season_id, rec=rec) for rec in candidates]
        self._write_repository.prune_missing(
            crop_season_id=crop_season_id, keep_rule_codes=[rec.rule_code for rec in candidates],
        )
        return rows

    def set_status(
        self, *, read_repository: SupabaseReadRepository, recommendation_id: str, status: str,
    ) -> dict[str, Any]:
        self._actor_and_farmer_scope(read_repository)
        try:
            existing = self._write_repository.get(recommendation_id)
            read_repository.season(str(existing["crop_season_id"]))
        except (ReadNotFoundError, RecommendationNotFoundError) as exc:
            raise RecommendationAccessError() from exc
        return self._write_repository.set_status(recommendation_id, status)


class CvAccessError(Exception):
    """Normalized to 404 so scope cannot enumerate other farmers' seasons."""


class InvalidImageError(Exception):
    """A domain-safe, farmer-facing image validation failure."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


MAX_IMAGE_BYTES = 10 * 1024 * 1024  # matches the plant-images bucket's own file_size_limit
_ALLOWED_MIME_EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png"}
_MIN_DIMENSION_PX = 32


class CvService:
    """M03 Farmer CV integration: upload -> validate -> infer (existing
    baseline model, loaded once at startup) -> persist -> normalized read.

    Never re-implements preprocessing/calibration: `predict_with_model`
    (`ml/infer.py`) is the same function the CLI and `ml/tests` already use,
    given a model loaded once via `ml.model.load_checkpoint` and reused
    across requests — no per-request checkpoint reload.
    """

    def __init__(self, model: Any, model_config: dict, threshold: float, temperature: float, model_meta: dict, write_repository: PostgresCvRepository):
        self._model = model
        self._config = model_config
        self._threshold = threshold
        self._temperature = temperature
        self._model_meta = model_meta
        self._write_repository = write_repository
        self._model_version_id: str | None = None

    def _model_version_id_cached(self) -> str:
        if self._model_version_id is None:
            self._model_version_id = self._write_repository.get_or_create_model_version(**self._model_meta)
        return self._model_version_id

    @staticmethod
    def _actor_and_farmer_scope(read_repository: SupabaseReadRepository) -> str:
        me = read_repository.me()
        if "farmer" not in me["roles"]:
            raise CvAccessError()
        return str(me["user_id"])

    @staticmethod
    def _resolve_farm_id(read_repository: SupabaseReadRepository, crop_season_id: str) -> str:
        try:
            season = read_repository.season(crop_season_id)
            plot = read_repository.plot(season["plot_id"])
        except ReadNotFoundError as exc:
            raise CvAccessError() from exc
        farm_id = plot.get("farm_id")
        if not farm_id:
            raise CvAccessError()
        return str(farm_id)

    @staticmethod
    def _decode_and_validate(file_bytes: bytes, content_type: str) -> tuple[Image.Image, str]:
        if content_type not in _ALLOWED_MIME_EXTENSIONS:
            raise InvalidImageError("unsupported_image_type", "Chỉ hỗ trợ ảnh JPEG hoặc PNG.")
        if len(file_bytes) == 0:
            raise InvalidImageError("empty_image", "Tệp ảnh trống.")
        if len(file_bytes) > MAX_IMAGE_BYTES:
            raise InvalidImageError("image_too_large", "Ảnh vượt quá dung lượng cho phép (10MB).")
        try:
            probe = Image.open(io.BytesIO(file_bytes))
            probe.verify()  # cheap structural check before the real decode below
            image = Image.open(io.BytesIO(file_bytes)).convert("RGB")
        except Exception as exc:
            raise InvalidImageError(
                "invalid_image", "Không đọc được ảnh — tệp có thể bị hỏng hoặc không đúng định dạng.",
            ) from exc
        if image.width < _MIN_DIMENSION_PX or image.height < _MIN_DIMENSION_PX:
            raise InvalidImageError("image_too_small", "Ảnh quá nhỏ để phân tích.")
        return image, _ALLOWED_MIME_EXTENSIONS[content_type]

    def infer(self, *, read_repository: SupabaseReadRepository, crop_season_id: str, file_bytes: bytes, content_type: str) -> dict[str, Any]:
        actor_id = self._actor_and_farmer_scope(read_repository)
        farm_id = self._resolve_farm_id(read_repository, crop_season_id)
        image, extension = self._decode_and_validate(file_bytes, content_type)
        sha256 = hashlib.sha256(file_bytes).hexdigest()
        model_version_id = self._model_version_id_cached()

        try:
            existing_image = self._write_repository.find_image_by_sha(crop_season_id=crop_season_id, sha256=sha256)
        except DuplicateImageError as exc:
            raise InvalidImageError(
                "duplicate_image", "Ảnh này đã được tải lên cho một vụ canh tác khác.",
            ) from exc

        if existing_image is not None:
            # Same bytes already uploaded for this season — idempotent: reuse
            # the image, and reuse the inference if this model version has
            # already scored it (brief FW-2-style content-hash idempotency,
            # never a second identical row).
            existing_inference = self._write_repository.find_inference(image_id=existing_image["id"], model_version_id=model_version_id)
            if existing_inference is not None:
                return self._to_response(existing_inference)
            image_id = existing_image["id"]
        else:
            storage_path = self._write_repository.upload_image(
                farm_id=farm_id, crop_season_id=crop_season_id, file_bytes=file_bytes,
                mime_type=content_type, extension=extension,
            )
            image_id = self._write_repository.create_image(
                crop_season_id=crop_season_id, uploaded_by=actor_id, storage_object_path=storage_path,
                mime_type=content_type, file_size_bytes=len(file_bytes), sha256=sha256,
            )

        predicted = predict_with_model(image, self._model, self._config, self._threshold, self._temperature)
        # public.disease_label has no NULL state — 'unknown' is the schema's
        # own sentinel for "confidence below threshold" (brief FW M03 §17);
        # the API response maps it back to `label: null` below.
        predicted_label = predicted["label"] or "unknown"
        row = self._write_repository.create_inference(
            image_id=image_id, model_version_id=model_version_id,
            predicted_label=predicted_label, confidence=predicted["confidence"], threshold_used=self._threshold,
        )
        return self._to_response(row)

    def list(self, *, read_repository: SupabaseReadRepository, crop_season_id: str) -> list[dict[str, Any]]:
        try:
            read_repository.season(crop_season_id)
        except ReadNotFoundError as exc:
            raise CvAccessError() from exc
        return [self._to_response(row) for row in self._write_repository.list_inferences(crop_season_id)]

    def get(self, *, read_repository: SupabaseReadRepository, inference_id: str) -> dict[str, Any]:
        try:
            row = self._write_repository.get_inference(inference_id)
        except CvNotFoundError as exc:
            raise CvAccessError() from exc
        try:
            read_repository.season(row["crop_season_id"])
        except ReadNotFoundError as exc:
            raise CvAccessError() from exc
        return self._to_response(row)

    @staticmethod
    def _to_response(row: dict[str, Any]) -> dict[str, Any]:
        label = None if row["predicted_label"] == "unknown" else row["predicted_label"]
        return {
            "id": row["id"], "crop_season_id": row["crop_season_id"], "image_id": row["image_id"],
            "label": label, "label_vi": LABEL_VI.get(label) if label else None,
            "confidence": float(row["confidence"]), "uncertain": bool(row["is_uncertain"]),
            "threshold_used": float(row["threshold_used"]), "model_version": row["version_code"],
            "created_at": row["inferred_at"],
        }

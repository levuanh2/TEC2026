"""Lớp ứng dụng: nối Repository -> Carbon Engine -> Repository.

Đây là nơi DUY NHẤT biết cả hai phía. Carbon Engine không biết repository;
repository không biết Carbon Engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from carbon import CarbonResult, ParameterSet, calculate_carbon
from infrastructure.mapping import (
    breakdown_rows,
    calculation_row,
    map_crop_activity_data,
)
from infrastructure.repository import CarbonRepository
from infrastructure.read_repo import ReadNotFoundError, SupabaseReadRepository
from infrastructure.write_repo import ActivityNotFoundError, PostgresActivityWriteRepository
import schemas


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

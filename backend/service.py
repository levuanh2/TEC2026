"""Lớp ứng dụng: nối Repository -> Carbon Engine -> Repository.

Đây là nơi DUY NHẤT biết cả hai phía. Carbon Engine không biết repository;
repository không biết Carbon Engine.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import logging
import secrets
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from carbon import CarbonResult, ParameterSet, calculate_carbon, compute_input_hash
from carbon.errors import CarbonEngineError
from carbon.readiness import mapping_refused, readiness as carbon_readiness
from infrastructure import memberships, profiling
from infrastructure.mapping import (
    breakdown_rows,
    calculation_row,
    map_crop_activity_data,
    stored_calculation_view,
    record_refs,
)
from infrastructure.repository import CarbonRepository
from infrastructure.read_repo import ReadNotFoundError, SupabaseReadRepository
from infrastructure.cv_repo import CvNotFoundError, DuplicateImageError, PostgresCvRepository
from infrastructure.recommendation_repo import PostgresRecommendationRepository, RecommendationNotFoundError
from infrastructure.mrv_export_repo import (
    MrvArtifactCorruptError,
    MrvArtifactMissingError,
    MrvExportNotFoundError,
    PostgresMrvExportRepository,
)
from infrastructure.season_repo import PostgresSeasonRepository, SeasonScopeError
from infrastructure.auth_admin import AuthUserExistsError, SupabaseAuthAdmin
from infrastructure.provisioning_repo import (
    AccountExistsError,
    FarmCodeTakenError,
    PlotCodeTakenError,
    PostgresProvisioningRepository,
    ProvisioningScopeError,
)
from infrastructure.write_repo import ActivityNotFoundError, PostgresActivityWriteRepository, SeasonNotOpenError
from mrv import manifest as mrv_manifest
from mrv import report_pdf as mrv_report_pdf
from mrv import workbook as mrv_workbook
from recommendation import generate_recommendations
import schemas

# `ml/` lives at the repo root, a sibling of `backend/`, not a backend
# subpackage — add the repo root once so `import ml.*` below works
# regardless of the process's cwd (uvicorn from backend/, pytest from
# backend/ or repo root, ...).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ml.class_mapping import LABEL_VI  # noqa: E402 - thuần Python, không kéo torch

# CV (M03) cần Pillow + torch, KHÔNG nằm trong backend/requirements.txt (xem
# ml/requirements.txt): một môi trường nhỏ — ví dụ Render Free 512 MB — cài
# backend mà không cài CV. Thiếu thì API vẫn khởi động bình thường và các route
# CV trả 503 `backend_not_configured` (main._build_cv_service trả None), thay vì
# cả tiến trình chết lúc import.
try:  # noqa: E402
    from PIL import Image  # noqa: E402
    from ml.infer import predict_with_model  # noqa: E402
except Exception:  # noqa: BLE001 - môi trường không có CV
    Image = None  # type: ignore[assignment]
    predict_with_model = None  # type: ignore[assignment]


@dataclass
class CalculationOutcome:
    result: CarbonResult
    calculation_id: str | None
    persisted: bool
    #: What `calculate(prepare=...)` built from the result BEFORE anything was
    #: written; None when no `prepare` was given.
    prepared: Any = None


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

    def session(self):
        """The repository's one-connection block, when it has one (Round 5.1)."""
        session = getattr(self._repo, "session", None)
        return session() if session is not None else contextlib.nullcontext()

    def calculate(
        self, crop_season_id: str, scenario: str = "as_recorded", *, persist: bool = True,
        prepare: Callable[[CarbonResult], Any] | None = None, caller: str | None = None,
    ) -> CalculationOutcome:
        # A repository that can keep one connection for the read-then-write
        # does (Round 5.1); others behave exactly as before.
        session = getattr(self._repo, "session", None)
        with session() if session is not None else contextlib.nullcontext():
            return self._calculate(crop_season_id, scenario, persist=persist, prepare=prepare, caller=caller)

    def can_authorize_reads(self) -> bool:
        """The repository can check the caller's read+write rules while it reads."""
        return hasattr(self._repo, "get_crop_bundle_as")

    def _calculate(
        self, crop_season_id: str, scenario: str, *, persist: bool,
        prepare: Callable[[CarbonResult], Any] | None, caller: str | None = None,
    ) -> CalculationOutcome:
        with profiling.phase("bundle read"):
            # `caller` (a verified user id): the repository enforces the caller's
            # read and write rules in the same round trip as the read, and
            # raises CropAccessError when either refuses (Round 5.1).
            bundle = (self._repo.get_crop_bundle_as(crop_season_id, caller) if caller is not None
                      else self._repo.get_crop_bundle(crop_season_id))
        with profiling.phase("engine"):
            activity_data = map_crop_activity_data(bundle)

            # Mọi lỗi phương pháp luận/thiếu hệ số nổ ra từ đây — fail closed, không nuốt.
            result = calculate_carbon(activity_data, scenario, self._params)

        # The success representation is built before the first write: a result
        # the API cannot serialize must fail here, with nothing saved, rather
        # than after `save_calculation` has stored it (an HTTP 500 for a saved
        # calculation, which a retry would then silently reuse).
        with profiling.phase("serialize"):
            prepared = prepare(result) if prepare is not None else None

        if not persist:
            return CalculationOutcome(result=result, calculation_id=None, persisted=False, prepared=prepared)

        with profiling.phase("factor lookup"):
            factor_set_id = self._repo.resolve_factor_set_id(result.ef_config_version)
            factor_ids = self._repo.factor_ids_by_code(factor_set_id)

        with profiling.phase("save result+breakdown"):
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
            result=result, calculation_id=calculation_id, persisted=True, prepared=prepared
        )

    def latest(self, crop_season_id: str, scenario: str | None = None) -> dict[str, Any] | None:
        return self._repo.latest_calculation(crop_season_id, scenario)

    def stored(self, crop_season_id: str, scenario: str = "as_recorded") -> dict[str, Any] | None:
        """Bản tính đã lưu gần nhất CỦA ĐÚNG KỊCH BẢN, theo từ vựng API.

        Không bao giờ "bản mới nhất bất kỳ": một kịch bản mô phỏng tính sau không
        được thay kết quả vận hành (`as_recorded`) của vụ.
        """
        return self._stored_view(self._repo.latest_calculation(crop_season_id, scenario))

    def _stored_view(self, row: dict[str, Any] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        factor_set_id = row.get("factor_set_id")
        version = self._repo.factor_set_version(str(factor_set_id)) if factor_set_id else None
        view = stored_calculation_view(row, ef_config_version=version)
        # Phương pháp chỉ gắn khi bản tính dùng ĐÚNG bộ tham số engine đang chạy —
        # không gán mô tả của bộ khác cho một kết quả cũ.
        if version and version == self._params.version:
            view["methodology"] = self._params.methodology.to_dict()
        return view

    def readiness(self, crop_season_id: str) -> dict[str, Any]:
        """Which Carbon inputs the season still lacks, derived server-side.

        Built from the same `CropActivityData` the engine consumes, so a client
        can name the missing input without holding any methodology of its own.
        """
        return self._readiness_of(self._repo.get_crop_bundle(crop_season_id))

    def _readiness_of(self, bundle) -> dict[str, Any]:
        try:
            data = map_crop_activity_data(bundle)
        except CarbonEngineError as exc:
            # The mapper itself refuses: either the plot has no area, or
            # irrigation records cannot be mapped to an IPCC class. Each has a
            # different fix, so name the one that actually applies.
            return mapping_refused(area_missing=bundle.plot.get("area_ha") is None, detail=str(exc))
        # Record identity rides alongside, so the client can open the exact record.
        body = carbon_readiness(data, record_refs(bundle))
        # Fingerprint của kết quả vận hành nếu tính bây giờ: đúng `input_hash` mà
        # engine sẽ ghi cho `as_recorded`. Chỉ Activity Data engine tiêu thụ đi vào
        # hash (không có chi phí, ghi chú), nên client so khớp hash thay vì so thời
        # điểm sửa bản ghi — sửa chi phí không còn làm kết quả "cần tính lại".
        body["input_hash"] = compute_input_hash(data, "as_recorded", self._params)
        body["ef_config_version"] = self._params.version
        return body

    def status_many(self, crop_season_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Readiness and the stored ACTUAL result of many seasons at once.

        Per season this is exactly `readiness(id)` and `stored(id, "as_recorded")`
        — the same helpers over the same rows — so a batch answer never
        disagrees with the per-season endpoints. Callers must already have
        established that the caller may read every id. A season that fails is
        an exception in its own slot; the others are unaffected.
        """
        ids = list(dict.fromkeys(crop_season_ids))
        many_bundles = getattr(self._repo, "get_crop_bundles", None)
        many_latest = getattr(self._repo, "latest_calculations", None)
        out: dict[str, dict[str, Any]] = {sid: {} for sid in ids}

        def settle(sid: str, key: str, compute: Callable[[], Any]) -> None:
            try:
                out[sid][key] = compute()
            except Exception as exc:  # noqa: BLE001 - reported per season by the route
                out[sid][key] = exc

        if many_bundles is not None:
            try:
                bundles: dict[str, Any] = many_bundles(ids)
            except Exception as exc:  # noqa: BLE001
                bundles = {sid: exc for sid in ids}
        else:
            bundles = {}
            for sid in ids:
                try:
                    bundles[sid] = self._repo.get_crop_bundle(sid)
                except Exception as exc:  # noqa: BLE001
                    bundles[sid] = exc

        def readiness_for(sid: str) -> dict[str, Any]:
            bundle = bundles[sid]
            if isinstance(bundle, Exception):
                raise bundle
            return self._readiness_of(bundle)

        if many_latest is not None:
            try:
                rows: dict[str, Any] = many_latest(ids, "as_recorded")
            except Exception as exc:  # noqa: BLE001
                rows = {sid: exc for sid in ids}
        else:
            rows = {}
            for sid in ids:
                try:
                    rows[sid] = self._repo.latest_calculation(sid, "as_recorded")
                except Exception as exc:  # noqa: BLE001
                    rows[sid] = exc

        def actual_for(sid: str) -> dict[str, Any] | None:
            row = rows.get(sid)
            if isinstance(row, Exception):
                raise row
            return self._stored_view(row)

        for sid in ids:
            settle(sid, "readiness", lambda sid=sid: readiness_for(sid))
            settle(sid, "actual", lambda sid=sid: actual_for(sid))
        return out


class ActivityWriteAccessError(Exception):
    """Normalized to 404 so write scope cannot enumerate other farmers' data."""


class InvalidCropSeasonStateError(Exception):
    pass


class HarvestAreaExceedsPlotError(Exception):
    """A harvest claims more hectares than the season's plot has."""

    def __init__(self, harvested_area_ha: float, plot_area_ha: float) -> None:
        self.harvested_area_ha = harvested_area_ha
        self.plot_area_ha = plot_area_ha
        super().__init__(
            f"Diện tích thu hoạch ({harvested_area_ha:g} ha) không được lớn hơn diện tích thửa ({plot_area_ha:g} ha)."
        )


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
    def _assert_harvest_within_plot(
        read_repository: SupabaseReadRepository, crop_season_id: str, activity_type: str, data: dict[str, Any],
    ) -> None:
        """`harvested_area_ha` may equal the plot area, never exceed it.

        Enforced here, not only in the form: the API is the boundary every client
        (Farmer Web, Flutter, scripts) goes through. A plot without a recorded
        area applies no bound — nothing is guessed.
        """
        if activity_type != "harvest" or data.get("harvested_area_ha") is None:
            return
        try:
            plot_id = read_repository.season(crop_season_id).get("plot_id")
            plot = read_repository.plot(str(plot_id)) if plot_id else {}
        except ReadNotFoundError as exc:
            raise ActivityWriteAccessError() from exc
        plot_area = plot.get("area_ha")
        if plot_area is None:
            return
        harvested = float(data["harvested_area_ha"])
        if harvested > float(plot_area) + 1e-9:
            raise HarvestAreaExceedsPlotError(harvested, float(plot_area))

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
        self._assert_harvest_within_plot(read_repository, crop_season_id, request.activity_type, data)
        try:
            # The repository re-checks write permission (farm owner/editor or
            # cooperative manager) inside its transaction; a read-only farm
            # member is normalized to the same 404 as an out-of-scope season.
            return self._write_repository.create(
                crop_season_id=crop_season_id, production_batch_id=batch_id,
                actor_id=actor_id, idempotency_key=str(request.idempotency_key),
                activity_type=request.activity_type, occurred_at=request.occurred_at,
                note=request.note, data=data,
                prepare=lambda out: schemas.success_payload(
                    schemas.ActivityWriteResponse, self._response(out[0], replay=out[1])),
            )
        except ActivityNotFoundError as exc:
            raise ActivityWriteAccessError() from exc

    def update(
        self, *, read_repository: SupabaseReadRepository, activity_id: str,
        request: schemas.ActivityUpdateRequest,
    ) -> dict[str, Any]:
        actor_id = self._actor_and_farmer_scope(read_repository)
        try:
            # RLS first: an out-of-scope ID and a nonexistent ID look identical.
            read_repository.activity(activity_id)
            # Own records plus unattributed (seeded/imported) ones, exactly as
            # the `activities_update` RLS policy allows; delete stays own-only.
            existing = self._write_repository.get_for_actor(activity_id, actor_id, allow_unattributed=True)
            self._write_batch(read_repository, str(existing["crop_season_id"]))
        except (ReadNotFoundError, ActivityNotFoundError) as exc:
            raise ActivityWriteAccessError() from exc
        data = None
        if request.data is not None:
            data = schemas.validate_activity_data(
                existing["activity_type"], {**existing["data"], **request.data}
            ).model_dump()
            self._assert_harvest_within_plot(
                read_repository, str(existing["crop_season_id"]), existing["activity_type"], data,
            )
        try:
            return self._write_repository.update(
                activity_id=activity_id, actor_id=actor_id, occurred_at=request.occurred_at,
                note=request.note, update_note="note" in request.model_fields_set, data=data,
                prepare=lambda row: schemas.success_payload(schemas.ActivityWriteResponse, self._response(row)),
            )
        except ActivityNotFoundError as exc:
            raise ActivityWriteAccessError() from exc

    def delete(self, *, read_repository: SupabaseReadRepository, activity_id: str) -> None:
        actor_id = self._actor_and_farmer_scope(read_repository)
        try:
            read_repository.activity(activity_id)
            existing = self._write_repository.get_for_actor(activity_id, actor_id)
            self._write_batch(read_repository, str(existing["crop_season_id"]))
            self._write_repository.soft_delete(activity_id=activity_id, actor_id=actor_id)
        except (ReadNotFoundError, ActivityNotFoundError) as exc:
            raise ActivityWriteAccessError() from exc

    def update_crop_season_methodology(
        self, *, read_repository: SupabaseReadRepository, crop_season_id: str,
        request: schemas.CropSeasonMethodologyUpdate,
    ) -> dict[str, Any]:
        """Record the season's IPCC water-regime inputs.

        Deliberately NOT behind `_actor_and_farmer_scope`: unlike the journal
        activities, these are methodology inputs a cooperative manager legitimately
        maintains for member farms, and the persist gate for Carbon (B4) already
        treats an active `cooperative_manager` as a writer. The authority check is
        `private.user_can_write_crop` in the repository, so this route grants
        nothing the `crop_seasons` UPDATE policy would not.

        Unlike the journal writes it also does not require `status = 'active'`:
        the water regime of a finished season is a fact worth correcting, and
        Carbon recalculation of a closed season is a normal review action.
        """
        me = read_repository.me()
        actor_id = str(me["user_id"])
        # Only the keys the client actually sent — an absent field keeps its
        # stored value, an explicit null clears it.
        fields = request.model_dump(include=request.model_fields_set)
        try:
            read_repository.season(crop_season_id)
            return self._write_repository.update_crop_season_methodology(
                crop_season_id=crop_season_id, actor_id=actor_id, fields=fields,
                prepare=lambda row: schemas.success_payload(schemas.CropSeasonResponse, row),
            )
        except (ReadNotFoundError, ActivityNotFoundError) as exc:
            raise ActivityWriteAccessError() from exc


class SeasonService:
    """Start a crop season on a plot: season + default production batch.

    One path for Farmer Web and Management Web. Who may do it is not decided
    here: the repository evaluates `private.user_can_write_farm` -- the rule
    behind the `crop_seasons` INSERT policy -- for the JWT-verified caller, so a
    farm owner/editor or an active cooperative manager of the farm's
    cooperative may, and a farm viewer, enterprise viewer, regulator or an
    out-of-scope caller gets the same 404 as a plot that does not exist.
    """

    def __init__(self, repository: PostgresSeasonRepository):
        self._repository = repository

    def create(
        self, *, read_repository: SupabaseReadRepository, plot_id: str,
        request: schemas.CropSeasonCreateRequest,
    ) -> dict[str, Any]:
        try:
            uuid.UUID(plot_id)
        except ValueError as exc:
            raise SeasonScopeError() from exc
        try:
            actor_id = read_repository.user_id()
        except ReadNotFoundError as exc:
            raise SeasonScopeError() from exc
        return self._repository.create(
            plot_id=plot_id, actor_id=actor_id, season_code=request.season_code,
            variety_name=request.variety_name, planting_date=request.planting_date,
            expected_harvest_date=request.expected_harvest_date,
            prepare=lambda out: schemas.success_payload(
                schemas.CropSeasonCreateResponse, {**out[0], "idempotent_replay": out[1]}),
        )


_provisioning_log = logging.getLogger("agricarbon.provisioning")

# No look-alikes (0/O, 1/l/I): the manager reads this out or writes it down.
_PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"


def generate_temporary_password() -> str:
    """12 random characters in three groups, for example Hk7m-Q2xa-9TfP.

    About 70 bits from `secrets`; always has upper, lower, digit and a symbol so
    it passes a strict Supabase password policy. Returned to the manager once
    and never stored or logged by the application.
    """
    while True:
        raw = "".join(secrets.choice(_PASSWORD_ALPHABET) for _ in range(12))
        if any(c.isupper() for c in raw) and any(c.islower() for c in raw) and any(c.isdigit() for c in raw):
            return f"{raw[:4]}-{raw[4:8]}-{raw[8:]}"


class ProvisioningFailedError(Exception):
    """Provisioning did not complete. `compensated` says whether the Auth
    identity created for it was removed (True) or could only be locked or not
    cleaned up at all (False). Never reported as success."""

    def __init__(self, *, compensated: bool):
        super().__init__("farmer provisioning failed")
        self.compensated = compensated


class ProvisioningService:
    """Management "Thêm nông hộ": a farmer account inside the manager's own
    cooperative, optionally with its farm and first plot.

    The Auth identity (Supabase Auth Admin API) and the application rows
    (profile, membership, farm, farm member, plot) live in two systems, so
    they cannot share one transaction. Strategy:

    1. `preflight` -- authorization, duplicate email, taken farm code -- in the
       database, before any identity exists;
    2. create the identity;
    3. write every application row in ONE transaction;
    4. if 3 fails, delete the identity (fallback: lock it). The request fails
       either way; there is no success for a half-provisioned farmer, and an
       identity that could not be deleted is locked and holds no membership.
    """

    def __init__(self, repository: PostgresProvisioningRepository, auth_admin: SupabaseAuthAdmin,
                 password_factory: Callable[[], str] = generate_temporary_password):
        self._repository = repository
        self._auth = auth_admin
        self._password = password_factory

    @staticmethod
    def _actor(read_repository: SupabaseReadRepository, *ids: str) -> str:
        for value in ids:
            try:
                uuid.UUID(value)
            except ValueError as exc:
                raise ProvisioningScopeError() from exc
        try:
            return read_repository.user_id()
        except ReadNotFoundError as exc:
            raise ProvisioningScopeError() from exc

    def list_farmers(self, *, read_repository: SupabaseReadRepository, organization_id: str) -> list[dict[str, Any]]:
        actor_id = self._actor(read_repository, organization_id)
        rows = self._repository.list_farmers(organization_id=organization_id, actor_id=actor_id)
        return [schemas.FarmerListItem.model_validate(r).model_dump(mode="json") for r in rows]

    def _compensate(self, user_id: str) -> bool:
        try:
            self._auth.delete_user(user_id)
            _provisioning_log.warning("farmer_provisioning_rolled_back user_id=%s identity=deleted", user_id)
            return True
        except Exception:  # noqa: BLE001
            _provisioning_log.exception("farmer_provisioning_delete_failed user_id=%s", user_id)
        try:
            self._auth.ban_user(user_id)
            _provisioning_log.error("farmer_provisioning_incomplete user_id=%s identity=locked_without_membership", user_id)
        except Exception:  # noqa: BLE001
            _provisioning_log.exception("farmer_provisioning_incomplete user_id=%s identity=UNCLEANED_without_membership", user_id)
        return False

    def provision(
        self, *, read_repository: SupabaseReadRepository, organization_id: str,
        request: schemas.FarmerProvisionRequest,
    ) -> dict[str, Any]:
        actor_id = self._actor(read_repository, organization_id)
        farm = request.farm.model_dump() if request.farm else None
        plot = request.plot.model_dump() if request.plot else None
        self._repository.preflight(
            organization_id=organization_id, actor_id=actor_id, email=request.email,
            farm_code=farm["farm_code"] if farm else None,
        )
        password = self._password()
        attempt = str(uuid.uuid4())
        try:
            user_id = self._auth.create_user(email=request.email, password=password, full_name=request.full_name, attempt=attempt)
        except AuthUserExistsError as exc:
            # Created between preflight and now: classify it the same way.
            self._repository.preflight(organization_id=organization_id, actor_id=actor_id, email=request.email, farm_code=None)
            raise AccountExistsError() from exc
        except Exception as exc:
            # Ambiguous: Auth may have created the user and the response was
            # lost. Find an identity this attempt created and remove it.
            try:
                orphan = self._repository.find_orphan_identity(email=request.email, attempt=attempt)
            except Exception:  # noqa: BLE001
                _provisioning_log.exception("farmer_provisioning_orphan_lookup_failed email_domain=%s",
                                            request.email.rsplit("@", 1)[-1])
                raise ProvisioningFailedError(compensated=False) from exc
            raise ProvisioningFailedError(compensated=self._compensate(orphan) if orphan else True) from exc
        try:
            body = self._repository.provision(
                organization_id=organization_id, actor_id=actor_id, user_id=user_id,
                full_name=request.full_name, phone=request.phone, farm=farm, plot=plot,
                prepare=lambda out: schemas.success_payload(schemas.FarmerProvisionResponse, {
                    **out, "email": request.email, "full_name": request.full_name,
                    "phone": request.phone, "temporary_password": password,
                }),
            )
        except Exception as exc:
            compensated = self._compensate(user_id)
            if compensated and isinstance(exc, (FarmCodeTakenError, PlotCodeTakenError, ProvisioningScopeError)):
                raise
            raise ProvisioningFailedError(compensated=compensated) from exc
        _provisioning_log.info("farmer_provisioned organization_id=%s actor_id=%s user_id=%s farm=%s plot=%s",
                               organization_id, actor_id, user_id, bool(farm), bool(plot))
        return body

    def create_farm(
        self, *, read_repository: SupabaseReadRepository, organization_id: str, request: schemas.FarmCreateRequest,
    ) -> dict[str, Any]:
        actor_id = self._actor(read_repository, organization_id)
        fields = request.model_dump(exclude={"owner_user_id"})
        return self._repository.create_farm(
            organization_id=organization_id, actor_id=actor_id, owner_user_id=str(request.owner_user_id), farm=fields,
            prepare=lambda out: schemas.success_payload(schemas.FarmCreatedResponse, out),
        )

    def create_plot(
        self, *, read_repository: SupabaseReadRepository, farm_id: str, request: schemas.PlotCreateRequest,
    ) -> dict[str, Any]:
        actor_id = self._actor(read_repository, farm_id)
        return self._repository.create_plot(
            farm_id=farm_id, actor_id=actor_id, plot=request.model_dump(),
            prepare=lambda out: schemas.success_payload(schemas.PlotCreatedResponse, out),
        )


class SeasonTransitionService:
    """End a crop season ("Kết thúc vụ") -- one path for Farmer and Management."""

    def __init__(self, repository: PostgresSeasonRepository):
        self._repository = repository

    def transition(
        self, *, read_repository: SupabaseReadRepository, crop_season_id: str,
        request: schemas.CropSeasonStatusUpdate,
    ) -> dict[str, Any]:
        try:
            uuid.UUID(crop_season_id)
            actor_id = read_repository.user_id()
        except (ValueError, ReadNotFoundError) as exc:
            raise SeasonScopeError() from exc
        return self._repository.transition(
            crop_season_id=crop_season_id, actor_id=actor_id, to_status=request.status,
            actual_harvest_date=request.actual_harvest_date,
            prepare=lambda row: schemas.success_payload(schemas.CropSeasonResponse, row),
        )


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
        # One transaction for the whole run: same rows as upserting each rule
        # then pruning, but a single DB connection and no window in which a
        # reader could see half of this run applied.
        return self._write_repository.save_generated(
            crop_season_id=crop_season_id, recs=candidates,
            prepare=lambda rows: [schemas.success_payload(schemas.RecommendationResponse, row) for row in rows],
        )

    def set_status(
        self, *, read_repository: SupabaseReadRepository, recommendation_id: str, status: str,
    ) -> dict[str, Any]:
        self._actor_and_farmer_scope(read_repository)
        try:
            existing = self._write_repository.get(recommendation_id)
            read_repository.season(str(existing["crop_season_id"]))
        except (ReadNotFoundError, RecommendationNotFoundError) as exc:
            raise RecommendationAccessError() from exc
        return self._write_repository.set_status(
            recommendation_id, status,
            prepare=lambda row: schemas.success_payload(schemas.RecommendationResponse, row),
        )


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
            try:
                image_id = self._write_repository.create_image(
                    crop_season_id=crop_season_id, uploaded_by=actor_id, storage_object_path=storage_path,
                    mime_type=content_type, file_size_bytes=len(file_bytes), sha256=sha256,
                )
            except Exception:
                # Same compensation as the MRV renderer: best-effort removal of
                # the object the failed row would have pointed at.
                try:
                    self._write_repository.delete_image_object(storage_path)
                except Exception:  # noqa: BLE001 - the original failure is the one to report
                    pass
                raise

        predicted = predict_with_model(image, self._model, self._config, self._threshold, self._temperature)
        # public.disease_label has no NULL state — 'unknown' is the schema's
        # own sentinel for "confidence below threshold" (brief FW M03 §17);
        # the API response maps it back to `label: null` below.
        predicted_label = predicted["label"] or "unknown"
        return self._write_repository.create_inference(
            image_id=image_id, model_version_id=model_version_id,
            predicted_label=predicted_label, confidence=predicted["confidence"], threshold_used=self._threshold,
            prepare=lambda row: schemas.success_payload(schemas.CvInferenceResponse, self._to_response(row)),
        )

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


class MrvExportAccessError(Exception):
    """Normalized to 404 so an export cannot enumerate other organizations' cases."""


class UnsupportedExportFormatError(Exception):
    """Asked for a format this part does not produce yet."""


class MrvExportService:
    """Assemble and persist an MRV evidence package.

    Everything it exports comes from a service or repository that already owns
    that data: scope and evidence from the RLS-bound read repository, resource
    metrics from `metrics()`, CO2e from `CarbonService.latest()`. No formula and
    no domain query is reimplemented here -- this class orders the reads,
    delegates shaping to `mrv.manifest`, and stores the result.

    Access is decided by an RLS-bound read of the case before any privileged
    connection is touched, exactly like the activity write path.
    """

    SUPPORTED_FORMATS = ("json", "xlsx", "pdf")

    JSON_MEDIA_TYPE = "application/json; charset=utf-8"
    XLSX_MEDIA_TYPE = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    PDF_MEDIA_TYPE = mrv_report_pdf.PDF_MEDIA_TYPE
    ARTIFACT_MEDIA_TYPES = {"xlsx": XLSX_MEDIA_TYPE, "pdf": PDF_MEDIA_TYPE}

    # A full-case evidence package is a Management capability, not a field one.
    # This is the same role `private.user_is_org_manager` keys on, and the same
    # authority `mrv_cases_insert`/`mrv_cases_update` already require: whoever
    # may create or change an MRV case may package it.
    #
    # `enterprise_viewer` and `regulator` are deliberately NOT included. They can
    # read a case through an `organization_data_grants` share, but letting a
    # grantee mint a persisted artifact attributed to themselves is a product
    # decision nobody has made; see docs/MRV_EXPORT_PACKAGE.md.
    MANAGEMENT_ROLE = "cooperative_manager"

    def __init__(self, export_repository: PostgresMrvExportRepository, carbon_service: CarbonService):
        self._exports = export_repository
        self._carbon = carbon_service

    @classmethod
    def _manages(cls, actor: dict[str, Any], organization_id: str) -> bool:
        """Python mirror of `private.user_is_org_manager`, including `ended_at`.

        Reads the membership rows `me()` already returned, so this costs no extra
        round trip. A lapsed membership is not management authority; the active
        rule is the shared `infrastructure.memberships` one, so this check can
        never disagree with `/v1/me` or the SQL helper. `me()` already drops ended
        rows — filtering again keeps this safe for any other actor source.
        """
        return any(
            str(membership.get("organization_id")) == str(organization_id)
            and str(membership.get("role")) == cls.MANAGEMENT_ROLE
            for membership in memberships.active_memberships(actor.get("organization_memberships") or [])
        )

    def _authorized_case(
        self, read_repository: SupabaseReadRepository, mrv_case_id: str, actor: dict[str, Any]
    ) -> dict[str, Any]:
        """Readable AND managed by the caller, or it does not exist as far as they know.

        Both misses raise the same error and become the same 404. A farmer who can
        read the case must not be able to tell the difference between "no such
        case" and "you may not export this one" -- that distinction is itself a
        disclosure, and 404-for-both is this API's existing convention.
        """
        try:
            case = read_repository.mrv_case_row(mrv_case_id)
        except ReadNotFoundError as exc:
            raise MrvExportAccessError() from exc
        if not self._manages(actor, str(case["organization_id"])):
            raise MrvExportAccessError()
        return case

    def create(
        self, *, read_repository: SupabaseReadRepository, mrv_case_id: str, fmt: str = "json",
    ) -> dict[str, Any]:
        """Produce an export of `fmt` for this case.

        There is exactly ONE assembly path. `xlsx` and `pdf` assemble nothing of
        their own: they take the canonical snapshot this call just produced and
        render it, so a rendering and its manifest can never disagree.
        """
        if fmt not in self.SUPPORTED_FORMATS:
            raise UnsupportedExportFormatError(fmt)

        view, row, manifest = self._create_snapshot(
            read_repository=read_repository, mrv_case_id=mrv_case_id,
            response_model=schemas.MrvExportCreatedResponse if fmt == "json" else None,
        )
        if fmt == "json":
            return view
        return self._render_from(
            read_repository=read_repository, snapshot_row=row, manifest=manifest, fmt=fmt,
            response_model=schemas.MrvExportCreatedResponse,
        )

    def render(
        self, *, read_repository: SupabaseReadRepository, export_id: str, fmt: str = "xlsx",
    ) -> dict[str, Any]:
        """Render an EXISTING snapshot into another format.

        This is the auditable path: the workbook demonstrably comes from a
        specific stored manifest rather than from data as it happens to look now.
        `json` is refused -- a snapshot is not re-derivable from itself, and
        allowing it would create a snapshot of a snapshot.
        """
        if fmt not in self.SUPPORTED_FORMATS or fmt == "json":
            raise UnsupportedExportFormatError(fmt)

        actor = read_repository.me()
        managed = self._managed_case_ids(read_repository, actor)
        try:
            row = self._exports.artifact_row(export_id, authorized_case_ids=managed)
        except MrvExportNotFoundError as exc:
            raise MrvExportAccessError() from exc
        if row["format"] != "json":
            # Renderers consume canonical snapshots, never other renderings.
            raise UnsupportedExportFormatError(row["format"])
        return self._render_from(
            read_repository=read_repository,
            snapshot_row=row,
            manifest=row["export_payload"],
            fmt=fmt,
            actor=actor,
            response_model=schemas.MrvArtifactResponse,
        )

    def _create_snapshot(
        self, *, read_repository: SupabaseReadRepository, mrv_case_id: str,
        response_model: type[schemas.BaseModel] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        """Assemble and persist one canonical snapshot.

        Returns (client view, stored row, manifest). The raw row is what a
        renderer needs -- it carries the lineage columns the view deliberately
        does not expose.
        """
        actor = read_repository.me()
        case = self._authorized_case(read_repository, mrv_case_id, actor)
        organization_id = str(case["organization_id"])

        # Reads that do not depend on each other, but kept sequential and small:
        # each is already batched internally, and an export is not on a
        # latency-critical path.
        steps = read_repository.mrv_steps(mrv_case_id)
        evidence_rows = read_repository.mrv_evidence_rows(mrv_case_id)
        scope_entries = read_repository.mrv_scope(mrv_case_id)
        try:
            organization = read_repository.organization(organization_id)
        except ReadNotFoundError:
            organization = None

        season_ids = sorted({
            str(e["crop_season_id"]) for e in scope_entries if e.get("crop_season_id")
        })
        activities = read_repository.export_activities(season_ids)

        # Batched: one pass for every season on the case, not a request chain
        # per season. Same computation the dashboards use.
        metrics_by_season = read_repository.metrics_for_seasons(season_ids)
        carbon_by_season: dict[str, dict[str, Any] | None] = {}
        for sid in season_ids:
            try:
                # M3: only the recorded (`as_recorded` <-> DB `actual`) calculation is
                # the season's result. AWD / continuous-flooding rows are what-if
                # scenarios and must never be exported as if they were measured;
                # Resource Metrics already reads `actual` only. No row -> the
                # section is `unavailable` with a warning, never another scenario.
                carbon_by_season[sid] = self._carbon.latest(sid, "as_recorded")
            except Exception:  # noqa: BLE001 - carbon being unreadable is a warning, not a failed export
                carbon_by_season[sid] = None

        factor_set_ids = [
            row.get("factor_set_id") for row in carbon_by_season.values() if row
        ]
        factor_sets, factors_by_set = read_repository.emission_factor_provenance(
            [str(x) for x in factor_set_ids if x]
        )

        export_id = mrv_manifest.new_export_id()
        generated_at = datetime.now(timezone.utc)
        manifest = mrv_manifest.build_manifest(mrv_manifest.ManifestInputs(
            export_id=export_id,
            generated_at=generated_at,
            generated_by=self._actor_metadata(actor),
            case=case,
            organization=organization,
            scope_entries=scope_entries,
            steps=steps,
            evidence=evidence_rows,
            activities=activities,
            metrics_by_season=metrics_by_season,
            carbon_by_season=carbon_by_season,
            factor_sets=factor_sets,
            factors_by_set=factors_by_set,
        ))

        # Two digests, two questions. `payload_sha256` answers "which snapshot",
        # `file_sha256` answers "which bytes were served". For JSON the served
        # bytes are the canonical manifest INCLUDING package_integrity, so the
        # two differ even here -- the manifest digest deliberately excludes its
        # own integrity block.
        payload_sha256 = manifest["package_integrity"]["manifest_sha256"]
        artifact_bytes = mrv_manifest.canonical_bytes(manifest)
        artifact_sha256 = hashlib.sha256(artifact_bytes).hexdigest()
        filename = mrv_manifest.export_filename(str(case["case_code"]), generated_at, export_id)
        row = self._exports.create(
            export_id=export_id,
            mrv_case_id=mrv_case_id,
            organization_id=organization_id,
            # A snapshot is always json: it IS the canonical manifest. Other
            # formats are renderings of it and are created by `_render_from`.
            fmt="json",
            factor_set_id=next((str(x) for x in factor_set_ids if x), None),
            scope_description=self._scope_description(case, scope_entries),
            data_as_of_at=generated_at,
            warning_text=mrv_manifest.DISCLAIMER,
            storage_object_path=f"{organization_id}/{mrv_case_id}/{filename}",
            file_sha256=artifact_sha256,
            payload=manifest,
            payload_sha256=payload_sha256,
            generated_by=str(actor["user_id"]),
            generated_at=generated_at,
            calculation_ids=[
                str(row["id"]) for row in carbon_by_season.values()
                if row and row.get("id")
            ],
            # When this snapshot IS the response (json), its representation is
            # validated before the row commits; the raw row is kept for callers
            # that go on to render it.
            prepare=lambda stored: (stored, schemas.success_payload(
                response_model, self._export_view(stored) | {"manifest": manifest},
            ) if response_model is not None else None),
        )
        row, view = row
        return (view if view is not None else self._export_view(row) | {"manifest": manifest}), row, manifest

    def download(
        self, *, read_repository: SupabaseReadRepository, export_id: str,
    ) -> tuple[bytes, str, str]:
        """Return (bytes, filename, media type) for a stored export. Never rebuilds.

        Scoped to cases the caller MANAGES, not merely ones they can read, so a
        known export id is not a way around the generation restriction.

        The bytes are checked against `file_sha256` before being served. A
        mismatch fails closed: serving an artifact that does not match its own
        record would defeat the point of recording a digest at all.
        """
        actor = read_repository.me()
        managed = self._managed_case_ids(read_repository, actor)
        try:
            row = self._exports.artifact_row(export_id, authorized_case_ids=managed)
        except MrvExportNotFoundError as exc:
            raise MrvExportAccessError() from exc

        filename = str(row["storage_object_path"]).rsplit("/", 1)[-1]
        if row["format"] == "json":
            # The canonical manifest IS the artifact; no object is stored for it.
            payload = row["export_payload"]
            data = mrv_manifest.canonical_bytes(payload)
            media_type = self.JSON_MEDIA_TYPE
            # Check the snapshot against its own self-describing digest. That is
            # stronger than re-hashing bytes we just serialized ourselves, and it
            # also validates rows written before `payload_sha256` existed.
            recorded = row.get("payload_sha256") or (
                payload.get("package_integrity") or {}
            ).get("manifest_sha256")
            actual = mrv_manifest.manifest_checksum(payload)
        else:
            media_type = self.ARTIFACT_MEDIA_TYPES.get(str(row["format"]))
            if media_type is None:
                raise UnsupportedExportFormatError(row["format"])
            data = self._exports.get_artifact(row["storage_object_path"])
            recorded = row.get("file_sha256")
            actual = hashlib.sha256(data).hexdigest()

        if recorded and actual != recorded:
            raise MrvArtifactCorruptError(export_id)
        return data, filename, media_type

    def _render_from(
        self, *, read_repository: SupabaseReadRepository, snapshot_row: dict[str, Any],
        manifest: dict[str, Any], fmt: str, actor: dict[str, Any] | None = None,
        response_model: type[schemas.BaseModel] = schemas.MrvArtifactResponse,
    ) -> dict[str, Any]:
        """Render one stored manifest into an artifact and persist it.

        The ONLY input is `manifest`. Nothing here reads an activity, a metric or
        a carbon result; if it did, the artifact could disagree with the snapshot
        it claims to render.
        """
        actor = actor or read_repository.me()
        mrv_case_id = str(snapshot_row["mrv_case_id"])
        organization_id = str(manifest.get("case", {}).get("organization_id") or "")
        case_code = str(manifest.get("case", {}).get("case_code") or "case")
        snapshot_id = str(snapshot_row["id"])
        payload_sha256 = (manifest.get("package_integrity") or {}).get("manifest_sha256")

        export_id = mrv_manifest.new_export_id()
        rendered_at = datetime.now(timezone.utc)
        # Rendering happens entirely in memory before anything is written, so a
        # renderer failure leaves no object, no row, and the snapshot untouched.
        if fmt == "pdf":
            data = mrv_report_pdf.render_pdf(manifest, export_id=export_id, rendered_at=rendered_at)
            filename = mrv_report_pdf.report_filename(case_code, manifest.get("generated_at"), export_id)
        else:
            data = mrv_workbook.render_workbook(manifest, rendered_at=rendered_at)
            filename = mrv_workbook.workbook_filename(
                case_code, manifest.get("generated_at"), export_id
            )
        artifact_sha256 = hashlib.sha256(data).hexdigest()
        object_path = f"{organization_id}/{mrv_case_id}/{filename}"

        # Object first: a metadata row pointing at nothing is worse than an
        # orphaned object, because the row promises a retrievable artifact.
        self._exports.put_artifact(object_path, data, self.ARTIFACT_MEDIA_TYPES[fmt])
        try:
            # The response is validated inside the row's transaction, so a
            # representation failure rolls the row back and lands in the
            # object cleanup below instead of 500ing a committed export.
            return self._create_rendered_row(
                export_id=export_id, mrv_case_id=mrv_case_id, organization_id=organization_id,
                fmt=fmt, snapshot_row=snapshot_row, object_path=object_path,
                artifact_sha256=artifact_sha256, manifest=manifest, payload_sha256=payload_sha256,
                snapshot_id=snapshot_id, actor=actor, rendered_at=rendered_at,
                prepare=lambda row: schemas.success_payload(
                    response_model, {**self._export_view(row), "byte_size": len(data)}),
            )
        except Exception:
            # Best effort: do not leave an object no row points at. If this delete
            # also fails, the orphan is still found by the documented cleanup,
            # which enumerates storage.objects by the case prefix.
            try:
                self._exports.delete_artifact(object_path)
            except Exception:  # noqa: BLE001 - the original failure is the one to report
                pass
            raise

    def _create_rendered_row(
        self, *, export_id: str, mrv_case_id: str, organization_id: str, fmt: str,
        snapshot_row: dict[str, Any], object_path: str, artifact_sha256: str,
        manifest: dict[str, Any], payload_sha256: str | None, snapshot_id: str,
        actor: dict[str, Any], rendered_at: datetime,
        prepare: Any = None,
    ) -> Any:
        return self._exports.create(
            export_id=export_id,
            mrv_case_id=mrv_case_id,
            organization_id=organization_id,
            fmt=fmt,
            factor_set_id=snapshot_row.get("factor_set_id"),
            scope_description=str(snapshot_row["scope_description"]),
            data_as_of_at=snapshot_row["data_as_of_at"],
            warning_text=mrv_manifest.DISCLAIMER,
            storage_object_path=object_path,
            file_sha256=artifact_sha256,
            payload=manifest,
            payload_sha256=payload_sha256,
            source_snapshot_export_id=snapshot_id,
            generated_by=str(actor["user_id"]),
            generated_at=rendered_at,
            calculation_ids=[],
            prepare=prepare,
        )
        return {**self._export_view(row), "byte_size": len(data)}

    def _managed_case_ids(
        self, read_repository: SupabaseReadRepository, actor: dict[str, Any]
    ) -> list[str]:
        return [
            str(scope["id"]) for scope in read_repository.mrv_case_scopes()
            if self._manages(actor, str(scope["organization_id"]))
        ]

    @staticmethod
    def _actor_metadata(actor: dict[str, Any]) -> dict[str, Any]:
        """Only the identity and roles. Never a token, a claim set or a session."""
        return {
            "user_id": str(actor["user_id"]),
            "roles": sorted(actor.get("roles") or []),
        }

    @staticmethod
    def _scope_description(case: dict[str, Any], entries: list[dict[str, Any]]) -> str:
        seasons = sorted({str(e.get("season_code")) for e in entries if e.get("season_code")})
        suffix = ", ".join(seasons) if seasons else "chưa gắn vụ canh tác"
        return f"Hồ sơ {case.get('case_code')} — {suffix}"

    @staticmethod
    def _export_view(row: dict[str, Any]) -> dict[str, Any]:
        """What a client is told about an export.

        `storage_bucket` / `storage_object_path` are deliberately NOT here. They
        name a real private object now that XLSX artifacts exist, and no client
        has any use for them -- the download route already supplies the filename.
        Only the filename is surfaced.
        """
        return {
            "export_id": row["id"], "mrv_case_id": row["mrv_case_id"],
            "format": row["format"], "schema_version": mrv_manifest.MANIFEST_SCHEMA_VERSION,
            "status": "generated",
            "generated_at": mrv_manifest.iso_utc(row["generated_at"]),
            "generated_by": row["generated_by"],
            "file_sha256": row["file_sha256"],
            "payload_sha256": row.get("payload_sha256"),
            "source_snapshot_export_id": row.get("source_snapshot_export_id"),
            "file_name": str(row["storage_object_path"]).rsplit("/", 1)[-1],
            "scope_description": row["scope_description"],
            "warning_text": row["warning_text"],
            "is_finalized": row["is_finalized"],
        }

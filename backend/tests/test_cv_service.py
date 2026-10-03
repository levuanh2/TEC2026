"""M03 CV service + API tests: upload validation, inference response shape,
authorization, persistence/idempotency, and the frozen error envelope.

Uses `ml.model.build_model(pretrained=False)` (random weights, offline, same
pattern as ml/tests/test_cv_pipeline.py) — these tests exercise the real
preprocessing/inference *pipeline* end to end, just not the trained
baseline's actual accuracy. Real-checkpoint reuse (the verified baseline
model itself) is proven separately in test_cv_real_model_smoke.py.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import api  # noqa: E402
from infrastructure.cv_repo import CvNotFoundError, DuplicateImageError  # noqa: E402
from infrastructure.read_repo import ReadNotFoundError  # noqa: E402
from ml.model import build_model  # noqa: E402
from infrastructure.crop_write_authz import CropWriteDeniedError  # noqa: E402
from service import CvAccessError, CvService, InvalidImageError, MAX_IMAGE_BYTES  # noqa: E402

ACTOR, SEASON, FARM, PLOT = "farmer-a", "season-a", "farm-a", "plot-a"


class FakeRead:
    def __init__(self, *, role: str = "farmer", visible: bool = True, actor: str = ACTOR):
        self.role, self.visible, self.actor = role, visible, actor

    def me(self):
        return {"user_id": self.actor, "roles": [self.role]}

    def season(self, season_id):
        if not self.visible:
            raise ReadNotFoundError("crop_seasons")
        return {"id": season_id, "plot_id": PLOT}

    def plot(self, plot_id):
        if not self.visible or plot_id != PLOT:
            raise ReadNotFoundError("plots")
        return {"id": PLOT, "farm_id": FARM}


class FakeCvRepository:
    def __init__(self):
        self.images: dict[str, dict] = {}
        self.inferences: dict[str, dict] = {}
        self.model_versions: dict[str, str] = {}
        self.model_version_codes: dict[str, str] = {}
        self.uploads: list[str] = []
        # Who `private.user_can_write_crop` says may write the season.
        self.writers: set[str] = {ACTOR}
        self._next = 1

    def assert_can_write(self, *, crop_season_id, actor_id):
        if actor_id not in self.writers:
            raise CropWriteDeniedError()

    def get_or_create_model_version(self, **kwargs):
        code = kwargs["version_code"]
        if code not in self.model_versions:
            self.model_versions[code] = f"mv-{len(self.model_versions) + 1}"
            self.model_version_codes[self.model_versions[code]] = code
        return self.model_versions[code]

    def find_image_by_sha(self, *, crop_season_id, sha256):
        for row in self.images.values():
            if row["sha256"] == sha256:
                if row["crop_season_id"] != crop_season_id:
                    raise DuplicateImageError()
                return {"id": row["id"], "crop_season_id": row["crop_season_id"]}
        return None

    def upload_image(self, *, farm_id, crop_season_id, file_bytes, mime_type, extension):
        path = f"{farm_id}/{crop_season_id}/fake-{self._next}.{extension}"
        self.uploads.append(path)
        return path

    def create_image(self, *, crop_season_id, uploaded_by, storage_object_path, mime_type, file_size_bytes, sha256):
        self.assert_can_write(crop_season_id=crop_season_id, actor_id=uploaded_by)
        image_id = f"img-{self._next}"
        self._next += 1
        self.images[image_id] = {"id": image_id, "crop_season_id": crop_season_id, "sha256": sha256}
        return image_id

    def find_inference(self, *, image_id, model_version_id):
        for row in self.inferences.values():
            if row["image_id"] == image_id and row["model_version_id"] == model_version_id:
                return dict(row)
        return None

    def create_inference(self, *, image_id, model_version_id, predicted_label, confidence, threshold_used, actor_id,
                         prepare=None):
        self.assert_can_write(crop_season_id=self.images[image_id]["crop_season_id"], actor_id=actor_id)
        inference_id = f"inf-{self._next}"
        self._next += 1
        crop_season_id = self.images[image_id]["crop_season_id"]
        row = {
            "id": inference_id, "crop_season_id": crop_season_id, "image_id": image_id,
            "model_version_id": model_version_id, "predicted_label": predicted_label,
            "confidence": confidence, "threshold_used": threshold_used,
            "is_uncertain": confidence < threshold_used, "inferred_at": "2026-09-11T00:00:00Z",
            "version_code": self.model_version_codes.get(model_version_id, "unknown-version"),
        }
        self.inferences[inference_id] = row
        return prepare(dict(row)) if prepare is not None else dict(row)

    def get_inference(self, inference_id):
        if inference_id not in self.inferences:
            raise CvNotFoundError()
        return dict(self.inferences[inference_id])

    def list_inferences(self, crop_season_id):
        return [dict(r) for r in self.inferences.values() if r["crop_season_id"] == crop_season_id]


def _fake_jpeg_bytes(size=(64, 64)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=(120, 180, 90)).save(buf, format="JPEG")
    return buf.getvalue()


def _fake_png_bytes(size=(64, 64)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=(80, 140, 70)).save(buf, format="PNG")
    return buf.getvalue()


def _service(repo: FakeCvRepository | None = None, threshold: float = 0.5) -> CvService:
    model = build_model(pretrained=False, freeze_backbone=False)
    model.eval()
    config = {"image_size": 224, "run_name": "test-run"}
    model_meta = {
        "version_code": "test-run", "model_name": "test-model", "test_dataset_name": "test-dataset",
        "test_dataset_version": None, "test_sample_count": 10, "accuracy": 0.5,
        "confusion_matrix": {}, "confidence_threshold": threshold, "source_reference": None,
    }
    return CvService(model, config, threshold, 1.0, model_meta, repo or FakeCvRepository())


CANONICAL_LABELS = {"rice_blast", "bacterial_leaf_blight", "brown_spot", "healthy"}


# ===========================================================================
# Upload validation
# ===========================================================================


def test_valid_jpeg_accepted():
    result = _service().infer(read_repository=FakeRead(), crop_season_id=SEASON, file_bytes=_fake_jpeg_bytes(), content_type="image/jpeg")
    assert 0.0 <= result["confidence"] <= 1.0


def test_valid_png_accepted():
    result = _service().infer(read_repository=FakeRead(), crop_season_id=SEASON, file_bytes=_fake_png_bytes(), content_type="image/png")
    assert 0.0 <= result["confidence"] <= 1.0


def test_invalid_mime_type_rejected():
    with pytest.raises(InvalidImageError) as exc:
        _service().infer(read_repository=FakeRead(), crop_season_id=SEASON, file_bytes=_fake_jpeg_bytes(), content_type="application/pdf")
    assert exc.value.code == "unsupported_image_type"


def test_corrupt_file_rejected():
    with pytest.raises(InvalidImageError) as exc:
        _service().infer(read_repository=FakeRead(), crop_season_id=SEASON, file_bytes=b"this is not an image", content_type="image/jpeg")
    assert exc.value.code == "invalid_image"


def test_oversized_image_rejected():
    with pytest.raises(InvalidImageError) as exc:
        _service().infer(read_repository=FakeRead(), crop_season_id=SEASON, file_bytes=b"\xff" * (MAX_IMAGE_BYTES + 1), content_type="image/jpeg")
    assert exc.value.code == "image_too_large"


def test_empty_file_rejected():
    with pytest.raises(InvalidImageError) as exc:
        _service().infer(read_repository=FakeRead(), crop_season_id=SEASON, file_bytes=b"", content_type="image/jpeg")
    assert exc.value.code == "empty_image"


# ===========================================================================
# Inference response contract
# ===========================================================================


def test_response_contains_expected_shape():
    result = _service().infer(read_repository=FakeRead(), crop_season_id=SEASON, file_bytes=_fake_jpeg_bytes(), content_type="image/jpeg")
    expected_keys = {"id", "crop_season_id", "image_id", "label", "label_vi", "confidence", "uncertain", "threshold_used", "model_version", "created_at"}
    assert expected_keys.issubset(result.keys())


def test_uncertain_result_never_leaks_a_label():
    service = _service(threshold=1.01)  # confidence can never reach this -> always uncertain
    result = service.infer(read_repository=FakeRead(), crop_season_id=SEASON, file_bytes=_fake_jpeg_bytes(), content_type="image/jpeg")
    assert result["uncertain"] is True
    assert result["label"] is None
    assert result["label_vi"] is None


def test_confident_result_has_a_canonical_label():
    service = _service(threshold=0.0)  # any confidence clears this -> always confident
    result = service.infer(read_repository=FakeRead(), crop_season_id=SEASON, file_bytes=_fake_jpeg_bytes(), content_type="image/jpeg")
    assert result["uncertain"] is False
    assert result["label"] in CANONICAL_LABELS
    assert result["label_vi"] is not None


def test_model_version_is_traceable():
    result = _service().infer(read_repository=FakeRead(), crop_season_id=SEASON, file_bytes=_fake_jpeg_bytes(), content_type="image/jpeg")
    assert result["model_version"] == "test-run"


# ===========================================================================
# Authorization
# ===========================================================================


@pytest.mark.parametrize("read", [FakeRead(role="cooperative_manager"), FakeRead(visible=False)])
def test_non_farmer_or_cross_scope_cannot_infer(read):
    with pytest.raises(CvAccessError):
        _service().infer(read_repository=read, crop_season_id=SEASON, file_bytes=_fake_jpeg_bytes(), content_type="image/jpeg")


def test_manager_can_list_and_get_but_never_calls_infer_in_this_test():
    repo = FakeCvRepository()
    service = _service(repo)
    created = service.infer(read_repository=FakeRead(), crop_season_id=SEASON, file_bytes=_fake_jpeg_bytes(), content_type="image/jpeg")
    manager_read = FakeRead(role="cooperative_manager")
    items = service.list(read_repository=manager_read, crop_season_id=SEASON)
    assert any(i["id"] == created["id"] for i in items)
    fetched = service.get(read_repository=manager_read, inference_id=created["id"])
    assert fetched["id"] == created["id"]


def test_a_reader_without_write_authority_uploads_nothing():
    """Viewer is read-only (product decision 2026-10-03): a farm viewer or a
    former owner READS the season, may hold a farmer role, but
    `user_can_write_crop` says no -- refused like an unknown id, before a byte
    reaches Storage."""
    repo = FakeCvRepository()
    with pytest.raises(CvAccessError):
        _service(repo).infer(read_repository=FakeRead(actor="viewer-or-former-owner"), crop_season_id=SEASON,
                             file_bytes=_fake_jpeg_bytes(), content_type="image/jpeg")
    assert repo.uploads == [] and repo.images == {} and repo.inferences == {}


def test_write_authority_lost_after_the_early_check_still_refuses_and_cleans_storage():
    """The row writes re-check in their own transaction; a refusal there is the
    same 404 and the uploaded object is removed."""
    class Revoking(FakeCvRepository):
        removed: list[str] = []

        def assert_can_write(self, *, crop_season_id, actor_id):
            if self.uploads:  # authority gone by the time the row is written
                raise CropWriteDeniedError()

        def delete_image_object(self, object_path):
            self.removed.append(object_path)

    repo = Revoking()
    with pytest.raises(CvAccessError):
        _service(repo).infer(read_repository=FakeRead(), crop_season_id=SEASON,
                             file_bytes=_fake_jpeg_bytes(), content_type="image/jpeg")
    assert repo.images == {} and repo.inferences == {} and repo.removed == repo.uploads


def test_cross_scope_list_normalizes_to_404():
    with pytest.raises(CvAccessError):
        _service().list(read_repository=FakeRead(visible=False), crop_season_id=SEASON)


def test_cross_scope_get_normalizes_to_404():
    repo = FakeCvRepository()
    service = _service(repo)
    created = service.infer(read_repository=FakeRead(), crop_season_id=SEASON, file_bytes=_fake_jpeg_bytes(), content_type="image/jpeg")
    with pytest.raises(CvAccessError):
        service.get(read_repository=FakeRead(visible=False), inference_id=created["id"])


def test_unknown_inference_id_normalizes_to_404():
    with pytest.raises(CvAccessError):
        _service().get(read_repository=FakeRead(), inference_id="does-not-exist")


# ===========================================================================
# Persistence / idempotency
# ===========================================================================


def test_same_image_bytes_are_reused_not_reuploaded():
    repo = FakeCvRepository()
    service = _service(repo)
    image_bytes = _fake_jpeg_bytes()
    first = service.infer(read_repository=FakeRead(), crop_season_id=SEASON, file_bytes=image_bytes, content_type="image/jpeg")
    second = service.infer(read_repository=FakeRead(), crop_season_id=SEASON, file_bytes=image_bytes, content_type="image/jpeg")
    assert first["id"] == second["id"]
    assert first["image_id"] == second["image_id"]
    assert len(repo.uploads) == 1


def test_duplicate_image_across_different_seasons_is_rejected():
    repo = FakeCvRepository()
    service = _service(repo)
    image_bytes = _fake_jpeg_bytes()
    service.infer(read_repository=FakeRead(), crop_season_id=SEASON, file_bytes=image_bytes, content_type="image/jpeg")
    with pytest.raises(InvalidImageError) as exc:
        service.infer(read_repository=FakeRead(), crop_season_id="season-b", file_bytes=image_bytes, content_type="image/jpeg")
    assert exc.value.code == "duplicate_image"


def test_plant_image_and_inference_are_linked_correctly():
    repo = FakeCvRepository()
    service = _service(repo)
    result = service.infer(read_repository=FakeRead(), crop_season_id=SEASON, file_bytes=_fake_jpeg_bytes(), content_type="image/jpeg")
    assert result["image_id"] in repo.images
    assert repo.images[result["image_id"]]["crop_season_id"] == SEASON


# ===========================================================================
# Route-level: auth envelope, error mapping, unavailable-service behavior
# ===========================================================================


def _write_client(read=None, cv_service=None) -> TestClient:
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api._read_repo] = lambda: read or FakeRead()
    app.dependency_overrides[api._cv_service] = lambda: cv_service or _service()
    return TestClient(app)


def test_infer_route_requires_bearer_authentication():
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api._cv_service] = lambda: _service()
    response = TestClient(app).post(
        f"/v1/crop-seasons/{SEASON}/cv/infer", files={"file": ("leaf.jpg", _fake_jpeg_bytes(), "image/jpeg")},
    )
    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "unauthenticated"


def test_infer_route_returns_normalized_response():
    client = _write_client()
    response = client.post(
        f"/v1/crop-seasons/{SEASON}/cv/infer", files={"file": ("leaf.jpg", _fake_jpeg_bytes(), "image/jpeg")},
        headers={"Authorization": "Bearer t"},
    )
    assert response.status_code == 200
    body = response.json()
    assert {"id", "confidence", "uncertain", "model_version"}.issubset(body.keys())


def test_infer_route_invalid_mime_maps_to_domain_error_not_raw_500():
    client = _write_client()
    response = client.post(
        f"/v1/crop-seasons/{SEASON}/cv/infer", files={"file": ("leaf.pdf", b"not an image", "application/pdf")},
        headers={"Authorization": "Bearer t"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error"]["code"] == "unsupported_image_type"


def test_infer_route_cross_scope_normalizes_to_404():
    client = _write_client(read=FakeRead(visible=False))
    response = client.post(
        f"/v1/crop-seasons/{SEASON}/cv/infer", files={"file": ("leaf.jpg", _fake_jpeg_bytes(), "image/jpeg")},
        headers={"Authorization": "Bearer t"},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["error"]["code"] == "not_found"


def test_list_then_get_routes():
    repo = FakeCvRepository()
    svc = _service(repo)
    client = _write_client(cv_service=svc)
    created = client.post(
        f"/v1/crop-seasons/{SEASON}/cv/infer", files={"file": ("leaf.jpg", _fake_jpeg_bytes(), "image/jpeg")},
        headers={"Authorization": "Bearer t"},
    ).json()

    listed = client.get(f"/v1/crop-seasons/{SEASON}/cv/inferences", headers={"Authorization": "Bearer t"})
    assert listed.status_code == 200
    assert any(i["id"] == created["id"] for i in listed.json()["items"])

    got = client.get(f"/v1/cv/inferences/{created['id']}", headers={"Authorization": "Bearer t"})
    assert got.status_code == 200
    assert got.json()["id"] == created["id"]


def test_cv_service_unavailable_returns_503_not_a_raw_500():
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api._read_repo] = lambda: FakeRead()
    # api._cv_service intentionally left unconfigured -> the default stub.
    response = TestClient(app).post(
        f"/v1/crop-seasons/{SEASON}/cv/infer", files={"file": ("leaf.jpg", _fake_jpeg_bytes(), "image/jpeg")},
        headers={"Authorization": "Bearer t"},
    )
    assert response.status_code == 503
    assert response.json()["detail"]["error"]["code"] == "backend_not_configured"

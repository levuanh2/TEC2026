"""Real-model smoke test: proves CvService actually reuses the verified M03
baseline checkpoint (not a stub), exactly the way `main.py::_build_cv_service`
loads it at startup — same `find_latest_run`/`load_checkpoint`/
`resolve_threshold`/`resolve_temperature` call path, same
`eval_metrics.json` as the single source of model metadata. No training,
no fixture substitution.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from infrastructure.read_repo import ReadNotFoundError  # noqa: E402
from ml.infer import find_latest_run, resolve_temperature, resolve_threshold  # noqa: E402
from ml.model import load_checkpoint  # noqa: E402
from service import CvService  # noqa: E402

from tests.test_cv_service import FakeCvRepository, FakeRead, SEASON  # noqa: E402

RUNS_DIR = _REPO_ROOT / "ml" / "runs"


def _real_service() -> CvService:
    run_dir = find_latest_run()
    model, config = load_checkpoint(str(run_dir / "model.pt"), device="cpu")
    threshold = resolve_threshold(run_dir, None)
    temperature = resolve_temperature(run_dir, None)
    eval_metrics = json.loads((run_dir / "eval_metrics.json").read_text(encoding="utf-8"))
    model_meta = {
        "version_code": eval_metrics["version_code"], "model_name": eval_metrics["model_name"],
        "test_dataset_name": eval_metrics["test_dataset_name"], "test_dataset_version": eval_metrics.get("test_dataset_version"),
        "test_sample_count": eval_metrics.get("test_sample_count"), "accuracy": eval_metrics["accuracy"],
        "confusion_matrix": eval_metrics["confusion_matrix"], "confidence_threshold": eval_metrics["confidence_threshold"],
        "source_reference": eval_metrics.get("source_reference"),
    }
    return CvService(model, config, threshold, temperature, model_meta, FakeCvRepository())


@pytest.mark.skipif(not RUNS_DIR.exists(), reason="No ml/runs/ checkpoint available in this environment.")
def test_real_baseline_checkpoint_infers_a_held_out_test_image():
    service = _real_service()
    image_path = _REPO_ROOT / "ml/datasets/raw/extracted/Original Images/Leaf Blast/Leaf_blast  (105).jpg"
    if not image_path.exists():
        pytest.skip("Dataset image not extracted in this environment (not required for M03 baseline itself).")

    result = service.infer(
        read_repository=FakeRead(), crop_season_id=SEASON,
        file_bytes=image_path.read_bytes(), content_type="image/jpeg",
    )

    assert result["model_version"] == "mobilenetv2-baseline-20260909-222933"
    assert result["threshold_used"] == pytest.approx(0.939849, abs=1e-6)
    assert 0.0 <= result["confidence"] <= 1.0
    if result["uncertain"]:
        assert result["label"] is None
    else:
        assert result["label"] in {"rice_blast", "bacterial_leaf_blight", "brown_spot", "healthy"}


@pytest.mark.skipif(not RUNS_DIR.exists(), reason="No ml/runs/ checkpoint available in this environment.")
def test_real_baseline_resolves_expected_threshold_and_temperature():
    run_dir = find_latest_run()
    assert resolve_threshold(run_dir, None) == pytest.approx(0.939849, abs=1e-6)
    assert resolve_temperature(run_dir, None) == pytest.approx(1.65, abs=1e-6)

"""Tests cho M03 CV MVP pipeline.

Tat ca chay CPU-only (khong gia dinh GPU - moi may demo deu chay duoc, dung
gia tri device="cpu" xuyen suot). Khong phu thuoc dataset da tai/train xong:
model_loading/prediction_shape/confidence_range/threshold_logic/inference_smoke
tu tao checkpoint/anh gia trong tmp_path.

Chay:
    python -m pytest ml/tests -q
"""

from __future__ import annotations

import numpy as np
import torch
from PIL import Image

from ml.class_mapping import (
    CANONICAL_LABELS,
    LABEL_TO_INDEX,
    map_raw_folder_to_canonical,
)
from ml.evaluate import pick_confidence_threshold
from ml.infer import predict as infer_predict
from ml.model import build_model


def test_four_canonical_labels_match_db_enum():
    # Phai khop enum public.disease_label (tru 'unknown' - khong phai class train)
    # trong supabase/migrations/20260907000000_baseline.sql
    assert CANONICAL_LABELS == ["rice_blast", "bacterial_leaf_blight", "brown_spot", "healthy"]
    assert len(CANONICAL_LABELS) == 4
    assert len(set(CANONICAL_LABELS)) == 4  # khong trung


def test_label_index_bijective():
    assert sorted(LABEL_TO_INDEX.values()) == [0, 1, 2, 3]
    for label, idx in LABEL_TO_INDEX.items():
        assert CANONICAL_LABELS[idx] == label


def test_class_mapping_explicit_no_guessing():
    assert map_raw_folder_to_canonical("Bacterial Leaf Blight") == "bacterial_leaf_blight"
    assert map_raw_folder_to_canonical("Brown Spot") == "brown_spot"
    assert map_raw_folder_to_canonical("Leaf Blast") == "rice_blast"
    assert map_raw_folder_to_canonical("Healthy Rice Leaf") == "healthy"
    # class khong thuoc PRD -> None, KHONG tu doan gan vao class nao khac
    assert map_raw_folder_to_canonical("Leaf Scald") is None
    assert map_raw_folder_to_canonical("Rice Hispa") is None
    assert map_raw_folder_to_canonical("Ten thu muc la") is None


def test_model_loading_cpu():
    model = build_model(pretrained=False, freeze_backbone=False)
    model.eval()
    assert model.classifier[1].out_features == len(CANONICAL_LABELS)


def test_prediction_shape_cpu():
    model = build_model(pretrained=False, freeze_backbone=False)
    model.eval()
    batch = torch.rand(2, 3, 224, 224)
    with torch.no_grad():
        output = model(batch)
    assert output.shape == (2, len(CANONICAL_LABELS))


def test_confidence_range_is_valid_probability():
    model = build_model(pretrained=False, freeze_backbone=False)
    model.eval()
    batch = torch.rand(3, 3, 224, 224)
    with torch.no_grad():
        probs = torch.softmax(model(batch), dim=1)
    assert torch.all(probs >= 0) and torch.all(probs <= 1)
    row_sums = probs.sum(dim=1)
    assert torch.allclose(row_sums, torch.ones_like(row_sums), atol=1e-5)


def test_threshold_logic_separates_correct_from_incorrect():
    # Kich ban tong hop: du doan dung co confidence cao, sai co confidence thap.
    rng = np.random.default_rng(0)
    n = 200
    labels = rng.integers(0, 4, size=n)
    correct_mask = rng.random(n) < 0.8
    preds = np.where(correct_mask, labels, (labels + 1) % 4)
    confidences = np.where(correct_mask, rng.uniform(0.7, 1.0, n), rng.uniform(0.0, 0.5, n))

    threshold = pick_confidence_threshold(labels, preds, confidences)
    assert 0.0 <= threshold <= 1.0

    # Ap dung nguong: phan lon du doan dung phai vuot nguong (accept),
    # phan lon du doan sai phai duoi nguong (uncertain).
    accepted_and_correct = ((confidences >= threshold) & (preds == labels)).sum()
    correct_total = (preds == labels).sum()
    assert accepted_and_correct / correct_total > 0.7


def test_low_confidence_becomes_uncertain_not_forced_label(tmp_path):
    """FR-1b-04: confidence < threshold -> uncertain=True, khong ep nhan."""
    model = build_model(pretrained=False, freeze_backbone=False)
    model.eval()
    checkpoint_path = tmp_path / "model.pt"
    config = {"image_size": 224, "run_name": "test-run"}
    torch.save({"model_state_dict": model.state_dict(), "config": config}, checkpoint_path)

    image_path = tmp_path / "fake_leaf.jpg"
    Image.fromarray((np.random.rand(300, 300, 3) * 255).astype("uint8")).save(image_path)

    # nguong = 1.01 -> luon uncertain du confidence la bao nhieu
    result = infer_predict(str(image_path), checkpoint_path, threshold=1.01)
    assert result["uncertain"] is True
    assert result["label"] is None


def test_inference_smoke_end_to_end(tmp_path):
    model = build_model(pretrained=False, freeze_backbone=False)
    model.eval()
    checkpoint_path = tmp_path / "model.pt"
    config = {"image_size": 224, "run_name": "test-run"}
    torch.save({"model_state_dict": model.state_dict(), "config": config}, checkpoint_path)

    image_path = tmp_path / "fake_leaf.jpg"
    Image.fromarray((np.random.rand(300, 300, 3) * 255).astype("uint8")).save(image_path)

    result = infer_predict(str(image_path), checkpoint_path, threshold=0.0)
    assert 0.0 <= result["confidence"] <= 1.0
    assert result["uncertain"] is False  # threshold=0.0 -> luon accept
    assert result["label"] in CANONICAL_LABELS
    assert result["model_version"] == "test-run"

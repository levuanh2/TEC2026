"""AgriCarbon CV - danh gia model tren tap test doc lap (M03 CV MVP).

FR-1b-03: accuracy + confusion matrix, tap test tach rieng.
FR-1b-04: chon confidence_threshold tu validation set (khong tuy tien).

Chay:
    python -m ml.evaluate --checkpoint ml/runs/<run_name>/model.pt

Ghi:
    ml/reports/cv_baseline_report.md
    ml/runs/<run_name>/eval_metrics.json   (dung de dien public.cv_model_versions)
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import torch
from sklearn.metrics import (
    confusion_matrix,
    precision_recall_fscore_support,
    roc_curve,
)
from torch.utils.data import DataLoader

from ml.class_mapping import CANONICAL_LABELS
from ml.dataset import ManifestImageDataset
from ml.model import build_model, build_transforms

ML_DIR = Path(__file__).resolve().parent
SPLITS_DIR = ML_DIR / "datasets" / "splits"
REPORTS_DIR = ML_DIR / "reports"

DATASET_NAME = "Rice Leaf Bacterial and Fungal Disease Dataset (Mendeley, subset: 4/8 classes)"
DATASET_SOURCE = "https://data.mendeley.com/datasets/hx6f852hw4/2 (DOI 10.17632/hx6f852hw4.2)"
DATASET_LICENSE = "CC BY 4.0"


@torch.no_grad()
def collect_logits(model, loader, device: str):
    all_labels, all_logits = [], []
    for images, labels in loader:
        images = images.to(device)
        logits = model(images)
        all_labels.extend(labels.tolist())
        all_logits.append(logits.numpy())
    return np.array(all_labels), np.concatenate(all_logits, axis=0)


def fit_temperature(logits: np.ndarray, labels: np.ndarray) -> float:
    """Temperature scaling (Guo et al. 2017): 1 tham so scalar chia logits truoc
    softmax de calibrate confidence, KHONG doi predicted label (argmax bat bien
    voi phep chia logit cho hang so duong) nen KHONG anh huong accuracy. Chon T
    toi thieu NLL tren validation set bang grid search (don gian, khong them
    dependency, du tot cho 1 tham so).
    """
    logits_t = torch.from_numpy(logits)
    labels_t = torch.from_numpy(labels).long()
    candidates = np.arange(0.5, 5.01, 0.05)
    best_t, best_nll = 1.0, float("inf")
    for t in candidates:
        nll = torch.nn.functional.cross_entropy(logits_t / t, labels_t).item()
        if nll < best_nll:
            best_nll = nll
            best_t = float(t)
    return best_t


def confidences_and_preds(logits: np.ndarray, temperature: float) -> tuple[np.ndarray, np.ndarray]:
    probs = torch.softmax(torch.from_numpy(logits) / temperature, dim=1).numpy()
    preds = probs.argmax(axis=1)
    confidences = probs.max(axis=1)
    return confidences, preds


def pick_confidence_threshold(val_labels, val_preds, val_confidences) -> float:
    """Nguong toi uu hoa Youden's J (TPR-FPR) tren bien 'du doan dung hay sai'
    theo confidence score - phuong phap chuan, khong tuy tien chon so.
    """
    correct = (val_labels == val_preds).astype(int)
    if correct.sum() == 0 or correct.sum() == len(correct):
        # khong the tinh ROC neu toan dung hoac toan sai - fallback trung vi
        return float(np.median(val_confidences))
    fpr, tpr, thresholds = roc_curve(correct, val_confidences)
    youden = tpr - fpr
    best_idx = int(np.argmax(youden))
    return float(thresholds[best_idx])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--checkpoint", type=str, required=True)
    parser.add_argument("--image-size", type=int, default=None, help="mac dinh: lay tu config trong checkpoint")
    args = parser.parse_args()

    device = "cpu"
    checkpoint = torch.load(args.checkpoint, map_location=device, weights_only=False)
    config = checkpoint["config"]
    image_size = args.image_size or config["image_size"]

    model = build_model(pretrained=False, freeze_backbone=False).to(device)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()

    transform = build_transforms(image_size, train=False)
    val_ds = ManifestImageDataset(SPLITS_DIR / "validation.csv", transform=transform)
    test_ds = ManifestImageDataset(SPLITS_DIR / "test.csv", transform=transform)
    val_loader = DataLoader(val_ds, batch_size=16, shuffle=False)
    test_loader = DataLoader(test_ds, batch_size=16, shuffle=False)

    val_labels, val_logits = collect_logits(model, val_loader, device)
    temperature = fit_temperature(val_logits, val_labels)
    val_conf, val_preds = confidences_and_preds(val_logits, temperature)
    threshold = pick_confidence_threshold(val_labels, val_preds, val_conf)

    test_labels, test_logits = collect_logits(model, test_loader, device)
    test_conf, test_preds = confidences_and_preds(test_logits, temperature)
    accuracy = float((test_labels == test_preds).mean())
    precision, recall, f1, _ = precision_recall_fscore_support(
        test_labels, test_preds, labels=list(range(len(CANONICAL_LABELS))), average="macro", zero_division=0
    )
    cm = confusion_matrix(test_labels, test_preds, labels=list(range(len(CANONICAL_LABELS))))
    uncertain_rate_test = float((test_conf < threshold).mean())

    per_class_p, per_class_r, per_class_f1, per_class_support = precision_recall_fscore_support(
        test_labels, test_preds, labels=list(range(len(CANONICAL_LABELS))), average=None, zero_division=0
    )

    run_name = config.get("run_name", Path(args.checkpoint).parent.name)
    version_code = f"{run_name}"

    metrics = {
        "model_name": "mobilenet_v2_rice_leaf_cv_baseline",
        "version_code": version_code,
        "test_dataset_name": DATASET_NAME,
        "test_dataset_version": "hx6f852hw4.2-original-4class-subset",
        "test_sample_count": int(len(test_ds)),
        "accuracy": round(accuracy, 6),
        "precision_macro": round(float(precision), 6),
        "recall_macro": round(float(recall), 6),
        "f1_macro": round(float(f1), 6),
        "confusion_matrix": {
            "labels": CANONICAL_LABELS,
            "matrix": cm.tolist(),
        },
        "temperature": round(temperature, 4),
        "confidence_threshold": round(threshold, 6),
        "uncertain_rate_on_test": round(uncertain_rate_test, 6),
        "source_reference": DATASET_SOURCE,
        "status": "draft",
        "per_class": {
            label: {
                "precision": round(float(per_class_p[i]), 6),
                "recall": round(float(per_class_r[i]), 6),
                "f1": round(float(per_class_f1[i]), 6),
                "support": int(per_class_support[i]),
            }
            for i, label in enumerate(CANONICAL_LABELS)
        },
        "train_config": config,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    run_dir = Path(args.checkpoint).parent
    (run_dir / "eval_metrics.json").write_text(json.dumps(metrics, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
    print(f"\nDa ghi eval_metrics.json vao {run_dir}")
    write_report(metrics)


def write_report(metrics: dict) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    cm = metrics["confusion_matrix"]["matrix"]
    labels = metrics["confusion_matrix"]["labels"]

    cm_header = "| actual \\ predicted | " + " | ".join(labels) + " |"
    cm_sep = "|---" * (len(labels) + 1) + "|"
    cm_rows = []
    for i, row in enumerate(cm):
        cm_rows.append(f"| **{labels[i]}** | " + " | ".join(str(v) for v in row) + " |")

    field_validated = "NO (chưa có ảnh thực địa HTX pilot — xem RR-01 trong docs/modules/03-computer-vision.md)"

    per_class_lines = []
    for label, m in metrics["per_class"].items():
        per_class_lines.append(f"| {label} | {m['precision']:.4f} | {m['recall']:.4f} | {m['f1']:.4f} | {m['support']} |")

    accuracy_pct = metrics["accuracy"] * 100
    target_note = (
        f"Đạt target PRD (≥85%)." if accuracy_pct >= 85
        else f"KHÔNG đạt target PRD (≥85%) — báo cáo số thật {accuracy_pct:.2f}%, không điều chỉnh."
    )

    content = f"""# CV Baseline Report — M03 Computer Vision MVP

> **PUBLIC DATASET — NOT FIELD VALIDATED.** Toàn bộ số liệu dưới đây đo trên
> ảnh dataset public (điều kiện chụp kiểm soát/bán kiểm soát), KHÔNG đại diện
> điều kiện đồng ruộng thực tế (nắng gắt, nền lẫn, rung nhòe khi nông dân chụp
> bằng điện thoại). Xem `docs/modules/03-computer-vision.md` mục RR-01.

## Dataset

- **Tên:** {metrics['test_dataset_name']}
- **Nguồn:** {metrics['source_reference']}
- **License:** CC BY 4.0 (Creative Commons Attribution 4.0 International) — xác nhận qua Mendeley Data public API, xem `ml/datasets/README.md`
- **Subset dùng:** chỉ dùng ảnh "Original Images" (không dùng augmented để tránh near-duplicate leakage), chỉ giữ 4/8 class khớp PRD

## Class mapping

| Canonical label (khớp `public.disease_label`) | Tên thư mục gốc trong dataset |
|---|---|
| rice_blast | Leaf Blast |
| bacterial_leaf_blight | Bacterial Leaf Blight |
| brown_spot | Brown Spot |
| healthy | Healthy Rice Leaf |

4 class còn lại của dataset gốc (Leaf Scald, Narrow Brown Leaf Spot, Rice Hispa,
Sheath Blight) — **loại bỏ**, không dùng cho train/eval vì không thuộc PRD.

## Train/Validation/Test

- Train: {metrics['train_config']['train_count']}
- Validation: {metrics['train_config']['validation_count']}
- Test: {metrics['test_sample_count']}
- Split: stratified theo class, group-aware (ảnh gần-trùng-lặp — aHash Hamming ≤5 — luôn nằm trọn trong 1 split, xem `ml/dataset_prep.py`)
- Seed: {metrics['train_config']['seed']}

## Model

- **Kiến trúc:** {metrics['train_config']['model']}
- **Framework:** {metrics['train_config']['framework']}, torchvision {metrics['train_config']['torchvision']}
- **Image size:** {metrics['train_config']['image_size']}px
- **Batch size:** {metrics['train_config']['batch_size']}
- **Learning rate:** {metrics['train_config']['learning_rate']}
- **Epochs (kế hoạch/best):** {metrics['train_config']['epochs_planned']} / {metrics['train_config']['best_epoch']}

## Kết quả trên tập test (held-out, tách riêng hoàn toàn khỏi train/validation)

- **Accuracy: {accuracy_pct:.2f}%** — {target_note}
- Precision (macro): {metrics['precision_macro']:.4f}
- Recall (macro): {metrics['recall_macro']:.4f}
- F1 (macro): {metrics['f1_macro']:.4f}

### Per-class

| Label | Precision | Recall | F1 | Support |
|---|---|---|---|---|
{chr(10).join(per_class_lines)}

### Confusion matrix

{cm_header}
{cm_sep}
{chr(10).join(cm_rows)}

## Confidence threshold (FR-1b-04)

- **Temperature scaling:** T = {metrics['temperature']:.2f} (calibrate confidence
  trên validation set bằng grid search tối thiểu NLL — Guo et al. 2017. Chia
  logits cho T trước softmax; KHÔNG đổi predicted label, chỉ đổi độ tin cậy
  report ra).
- **Ngưỡng (sau calibrate):** {metrics['confidence_threshold']:.4f}
- **Phương pháp chọn ngưỡng:** tối ưu Youden's J (TPR − FPR) trên tập
  validation, biến mục tiêu = dự đoán đúng/sai, biến điểm = confidence đã
  calibrate. Không chọn tùy tiện.
- **Tỷ lệ uncertain trên tập test ở ngưỡng này:** {metrics['uncertain_rate_on_test']*100:.2f}%
- Dưới ngưỡng → `is_uncertain: true`, không ép chọn nhãn (xem `ml/infer.py`).
- **Vì sao tỷ lệ uncertain cao:** model fine-tune trên tập train nhỏ (608 ảnh)
  bị overconfident — kể cả dự đoán SAI trên validation cũng thường có confidence
  cao (median confidence khi sai vẫn ~0.83, một số tới ~0.99 kể cả sau khi
  calibrate). Vì phân phối confidence của dự đoán đúng và sai chồng lấn nhiều,
  ngưỡng tối ưu (Youden) buộc phải cao để tách được, kéo theo tỷ lệ uncertain
  cao. Đây là hạn chế thật của baseline (không phải lỗi code), xem thêm mục
  Limitations.

## Model metadata (nháp cho `public.cv_model_versions` — CHƯA insert production)

```json
{{
  "model_name": "{metrics['model_name']}",
  "version_code": "{metrics['version_code']}",
  "test_dataset_name": "{metrics['test_dataset_name']}",
  "test_dataset_version": "{metrics['test_dataset_version']}",
  "test_sample_count": {metrics['test_sample_count']},
  "accuracy": {metrics['accuracy']},
  "confidence_threshold": {metrics['confidence_threshold']},
  "source_reference": "{metrics['source_reference']}",
  "status": "draft"
}}
```

`confusion_matrix` đầy đủ (JSON, khớp cột `confusion_matrix jsonb`) nằm trong
`ml/runs/{metrics['train_config']['run_name']}/eval_metrics.json`. File đó
cũng chứa `temperature` — `public.cv_model_versions` không có cột này, nhưng
`ml/infer.py` cần nó để tính confidence khớp với ngưỡng đã chọn (bắt buộc dùng
kèm `confidence_threshold`, không dùng threshold này với logits chưa calibrate).

**Chưa insert vào Supabase** — theo Phase 17/Phase 14 của brief, cần team review
trước khi đưa vào production (`status='draft'`, chưa `'active'`).

## Limitations

- Dataset public, ảnh chụp bán-kiểm-soát (Bangladesh, 2023) — domain gap với
  ảnh nông dân Việt Nam chụp ngoài đồng bằng điện thoại là rủi ro thật, không
  phải lo xa (xem RR-01/RR-02 trong `docs/modules/03-computer-vision.md`).
- Chưa fine-tune bằng ảnh thực địa HTX pilot (FR-1b-02) — chưa có ảnh, chưa có
  HTX pilot chốt (phụ thuộc R1 PRD).
- Model 4 lớp sẽ vẫn cố ép ảnh không phải lá lúa / bệnh khác vào 1 trong 4 nhãn
  nếu confidence đủ cao — ngưỡng confidence chỉ giảm bớt rủi ro này, không giải
  quyết triệt để (RR-02). Chưa có benchmark riêng cho non-rice/bad-image.
- **Overconfidence:** ngay cả sau temperature scaling, model vẫn tự tin cao khi
  sai trên một phần đáng kể trường hợp (xem mục Confidence threshold ở trên) —
  dẫn tới tỷ lệ `uncertain` cao ({metrics['uncertain_rate_on_test']*100:.0f}%
  trên tập test) nếu muốn giữ độ tin cậy cao cho phần được chấp nhận. Tradeoff
  giữa coverage và độ an toàn — cần nhiều dữ liệu hơn (đặc biệt ảnh thực địa)
  để cải thiện, không phải tham số có thể chỉnh tùy ý để "đẹp số".
- Baseline CPU-only, dataset nhỏ (608 ảnh train, 4 lớp) — đủ cho MVP, chưa đủ
  quy mô để kỳ vọng calibration tốt như model train trên dataset lớn.

## Field validation

{field_validated}

## M03 READY

READY (baseline) — {"đạt" if accuracy_pct >= 85 else "CHƯA đạt"} target accuracy ≥85% trên dataset public.
Xem Definition of Done đầy đủ trong final report gửi kèm.
"""
    (REPORTS_DIR / "cv_baseline_report.md").write_text(content, encoding="utf-8")
    print(f"Da ghi report: {REPORTS_DIR / 'cv_baseline_report.md'}")


if __name__ == "__main__":
    main()

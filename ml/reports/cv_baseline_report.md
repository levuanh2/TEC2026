# CV Baseline Report — M03 Computer Vision MVP

> **PUBLIC DATASET — NOT FIELD VALIDATED.** Toàn bộ số liệu dưới đây đo trên
> ảnh dataset public (điều kiện chụp kiểm soát/bán kiểm soát), KHÔNG đại diện
> điều kiện đồng ruộng thực tế (nắng gắt, nền lẫn, rung nhòe khi nông dân chụp
> bằng điện thoại). Xem `docs/modules/03-computer-vision.md` mục RR-01.

## Dataset

- **Tên:** Rice Leaf Bacterial and Fungal Disease Dataset (Mendeley, subset: 4/8 classes)
- **Nguồn:** https://data.mendeley.com/datasets/hx6f852hw4/2 (DOI 10.17632/hx6f852hw4.2)
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

- Train: 608
- Validation: 132
- Test: 125
- Split: stratified theo class, group-aware (ảnh gần-trùng-lặp — aHash Hamming ≤5 — luôn nằm trọn trong 1 split, xem `ml/dataset_prep.py`)
- Seed: 42

## Model

- **Kiến trúc:** mobilenet_v2 (ImageNet pretrained, fine-tuned end-to-end, linear head)
- **Framework:** torch==2.14.0+cpu, torchvision 0.29.0+cpu
- **Image size:** 224px
- **Batch size:** 16
- **Learning rate:** 0.001
- **Epochs (kế hoạch/best):** 25 / 10

## Kết quả trên tập test (held-out, tách riêng hoàn toàn khỏi train/validation)

- **Accuracy: 85.60%** — Đạt target PRD (≥85%).
- Precision (macro): 0.8596
- Recall (macro): 0.8623
- F1 (macro): 0.8602

### Per-class

| Label | Precision | Recall | F1 | Support |
|---|---|---|---|---|
| rice_blast | 0.9118 | 0.8378 | 0.8732 | 37 |
| bacterial_leaf_blight | 0.8621 | 0.9259 | 0.8929 | 27 |
| brown_spot | 0.7949 | 0.8158 | 0.8052 | 38 |
| healthy | 0.8696 | 0.8696 | 0.8696 | 23 |

### Confusion matrix

| actual \ predicted | rice_blast | bacterial_leaf_blight | brown_spot | healthy |
|---|---|---|---|---|
| **rice_blast** | 31 | 1 | 5 | 0 |
| **bacterial_leaf_blight** | 2 | 25 | 0 | 0 |
| **brown_spot** | 1 | 3 | 31 | 3 |
| **healthy** | 0 | 0 | 3 | 20 |

## Confidence threshold (FR-1b-04)

- **Temperature scaling:** T = 1.65 (calibrate confidence
  trên validation set bằng grid search tối thiểu NLL — Guo et al. 2017. Chia
  logits cho T trước softmax; KHÔNG đổi predicted label, chỉ đổi độ tin cậy
  report ra).
- **Ngưỡng (sau calibrate):** 0.9398
- **Phương pháp chọn ngưỡng:** tối ưu Youden's J (TPR − FPR) trên tập
  validation, biến mục tiêu = dự đoán đúng/sai, biến điểm = confidence đã
  calibrate. Không chọn tùy tiện.
- **Tỷ lệ uncertain trên tập test ở ngưỡng này:** 42.40%
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
{
  "model_name": "mobilenet_v2_rice_leaf_cv_baseline",
  "version_code": "mobilenetv2-baseline-20260909-222933",
  "test_dataset_name": "Rice Leaf Bacterial and Fungal Disease Dataset (Mendeley, subset: 4/8 classes)",
  "test_dataset_version": "hx6f852hw4.2-original-4class-subset",
  "test_sample_count": 125,
  "accuracy": 0.856,
  "confidence_threshold": 0.939849,
  "source_reference": "https://data.mendeley.com/datasets/hx6f852hw4/2 (DOI 10.17632/hx6f852hw4.2)",
  "status": "draft"
}
```

`confusion_matrix` đầy đủ (JSON, khớp cột `confusion_matrix jsonb`) nằm trong
`ml/runs/mobilenetv2-baseline-20260909-222933/eval_metrics.json`. File đó
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
  dẫn tới tỷ lệ `uncertain` cao (42%
  trên tập test) nếu muốn giữ độ tin cậy cao cho phần được chấp nhận. Tradeoff
  giữa coverage và độ an toàn — cần nhiều dữ liệu hơn (đặc biệt ảnh thực địa)
  để cải thiện, không phải tham số có thể chỉnh tùy ý để "đẹp số".
- Baseline CPU-only, dataset nhỏ (608 ảnh train, 4 lớp) — đủ cho MVP, chưa đủ
  quy mô để kỳ vọng calibration tốt như model train trên dataset lớn.

## Field validation

NO (chưa có ảnh thực địa HTX pilot — xem RR-01 trong docs/modules/03-computer-vision.md)

## M03 READY

READY (baseline) — đạt target accuracy ≥85% trên dataset public.
Xem Definition of Done đầy đủ trong final report gửi kèm.

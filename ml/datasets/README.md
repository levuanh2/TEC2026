# Datasets — nguồn & license

## Bộ dùng cho M03 CV MVP baseline (đã xác nhận)

| Trường | Giá trị |
|---|---|
| **Tên** | Rice Leaf Bacterial and Fungal Disease Dataset (còn gọi RiceyLeafDisease) |
| **Nguồn** | Mendeley Data |
| **URL** | https://data.mendeley.com/datasets/hx6f852hw4/2 |
| **DOI** | 10.17632/hx6f852hw4.2 |
| **Tác giả** | Mehedi Hasan, Sonia Khatun, Md. Abu Raihan, Abdul Hasib Uddin (Khwaja Yunus Ali University) |
| **License** | **CC BY 4.0** (Creative Commons Attribution 4.0 International) — xác nhận qua Mendeley public API (`data_licence.short_name`), ngày xác nhận **2026-09-09** |
| **Quy mô gốc** | 1.701 ảnh gốc ("Original Images.zip") + 5.188 ảnh augmented (không dùng bản augmented — xem lý do bên dưới) |
| **8 lớp gốc** | Bacterial Leaf Blight, Brown Spot, Leaf Scald, Narrow Brown Leaf Spot, Rice Hispa, Sheath Blight, Leaf Blast, Healthy Rice Leaf |
| **4 lớp dùng cho M03** | Bacterial Leaf Blight → `bacterial_leaf_blight`, Brown Spot → `brown_spot`, Leaf Blast → `rice_blast`, Healthy Rice Leaf → `healthy` |

**Vì sao đổi so với dataset dự kiến trước đó (Sethy et al.):** bộ Sethy et al.
(`fwcj7stb8r`, 5.932 ảnh) chỉ có 4 lớp **blast/bacterial blight/brown
spot/tungro** — **không có lớp `healthy`**, không đủ 4 nhãn PRD yêu cầu
(`rice_blast, bacterial_leaf_blight, brown_spot, healthy` — khớp enum
`public.disease_label`). Bộ `hx6f852hw4` có đủ cả 4 nhãn cần thiết trong 8 lớp
của nó nên được chọn thay thế, xác nhận qua Mendeley public API ngày 2026-09-09.

**Chỉ dùng "Original Images.zip"**, không dùng "Augmented Images.zip": ảnh
augmented là biến đổi (xoay/lật/crop) của ảnh gốc — dùng chung sẽ tạo
near-duplicate giữa train/test, vi phạm yêu cầu tập test phải tách biệt hoàn
toàn (FR-1b-03). `ml/dataset_prep.py` còn tự phát hiện near-duplicate trong
chính tập Original bằng aHash và đảm bảo các ảnh gần giống nhau nằm trọn trong
1 split.

**4 lớp bị loại** (Leaf Scald, Narrow Brown Leaf Spot, Rice Hispa, Sheath
Blight) — không thuộc phạm vi PRD, `ml/dataset_prep.py` bỏ qua hoàn toàn, không
đưa vào train/eval.

## Domain gap — vẫn là rủi ro thật

Dataset public chụp tại Bangladesh (2023), điều kiện ánh sáng ngoài trời/trong
nhà có kiểm soát tương đối. Ảnh nông dân Việt Nam chụp ngoài đồng bằng điện
thoại có nắng gắt, nền lẫn nhiều lá, ảnh rung nhòe. `ml/reports/cv_baseline_report.md`
ghi rõ **PUBLIC DATASET — NOT FIELD VALIDATED**.

## Bộ dự kiến khác (chưa dùng, giữ tham khảo)

| Bộ | Quy mô | Lớp | Nguồn | License | Vấn đề |
|---|---|---|---|---|---|
| Sethy et al. — Rice Leaf Disease | ~5.932 ảnh | blast/bacterial blight/brown spot/tungro (4) | Mendeley (`fwcj7stb8r`) | CC BY 4.0 | Thiếu lớp `healthy` |
| Ảnh thực địa HTX pilot | mục tiêu ≥ vài trăm ảnh | theo nhãn chuyên gia/khuyến nông | Tự thu thập | Thỏa thuận với HTX | Chưa có — chưa chốt HTX pilot (R1 PRD) |

## Quy ước thư mục

```text
datasets/
├── README.md          # file này (có trong git)
├── raw/                # zip đã tải + giải nén — KHÔNG commit (đã .gitignore)
│   ├── rice_hx6f852hw4_original_images.zip
│   └── extracted/
└── splits/             # manifest CSV train/validation/test.csv — CÓ commit
    ├── train.csv
    ├── validation.csv
    ├── test.csv
    └── split_summary.json
```

`splits/*.csv` chỉ chứa đường dẫn + nhãn (text nhỏ, tái lập được split), không
chứa ảnh — ảnh thật vẫn nằm trong `raw/` (không commit).

## Việc cần làm (còn mở)

- [ ] Thỏa thuận với HTX pilot về quyền sử dụng ảnh thực địa (FR-1b-02, phụ thuộc R1 PRD)
- [ ] Chốt quy trình gán nhãn ảnh thực địa khi có (ai gán, đối chiếu với ai)
- [ ] Fine-tune bằng ảnh thực địa khi HTX pilot có ảnh, so sánh accuracy trước/sau

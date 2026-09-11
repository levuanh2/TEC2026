# ml/ — Computer Vision: phát hiện bệnh lá lúa

- **Lớp MVP:** 1b (AI/CV) — làm ngay sau khi 1a chạy ổn.
- **Phụ trách:** Người B.
- **Đặc tả:** [`../docs/modules/03-computer-vision.md`](../docs/modules/03-computer-vision.md)

## Vai trò

Một bài toán duy nhất: phân loại bệnh lá lúa — **đạo ôn (blast)**, **bạc lá
(bacterial blight)**, **đốm nâu (brown spot)**, và lá khỏe. Pretrain trên dataset
public, fine-tune bằng ảnh thực địa từ HTX pilot.

Không ôm thêm bài toán khác (đếm bông, ước lượng năng suất) ở giai đoạn này.

## Trạng thái

**M03 CV MVP READY (baseline)** — xem [`reports/cv_baseline_report.md`](reports/cv_baseline_report.md)
cho accuracy/confusion matrix thật. Dataset public, **chưa field-validated**
(chưa có ảnh thực địa HTX pilot).

## Chạy

```bash
python -m venv .venv && .venv/Scripts/activate   # Windows
pip install -r requirements.txt
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

# 1. Tải "Original Images.zip" tu https://data.mendeley.com/datasets/hx6f852hw4/2
#    vao ml/datasets/raw/ (khong commit - da .gitignore)
# 2. Chuan bi split (loc 4 class, dedup, chia train/val/test):
python -m ml.dataset_prep
# 3. Train baseline (MobileNetV2 transfer learning, CPU):
python -m ml.train
# 4. Danh gia tren tap test doc lap + chon confidence threshold:
python -m ml.evaluate --checkpoint ml/runs/<run_name>/model.pt
# 5. Inference 1 anh:
python -m ml.infer path/to/image.jpg
```

Test: `python -m pytest ml/tests -q` (không cần dataset đã tải — tự tạo model/ảnh giả).

Dataset: xem [`datasets/README.md`](datasets/README.md) — license đã xác nhận (CC BY 4.0).

Contract cho Flutter tích hợp: [`../docs/CV_INTEGRATION.md`](../docs/CV_INTEGRATION.md).

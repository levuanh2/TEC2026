# ml/ — Computer Vision: phát hiện bệnh lá lúa

- **Lớp MVP:** 1b (AI/CV) — làm ngay sau khi 1a chạy ổn.
- **Phụ trách:** Người B.
- **Đặc tả:** [`../docs/modules/03-computer-vision.md`](../docs/modules/03-computer-vision.md)

## Vai trò

Một bài toán duy nhất: phân loại bệnh lá lúa — **đạo ôn (blast)**, **bạc lá
(bacterial blight)**, **đốm nâu (brown spot)**, và lá khỏe. Pretrain trên dataset
public, fine-tune bằng ảnh thực địa từ HTX pilot.

Không ôm thêm bài toán khác (đếm bông, ước lượng năng suất) ở giai đoạn này.

## Chạy

```bash
python -m venv .venv && .venv/Scripts/activate   # Windows
pip install -r requirements.txt
python train.py   # chưa có logic, mới là entrypoint TODO
```

Dataset: xem [`datasets/README.md`](datasets/README.md) — **kiểm tra license trước khi dùng**.

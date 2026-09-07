# Datasets — nguồn & license

> **Bắt buộc:** kiểm tra license của TỪNG bộ trước khi dùng. Đa số là CC BY 4.0
> nhưng phải xác nhận lại từng bộ và ghi lại ngày xác nhận vào bảng dưới.

## Bộ dữ liệu dự kiến

| Bộ | Quy mô | Lớp | Nguồn | License | Đã xác nhận license? |
|---|---|---|---|---|---|
| Sethy et al. — Rice Leaf Disease | ~5.932 ảnh | 4 lớp (blast, bacterial blight, brown spot, tungro) | Mendeley Data | Cần kiểm tra (dự kiến CC BY 4.0) | ❌ chưa |
| Ảnh thực địa HTX pilot | mục tiêu ≥ vài trăm ảnh | theo nhãn chuyên gia/khuyến nông | Tự thu thập | Thỏa thuận với HTX | ❌ chưa có |

## Lưu ý về domain gap

Dataset public chụp trong điều kiện kiểm soát; ảnh nông dân chụp bằng điện thoại
ngoài đồng có nắng gắt, nền lẫn, rung nhòe. Fine-tune bằng ảnh thực địa là bắt buộc,
không phải tùy chọn — nếu không có ảnh thực địa, PHẢI báo cáo accuracy kèm cảnh báo
rằng con số đo trên dataset public không đại diện điều kiện đồng ruộng.

## Quy ước thư mục

```text
datasets/
├── README.md          # file này (có trong git)
├── raw/               # ảnh gốc tải về — KHÔNG commit (đã ignore)
└── field/             # ảnh thực địa HTX — KHÔNG commit (đã ignore)
```

## Việc cần làm

- [ ] Xác nhận license bộ Sethy et al., ghi ngày xác nhận vào bảng trên
- [ ] Thỏa thuận với HTX pilot về quyền sử dụng ảnh thực địa
- [ ] Chốt quy trình gán nhãn ảnh thực địa (ai gán, đối chiếu với ai)

# web-dashboard/ — Dashboard quản trị cho HTX / doanh nghiệp

- **Lớp MVP:** 1c (trình bày/vận hành) — làm cuối cùng, **được phép cắt xuống mock**.
- **Phụ trách:** Người A.
- **Đặc tả:** [`../docs/modules/06-web-dashboard.md`](../docs/modules/06-web-dashboard.md)

## Vai trò

Xem dữ liệu theo cấp bậc Farm → Plot → Crop → Batch → Activity → Carbon, tổng hợp
nhiều hộ trong một HTX, phân quyền 3 vai trò (Nông dân / Quản lý HTX / Doanh nghiệp
– Cơ quan quản lý).

## Stack

Hiện tại: 1 file `index.html` tĩnh, dữ liệu mock. Cố ý — 1c là lớp có thể cắt, không
đáng dựng build toolchain trước khi 1a và 1b xong. Nâng lên Vite + React chỉ khi
dashboard thật sự cần gọi API động.

## Chạy

Mở `index.html` bằng trình duyệt. Không cần build, không cần cài gì.

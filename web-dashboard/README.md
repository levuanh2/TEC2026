# web-dashboard/ — Dashboard quản trị cho HTX / doanh nghiệp

- **Lớp MVP:** 1c (trình bày/vận hành) — làm cuối cùng, **được phép cắt xuống mock**.
- **Phụ trách:** Người A.
- **Đặc tả:** [`../docs/modules/06-web-dashboard.md`](../docs/modules/06-web-dashboard.md)

## Vai trò

Xem dữ liệu theo cấp bậc Farm → Plot → Crop → Batch → Activity → Carbon, tổng hợp
nhiều hộ trong một HTX, phân quyền 3 vai trò (Nông dân / Quản lý HTX / Doanh nghiệp
– Cơ quan quản lý).

## Stack

Vite + React + `@supabase/supabase-js`. Biến browser chỉ nhận publishable key; service-role
key không bao giờ xuất hiện trong dashboard. Trạng thái đăng nhập được lấy qua Supabase Auth,
và các truy vấn dữ liệu sau này phải dựa vào RLS thay vì lọc dữ liệu ở giao diện.

## Chạy

```bash
npm install
npm run dev
```

Sao chép `.env.example` thành `.env` và điền URL + publishable key. Không commit `.env`.

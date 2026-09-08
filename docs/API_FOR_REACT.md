# API cho React (`web-dashboard/`)

Ngày: 2026-09-08. Đọc `docs/API_CATALOG.md` (danh sách đầy đủ) +
`docs/API_FOR_FLUTTER.md` §0 (error contract, auth) trước — tài liệu này chỉ
thêm phần đặc thù React/dashboard. Không lặp lại nội dung đã có ở 2 file đó.

## 1. Nguyên tắc bắt buộc

**Không tính toán chỉ số ở client.** `co2e_per_kg`, `water_per_kg`,
`fertilizer_per_kg`, `cost_per_kg`, tổng `total_co2e_kg`/`total_yield_kg` ở cấp
farm/organization — TẤT CẢ đã tính sẵn ở backend (`/v1/.../metrics`,
`/v1/organizations/{id}/summary`, `/v1/organizations/{id}/farm-performance`,
`/v1/organizations/{id}/metrics`, `/v1/farms/{id}/metrics`). Lý do: nguyên tắc
"sum/sum, không average of averages" (xem §14 yêu cầu gốc) chỉ đúng nếu tính
đúng MỘT chỗ — nếu React tự `reduce()` lại từ danh sách farm, dễ vô tình tính
trung bình cộng `co2e_per_kg` thay vì tổng/tổng. Chỉ hiển thị số backend trả,
không suy ra số mới từ nhiều response gộp lại.

**`null` khác `0`.** Mọi field có thể `null` (thiếu dữ liệu, chưa đo được) —
hiện "Chưa có dữ liệu" / "—", KHÔNG hiện `0` hay bỏ qua coi như 0 khi cộng ở UI.

## 2. Auth

Supabase Auth (client-side, `@supabase/supabase-js` chỉ dùng để LOGIN — lấy
session/access_token, KHÔNG dùng để đọc bảng nghiệp vụ trực tiếp). Sau khi có
session, gọi FastAPI với header:

```
Authorization: Bearer <session.access_token>
```

Token hết hạn → 401 `unauthenticated` — bắt lỗi này ở một chỗ chung (interceptor
fetch), refresh session qua Supabase Auth rồi retry, không lặp lại logic ở mỗi
component.

## 3. Pagination

Mọi list endpoint nhận `?page=1&page_size=20` (mặc định), trả:

```json
{ "items": [...], "page": 1, "page_size": 20, "total": 37, "has_more": true }
```

Dùng `has_more` để quyết định hiện nút "Tải thêm" — KHÔNG tự suy `has_more` từ
`items.length == page_size` (biên page cuối cùng vừa khít page_size sẽ sai).

## 4. Error handling

```json
{ "detail": { "error": { "code": "not_found", "message": "..." } } }
```

Một hàm dùng chung cho mọi fetch:

```ts
async function callApi(path: string, token: string) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    const body = await res.json();
    throw new ApiError(body.detail.error.code, body.detail.error.message, res.status);
  }
  return res.json();
}
```

`code` để rẽ nhánh logic (vd `no_calculation` → hiện nút "Tính CO2e" thay vì
báo lỗi đỏ), `message` để hiện cho người dùng — đã là tiếng Việt, không cần
dịch/map thêm ở client.

## 5. Base URL

`VITE_API_BASE_URL` (hay tên biến tương ứng trong `web-dashboard/.env.example`)
trỏ tới FastAPI, KHÔNG trỏ tới Supabase URL — React không có lý do gọi thẳng
`*.supabase.co` cho dữ liệu nghiệp vụ nữa (chỉ Supabase Auth SDK cho login).

## 6. Không có sẵn — đừng giả lập bằng mock nữa

`docs/WEB_BACKEND_GAPS.md` (2026-09-08) liệt kê endpoint còn thiếu tại thời
điểm viết — phần lớn ĐÃ CÓ sau lần hoàn thiện này (xem `docs/API_CATALOG.md`).
Việc còn lại: rà lại `web-dashboard/src/` xem còn gọi mock/hardcode ở đâu và
thay bằng gọi thật — **việc này CHƯA làm trong phiên backend hiện tại** (ngoài
phạm vi file backend chạm tới), cần một lượt audit riêng cho `web-dashboard/`.

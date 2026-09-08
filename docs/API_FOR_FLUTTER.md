# AgriCarbon REST API — hợp đồng dùng chung Flutter + React

Phiên bản: 0.2 · Ngày: 2026-09-08 · Nguồn sự thật: `backend/api.py`,
`backend/main.py`, `backend/infrastructure/read_repo.py`, `docs/openapi.json`
(xuất bằng `python backend/scripts/export_openapi.py`, chạy `/docs` để xem
Swagger UI khi backend đang chạy). Chỉ ghi endpoint THỰC SỰ tồn tại trong code —
không suy đoán.

> Thay thế/superset `docs/FRONTEND_API_CONTRACT.md` (tài liệu cũ chỉ có 3 route
> carbon, viết trước khi các route đọc dashboard được thêm). Tài liệu cũ vẫn còn
> vì có phần §5 giải thích kiến trúc ghi trực tiếp Supabase — xem thêm
> `docs/SYNC_ARCHITECTURE_GAP.md`.

## 0. Auth & error contract (áp dụng cho MỌI route `/v1/*`)

**Header:** `Authorization: Bearer <supabase_jwt>` — bắt buộc cho mọi route trừ
`GET /health` và `GET /v1/carbon/scenarios`. Backend replay JWT này qua
publishable key (`infrastructure/auth.py`, `infrastructure/read_repo.py`) để
chính PostgREST/RLS quyết định quyền — KHÔNG tự quyết bằng code Python, KHÔNG
bao giờ dùng service-role key để trả lời "được phép" thay RLS.

**Error contract thống nhất — MỘT hình dạng cho toàn bộ API:**

```json
{ "detail": { "error": { "code": "crop_not_found", "message": "..." } } }
```

Client đọc `response.detail.error.code` để rẽ nhánh, `response.detail.error.message`
để hiện cho người dùng (tiếng Việt, không phải chuỗi kỹ thuật). Không còn route
nào dùng dạng cũ `detail.error` là string phẳng.

**Không phân biệt 403/404** cho resource-scoped route — RLS từ chối hay resource
không tồn tại đều trả 404, tránh lộ ra rằng một id nào đó tồn tại nhưng thuộc
tổ chức/nông hộ khác.

## 1. Auth

### `GET /v1/me`
Trả `user_id`, `full_name`, `organization_memberships`, `farm_memberships`,
`roles` (hợp từ role trong 2 bảng trên) — vai trò LẤY TỪ DB, không tin client.

## 2. Farms / Plots / Crop Seasons

| Route | Ghi chú |
|---|---|
| `GET /v1/farms?page&page_size` | Phân trang, mặc định `page=1, page_size=20`, tối đa `page_size=100`. |
| `GET /v1/farms/{farm_id}` | |
| `GET /v1/farms/{farm_id}/plots` | |
| `GET /v1/plots/{plot_id}` | |
| `GET /v1/plots/{plot_id}/crop-seasons` | |
| `GET /v1/crop-seasons/{crop_season_id}` | |

Response phân trang có hình dạng:
```json
{ "items": [...], "page": 1, "page_size": 20, "total": 3, "has_more": false }
```
`page < 1` hoặc `page_size` ngoài `1..100` → `400 invalid_page` / `invalid_page_size`.

## 3. Activities

`GET /v1/crop-seasons/{crop_season_id}/activities?page&page_size` — gộp từ 7
bảng chi tiết (`fertilizer_applications`, `irrigation_events`, ...) theo
`activity_id`, đã lọc `deleted_at is null`. Trả phân trang như trên.

## 4. Production Batches (traceability, KHÔNG phải scope tính carbon)

| Route | Ghi chú |
|---|---|
| `GET /v1/crop-seasons/{crop_season_id}/production-batches` | |
| `GET /v1/production-batches/{batch_id}` | |

Carbon LUÔN tính theo Crop Season — xem `docs/CARBON_CALCULATION_SCOPE_RESOLUTION.md`.
Batch chỉ để tra cứu/truy vết, không dùng để tính hay chia CO2e.

## 5. Metrics

`GET /v1/crop-seasons/{crop_season_id}/metrics` — đơn vị chuẩn: nước = m³, phân
bón = kg, sản lượng = kg, CO2e = kg, chi phí = VND. `data_completeness` báo
`water/fertilizer/cost/carbon` có đủ dữ liệu hay không — field tổng hợp tương
ứng (`water_m3`, `fertilizer_kg`, `total_co2e_kg`, `cost_per_kg`, ...) là `null`
(không phải `0`) khi thiếu, để UI không hiểu lầm "0" là đã đo.

## 6. Organizations

| Route | Ghi chú |
|---|---|
| `GET /v1/organizations` | Chỉ org caller nhìn thấy được (qua RLS). |
| `GET /v1/organizations/{organization_id}` | |
| `GET /v1/organizations/{organization_id}/farms` | Farm thuộc tổ chức — lọc theo `cooperative_id`, khác `GET /v1/farms` (toàn bộ farm caller thấy được, không lọc theo org). |
| `GET /v1/organizations/{organization_id}/summary` | `total_yield_kg`/`total_co2e_kg` = **tổng (sum)**, không phải trung bình `co2e_per_kg` của từng vụ — `co2e_per_kg = total_co2e_kg / total_yield_kg`, và cả hai `null` nếu BẤT KỲ vụ nào trong tổ chức còn thiếu yield hoặc carbon (không lặng lẽ bỏ qua vụ thiếu dữ liệu). |
| `GET /v1/organizations/{organization_id}/metrics` | Cùng hình dạng `MetricResponse` như crop-season/farm metrics, cộng dồn toàn tổ chức — tiện để dùng chung 1 component hiển thị ở mọi cấp. |
| `GET /v1/organizations/{organization_id}/farm-performance` | Mảng theo từng farm, `data_status`: `"complete"` (mọi vụ đủ mọi loại dữ liệu) / `"partial"` / `"missing"` (farm chưa có vụ nào). |

## 6b. Farm-level rollup

| Route | Ghi chú |
|---|---|
| `GET /v1/farms/{farm_id}/crop-seasons` | Gộp vụ của MỌI thửa trong farm (khác `GET /v1/plots/{plot_id}/crop-seasons` — theo từng thửa). |
| `GET /v1/farms/{farm_id}/metrics` | `MetricResponse` cộng dồn toàn farm, cùng nguyên tắc null-nếu-thiếu như organization metrics. |

## 6c. Activity đơn lẻ

`GET /v1/activities/{activity_id}` — cùng hình dạng phần tử trong
`GET /v1/crop-seasons/{id}/activities`, dùng khi đã có `activity_id` (vd từ
notification) và không muốn tải lại cả danh sách.

## 6d. MRV sub-resources

| Route | Ghi chú |
|---|---|
| `GET /v1/mrv/cases/{mrv_case_id}/steps` | Luôn đủ 6 bước (`not_started` nếu chưa có record) — cùng dữ liệu đã lồng sẵn trong `GET /v1/mrv/cases/{id}` field `steps`, tách route riêng cho UI chỉ cần bước. |
| `GET /v1/mrv/cases/{mrv_case_id}/batches` | Batch thuộc case (qua bảng liên kết `mrv_case_batches`), kèm `farm_id`/`plot_id` đã resolve sẵn. |
| `GET /v1/mrv/cases/{mrv_case_id}/evidence` | Metadata bằng chứng — KHÔNG có signed URL tải file. |
| `GET /v1/mrv/cases/{mrv_case_id}/exports` | |
| `GET /v1/mrv/exports/{mrv_export_id}` | Đọc 1 export theo id, không cần biết case trước. |

**Chưa có:** tạo export (`POST`) — bảng `mrv_exports` chỉ có quyền đọc cho
`authenticated`, tạo export là việc của job backend riêng, chưa viết.

## 6e. Đổi tên path param (không đổi URL, chỉ đổi tên biến trong OpenAPI)

`{batch_id}` → `{production_batch_id}`, `{set_id}` → `{emission_factor_set_id}`,
`{case_id}` → `{mrv_case_id}`. URL không đổi, chỉ ảnh hưởng nếu code sinh tự
động từ tên param OpenAPI.

## 7. Carbon (giữ nguyên hợp đồng cũ — không đổi trường dữ liệu, chỉ đổi hình dạng lỗi)

`POST /v1/carbon/calculate`, `GET /v1/crop-seasons/{crop_season_id}/carbon`,
`GET /v1/carbon/scenarios` — xem `docs/FRONTEND_API_CONTRACT.md` §1–§3 cho đầy
đủ response 200. **Khác duy nhất so với tài liệu đó:** body lỗi giờ nested
(`detail.error.code`/`detail.error.message`) như §0 ở trên, KHÔNG còn
`detail.error` là string.

## 8. Emission Factors (chỉ đọc, chỉ bản đã published)

| Route | Ghi chú |
|---|---|
| `GET /v1/emission-factor-sets` | |
| `GET /v1/emission-factor-sets/{set_id}` | 404 nếu set không tồn tại HOẶC chưa published (farmer không xem được bản draft). |
| `GET /v1/emission-factor-sets/{set_id}/factors` | |

Farmer không sửa hệ số qua API này — chỉ đọc, để hiển thị nguồn/tham chiếu.

## 9. MRV

| Route | Ghi chú |
|---|---|
| `GET /v1/mrv/cases?page&page_size` | |
| `GET /v1/mrv/cases/{case_id}` | Trả đúng 6 bước theo QĐ 4801: Chuẩn bị, Đăng ký, Thiết lập đường cơ sở, Đo đạc, Báo cáo, Thẩm định — mỗi bước có `status` (`not_started` nếu chưa có `mrv_case_steps`). |

**Chưa có:** `GET /v1/mrv/cases/{case_id}/batches`, `/evidence`, `/steps` riêng
lẻ, và MRV exports. Nếu cần, phải trả `501` kèm `error.code = "not_implemented"`
thay vì bịa dữ liệu — CHƯA triển khai trong lần hoàn thiện này, ghi nhận là việc
còn lại, không phải đã xong.

## 10. Health

`GET /health` — không cần auth, không query Supabase. `carbon_production_ready`
chỉ `true` khi GWP đã xác minh (hiện tại luôn `false` — xem OI-05).

## 11. Ghi dữ liệu (Flutter) — vẫn KHÔNG qua backend

Xem `docs/SYNC_ARCHITECTURE_GAP.md`. Flutter ghi Activity/Plot/CropSeason
thẳng Supabase qua RLS, chưa qua FastAPI — ghi nhận có chủ đích, không tự đổi
trong lần hoàn thiện REST-API-đọc này.

## 12. Chưa triển khai / còn lại thật (không tự nhận đã xong)

- Hosted Supabase E2E cho các route đọc mới (`SMOKE-TEST-API`) — **CHƯA chạy**
  trong lần này, chỉ verify bằng unit test (fake Supabase client, xem
  `backend/tests/test_read_repository.py`) + 101 test carbon cũ.
- MRV sub-resource (`/batches`, `/evidence`, `/steps`, exports) — chưa có.
- Request-ID middleware + OpenAPI tags/security scheme — có, nhưng structured
  logging mới ở mức method/path/status/duration; chưa có `user_id` trong log
  (cần giải mã JWT thêm, chưa làm vì không muốn parse JWT tuỳ tiện ở tầng log).
- React (`web-dashboard/`) chưa được audit lại xem còn mock hay đã gọi hết qua
  các route mới — nằm ngoài phạm vi file mà phiên làm việc backend này chạm tới.

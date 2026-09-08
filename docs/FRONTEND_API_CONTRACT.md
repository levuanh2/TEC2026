# Frontend API Contract — Flutter + React dùng chung

> ⚠️ **Superseded bởi `docs/API_FOR_FLUTTER.md`** (2026-09-08, sau khi thêm đầy
> đủ route đọc dashboard). Tài liệu này giữ lại vì §5 vẫn đúng (kiến trúc ghi
> trực tiếp Supabase). **Hình dạng lỗi bên dưới (`detail.error` là string) đã
> LỖI THỜI** — API giờ trả `detail.error.code`/`detail.error.message` (nested)
> cho MỌI route, xem `docs/API_FOR_FLUTTER.md` §0. Response 200 (trường dữ
> liệu carbon) dưới đây vẫn đúng, không đổi.

Phiên bản: 0.1 · Ngày: 2026-09-08
Nguồn sự thật: `backend/api.py`, `backend/infrastructure/auth.py` (đọc code thật, không
suy từ prompt cũ). Mọi thay đổi hợp đồng phải sửa file này CÙNG lúc với `backend/api.py`.

> **Không có `POST /v1/sync`.** Backend hiện chỉ có 2 route nghiệp vụ (`/v1/carbon/*`) +
> `/health`. Ghi Activity/Plot/CropSeason đi THẲNG vào Supabase qua RLS (publishable key +
> JWT người dùng), không qua backend — xem `app/README.md` mục "Kiến trúc". Backend chỉ
> giữ đúng một việc nó có: Carbon Engine.

---

## 1. `POST /v1/carbon/calculate`

Tính CO2e cho một vụ canh tác (scope = Crop Season, không phải Batch — xem
`docs/CARBON_CALCULATION_SCOPE_RESOLUTION.md`) và lưu kết quả.

**Auth bắt buộc:** header `Authorization: Bearer <supabase_jwt>`. Backend replay JWT này
qua publishable key để RLS thật quyết định caller có đọc được `crop_seasons` đó không,
TRƯỚC khi chạm service role (`backend/infrastructure/auth.py`).

### Request

```json
{
  "crop_season_id": "uuid",
  "water_regime_scenario": "as_recorded"
}
```

| Field | Kiểu | Bắt buộc | Giá trị |
|---|---|---|---|
| `crop_season_id` | string (uuid) | ✅ | id của `crop_seasons` |
| `water_regime_scenario` | string enum | mặc định `"as_recorded"` | `"awd"` \| `"continuous_flooding"` \| `"as_recorded"` |

### Response 200

```json
{
  "crop_season_id": "uuid",
  "scenario": "awd",
  "water_regime_scenario": "awd",
  "water_regime_applied": "irrigated_multiple_drainage",
  "total_co2e_kg": 1990.494,
  "co2e_total_kg": 1990.494,
  "yield_kg": 5200.0,
  "co2e_per_kg": 0.3828,
  "breakdown": [
    {
      "source": "ch4_rice_cultivation",
      "gas": "ch4",
      "activity_value": 100.0,
      "activity_unit": "ha_day",
      "gas_kg": 262.5,
      "co2e_kg": 2625.0,
      "formula": "IPCC 2019 Refinement Eq 5.1 + 5.2: ...",
      "factors_used": { "...": "..." },
      "provenance": { "...": "..." },
      "parameter_status": { "...": "VERIFIED | PENDING_VERIFICATION | TEST" }
    }
  ],
  "methodology": { "name": "IPCC 2019 Refinement...", "version": "2019", "tier": 1 },
  "ef_config_version": "0.2.0-ipcc-tier1",
  "engine_version": "0.2.0",
  "input_hash": "64-hex-chars",
  "calculated_at": "2026-09-08T00:00:00+00:00",
  "warnings": ["..."],
  "calculation_id": "uuid | null"
}
```

**Hai field trùng nghĩa cố ý — tương thích ngược:** `co2e_total_kg` (SRS §4.2 gốc) và
`total_co2e_kg` (tên trong `CarbonResult.to_dict()`) cùng giá trị. `scenario` và
`water_regime_scenario` cũng vậy. Client dùng field nào cũng được, không cần chọn.

**`co2e_per_kg: null`** — hợp lệ, KHÔNG phải lỗi. Nghĩa là đã tính được tổng CO2e nhưng
chưa có sản lượng thu hoạch. `warnings` sẽ có dòng giải thích. UI KHÔNG được hiện `0`.

### Lỗi

| HTTP | `detail.error` | Khi nào |
|---|---|---|
| 400 | `invalid_water_regime` | `water_regime_scenario` không hợp lệ (Pydantic thường chặn trước ở 422 nếu sai kiểu JSON) |
| 401 | `missing_authorization` | Thiếu/sai định dạng header `Authorization` |
| 404 | `crop_not_found` | RLS từ chối HOẶC `crop_season_id` không tồn tại — **cố ý không phân biệt hai trường hợp** |
| 409 | `conflicting_water_records` | Nhiều bản ghi tưới ghi chế độ nước mâu thuẫn nhau |
| 409 | `double_counting` | Bug-guard nội bộ (rơm vừa vào SFo vừa vào nguồn đốt) — không nên gặp trong vận hành bình thường |
| 422 | `missing_emission_factor` | Thiếu hệ số bắt buộc (hiện tại luôn gặp ở `gwp.ch4` — GWP chưa xác minh) |
| 422 | `methodology_gap` | Thiếu biến phương pháp luận (SFp, dry_matter_fraction, days_before_cultivation, ...) |
| 422 | `missing_activity_data` | Thiếu dữ liệu hoạt động cơ bản (diện tích, %N, ...) |
| 503 | `factor_set_not_imported` | Bộ hệ số YAML chưa import vào Supabase |
| 503 | `backend_not_configured` / `auth_not_configured` | Backend thiếu biến môi trường — lỗi vận hành, không phải lỗi người dùng |
| 500 | `internal_error` | Lỗi không xác định. Response CHỈ có `request_id`, không có message/stack trace gốc |

Cấu trúc lỗi luôn là:

```json
{ "detail": { "error": "missing_emission_factor", "message": "..." } }
```

---

## 2. `GET /v1/crop-seasons/{crop_season_id}/carbon`

Trả bản tính **thành công** gần nhất của vụ. Không bao giờ trả bản tính `failed` như một
kết quả thành công.

**Auth bắt buộc:** giống hệt POST ở trên.

### Query params

| Param | Bắt buộc | Giá trị |
|---|---|---|
| `scenario` | tuỳ chọn | `"awd"` \| `"continuous_flooding"` \| `"as_recorded"` — không truyền = lấy bản gần nhất bất kể kịch bản nào |

### Response 200

Giống hệt cấu trúc của POST ở trên.

### Lỗi

Giống bảng lỗi của POST, **cộng thêm**:

| HTTP | `detail.error` | Khi nào |
|---|---|---|
| 404 | `crop_not_found` | RLS từ chối / không tồn tại (giống POST) |
| 404 | `no_calculation` | Vụ hợp lệ, người dùng CÓ quyền xem, nhưng **chưa từng tính CO2e** cho vụ này (hoặc chưa tính cho đúng `scenario` được lọc) |

**⚠️ Hai loại 404 ở trên KHÁC NHAU HOÀN TOÀN, client PHẢI đọc `detail.error` để phân biệt:**

- `no_calculation` → trạng thái bình thường, hiện "Chưa tính CO2e, bấm để tính".
- `crop_not_found` → lỗi thật (không có quyền hoặc vụ không tồn tại), phải báo cho người
  dùng, KHÔNG được âm thầm coi như "chưa tính".

(`app/lib/services/carbon_api_service.dart` implement đúng phân biệt này — xem
`app/test/carbon_api_service_test.dart` cho 2 test case tương ứng.)

---

## 3. `GET /v1/carbon/scenarios`

Không cần auth. Trả danh sách kịch bản hợp lệ — tiện cho client tự dựng UI thay vì
hardcode:

```json
{ "scenarios": ["awd", "continuous_flooding", "as_recorded"] }
```

---

## 4. `GET /health`

Không cần auth. Không query Supabase (nhẹ — chỉ đọc `emission_factors.yaml`).

```json
{
  "status": "ok",
  "engine_version": "0.2.0",
  "ef_config_version": "0.2.0-ipcc-tier1",
  "methodology": { "name": "...", "version": "2019", "tier": 1 },
  "supabase_configured": true,
  "auth_configured": true,
  "carbon_production_ready": false,
  "mrv_compliant": false,
  "note": "GWP chưa xác minh (OI-05) nên chưa ra được CO2e thật. ..."
}
```

`carbon_production_ready: false` là trạng thái **đúng hiện tại** — không phải lỗi cần
sửa ở client.

---

## 5. Ghi dữ liệu canh tác — KHÔNG qua backend

Farm/Plot/CropSeason/Activity đọc/ghi **trực tiếp Supabase** bằng publishable key + JWT
người dùng, RLS quyết định quyền. Đây không phải "API contract" theo nghĩa REST cố định —
là truy cập bảng trực tiếp qua Supabase client SDK (`supabase_flutter` cho mobile,
`@supabase/supabase-js` cho React nếu web-dashboard cần).

Bảng liên quan và ràng buộc quan trọng nhất (đọc `supabase/migrations/20260907000000_baseline.sql`
để biết đầy đủ mọi cột/policy — đây chỉ là tóm tắt phần hay dùng):

| Bảng | Ghi chú bắt buộc biết |
|---|---|
| `activities` | `production_batch_id` **NOT NULL** dù carbon tính theo Crop Season — client phải tự đảm bảo có batch (mobile app tự tạo batch `"default"`, xem `sync_service.dart`). `client_event_id` + `device_id` tạo unique index — dùng `upsert(onConflict: 'device_id,client_event_id')` để đồng bộ idempotent, KHÔNG dùng `insert` thường. |
| 7 bảng chi tiết (`fertilizer_applications`, `irrigation_events`, ...) | `activity_id` là PRIMARY KEY (không phải id riêng) — `upsert(onConflict: 'activity_id')`. |
| `devices` | Đăng ký 1 lần, khoá bởi `installation_id` (client tự sinh, ổn định). Trả về `devices.id` dùng làm `activities.device_id`. |
| `production_batches` | `unique (crop_season_id, batch_code)` — mobile app dùng `batch_code = 'default'`, `upsert(onConflict: 'crop_season_id,batch_code')`. |

**Client KHÔNG BAO GIỜ dùng `SUPABASE_SERVICE_ROLE_KEY`** cho các thao tác này — RLS trên
`authenticated` role đã đủ quyền cho farmer ghi dữ liệu của chính họ (baseline đã có sẵn
policy insert/update cho từng bảng).

---

## 6. ⚠️ Route đọc khác (`/v1/me`, `/v1/farms*`, `/v1/plots*`, `/v1/crop-seasons/{id}*`)

Trong lúc soạn tài liệu này, `backend/api.py` bị một tiến trình KHÁC (ngoài phiên audit
Flutter này — không phải việc của task hiện tại) thêm một bộ route đọc mới:
`GET /v1/me`, `/v1/farms`, `/v1/farms/{id}`, `/v1/farms/{id}/plots`, `/v1/plots/{id}`,
`/v1/plots/{id}/crop-seasons`, `/v1/crop-seasons/{id}`, `/v1/crop-seasons/{id}/activities`,
`/v1/crop-seasons/{id}/metrics`, đọc qua `infrastructure/read_repo.py` (publishable key +
JWT người gọi, không service role — cùng nguyên tắc RLS như §1/§2).

**Tài liệu này CHƯA mô tả chi tiết các route đó** — nằm ngoài phạm vi audit Flutter lần
này, chưa được tôi verify. Nếu React (web-dashboard) sẽ dùng các route này, cần một lượt
audit riêng cho chúng trước khi coi tài liệu này là đầy đủ cho mục tiêu "Flutter + React
dùng chung contract". Mobile app hiện tại (`app/`) đọc Farm/Plot/CropSeason **trực tiếp
từ Supabase** (§5), không qua các route mới này — không có xung đột, chỉ là tài liệu
chưa theo kịp.

## 7. Đồng bộ tên field engine ↔ HTTP response

`carbon/engine.py` (Python, nội bộ) dùng `crop_season_id` là tên field chính thức từ v0.2
trở đi — không còn `crop_id` (tên cũ, đã đổi toàn bộ, xem
`docs/CARBON_CALCULATION_SCOPE_RESOLUTION.md`). Nếu thấy tài liệu cũ nào còn ghi `crop_id`
trong ngữ cảnh API carbon, đó là tài liệu chưa cập nhật — **tin vào `backend/api.py`**, không
tin prompt/tài liệu cũ.

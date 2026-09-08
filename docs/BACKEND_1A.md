# Backend MVP — Lớp 1a

Phiên bản: 0.3 · Ngày: 2026-09-08
Liên quan: [`SRS.md`](SRS.md) §4 · [`CARBON_METHOD.md`](CARBON_METHOD.md) ·
[`CARBON_CALCULATION_SCOPE_RESOLUTION.md`](CARBON_CALCULATION_SCOPE_RESOLUTION.md) ·
[`MIGRATION_HISTORY.md`](MIGRATION_HISTORY.md)

> **REAL CO2e READY = NO.** Toàn bộ tài liệu này mô tả một pipeline **chạy đúng và đã
> verify thật trên Supabase hosted** — nhưng số CO2e nó ra hiện vẫn không dùng được cho
> báo cáo thật, vì GWP chưa xác minh (OI-05), hệ số nhiên liệu chưa có (OI-06), và chưa
> lấy được toàn văn QĐ 4801/QĐ-BNNMT (OI-02). Xem §11.

---

## 1. Kiến trúc

```text
Flutter
   │  (JWT của người dùng)
   ▼
FastAPI (backend/api.py, main.py)
   │
   ├─► CropAccessChecker  ─────► Supabase (publishable key + JWT người gọi)
   │   (RLS quyết định, KHÔNG      → RLS thật trả lời "được" hay "không"
   │    phải code Python)           → không phân biệt 403/404, luôn 404
   │
   └─► CarbonService (backend/service.py)
          │
          ├─► SupabaseCarbonRepository (service role — CHỈ sau khi đã qua bước trên)
          │      → Farm/Plot/Crop Season/Batch/Activity + 7 bảng chi tiết
          │      → CropActivityData
          │
          ├─► Carbon Engine (backend/carbon/) — KHÔNG import Supabase
          │      → CarbonResult (breakdown, warnings, input_hash)
          │
          └─► ghi carbon_calculations + carbon_breakdowns (service role)
```

**Nguyên tắc bất biến, có test chặn hồi quy:** `backend/carbon/` chỉ import stdlib +
`pyyaml`. Không FastAPI, không Supabase, không pydantic.

## 2. Biến môi trường

`backend/.env` (đã gitignore, copy từ `.env.example`):

| Biến | Dùng ở đâu | Bắt buộc |
|---|---|---|
| `SUPABASE_URL` | cả hai client (service role + publishable) | ✅ |
| `SUPABASE_PUBLISHABLE_KEY` | `CropAccessChecker` — kiểm quyền qua RLS bằng JWT người gọi. **An toàn để đưa vào Flutter/web** vì RLS vẫn chặn | ✅ (để bật auth) |
| `SUPABASE_SERVICE_ROLE_KEY` | `SupabaseCarbonRepository` — đọc/ghi carbon **sau khi** đã qua CropAccessChecker | ✅ (để ghi được) |
| `SUPABASE_DB_URL` | chỉ `scripts/validate_supabase_schema.py` (đọc trực tiếp qua psycopg) | không bắt buộc cho backend chạy |
| `AGRICARBON_EF_CONFIG` | đường dẫn `emission_factors.yaml` — nguồn sự thật cho GIÁ TRỊ hệ số | ✅ |
| `AGRICARBON_REQUIRE_FACTOR_SET_IN_DB` | bắt buộc factor set đã import vào Supabase trước khi ghi | mặc định `1` |

**Không có biến nào ở đây được đưa vào Flutter ngoại trừ `SUPABASE_URL` và
`SUPABASE_PUBLISHABLE_KEY`.** `SERVICE_ROLE_KEY` chỉ tồn tại ở backend.

## 3. Supabase setup

1. Migration nằm ở `supabase/migrations/`, chạy tuần tự — xem
   [`MIGRATION_HISTORY.md`](MIGRATION_HISTORY.md) cho danh sách đầy đủ và lệnh chạy
   from-zero (`npx supabase db reset` cho local, `npx supabase db push` để đẩy migration
   còn thiếu lên project đã link).
2. `scripts/validate_supabase_schema.py` — chỉ đọc, kiểm bảng/cột/enum/index/RLS/
   policy/trigger/view của phần MVP 1a. Chạy được cả trên local lẫn hosted (cần
   `SUPABASE_DB_URL`).
3. Bộ hệ số phát thải: **YAML là nguồn sự thật cho giá trị** (`backend/config/
   emission_factors.yaml`). Bảng `emission_factor_sets`/`emission_factors` trên Supabase
   là **bản sao có kiểm soát**, chỉ để bản tính liên kết được `factor_set_id` — không
   phải nguồn giá trị thứ hai. Chưa có bộ nào `status='published'` trùng
   `version_code` với YAML → `FactorSetNotFoundError` (503), **không tự tạo bộ rỗng**.

## 4. Repository layer

`backend/infrastructure/`:

| File | Vai trò |
|---|---|
| `config.py` | Đọc `.env`, không default cho khoá bí mật |
| `mapping.py` | **Hàm thuần**, không I/O — hàng Supabase ↔ `CropActivityData` ↔ hàng kết quả |
| `repository.py` | `Protocol CarbonRepository` + `InMemoryCarbonRepository` (test/dev offline) |
| `supabase_repo.py` | `SupabaseCarbonRepository` — bản thật, service role |
| `auth.py` | `CropAccessChecker` — bản thật dùng publishable key + JWT người gọi, replay qua RLS |

Không có cấu trúc file trùng lặp — mở rộng file có sẵn thay vì tạo bản sao. Đặt tên
khác cấu trúc gợi ý trong task gốc (`infrastructure/supabase/client.py` v.v.) có chủ ý:
`config.py`/`mapping.py`/`repository.py`/`supabase_repo.py`/`auth.py` đã tách đúng mối
quan tâm, tạo thêm package con `supabase/` sẽ chỉ là đổi tên không thêm giá trị.

## 5. Data mapping — nguyên tắc "không đoán, không nhân chéo"

`get_crop_bundle(crop_season_id)` đọc **từng bảng riêng** (`crop_seasons`, `plots`,
`farms`, `production_batches`, `activities`, rồi 7 bảng chi tiết theo `activity_id`) và
ghép trong Python — **không** dùng một câu JOIN 1-n lớn, vì JOIN nhiều bảng 1-n cùng lúc
sẽ nhân bản hàng (3 bản ghi phân bón × 2 bản ghi thu hoạch → 6 hàng giả).
`test_no_cross_multiplication_across_three_sources` chốt bất biến này bằng 3 phân bón +
2 tưới + 2 thu hoạch cùng lúc.

| Nguồn | Quy tắc gộp | Khi thiếu |
|---|---|---|
| Phân bón | `kg N = Σ (amount_kg × n_content_pct / 100)` — **không** áp hệ số lên kg phân | thiếu `nitrogen_percent` → `ValidationError`, không tra bảng thành phần |
| Tưới | `irrigation_method` chỉ map chắc `awd`/`continuous_flooding`; `alternate`/`other` → `MethodologyGapError` (không đoán, lệch CH4 ~29%) | nhiều bản ghi mâu thuẫn chế độ → `ConflictingWaterRegimeError` |
| Chế độ nước trước vụ | đọc thẳng `crop_seasons.pre_season_water_regime` | thiếu → `MethodologyGapError`, **không default** |
| Rơm rạ | `incorporated`/`composted` (trả ruộng) → SFo; `burned` → nguồn đốt riêng; `removed` → không tính. Không bao giờ cả hai đường cho cùng 1 bản ghi | thiếu `dry_matter_fraction`/`days_before_cultivation` → `MethodologyGapError` |
| Thu hoạch | `yield_kg = Σ` mọi `harvest_events` còn hiệu lực của **cả crop season** | không có bản ghi nào → `None`, `co2e_per_kg` = `null`, **không phải 0** |

## 6. Carbon calculation flow — scope là Crop Season

Xem đầy đủ lý do và migration tại
[`CARBON_CALCULATION_SCOPE_RESOLUTION.md`](CARBON_CALCULATION_SCOPE_RESOLUTION.md).
Tóm tắt bất biến:

- `carbon_calculations.crop_season_id` **NOT NULL** — scope tính toán luôn là cả vụ.
- `carbon_calculations.production_batch_id` **nullable** — chỉ để truy xuất nguồn gốc,
  **không bao giờ** dùng để chia lại `area_ha`/`cultivation_days`.
- Một vụ có 1 hay nhiều batch, CH4 **chỉ tính một lần** cho cả vụ (test B/C).
- `CO2e/kg = tổng CO2e canh tác / tổng yield của cả vụ`, không phải yield một batch (test D).
- Chưa có allocation methodology cho carbon theo batch → **không tự chia** (test E).

`CarbonService.calculate(crop_season_id, scenario, persist=True)`:

```text
crop_season_id, scenario
        │
        ▼
map_crop_activity_data()  →  CropActivityData
        │
        ▼
calculate_carbon()  →  CarbonResult (fail closed: MissingEmissionFactorError,
        │                MethodologyGapError, ConflictingWaterRegimeError, ...)
        ▼
calculation_row() + breakdown_rows()
        │
        ▼
repository.save_calculation()  →  INSERT carbon_calculations + carbon_breakdowns
```

`persist=False` chạy toàn bộ pipeline mà không ghi — dùng cho What-if Simulation
(giai đoạn 2) sau này, không cần đổi gì ở engine.

## 7. Breakdown persistence — đủ để audit ngược

Mỗi dòng `carbon_breakdowns` (quy ước ở migration `20260908000000` §5):

| Cột | Ý nghĩa |
|---|---|
| `emission_factor_id` | tham số **chính** của nguồn (CH4: EFc, N2O: EF1FR, đốt rơm: Gef, fuel: EF nhiên liệu) |
| `factor_value_used` | hệ số **hiệu dụng** đã nhân hết — với CH4 là `EFi = EFc×SFw×SFp×SFo`, không phải `EFc` thô |
| `gas_kg` | khối lượng khí **trước** khi nhân GWP |
| `co2e_kg` | sau khi nhân GWP |
| `formula_metadata` | `factors_used` (mọi tham số), `derived` (`sfo`, `ef_i`, ...), `provenance` (nguồn từng tham số), `parameter_status` (VERIFIED hay chưa) |

Chuỗi truy vết: `co2e_per_kg → total → breakdown → factor_value_used → formula_metadata → provenance → tài liệu IPCC gốc`.

## 8. API

### `POST /v1/carbon/calculate`

Header bắt buộc: `Authorization: Bearer <jwt>`.

```json
{ "crop_season_id": "uuid", "water_regime_scenario": "awd" }
```

`water_regime_scenario` ∈ `awd | continuous_flooding | as_recorded`.

### `GET /v1/crop-seasons/{crop_season_id}/carbon?scenario=awd`

Header bắt buộc: `Authorization: Bearer <jwt>`. Trả bản tính **thành công** gần nhất;
không bao giờ trả bản tính `failed` như một kết quả thành công.

### `GET /health`

Không query Supabase (nhẹ) — chỉ đọc `emission_factors.yaml` để báo
`carbon_production_ready`, và báo `supabase_configured`/`auth_configured`.

## 9. Error semantics

| Tình huống | HTTP | Mã lỗi |
|---|---|---|
| Thiếu `Authorization` | 401 | `missing_authorization` |
| RLS từ chối HOẶC crop season không tồn tại | 404 | `crop_not_found` (**cố ý không phân biệt** hai trường hợp — tránh lộ ra rằng một vụ tồn tại nhưng thuộc nông hộ khác) |
| Kịch bản nước sai cú pháp | 400 | `invalid_water_regime` |
| Bản ghi nước mâu thuẫn | 409 | `conflicting_water_records` |
| Rơm tính hai lần (bug guard) | 409 | `double_counting` |
| Thiếu hệ số bắt buộc (kể cả GWP) | 422 | `missing_emission_factor` |
| Thiếu biến phương pháp luận (SFp, dry matter, ...) | 422 | `methodology_gap` |
| Thiếu Activity Data (diện tích, %N, ...) | 422 | `missing_activity_data` |
| Bộ hệ số YAML chưa import vào Supabase | 503 | `factor_set_not_imported` |
| Lỗi không xác định (bug, mất kết nối Supabase, ...) | 500 | `internal_error` — **không** trả message/stack trace gốc, chỉ trả `request_id`; chi tiết nằm trong log server-side |

## 10. Auth / RLS

Xem chi tiết trong `backend/infrastructure/auth.py`. Nguyên tắc: **service role không
bao giờ tự quyết định ai thấy gì**. Trước khi service role chạm vào dữ liệu, request
phải qua `CropAccessChecker`, dùng `SUPABASE_PUBLISHABLE_KEY` + JWT của người gọi để
replay đúng câu SELECT mà PostgREST sẽ chạy — để RLS thật trả lời.

**Đã verify thật trên Supabase hosted (không phải JWT giả):**

1. Tạo 1 Supabase Auth user thật (`admin.create_user`, xác nhận email luôn).
2. Đăng nhập bằng publishable key như Flutter sẽ làm, lấy JWT thật.
3. Gọi `crop_seasons` của chính user đó **trước khi** cấp quyền → **bị chặn**.
4. Cấp `organization_memberships` (vai `farmer`) + `farm_members` (đúng schema — cần
   **cả hai**, có trigger baseline bắt buộc farm member phải là thành viên HTX đang
   hoạt động trước) → **được phép**.
5. Cùng JWT đó gọi crop season của **một nông hộ khác** (org/farm/plot/crop season
   riêng, chưa từng cấp quyền) → **vẫn bị chặn** — chứng minh cách ly giữa các nông hộ
   hoạt động thật, không chỉ đúng trên lý thuyết.
6. Dọn sạch: xoá user, xoá toàn bộ dữ liệu test — đếm lại bảng, khớp đúng dữ liệu gốc.

## 11. Local development

```bash
cd backend
pip install -r requirements.txt
python -m pytest tests -q                      # 101 passed
python -m carbon.demo                           # TEST FACTORS — chạy thông
python -m carbon.demo --real                    # config thật — dừng ở gwp.ch4 (đúng)

cp .env.example .env                            # rồi điền — xem §2
uvicorn main:app --reload
```

Không có Supabase local? `npx supabase start` rồi `npx supabase db reset` để dựng từ
đầu — xem [`MIGRATION_HISTORY.md`](MIGRATION_HISTORY.md).

## 12. Hosted smoke test — đã chạy thật, đã dọn sạch

Chạy trên project hosted (`awazhdqzkktekbwaqiic`), **không đụng dữ liệu thật của
người dùng** — dựng riêng một nhánh `SMOKE-TEST-*` (org/farm/plot/crop season/factor
set), chạy hết pipeline qua `SupabaseCarbonRepository` thật (không phải in-memory),
rồi xoá sạch và đếm lại bảng để xác nhận.

| Case | Kết quả |
|---|---|
| Ghi có sản lượng | ✅ `co2e_per_kg` đúng |
| Ghi **không** sản lượng | ✅ Insert thành công, `co2e_per_kg: null` (migration `20260908000003`) |
| Đọc lại qua `service.latest()` | ✅ đúng bản tính, đúng số dòng breakdown |
| HTTP thật qua FastAPI (`main.py`, config production thật) | ✅ `/health` đúng; `POST` → **422** vì GWP thật vẫn `PENDING_VERIFICATION` — chứng minh fail-closed giữ nguyên xuyên suốt cả tầng HTTP |
| Vụ không tồn tại | ✅ 404 |
| Auth/RLS thật (§10) | ✅ chặn/cho phép/cách ly đúng như thiết kế |
| Dọn dẹp | ✅ đếm lại bảng khớp đúng dữ liệu gốc (1 org/1 farm/1 plot có sẵn, 0 dữ liệu test còn sót) |

## 13. Scientific blockers — chưa đổi

| # | Việc | Chặn gì |
|---|---|---|
| OI-05 | **GWP chưa xác minh** | Chặn toàn bộ việc ra số CO2e — `/health.carbon_production_ready: false` |
| OI-06 | Hệ số nhiên liệu chưa có | Nguồn `fuel_*` |
| OI-02 | Chưa lấy được toàn văn QĐ 4801/QĐ-BNNMT | **Không được gọi là MRV-compliant** dù pipeline chạy đúng |

`mrv_compliant` luôn `false` trong mọi bản ghi `carbon_calculations` cho tới khi ba
mục trên được giải quyết.

# backend/ — API + Carbon Engine

- **Lớp MVP:** 1a (Carbon Engine — đường găng) + 1b + 1c.
- **Phụ trách:** Người B.
- **Đặc tả:** [`../docs/modules/02-carbon-engine.md`](../docs/modules/02-carbon-engine.md)
- **Phương pháp luận:** [`../docs/CARBON_METHOD.md`](../docs/CARBON_METHOD.md)
- **Nguồn từng hệ số:** [`../docs/CARBON_METHOD_SOURCES.md`](../docs/CARBON_METHOD_SOURCES.md)

## Trạng thái

| Phần | Trạng thái |
|---|---|
| `carbon/` — Carbon Engine | ✅ chạy được, 90 test pass (57 engine + 33 integration/API) |
| Phương pháp luận CH4 / N2O / đốt rơm | ✅ VERIFIED theo IPCC, trích dẫn số hiệu bảng |
| **GWP** | ⛔ **PENDING_VERIFICATION — đang chặn toàn bộ việc ra số CO2e** |
| Hệ số nhiên liệu | ⏳ PENDING_VERIFICATION |
| QĐ 4801/QĐ-BNNMT (Tier 1) | ❌ chưa lấy được toàn văn → **không được nói "MRV-compliant"** |
| API `/v1/carbon/*` | ✅ POST calculate + GET result, chạy trên repository in-memory |
| Supabase repository | ⚠️ code xong, **CHƯA kết nối DB thật lần nào** |
| Migration | baseline + 3 migration ở `../supabase/migrations/`; đã verified trên Supabase local, **chưa chạy lên hosted DB** |

**Chạy với config thật sẽ dừng ở `MissingEmissionFactorError: gwp.ch4`.** Đó là hành vi
đúng, không phải bug.

## Cấu trúc

```text
backend/
├── carbon/                      # Carbon Engine — chỉ stdlib + pyyaml
│   ├── models.py                # dataclass Activity Data
│   ├── factors.py               # nạp tham số từ YAML — đường DUY NHẤT lấy hệ số
│   ├── methodology.py           # 1 class cho mỗi nguồn phát thải + phân luồng rơm rạ
│   ├── engine.py                # điều phối, tổng hợp, validation, input hash
│   ├── errors.py                # lỗi rõ ràng, không fallback
│   └── demo.py                  # chạy thử end-to-end
├── infrastructure/              # biết Supabase, KHÔNG được import ngược vào carbon/
│   ├── config.py                # đọc .env
│   ├── mapping.py               # THUẦN: hàng DB <-> CropActivityData <-> hàng kết quả
│   ├── repository.py            # Protocol + InMemoryCarbonRepository
│   └── supabase_repo.py         # repository thật (service role)
├── service.py                   # Repository -> Engine -> Repository
├── api.py                       # routes /v1/carbon/*
├── main.py                      # FastAPI app + /health
├── config/
│   └── emission_factors.yaml    # hệ số + nguồn + status (RB-01)
└── tests/
    ├── test_carbon_engine.py        # 57 test engine
    ├── test_integration_supabase.py # 33 test adapter + persistence + API
    └── fixtures/
        ├── demo_crop.json           # DEMO — dữ liệu bịa
        ├── supabase_rows.py         # DEMO — hàng mô phỏng đúng schema
        └── test_factors.yaml        # TEST ONLY — NOT SCIENTIFIC VALUES
```

## Cài đặt

```bash
python -m venv .venv && .venv/Scripts/activate   # Windows
pip install -r requirements.txt
```

## Chạy test

```bash
cd backend
python -m pytest tests -q
```

## Chạy API

```bash
cp .env.example .env          # điền SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY
uvicorn main:app --reload
```

Chưa có `.env` thì app vẫn chạy, `/health` báo `supabase_configured: false`, và mọi
route `/v1/carbon/*` trả **503** kèm hướng dẫn — cố ý, để không âm thầm chạy bằng dữ liệu giả.

| Route | Việc |
|---|---|
| `GET /health` | trạng thái thật: `ef_config_version`, `carbon_production_ready`, `mrv_compliant` |
| `POST /v1/carbon/calculate` | `{crop_season_id, water_regime_scenario}` → tính + lưu cho toàn vụ |
| `GET /v1/crop-seasons/{crop_season_id}/carbon?scenario=` | bản tính **thành công** gần nhất của vụ |

Mã lỗi: 404 không có vụ · 409 dữ liệu mâu thuẫn / phạm vi không rõ · 422 thiếu dữ liệu
hoặc thiếu hệ số (gồm GWP) · 503 chưa import bộ hệ số vào Supabase.

## Kiểm tra schema Supabase thật

```bash
# đặt SUPABASE_DB_URL trong backend/.env — KHÔNG dán vào chat/commit
python ../scripts/validate_supabase_schema.py
```

Chỉ đọc. Kiểm bảng/cột/enum/index/RLS/policy/hàm phân quyền của phần MVP 1a.

## Chạy thử engine

```bash
cd backend

# TEST FACTORS (số bịa) — chạy thông, in cả 2 kịch bản kèm phân rã và provenance
python -m carbon.demo

# Config thật — dừng ở GWP. Đây là hành vi đúng.
python -m carbon.demo --real
```

## Dùng engine trong code

```python
from carbon import CropActivityData, ParameterSet, calculate_carbon

crop = CropActivityData.from_dict({
    "crop_season_id": "plot-a-he-thu-2026",
    "area_ha": 1.0,
    "cultivation_days": 100,
    "yield_kg": 5200,

    # Hai trường này phương pháp luận IPCC BẮT BUỘC có
    "water_regime": "irrigated_multiple_drainage",          # AWD (Table 5.12)
    "pre_season_water_regime": "non_flooded_pre_season_lt_180d",  # SFp (Table 5.13)

    "fertilizer": [{"fertilizer_type": "Urea", "amount_kg": 120, "n_content_pct": 46}],
    "straw": [{
        "method": "incorporated",
        "mass_kg": 5000,
        "dry_matter_fraction": 0.85,      # Eq 5.3 tính theo khối lượng KHÔ
        "days_before_cultivation": 10,    # <30 ngày -> CFOA 1,00; >=30 -> 0,19
    }],
    "fuel": [{"fuel_type": "diesel", "amount_litre": 25}],
})

result = calculate_carbon(crop, scenario="awd")   # awd | continuous_flooding | as_recorded
print(result.to_dict())
```

## Ranh giới kiến trúc

`carbon/` **chỉ** import stdlib + `pyyaml`. Không FastAPI, không pydantic, không Supabase.
Khi nối database, viết lớp adapter riêng ánh xạ bảng Supabase → `CropActivityData`;
**đừng import Supabase vào `carbon/`**.

Hàm `assert_consistent_water_records()` dành cho lớp adapter đó: gộp nhiều bản ghi
`irrigation_events` thành một chế độ nước cấp vụ, và **báo lỗi** nếu chúng mâu thuẫn.

## Quy tắc bắt buộc

1. **Không hardcode hệ số.** Mọi tham số ở `config/emission_factors.yaml` kèm `unit`,
   `source`, `status`. Có test tự động quét mã nguồn tìm hằng số phát thải
   (`test_no_magic_numbers_in_engine_source`).
2. **Không tự điền số chưa xác minh.** `status: VERIFIED` chỉ khi đã trích dẫn được số hiệu
   bảng/phương trình trong tài liệu gốc, và ghi số hiệu đó vào `source`.
3. **Không fallback, không default.** Thiếu tham số → `MissingEmissionFactorError`. Thiếu biến
   phương pháp luận → `MethodologyGapError`. Thiếu sản lượng → `co2e_per_kg = None`,
   **không trả 0**. Thiếu số ngày canh tác → lỗi, **không dùng 102 ngày mặc định của IPCC**
   (đó là trung bình vùng cho kiểm kê quốc gia, sai phạm vi cho cấp thửa ruộng).
4. **Không double count rơm rạ.** Rơm vùi vào SFo; rơm đốt là nguồn riêng; không bao giờ cả hai.
5. **Không áp tỷ lệ giảm phẳng cho kịch bản AWD.** Đổi SFw và EF1FR rồi chạy lại công thức —
   AWD giảm CH4 nhưng **tăng** N2O.
6. **Số sinh từ TEST FACTORS không được đem đi pitch.**
7. **Không gắn nhãn "MRV-compliant"** khi chưa lấy được QĐ 4801/QĐ-BNNMT.
8. **Service-role key chỉ tồn tại ở backend.** Không bao giờ đưa vào Flutter app hay web.
   Client đọc qua API này, hoặc qua Supabase với anon key + RLS.
9. **YAML là nguồn sự thật cho GIÁ TRỊ hệ số.** Bảng `emission_factor_sets`/`emission_factors`
   là bản sao có kiểm soát để bản tính liên kết được `factor_set_id`. Không có bộ hệ số
   published trùng `version_code` → backend từ chối ghi, **không tự tạo bộ rỗng**.

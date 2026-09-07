# backend/ — API + Carbon Engine

- **Lớp MVP:** 1a (Carbon Engine — đường găng) + 1b (benchmark, recommendation) + 1c (export MRV).
- **Phụ trách:** Người B.
- **Đặc tả:** [`../docs/modules/02-carbon-engine.md`](../docs/modules/02-carbon-engine.md)
- **Công thức & trạng thái xác minh:** [`../docs/CARBON_METHOD.md`](../docs/CARBON_METHOD.md)

## Trạng thái hiện tại

| Phần | Trạng thái |
|---|---|
| `carbon/` — Carbon Engine | ✅ chạy được, 21 unit test pass |
| `config/emission_factors.yaml` | ⚠️ **toàn bộ hệ số đang `null`** — chờ open issue OI-02 |
| `main.py` — API FastAPI | ❌ mới là entrypoint TODO |
| Supabase / database | ❌ ngoài phạm vi — thành viên khác đang thiết kế |

**Engine chưa tính được số thật.** Chạy với config thật sẽ ném `MissingEmissionFactorError` —
đó là hành vi đúng, không phải bug. Xem [`../docs/CARBON_METHOD.md`](../docs/CARBON_METHOD.md).

## Cấu trúc

```text
backend/
├── carbon/                     # Carbon Engine — KHÔNG phụ thuộc FastAPI/Supabase/UI
│   ├── models.py               # dataclass Activity Data (stdlib, không pydantic)
│   ├── factors.py              # nạp hệ số từ YAML, đường duy nhất engine lấy hệ số
│   ├── engine.py               # calculate_carbon() — hàm thuần
│   ├── errors.py               # lỗi rõ ràng, không fallback
│   └── demo.py                 # chạy thử end-to-end
├── config/
│   └── emission_factors.yaml   # hệ số + nguồn + status (RB-01)
├── tests/
│   ├── test_carbon_engine.py
│   └── fixtures/
│       ├── demo_crop.json      # DEMO — dữ liệu bịa
│       └── test_factors.yaml   # TEST FACTORS — số bịa, chỉ để test implementation
└── main.py                     # API — chưa làm
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

## Chạy thử engine

```bash
cd backend

# Dùng TEST FACTORS (số bịa) — chạy thông, in ra cả 2 kịch bản awd và continuous_flooding
python -m carbon.demo

# Dùng config thật — SẼ BÁO LỖI vì hệ số còn null. Đây là hành vi đúng.
python -m carbon.demo --real
```

## Dùng engine trong code

```python
from carbon import CropActivityData, EmissionFactorSet, calculate_carbon

crop = CropActivityData.from_dict({
    "crop_id": "plot-a-vu-he-thu",
    "area_ha": 1.0,
    "cultivation_days": 100,
    "yield_kg": 5200,
    "water": {"regime": "awd", "drainage_events": 3, "pump_fuel_litre": 25},
    "fertilizer": [{"fertilizer_type": "Urea", "amount_kg": 120, "n_content_pct": 46}],
    "straw": {"method": "removed", "amount_kg": 5000},
})

result = calculate_carbon(crop, water_regime_scenario="awd")
print(result.to_dict())
```

`water_regime_scenario` nhận `awd`, `continuous_flooding`, hoặc `as_recorded`.

## Quy tắc bắt buộc

1. **Không hardcode hệ số phát thải** (RB-01). Mọi hệ số nằm ở `config/emission_factors.yaml`
   kèm `unit`, `source`, `status`. `carbon/factors.py` là đường duy nhất engine lấy hệ số.
2. **Không tự điền số chưa xác minh.** Hệ số chỉ chuyển sang `status: VERIFIED` khi đã đối
   chiếu nguồn chính thức và ghi nguồn đó vào config.
3. **Không fallback.** Thiếu hệ số → `MissingEmissionFactorError`. Thiếu sản lượng →
   `co2e_per_kg = None` kèm cảnh báo, **không trả 0**.
4. **Engine không phụ thuộc UI/database.** `carbon/` chỉ import stdlib + `pyyaml`.
   Khi nối Supabase, viết lớp mapping riêng — đừng import Supabase vào `carbon/`.
5. **Số sinh từ TEST FACTORS không được đem đi pitch.** Đó là số bịa để kiểm chứng phép tính.

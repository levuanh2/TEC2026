# Sequence: tính Carbon

Route thật: `POST /v1/carbon/calculate` với body
`{"crop_season_id": "<uuid>", "water_regime_scenario": "as_recorded" | "awd" | "continuous_flooding"}`.
Client gọi route này: Management Web (`features/carbon.tsx`, nút tính lại) và
Flutter (`screens/carbon_result_screen.dart`). Farmer Web chỉ đọc kết quả.

## Tính và lưu

```mermaid
sequenceDiagram
    autonumber
    actor U as Người dùng
    participant C as Management Web / Flutter
    participant API as FastAPI api.py
    participant AC as SupabaseCropAccessChecker
    participant CS as CarbonService
    participant REPO as SupabaseCarbonRepository
    participant MAP as mapping.py
    participant ENG as calculate_carbon
    participant PS as ParameterSet YAML
    participant DB as PostgreSQL

    U->>C: Bấm tính cho vụ + kịch bản
    C->>API: POST /v1/carbon/calculate + Bearer JWT
    API->>AC: assert_can_access(JWT, crop_season_id)
    AC->>DB: SELECT crop_seasons.id bằng JWT (RLS)
    alt không có hàng
        API-->>C: 404 crop_not_found
    end
    API->>CS: calculate(crop_season_id, scenario)
    CS->>REPO: get_crop_bundle(crop_season_id)
    REPO->>DB: crop_seasons, plots, farms (service role)
    REPO->>DB: production_batches của vụ
    REPO->>DB: activities theo từng lô chưa xoá
    REPO->>DB: bảng chi tiết theo activity_type (IN activity_id)
    REPO-->>CS: RawCropBundle
    CS->>MAP: map_crop_activity_data(bundle)
    MAP->>MAP: area_ha, water regime, Σ yield_kg, fertilizer, straw, fuel
    MAP-->>CS: CropActivityData
    CS->>ENG: calculate_carbon(data, scenario, params)
    ENG->>ENG: kiểm tra chế độ nước, số ngày, rơm, double counting
    ENG->>PS: EFc, SFw, SFp, CFOA, sfo_exponent
    ENG->>PS: gwp ch4
    alt gwp null (cấu hình hiện tại)
        PS-->>ENG: MissingEmissionFactorError
        ENG-->>CS: lỗi
        CS-->>API: lỗi
        API-->>C: 422 missing_emission_factor
    else đủ tham số
        ENG->>PS: EF1FR, 44/28, gwp n2o, Cf, Gef, EF fuel
        ENG->>ENG: tổng CO2e, CO2e/kg, cảnh báo, input_hash
        ENG-->>CS: CarbonResult
        CS->>REPO: resolve_factor_set_id(ef_config_version)
        REPO->>DB: emission_factor_sets published
        alt chưa import bộ hệ số
            API-->>C: 503 factor_set_not_imported
        end
        CS->>REPO: factor_ids_by_code(factor_set_id)
        CS->>REPO: save_calculation(row, breakdown_rows)
        REPO->>DB: INSERT carbon_calculations
        REPO->>DB: INSERT carbon_breakdowns
        REPO-->>CS: calculation_id
        CS-->>API: CalculationOutcome
        API-->>C: 200 CarbonResult + calculation_id
    end
```

Các nhánh kiểm tra dữ liệu (không hiện hết trong sơ đồ để giữ gọn) trả lỗi trước
khi tới bước hệ số:

| Kiểm tra | HTTP |
|---|---|
| Thửa thiếu `area_ha` | 422 `missing_activity_data` |
| Tưới `alternate`/`other` không có `ipcc_water_regime` | 422 `methodology_gap` |
| Nhiều chế độ tưới mâu thuẫn | 409 `conflicting_water_records` |
| `as_recorded` nhưng không có chế độ nước | 422 `missing_activity_data` |
| Thiếu số ngày canh tác | 422 `missing_activity_data` |
| Rơm vùi thiếu `days_before_cultivation` / thiếu `dry_matter_fraction` | 422 `methodology_gap` |
| Thiếu `pre_season_water_regime` | 422 `methodology_gap` |

## Đọc bản tính đã lưu

```mermaid
sequenceDiagram
    autonumber
    participant C as Client
    participant API as FastAPI
    participant AC as SupabaseCropAccessChecker
    participant CS as CarbonService
    participant REPO as SupabaseCarbonRepository
    participant DB as PostgreSQL

    C->>API: GET /v1/crop-seasons/id/carbon?scenario=
    API->>AC: assert_can_access(JWT, id)
    AC->>DB: SELECT crop_seasons bằng JWT (RLS)
    API->>CS: latest(id, scenario)
    CS->>REPO: latest_calculation
    REPO->>DB: carbon_calculations status succeeded, mới nhất
    REPO->>DB: carbon_breakdowns của bản tính đó
    alt không có bản tính
        API-->>C: 404 no_calculation
    else có
        API-->>C: 200 hàng đã lưu + breakdown
    end
```

## Chạy giả định không lưu (`persist=False`)

`RecommendationService` gọi `CarbonService.calculate(crop_season_id, scenario, persist=False)`:
toàn bộ bước nạp dữ liệu và tính giống hệt sơ đồ đầu, nhưng dừng sau khi có
`CarbonResult` — không resolve bộ hệ số, không ghi bảng nào. Xem
[sequence Recommendation](system-sequences.md#5-recommendation-simulation).

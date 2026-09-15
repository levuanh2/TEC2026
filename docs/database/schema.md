# Database schema

Nguồn sự thật: chuỗi migration trong `supabase/migrations/`. Trang này mô tả các
bảng **ứng dụng đang dùng**, gom theo nhóm, kèm ER diagram từng nhóm. Tên bảng,
cột và enum giữ nguyên như trong SQL.

## Chuỗi migration

| File | Nội dung chính |
|---|---|
| `20260907000000_baseline.sql` | Toàn bộ schema gốc: enum, bảng nghiệp vụ, trigger toàn vẹn, hàm RLS `private.*`, policy, view, schema `audit` và `pm`, policy Storage |
| `20260908000000_carbon_methodology_alignment.sql` | Enum `parameter_kind`, `parameter_verification_status`, `ipcc_water_regime`, `ipcc_pre_season_regime`; cột methodology trên `crop_seasons`, `straw_management_events`, `emission_factors`, `carbon_breakdowns`, `carbon_calculations`; view `v_carbon_results_detailed` |
| `20260908000001_carbon_calculation_scope_audit.sql` | `carbon_calculations.crop_season_id`, `area_ha_used`, `cultivation_days_used`, `water_regime_applied`, `pre_season_water_regime_applied` |
| `20260908000002_crop_season_carbon_scope.sql` | Khoá phạm vi bản tính vào crop season; `production_batch_id` thành tuỳ chọn; trigger kiểm lô cùng vụ; policy đọc theo crop season |
| `20260908000003_carbon_success_allows_unknown_yield.sql` | `succeeded` không còn bắt buộc `yield_kg` |
| `20260908134822_grant_private_schema_service_role.sql` | `grant usage on schema private to service_role` |
| `20260910080441_farmer_web_activity_idempotency.sql` | `activities.web_idempotency_key` + unique index `(recorded_by, web_idempotency_key)` |
| `20260911120000_season_recommendations.sql` | Bảng `season_recommendations` + RLS đọc |
| `20260913090000_allow_owner_soft_delete_activities.sql` | RPC `public.soft_delete_activity`, helper `private.user_can_delete_activity`, trigger giữ bất biến chủ sở hữu |
| `20260913120000_mrv_json_export_manifest.sql` | `export_format` thêm `json`; `mrv_exports.factor_set_id` thành nullable |
| `20260913150000_mrv_xlsx_export_artifacts.sql` | `source_snapshot_export_id`, `payload_sha256`, ràng buộc lineage; siết `mrv_exports_select` về manager |

Không có migration riêng cho PDF: giá trị `pdf` đã có trong enum `export_format`
từ baseline.

## 1. Organization / Membership

```mermaid
erDiagram
    PROFILES ||--o{ ORGANIZATION_MEMBERSHIPS : "thuộc"
    ORGANIZATIONS ||--o{ ORGANIZATION_MEMBERSHIPS : "có"
    ORGANIZATIONS ||--o{ ORGANIZATION_DATA_GRANTS : "cấp cho grantee"
    PROFILES {
        uuid id PK "auth.users.id"
        text full_name
        boolean is_active
    }
    ORGANIZATIONS {
        uuid id PK
        text organization_code UK
        text name
        organization_type organization_type
        boolean is_active
    }
    ORGANIZATION_MEMBERSHIPS {
        uuid id PK
        uuid organization_id FK
        uuid user_id FK
        organization_role role
        timestamptz joined_at
        timestamptz ended_at
    }
    ORGANIZATION_DATA_GRANTS {
        uuid id PK
        uuid grantee_organization_id FK
        uuid source_organization_id FK
        data_access_level access_level
        date valid_from
        date valid_to
    }
```

- `organization_role`: `farmer`, `cooperative_manager`, `enterprise_viewer`, `regulator`.
- `organization_type`: `cooperative`, `enterprise`, `government`, `research`, `other`.
- Trigger `on_auth_user_created` (`private.handle_new_user`) tạo `profiles` khi có user mới.
- `ended_at` trong quá khứ nghĩa là membership hết hiệu lực — mọi helper RLS và
  `MrvExportService._manages` đều kiểm tra điều này.

## 2. Farm / Plot / Season / Batch

```mermaid
erDiagram
    ORGANIZATIONS ||--o{ FARMS : "cooperative_id"
    FARMS ||--o{ FARM_MEMBERS : "có"
    PROFILES ||--o{ FARM_MEMBERS : "là"
    FARMS ||--o{ PLOTS : "có"
    PLOTS ||--o{ CROP_SEASONS : "có"
    CROP_SEASONS ||--o{ PRODUCTION_BATCHES : "có"
    PROFILES ||--o{ DEVICES : "đăng ký"
    FARMS {
        uuid id PK
        uuid cooperative_id FK
        text farm_code "unique theo cooperative"
        text farm_name
        timestamptz deleted_at
    }
    FARM_MEMBERS {
        uuid farm_id PK
        uuid user_id PK
        farm_role farm_role
    }
    PLOTS {
        uuid id PK
        uuid farm_id FK
        text plot_code "unique theo farm"
        numeric area_ha "lớn hơn 0"
        timestamptz deleted_at
    }
    CROP_SEASONS {
        uuid id PK
        uuid plot_id FK
        text season_code "unique theo plot"
        date planting_date
        date actual_harvest_date
        crop_status status
        ipcc_water_regime ipcc_water_regime
        ipcc_pre_season_regime pre_season_water_regime
        integer cultivation_days
        timestamptz deleted_at
    }
    PRODUCTION_BATCHES {
        uuid id PK
        uuid crop_season_id FK
        text batch_code "unique theo season"
        batch_status status
        timestamptz deleted_at
    }
    DEVICES {
        uuid id PK
        uuid user_id FK
        uuid installation_id UK
        text platform
    }
```

- `farm_role`: `owner`, `editor`, `viewer`.
- `crop_status` / `batch_status`: `planned`, `active`, `harvested`, `closed`, `cancelled`.
- Farmer Web chỉ cho ghi khi `crop_seasons.status = 'active'`.
- Các cột phương pháp luận trên `crop_seasons` (`ipcc_water_regime`,
  `pre_season_water_regime`, `cultivation_days`, `drainage_event_count`) nullable;
  thiếu thì Carbon Engine báo lỗi thay vì đoán.

## 3. Activities

```mermaid
erDiagram
    PRODUCTION_BATCHES ||--o{ ACTIVITIES : "neo"
    ACTIVITIES ||--o| SEEDING_EVENTS : "chi tiết"
    ACTIVITIES ||--o| FERTILIZER_APPLICATIONS : "chi tiết"
    ACTIVITIES ||--o| IRRIGATION_EVENTS : "chi tiết"
    ACTIVITIES ||--o| PESTICIDE_APPLICATIONS : "chi tiết"
    ACTIVITIES ||--o| FUEL_USAGES : "chi tiết"
    ACTIVITIES ||--o| STRAW_MANAGEMENT_EVENTS : "chi tiết"
    ACTIVITIES ||--o| HARVEST_EVENTS : "chi tiết"
    ACTIVITIES {
        uuid id PK
        uuid production_batch_id FK
        activity_type activity_type
        timestamptz occurred_at
        timestamptz recorded_at
        timestamptz server_received_at
        data_source source
        uuid recorded_by FK
        uuid device_id FK
        uuid client_event_id
        uuid web_idempotency_key
        bigint row_version
        timestamptz deleted_at
    }
    SEEDING_EVENTS {
        uuid activity_id PK
        numeric seed_kg
        numeric cost_vnd
    }
    FERTILIZER_APPLICATIONS {
        uuid activity_id PK
        text fertilizer_name
        numeric amount_kg
        numeric nitrogen_percent
        numeric total_cost_vnd
    }
    IRRIGATION_EVENTS {
        uuid activity_id PK
        irrigation_method method
        numeric water_volume_m3
        numeric pump_energy_kwh
        numeric total_cost_vnd
    }
    PESTICIDE_APPLICATIONS {
        uuid activity_id PK
        text product_name
        numeric amount
        text unit
        numeric total_cost_vnd
    }
    FUEL_USAGES {
        uuid activity_id PK
        fuel_type fuel_type
        numeric amount_liter
        numeric total_cost_vnd
    }
    STRAW_MANAGEMENT_EVENTS {
        uuid activity_id PK
        straw_management_method method
        numeric straw_mass_kg
        numeric dry_matter_fraction
        integer days_before_cultivation
        boolean returned_to_field
        numeric total_cost_vnd
    }
    HARVEST_EVENTS {
        uuid activity_id PK
        numeric yield_kg "lớn hơn 0"
        numeric harvested_area_ha
        numeric moisture_percent
        numeric total_cost_vnd
    }
```

| Ràng buộc | Ý nghĩa |
|---|---|
| `activities_device_event_pair_chk` | `device_id` và `client_event_id` cùng null hoặc cùng có |
| `activities_mobile_device_chk` | `source` là `mobile_offline`/`mobile_online` thì bắt buộc `device_id` |
| `activities_device_event_uidx` | Unique `(device_id, client_event_id)` (partial) — idempotency của Flutter |
| `activities_web_idempotency_uidx` | Unique `(recorded_by, web_idempotency_key)` (partial) — idempotency của Farmer Web |
| `private.enforce_activity_type` | Bảng chi tiết phải khớp `activity_type` của activity cha |
| `enforce_activity_ownership_immutable_trg` | Khi RLS đang áp: không đổi `recorded_by` đã có, `activity_type`, `device_id`, `client_event_id` |
| `touch_activity_row_trg` | Tăng `row_version`, cập nhật `updated_at` |

Enum liên quan: `activity_type` (`seeding`, `fertilizer`, `irrigation`, `pesticide`,
`fuel`, `straw_management`, `harvest`, `other`), `data_source` (`mobile_offline`,
`mobile_online`, `web`, `api`, `import`, `system`), `irrigation_method` (`awd`,
`continuous_flooding`, `alternate`, `other`), `straw_management_method`
(`incorporated`, `removed`, `burned`, `composted`, `other`), `fuel_type` (`diesel`,
`gasoline`, `lpg`, `other`).

## 4. Carbon

```mermaid
erDiagram
    CROP_SEASONS ||--o{ CARBON_CALCULATIONS : "phạm vi"
    EMISSION_FACTOR_SETS ||--o{ EMISSION_FACTORS : "gồm"
    EMISSION_FACTOR_SETS ||--o{ CARBON_CALCULATIONS : "factor_set_id"
    CARBON_CALCULATIONS ||--o{ CARBON_BREAKDOWNS : "phân rã"
    EMISSION_FACTORS ||--o{ CARBON_BREAKDOWNS : "hệ số chính"
    EMISSION_FACTOR_SETS {
        uuid id PK
        text version_code UK
        text methodology_name
        ef_status status
        timestamptz published_at
    }
    EMISSION_FACTORS {
        uuid id PK
        uuid factor_set_id FK
        text factor_code "unique theo set"
        emission_category category
        greenhouse_gas gas
        numeric factor_value
        parameter_kind parameter_kind
        parameter_verification_status verification_status
        text source_reference
    }
    CARBON_CALCULATIONS {
        uuid id PK
        uuid crop_season_id FK
        uuid production_batch_id FK "tuỳ chọn"
        carbon_scenario scenario
        uuid factor_set_id FK
        text engine_version
        text input_hash
        numeric total_co2e_kg
        numeric yield_kg
        numeric co2e_per_kg "generated"
        calculation_status status
        smallint methodology_tier
        boolean mrv_compliant
        jsonb warnings
        numeric area_ha_used
        integer cultivation_days_used
        timestamptz calculated_at
    }
    CARBON_BREAKDOWNS {
        uuid id PK
        uuid calculation_id FK
        uuid emission_factor_id FK
        emission_category category
        greenhouse_gas gas
        numeric activity_value
        numeric factor_value_used
        numeric gas_kg
        numeric co2e_kg
        jsonb formula_metadata
        text formula_expression
    }
```

- `carbon_scenario`: `actual`, `awd`, `continuous_flooding` — engine gọi `actual`
  là `as_recorded` (`carbon/models.py::SCENARIO_TO_DB`).
- `calculation_status`: `pending`, `succeeded`, `failed`, `superseded`. Backend chỉ
  ghi `succeeded`; lỗi tính không được lưu thành hàng.
- `carbon_success_chk`: `succeeded` bắt buộc `total_co2e_kg` và không có `failure_reason`.
- `carbon_calculations_season_input_uniq`: unique `(crop_season_id, scenario, factor_set_id, input_hash)`
  cho bản tính cả vụ (`production_batch_id is null`).
- `carbon_breakdown_multiparam_needs_metadata_chk`: dòng `irrigation_ch4` bắt buộc có `formula_metadata`.
- `ef_verified_needs_table_reference_chk`: tham số `VERIFIED` bắt buộc có `source_table_reference`.
- `mrv_compliant` mặc định `false` và backend luôn ghi `false`.

## 5. Recommendation

```mermaid
erDiagram
    CROP_SEASONS ||--o{ SEASON_RECOMMENDATIONS : "có"
    SEASON_RECOMMENDATIONS {
        uuid id PK
        uuid crop_season_id FK
        text rule_code "unique theo season"
        text rule_version
        text engine_version
        text type "optimization hoặc data_task"
        recommendation_status status
        text title
        text reason
        text compared_to
        numeric co2e_total_kg_before
        numeric co2e_total_kg_after
        numeric co2e_total_kg_delta
        numeric co2e_percent_delta
        text impact_status "available hoặc unavailable"
        text impact_unavailable_reason
        jsonb evidence
        text input_hash
        timestamptz generated_at
    }
```

`recommendation_status`: `generated`, `accepted`, `dismissed`, `expired`. Bảng
baseline `recommendations` / `recommendation_rules` / `benchmark_snapshots` /
`resource_metric_snapshots` **không được code dùng**.

## 6. Computer Vision

```mermaid
erDiagram
    CROP_SEASONS ||--o{ PLANT_IMAGES : "có"
    PLANT_IMAGES ||--o{ CV_INFERENCES : "được suy luận"
    CV_MODEL_VERSIONS ||--o{ CV_INFERENCES : "bởi"
    PLANT_IMAGES {
        uuid id PK
        uuid crop_season_id FK
        text storage_bucket "plant-images"
        text storage_object_path UK
        text mime_type "jpeg hoặc png"
        text sha256 "unique khi chưa xoá"
        uuid uploaded_by FK
        timestamptz deleted_at
    }
    CV_MODEL_VERSIONS {
        uuid id PK
        text version_code UK
        text model_name
        numeric accuracy
        jsonb confusion_matrix
        numeric confidence_threshold
        model_status status
    }
    CV_INFERENCES {
        uuid id PK
        uuid image_id FK
        uuid model_version_id FK
        disease_label predicted_label
        numeric confidence
        numeric threshold_used
        boolean is_uncertain "generated"
        timestamptz inferred_at
    }
```

- `disease_label`: `rice_blast`, `bacterial_leaf_blight`, `brown_spot`, `healthy`, `unknown`.
  Backend ghi `unknown` khi độ tin cậy dưới ngưỡng và API trả `label: null`.
- `cv_model_versions` do backend tạo với `status = 'draft'`; policy đọc của
  `authenticated` chỉ thấy `active`/`retired` (backend đọc bằng kết nối riêng).
- Trigger `private.validate_plant_image_path`: đường dẫn phải là `<farm_uuid>/<crop_season_uuid>/<file>`.

## 7. MRV và Exports

```mermaid
erDiagram
    ORGANIZATIONS ||--o{ MRV_CASES : "sở hữu"
    MRV_STEP_CATALOG ||--o{ MRV_CASE_STEPS : "định nghĩa"
    MRV_CASES ||--o{ MRV_CASE_STEPS : "6 bước"
    MRV_CASES ||--o{ MRV_CASE_BATCHES : "liên kết"
    PRODUCTION_BATCHES ||--o{ MRV_CASE_BATCHES : "được liên kết"
    MRV_CASES ||--o{ MRV_EVIDENCE : "có"
    MRV_CASES ||--o{ MRV_EXPORTS : "xuất"
    MRV_EXPORTS ||--o{ MRV_EXPORT_CALCULATIONS : "tham chiếu"
    CARBON_CALCULATIONS ||--o{ MRV_EXPORT_CALCULATIONS : "được dùng"
    MRV_EXPORTS |o--o{ MRV_EXPORTS : "source_snapshot_export_id"
    MRV_STEP_CATALOG {
        smallint step_no PK "1 đến 6"
        text name UK
        text description
    }
    MRV_CASES {
        uuid id PK
        uuid organization_id FK
        text case_code "unique theo org"
        text name
        date period_start
        date period_end
        mrv_case_status status
        uuid created_by FK
    }
    MRV_CASE_STEPS {
        uuid mrv_case_id PK
        smallint step_no PK
        mrv_step_status status
        timestamptz started_at
        timestamptz completed_at
        text notes
    }
    MRV_CASE_BATCHES {
        uuid mrv_case_id PK
        uuid production_batch_id PK
        timestamptz added_at
    }
    MRV_EVIDENCE {
        uuid id PK
        uuid mrv_case_id FK
        smallint step_no FK
        uuid production_batch_id FK
        text evidence_type
        text storage_object_path UK
        text file_name
        text mime_type
        text sha256
        uuid uploaded_by FK
    }
    MRV_EXPORTS {
        uuid id PK
        uuid mrv_case_id FK
        export_format format
        uuid factor_set_id FK "nullable"
        text scope_description
        timestamptz data_as_of_at
        boolean contains_sample_data
        boolean is_finalized
        text warning_text
        text storage_object_path UK
        text file_sha256
        text payload_sha256
        uuid source_snapshot_export_id FK
        jsonb export_payload
        uuid generated_by FK
        timestamptz generated_at
    }
    MRV_EXPORT_CALCULATIONS {
        uuid mrv_export_id PK
        uuid carbon_calculation_id PK
    }
```

- `mrv_step_catalog` được seed 6 bước với tên tiếng Anh (`Preparation`, `Registration`,
  `Baseline`, `Measurement`, `Reporting`, `Verification`); API hiển thị nhãn tiếng
  Việt cố định trong `read_repo.py::MRV_STEP_LABELS`.
- Trigger `populate_mrv_steps_trg` tự tạo 6 dòng `mrv_case_steps` khi insert case.
- `mrv_case_status`: `draft`, `in_progress`, `ready_for_verification`, `verified`, `closed`
  (giá trị lưu trong DB, không phải kết luận của AgriCarbon).
- `mrv_step_status`: `not_started`, `in_progress`, `completed`, `blocked`.
- `export_format`: `pdf`, `xlsx`, `json`.
- `mrv_export_warning_chk`: gói chưa finalized phải có `warning_text` — backend luôn ghi
  `is_finalized = false` kèm disclaimer.
- `mrv_export_snapshot_lineage_chk`: `json` không có `source_snapshot_export_id`; `xlsx`/`pdf` bắt buộc có.
- Trigger `validate_mrv_evidence_path_trg` / `validate_mrv_export_path_trg`: đường dẫn
  `<organization_uuid>/<mrv_case_uuid>/<file>`.

## Storage

| Bucket | Đường dẫn | Ghi bởi | Policy `storage.objects` cho `authenticated` |
|---|---|---|---|
| `plant-images` | `<farm_uuid>/<crop_season_uuid>/<file>` | Backend (service role) | Đọc: `user_can_read_farm`; ghi/sửa/xoá: `user_can_write_farm`, đuôi `jpg/jpeg/png` |
| `mrv-evidence` | `<organization_uuid>/<mrv_case_uuid>/<file>` | Chưa có luồng upload trong code | Đọc: `user_can_read_organization`; ghi: `user_is_org_manager` |
| `mrv-exports` | `<organization_uuid>/<mrv_case_uuid>/<file>` | Backend (service role), chỉ XLSX/PDF | Đọc: `user_can_read_organization`; ghi: `user_is_org_manager` |

Backend **không** cấp signed URL; artifact MRV chỉ tải qua
`GET /v1/mrv/exports/{id}/download` sau khi kiểm quyền và SHA-256.

!!! bug "Policy đọc Storage của `mrv-exports` rộng hơn metadata"
    `mrv_files_storage_select` (baseline) cho `user_can_read_organization` — gồm
    `farmer` của tổ chức và `enterprise_viewer`/`regulator` qua data grant — đọc
    object trong `mrv-exports`, trong khi `mrv_exports_select` đã siết về manager
    (migration `20260913150000`). Ứng dụng không gọi Storage trực tiếp, nhưng policy
    không phụ thuộc ứng dụng: ai có JWT hợp lệ vẫn gọi được Storage API. Đây là lỗ
    hổng đã biết, chưa sửa ([M7](../limitations/implementation-audit-findings.md#m7)).

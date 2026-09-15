# Domain model

Mô hình miền lấy từ migration thực tế (`supabase/migrations/`). Chỉ các field
quan trọng cho việc hiểu hệ thống được đưa vào sơ đồ; danh sách cột đầy đủ xem
[Database schema](../database/schema.md).

## Phân cấp lõi

```text
Organization (HTX)
 └─ Farm (nông hộ)
     └─ Plot (thửa, có area_ha)
         └─ Crop Season (vụ canh tác)  ← PHẠM VI tính Carbon, metrics, khuyến nghị, CV
             ├─ Production Batch       ← chỉ để truy xuất nguồn gốc / neo activity
             │   └─ Activity + bảng chi tiết (seeding, fertilizer, irrigation,
             │                              pesticide, fuel, straw, harvest)
             ├─ Carbon Calculation → Carbon Breakdown
             ├─ Season Recommendation
             └─ Plant Image → CV Inference
MRV Case (thuộc Organization) ─ liên kết Production Batch qua mrv_case_batches
```

!!! note "Batch là truy xuất nguồn gốc, không phải phạm vi Carbon"
    `activities.production_batch_id` là `NOT NULL`, nên mọi hoạt động phải neo vào
    một lô. Nhưng migration `20260908000002_crop_season_carbon_scope.sql` khoá phạm
    vi bản tính vào `carbon_calculations.crop_season_id` (bắt buộc) và biến
    `production_batch_id` thành tuỳ chọn. Repository Carbon gom activity của **mọi
    lô chưa xoá** trong vụ (`SupabaseCarbonRepository.get_crop_bundle`).
    Flutter tự tạo một lô `batch_code = 'default'` cho mỗi vụ; Farmer Web yêu cầu
    vụ có **đúng một** lô đang mở mới cho ghi.

## 1. Tổ chức, nông hộ và vụ

```mermaid
classDiagram
    direction LR
    class Organization {
        uuid id
        text organization_code
        organization_type organization_type
    }
    class OrganizationMembership {
        uuid user_id
        organization_role role
        timestamptz ended_at
    }
    class OrganizationDataGrant {
        uuid grantee_organization_id
        uuid source_organization_id
        data_access_level access_level
        date valid_from
        date valid_to
    }
    class Farm {
        uuid id
        uuid cooperative_id
        text farm_code
        text farm_name
    }
    class FarmMember {
        uuid user_id
        farm_role farm_role
    }
    class Plot {
        uuid id
        text plot_code
        numeric area_ha
    }
    class CropSeason {
        uuid id
        text season_code
        date planting_date
        date actual_harvest_date
        crop_status status
        ipcc_water_regime ipcc_water_regime
        ipcc_pre_season_regime pre_season_water_regime
        int cultivation_days
    }
    class ProductionBatch {
        uuid id
        text batch_code
        batch_status status
    }
    Organization "1" --> "*" OrganizationMembership
    Organization "1" --> "*" OrganizationDataGrant : source hoặc grantee
    Organization "1" --> "*" Farm : cooperative_id
    Farm "1" --> "*" FarmMember
    Farm "1" --> "*" Plot
    Plot "1" --> "*" CropSeason
    CropSeason "1" --> "*" ProductionBatch
```

## 2. Hoạt động canh tác

```mermaid
classDiagram
    direction TB
    class Activity {
        uuid id
        uuid production_batch_id
        activity_type activity_type
        timestamptz occurred_at
        timestamptz recorded_at
        data_source source
        uuid recorded_by
        uuid device_id
        uuid client_event_id
        uuid web_idempotency_key
        timestamptz deleted_at
    }
    class SeedingEvent {
        numeric seed_kg
        numeric cost_vnd
    }
    class FertilizerApplication {
        numeric amount_kg
        numeric nitrogen_percent
        numeric total_cost_vnd
    }
    class IrrigationEvent {
        irrigation_method method
        numeric water_volume_m3
        numeric pump_energy_kwh
    }
    class PesticideApplication {
        numeric amount
        text unit
    }
    class FuelUsage {
        fuel_type fuel_type
        numeric amount_liter
    }
    class StrawManagementEvent {
        straw_management_method method
        numeric straw_mass_kg
        numeric dry_matter_fraction
        int days_before_cultivation
        bool returned_to_field
    }
    class HarvestEvent {
        numeric yield_kg
        numeric harvested_area_ha
    }
    ProductionBatch "1" --> "*" Activity
    Activity "1" --> "0..1" SeedingEvent
    Activity "1" --> "0..1" FertilizerApplication
    Activity "1" --> "0..1" IrrigationEvent
    Activity "1" --> "0..1" PesticideApplication
    Activity "1" --> "0..1" FuelUsage
    Activity "1" --> "0..1" StrawManagementEvent
    Activity "1" --> "0..1" HarvestEvent
```

Mỗi bảng chi tiết dùng `activity_id` làm khoá chính; trigger
`private.enforce_activity_type` bảo đảm bảng chi tiết khớp `activity_type`.

## 3. Kết quả theo vụ

```mermaid
classDiagram
    direction LR
    class CropSeason {
        uuid id
    }
    class CarbonCalculation {
        uuid crop_season_id
        uuid production_batch_id
        carbon_scenario scenario
        uuid factor_set_id
        numeric total_co2e_kg
        numeric yield_kg
        numeric co2e_per_kg
        calculation_status status
        text input_hash
        bool mrv_compliant
        jsonb warnings
    }
    class CarbonBreakdown {
        emission_category category
        greenhouse_gas gas
        numeric activity_value
        numeric factor_value_used
        numeric gas_kg
        numeric co2e_kg
        jsonb formula_metadata
    }
    class EmissionFactorSet {
        text version_code
        ef_status status
    }
    class EmissionFactor {
        text factor_code
        numeric factor_value
        parameter_kind parameter_kind
        parameter_verification_status verification_status
    }
    class SeasonRecommendation {
        text rule_code
        text type
        recommendation_status status
        numeric co2e_total_kg_delta
        text impact_status
    }
    class PlantImage {
        text storage_object_path
        text sha256
    }
    class CvInference {
        disease_label predicted_label
        numeric confidence
        numeric threshold_used
        bool is_uncertain
    }
    class CvModelVersion {
        text version_code
        numeric accuracy
        model_status status
    }
    CropSeason "1" --> "*" CarbonCalculation
    CarbonCalculation "1" --> "*" CarbonBreakdown
    EmissionFactorSet "1" --> "*" EmissionFactor
    CarbonCalculation "*" --> "1" EmissionFactorSet
    CropSeason "1" --> "*" SeasonRecommendation
    CropSeason "1" --> "*" PlantImage
    PlantImage "1" --> "*" CvInference
    CvInference "*" --> "1" CvModelVersion
```

`carbon_calculations.co2e_per_kg` là cột generated
`total_co2e_kg / nullif(yield_kg, 0)`; `cv_inferences.is_uncertain` là cột
generated `confidence < threshold_used`.

## 4. MRV

```mermaid
classDiagram
    direction LR
    class MrvCase {
        uuid organization_id
        text case_code
        date period_start
        date period_end
        mrv_case_status status
    }
    class MrvCaseStep {
        smallint step_no
        mrv_step_status status
    }
    class MrvCaseBatch {
        uuid production_batch_id
    }
    class MrvEvidence {
        smallint step_no
        text evidence_type
        text storage_object_path
        text sha256
    }
    class MrvExport {
        export_format format
        jsonb export_payload
        text payload_sha256
        text file_sha256
        uuid source_snapshot_export_id
        bool is_finalized
    }
    class MrvExportCalculation {
        uuid carbon_calculation_id
    }
    MrvCase "1" --> "6" MrvCaseStep
    MrvCase "1" --> "*" MrvCaseBatch
    MrvCase "1" --> "*" MrvEvidence
    MrvCase "1" --> "*" MrvExport
    MrvExport "1" --> "*" MrvExportCalculation
    MrvExport "0..1" --> "*" MrvExport : source_snapshot_export_id
```

## Bảng có trong schema nhưng chưa được code ứng dụng dùng

Migration baseline còn định nghĩa `resource_metric_snapshots`,
`benchmark_snapshots`, `benchmark_snapshot_members`, `recommendation_rules`,
`recommendations`, `ingestion_batches`, `data_quality_flags`, `sync_batches`, các
view `v_*`, schema `audit` và `pm`. Không có code backend/web/Flutter nào đọc hay
ghi các bảng/view này (đã grep). Khuyến nghị M05 dùng bảng riêng
`season_recommendations`; chỉ số tài nguyên được tính trực tiếp khi đọc, không
lưu snapshot.

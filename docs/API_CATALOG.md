# API Catalog — toàn bộ endpoint thật

Ngày: 2026-09-08. Sinh trực tiếp từ `docs/openapi.json` (export bằng
`python backend/scripts/export_openapi.py`) — không tay gõ, không thể lệch
schema. Nếu bảng dưới khác `docs/openapi.json`, tin `openapi.json`, export lại
tài liệu này.

34 operation, tất cả GET trừ `POST /v1/carbon/calculate`. Auth = `yes` nghĩa là
bắt buộc header `Authorization: Bearer <supabase_jwt>` (xem `docs/API_FOR_FLUTTER.md`
§0 cho error contract và semantics 404 dùng chung).

## FW-2 Part 1 + Part 3 supersession

The catalog now also includes three authenticated Farmer Web activity-write
operations: `POST /v1/crop-seasons/{crop_season_id}/activities`,
`PATCH /v1/activities/{activity_id}`, and `DELETE /v1/activities/{activity_id}`.
They support six activity types: fertilizer, irrigation, and harvest (FW-2
Part 1), plus seeding, pesticide, and straw_management (FW-2 Part 3, same
routes/transaction/idempotency — only `schemas.ActivityType`'s enum and
`infrastructure/write_repo.py`'s detail-table mapping grew). The historical
count and write-gap note below predate FW-2; `docs/openapi.json` remains the
authoritative operation inventory.

## M05 supersession

Also added: `GET /v1/crop-seasons/{crop_season_id}/recommendations` (list),
`POST .../recommendations/generate` (idempotent, farmer-scope only), and
`PATCH /v1/recommendations/{recommendation_id}` (`{"status": "accepted" |
"dismissed"}`, farmer-scope only). See `docs/modules/05-ai-recommendation.md`
and `docs/M05_RECOMMENDATION_REPORT.md`.

## M03 supersession

Also added: `POST /v1/crop-seasons/{crop_season_id}/cv/infer` (multipart
image upload, farmer scope only), `GET .../cv/inferences` (list),
`GET /v1/cv/inferences/{inference_id}`. Uses the existing draft M03
baseline model (MobileNetV2, not field-validated) — see
`docs/CV_FARMER_INTEGRATION_REPORT.md`.

| Method | Path | Tag | Auth |
|---|---|---|---|
| GET | `/health` | Health | no |
| GET | `/v1/activities/{activity_id}` | Activities | yes |
| PATCH | `/v1/activities/{activity_id}` | Activities | yes |
| DELETE | `/v1/activities/{activity_id}` | Activities | yes |
| POST | `/v1/carbon/calculate` | Carbon | yes |
| GET | `/v1/carbon/scenarios` | Carbon | no |
| GET | `/v1/crop-seasons/{crop_season_id}` | Crop Seasons | yes |
| GET | `/v1/crop-seasons/{crop_season_id}/activities` | Activities | yes |
| POST | `/v1/crop-seasons/{crop_season_id}/activities` | Activities | yes |
| GET | `/v1/crop-seasons/{crop_season_id}/carbon` | Carbon | yes |
| POST | `/v1/crop-seasons/{crop_season_id}/cv/infer` | CV | yes |
| GET | `/v1/crop-seasons/{crop_season_id}/cv/inferences` | CV | yes |
| GET | `/v1/crop-seasons/{crop_season_id}/metrics` | Metrics | yes |
| GET | `/v1/crop-seasons/{crop_season_id}/production-batches` | Production Batches | yes |
| GET | `/v1/crop-seasons/{crop_season_id}/recommendations` | Recommendations | yes |
| POST | `/v1/crop-seasons/{crop_season_id}/recommendations/generate` | Recommendations | yes |
| GET | `/v1/cv/inferences/{inference_id}` | CV | yes |
| GET | `/v1/emission-factor-sets` | Emission Factors | yes |
| GET | `/v1/emission-factor-sets/{emission_factor_set_id}` | Emission Factors | yes |
| GET | `/v1/emission-factor-sets/{emission_factor_set_id}/factors` | Emission Factors | yes |
| GET | `/v1/farms` | Farms | yes |
| GET | `/v1/farms/{farm_id}` | Farms | yes |
| GET | `/v1/farms/{farm_id}/crop-seasons` | Crop Seasons | yes |
| GET | `/v1/farms/{farm_id}/metrics` | Metrics | yes |
| GET | `/v1/farms/{farm_id}/plots` | Plots | yes |
| GET | `/v1/me` | Auth | yes |
| GET | `/v1/mrv/cases` | MRV | yes |
| GET | `/v1/mrv/cases/{mrv_case_id}` | MRV | yes |
| GET | `/v1/mrv/cases/{mrv_case_id}/batches` | MRV | yes |
| GET | `/v1/mrv/cases/{mrv_case_id}/evidence` | MRV | yes |
| GET | `/v1/mrv/cases/{mrv_case_id}/exports` | MRV | yes |
| GET | `/v1/mrv/cases/{mrv_case_id}/steps` | MRV | yes |
| GET | `/v1/mrv/exports/{mrv_export_id}` | MRV | yes |
| GET | `/v1/organizations` | Organizations | yes |
| GET | `/v1/organizations/{organization_id}` | Organizations | yes |
| GET | `/v1/organizations/{organization_id}/farm-performance` | Organizations | yes |
| GET | `/v1/organizations/{organization_id}/farms` | Organizations | yes |
| GET | `/v1/organizations/{organization_id}/metrics` | Organizations | yes |
| GET | `/v1/organizations/{organization_id}/summary` | Organizations | yes |
| GET | `/v1/plots/{plot_id}` | Plots | yes |
| GET | `/v1/plots/{plot_id}/crop-seasons` | Crop Seasons | yes |
| GET | `/v1/production-batches/{production_batch_id}` | Production Batches | yes |
| PATCH | `/v1/recommendations/{recommendation_id}` | Recommendations | yes |

## Chưa có (biết rõ, không giả vờ)

- `POST /v1/mrv/exports` (tạo export) — bảng `mrv_exports` chỉ có `SELECT` grant
  cho `authenticated` (baseline schema), tạo export là việc của một job backend
  dùng service role; job đó CHƯA được viết trong lần hoàn thiện REST API này.
- `POST/PATCH` cho farms/plots/crop-seasons/activities — ghi dữ liệu KHÔNG qua
  backend, xem `docs/SYNC_ARCHITECTURE_GAP.md`.
- `GET /v1/organizations/{id}/farms` trả `FarmResponse` (không có `plot_count`
  scoped riêng theo org — dùng lại `plot_count` toàn cục của farm, đúng vì 1 farm
  chỉ thuộc 1 organization qua `cooperative_id`, không có multi-tenancy farm).

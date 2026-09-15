# API overview

Nguồn: `backend/api.py` (router `/v1`) và `backend/main.py` (`/health`). Bản OpenAPI
đầy đủ được FastAPI sinh tại runtime (`/openapi.json`, `/docs`) và bản xuất tĩnh nằm ở
`docs/openapi.json` (sinh bằng `backend/scripts/export_openapi.py`).

## Quy ước chung

| Mục | Quy ước |
|---|---|
| Auth | `Authorization: Bearer <Supabase JWT>` cho mọi route nghiệp vụ liệt kê dưới đây, trừ `GET /health` và `GET /v1/carbon/scenarios`. Các route mặc định của FastAPI (`/openapi.json`, `/docs`, `/redoc`) cũng công khai |
| Phạm vi đọc | RLS với JWT của người gọi — dữ liệu ngoài phạm vi trả `404`, không phải `403` |
| Envelope lỗi | `{"detail": {"error": {"code": "...", "message": "...", "request_id"?: "..."}}}` — kể cả lỗi validate (`422 validation_error`) |
| Phân trang | `?page=1&page_size=20` → `{items, page, page_size, total, has_more}` cho `/v1/farms`, `/v1/crop-seasons/{id}/activities`, `/v1/mrv/cases` |
| Danh sách không phân trang | `{items: [...]}` |
| Request id | Middleware `RequestIdMiddleware` trả header `X-Request-ID`; `Server-Timing` chỉ khi `AGRICARBON_SERVER_TIMING` bật |
| Số liệu thiếu | `null`, không phải `0` |

Cột "Scope" mô tả cổng quyền: **RLS** = đọc bằng JWT; **farmer** = `roles` phải có
`farmer`; **manager** = `cooperative_manager` còn hiệu lực của tổ chức sở hữu case.

## Health

| Method | Path | Mục đích | Auth | Scope |
|---|---|---|---|---|
| GET | `/health` | Trạng thái cấu hình, `engine_version`, `ef_config_version`, `carbon_production_ready`, `mrv_compliant: false` | Không | — |

## Auth

| Method | Path | Mục đích | Auth | Scope |
|---|---|---|---|---|
| GET | `/v1/me` | Người gọi, memberships, `roles` | JWT | RLS |

## Organizations

| Method | Path | Mục đích | Auth | Scope |
|---|---|---|---|---|
| GET | `/v1/organizations` | Tổ chức đọc được | JWT | RLS |
| GET | `/v1/organizations/{organization_id}` | Chi tiết tổ chức | JWT | RLS |
| GET | `/v1/organizations/{organization_id}/farms` | Nông hộ thuộc tổ chức | JWT | RLS |
| GET | `/v1/organizations/{organization_id}/summary` | Số farm/thửa/vụ, diện tích, tổng sản lượng, CO₂e | JWT | RLS |
| GET | `/v1/organizations/{organization_id}/metrics` | Chỉ số tổng hợp có trọng số | JWT | RLS |
| GET | `/v1/organizations/{organization_id}/farm-performance` | So sánh nông hộ, `data_status` | JWT | RLS |

## Farms / Plots / Crop Seasons / Production Batches

| Method | Path | Mục đích | Auth | Scope |
|---|---|---|---|---|
| GET | `/v1/farmer/scope` | Farm + thửa + vụ đọc được trong một lần gọi | JWT | RLS |
| GET | `/v1/farms` | Danh sách nông hộ (phân trang) | JWT | RLS |
| GET | `/v1/farms/{farm_id}` | Chi tiết nông hộ | JWT | RLS |
| GET | `/v1/farms/{farm_id}/plots` | Thửa của nông hộ | JWT | RLS |
| GET | `/v1/farms/{farm_id}/crop-seasons` | Mọi vụ trên các thửa của nông hộ | JWT | RLS |
| GET | `/v1/farms/{farm_id}/metrics` | Chỉ số tổng hợp của nông hộ | JWT | RLS |
| GET | `/v1/plots/{plot_id}` | Chi tiết thửa | JWT | RLS |
| GET | `/v1/plots/{plot_id}/crop-seasons` | Vụ của thửa | JWT | RLS |
| GET | `/v1/crop-seasons/{crop_season_id}` | Chi tiết vụ | JWT | RLS |
| GET | `/v1/crop-seasons/{crop_season_id}/production-batches` | Lô của vụ (truy xuất nguồn gốc) | JWT | RLS |
| GET | `/v1/production-batches/{production_batch_id}` | Chi tiết lô | JWT | RLS |

Không có route tạo/sửa farm, thửa, vụ hay lô.

## Activities

| Method | Path | Mục đích | Auth | Scope |
|---|---|---|---|---|
| GET | `/v1/crop-seasons/{crop_season_id}/activities` | Nhật ký của vụ (phân trang, bỏ activity đã xoá) | JWT | RLS |
| GET | `/v1/activities/{activity_id}` | Chi tiết activity | JWT | RLS |
| POST | `/v1/crop-seasons/{crop_season_id}/activities` | Tạo activity (`seeding`, `fertilizer`, `irrigation`, `pesticide`, `straw_management`, `harvest`) — `201`, idempotent theo `idempotency_key` | JWT | farmer + `farm_role` owner/editor (hoặc manager) + vụ `active` + đúng 1 lô mở |
| PATCH | `/v1/activities/{activity_id}` | Sửa `occurred_at`, `note`, `data` (merge) | JWT | farmer + là người ghi + quyền ghi farm |
| DELETE | `/v1/activities/{activity_id}` | Xoá mềm — `204` | JWT | farmer + là người ghi + quyền ghi farm |

Lỗi riêng: `422 invalid_crop_season_state`, `409 duplicate_event`, `404 not_found`.

## Metrics

| Method | Path | Mục đích | Auth | Scope |
|---|---|---|---|---|
| GET | `/v1/crop-seasons/{crop_season_id}/metrics` | Nước/phân/chi phí/CO₂e trên kg + `data_completeness` | JWT | RLS |

(Chỉ số farm và tổ chức nằm ở hai nhóm trên.)

## Carbon

| Method | Path | Mục đích | Auth | Scope |
|---|---|---|---|---|
| GET | `/v1/carbon/scenarios` | `as_recorded`, `awd`, `continuous_flooding` | Không | — |
| POST | `/v1/carbon/calculate` | Tính và lưu CO₂e của một vụ | JWT | RLS đọc vụ (không kiểm role) |
| GET | `/v1/crop-seasons/{crop_season_id}/carbon?scenario=` | Bản tính thành công mới nhất (`404 no_calculation` nếu chưa có) | JWT | RLS đọc vụ |

## Emission Factors

| Method | Path | Mục đích | Auth | Scope |
|---|---|---|---|---|
| GET | `/v1/emission-factor-sets` | Bộ hệ số `published` | JWT | RLS |
| GET | `/v1/emission-factor-sets/{emission_factor_set_id}` | Chi tiết bộ (chỉ `published`) | JWT | RLS |
| GET | `/v1/emission-factor-sets/{emission_factor_set_id}/factors` | Hệ số của bộ | JWT | RLS |

## Recommendations

| Method | Path | Mục đích | Auth | Scope |
|---|---|---|---|---|
| GET | `/v1/crop-seasons/{crop_season_id}/recommendations` | Khuyến nghị đã lưu | JWT | RLS |
| POST | `/v1/crop-seasons/{crop_season_id}/recommendations/generate` | Chạy rule, lưu, trả danh sách | JWT | farmer + RLS đọc vụ |
| PATCH | `/v1/recommendations/{recommendation_id}` | `{"status": "accepted" \| "dismissed"}` | JWT | farmer + RLS đọc vụ |

## CV

| Method | Path | Mục đích | Auth | Scope |
|---|---|---|---|---|
| POST | `/v1/crop-seasons/{crop_season_id}/cv/infer` | Upload ảnh (multipart `file`), suy luận, lưu | JWT | farmer + RLS đọc vụ |
| GET | `/v1/crop-seasons/{crop_season_id}/cv/inferences` | Kết quả của vụ, mới nhất trước | JWT | RLS đọc vụ |
| GET | `/v1/cv/inferences/{inference_id}` | Một kết quả | JWT | RLS đọc vụ |

Lỗi ảnh: `422 unsupported_image_type`, `empty_image`, `image_too_large`,
`invalid_image`, `image_too_small`, `duplicate_image`. Không có checkpoint:
`503 backend_not_configured`.

## MRV

| Method | Path | Mục đích | Auth | Scope |
|---|---|---|---|---|
| GET | `/v1/mrv/cases` | Case đọc được (phân trang) | JWT | RLS |
| GET | `/v1/mrv/cases/{mrv_case_id}` | Case + 6 bước + số lô, số bằng chứng | JWT | RLS |
| GET | `/v1/mrv/cases/{mrv_case_id}/steps` | 6 bước | JWT | RLS |
| GET | `/v1/mrv/cases/{mrv_case_id}/batches` | Lô liên kết + vụ/thửa/nông hộ | JWT | RLS |
| GET | `/v1/mrv/cases/{mrv_case_id}/evidence` | Metadata bằng chứng | JWT | RLS |
| GET | `/v1/mrv/cases/{mrv_case_id}/exports` | Lịch sử xuất | JWT | RLS (`mrv_exports` chỉ manager) |
| GET | `/v1/mrv/exports/{mrv_export_id}` | Metadata một gói | JWT | RLS (chỉ manager) |
| POST | `/v1/mrv/cases/{mrv_case_id}/exports` | `{"format": "json" \| "xlsx" \| "pdf"}` — `201` | JWT | manager |
| POST | `/v1/mrv/exports/{mrv_export_id}/render` | `{"format": "xlsx" \| "pdf"}` từ snapshot có sẵn — `201` | JWT | manager |
| GET | `/v1/mrv/exports/{mrv_export_id}/download` | Bytes đã lưu, kiểm SHA-256 | JWT | manager |

Chi tiết: [MRV](../modules/mrv.md).

## Không tồn tại trong API

Để tránh hiểu nhầm từ các tài liệu cũ: **không có** `POST /v1/sync`,
`GET /v1/plots/{id}/efficiency`, `GET /v1/reports/mrv` (còn là TODO trong `main.py`),
cũng không có route tạo tổ chức, nông hộ, thửa, vụ, lô, MRV case, bước MRV hay
upload bằng chứng.

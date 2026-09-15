# Kiểm toán mã nguồn

Bộ tài liệu này được viết **sau** khi đọc trực tiếp mã nguồn tại commit
`81a8e24` (`main`) và được rà soát lại lần cuối tại `2f33972` (kể từ `81a8e24` chỉ có
CSS của Farmer Web thay đổi). Trang này ghi lại phạm vi đã đọc, kết luận cho từng hạng
mục, và phân loại rõ: đã xác nhận, chưa hoàn chỉnh, thử nghiệm, blocker khoa học, chỉ demo.

## Phương pháp

- Đọc code: `backend/` (`main.py`, `api.py`, `service.py`, `schemas.py`, `carbon/`,
  `recommendation/`, `mrv/manifest.py`, `infrastructure/*`, `config/emission_factors.yaml`),
  `supabase/migrations/` (11 file), `web-dashboard/src/` (client, auth, roles, routes,
  farmer shell, pages, features), `app/lib/` (sync, gateway, database, device, CV,
  recommendation, config, pubspec), `ml/` (`infer.py`, `model.py`, báo cáo baseline),
  file `.env.example`, `requirements.txt`, `package.json`, `pubspec.yaml`,
  `supabase/config.toml`, `infra/README.md`, `AGENTS.md`, `docs/MRV_EXPORT_PACKAGE.md`.
- Grep xác nhận những gì **không** tồn tại: file Docker/CI/deploy, job nền/cron, route
  sync, việc sử dụng bảng/view baseline, biến môi trường.
- Kiểm tra chéo read-only bởi agent Codex (qua Herdr) cho: ma trận phân quyền route,
  quyền của `enterprise_viewer`/`regulator`, danh sách biến môi trường, 10 trang kỹ
  thuật chính, và **toàn bộ** phát hiện B1–B12, M3, M7 — xem
  [Phát hiện kiểm toán mã nguồn](limitations/implementation-audit-findings.md).
- Đối chiếu route trong tài liệu API với decorator trong `api.py`/`main.py`, tên bảng
  trong sơ đồ ER với `create table` trong migration, và chuỗi giao diện trong hướng
  dẫn sử dụng với `web-dashboard/src`.
- **Không** gọi Supabase hosted trong audit này; tài liệu mô tả hành vi theo code,
  không phải kết quả runtime mới.

## Trạng thái test trong audit

| Nhóm test | Trạng thái |
|---|---|
| Backend `python -m pytest tests -q` (repository giả, không gọi Supabase) | **PASS** — 463 passed |
| RLS/Storage trên Supabase hosted, Playwright dữ liệu thật | **BLOCKED** — Supabase environment/credential unavailable |
| Web Vitest, Playwright mock, ML `pytest`, Flutter | **NOT RUN** — không chạy trong lượt audit tài liệu |

## Kết luận theo hạng mục

| # | Hạng mục | Kết luận từ code | Vị trí chính |
|---|---|---|---|
| 1 | Module | Auth, Farm/Plot/Season, Activities, Harvest, Carbon, Resource Metrics, Recommendation, CV, MRV, Export, Flutter Sync | [Module map](architecture/module-map.md) |
| 2 | Entry point | Backend `backend/main.py` (`uvicorn main:app`); Web `web-dashboard/src/main.tsx` → `App.tsx`; Flutter `app/lib/main.dart`; ML CLI `python -m ml.train/evaluate/infer` | [Chạy local](getting-started/index.md) |
| 3 | API routes | 46 route `/v1` trong `api.py` + `GET /health` trong `main.py` | [API](api/overview.md) |
| 4 | Services | `CarbonService`, `ActivityWriteService`, `RecommendationService`, `CvService`, `MrvExportService` | `backend/service.py` |
| 5 | Repositories | `SupabaseReadRepository`, `SupabaseCropAccessChecker`, `SupabaseCarbonRepository`, `PostgresActivityWriteRepository`, `PostgresRecommendationRepository`, `PostgresCvRepository`, `PostgresMrvExportRepository` | `backend/infrastructure/` |
| 6 | DB tables | Bảng nghiệp vụ + bảng dormant của baseline | [Database](database/schema.md) |
| 7 | RLS | Helper `private.*` security definer + policy từng bảng; `mrv_exports` siết về manager | [Security](security/authentication-and-rls.md) |
| 8 | Auth flow | Supabase Auth → JWT → FastAPI replay JWT qua publishable key | [Security](security/authentication-and-rls.md) |
| 9 | Carbon flow | Crop season scope, IPCC Tier 1, fail-closed; GWP null | [Carbon Engine](modules/carbon-engine.md) |
| 10 | Resource metrics | Tính khi đọc, `null ≠ 0`, tổng hợp có trọng số | [Resource Metrics](modules/resource-metrics.md) |
| 11 | Recommendation | 2 nhóm rule; AWD tái dùng `CarbonService(persist=False)` | [Recommendation](modules/recommendation.md) |
| 12 | CV | MobileNetV2 baseline, threshold 0,939849, label null khi uncertain | [Computer Vision](modules/computer-vision.md) |
| 13 | MRV | Case/6 bước/lô/bằng chứng chỉ đọc qua API | [MRV](modules/mrv.md) |
| 14 | Farmer Web | Khu `/farmer/*`, ghi 6 loại activity qua FastAPI | [Web](modules/web-dashboard.md) |
| 15 | Management Web | Chỉ đọc + tính lại Carbon + xuất MRV | [Web](modules/web-dashboard.md) |
| 16 | Flutter offline/sync | SQLite + `sync_state`, ghi thẳng Supabase, idempotent `(device_id, client_event_id)` | [Flutter Mobile](modules/flutter-mobile.md) |
| 17 | Supabase Storage | `plant-images`, `mrv-exports` (backend service role); `mrv-evidence` chỉ có policy | [Database](database/schema.md#storage) |
| 18 | Export JSON/XLSX/PDF | Snapshot JSON chuẩn + renderer thuần + tải về kiểm SHA-256 | [MRV](modules/mrv.md) |
| 19 | Job nền / cron | **Không có** | [Deployment](deployment/architecture.md) |
| 20 | Deployment topology | Không có cấu hình triển khai; local uvicorn + Vite + Supabase hosted | [Deployment](deployment/architecture.md) |

## Đã xác nhận từ code

- Carbon tính theo **crop season**; activity gom từ mọi lô chưa xoá; production batch
  chỉ để truy xuất (`20260908000002`, `mapping.calculation_row`).
- Công thức CH₄ `EFi = EFc × SFw × SFp × SFo`, `CH4 = EFi × ngày × ha`; SFo theo Eq 5.3;
  N₂O trực tiếp theo kg N × EF1FR × 44/28; đốt rơm theo Eq 2.27; nhiên liệu theo lít.
- Rơm vùi → SFo; rơm đốt → nguồn riêng; guard double counting.
- AWD là kịch bản chạy lại engine (SFw và EF1FR đổi cùng lúc), không phải tỷ lệ cố định.
- Mẫu số = Σ `harvest_events.yield_kg` của activity chưa xoá; thiếu → `co2e_per_kg = null`.
- Resource metrics: tổng tử số / tổng sản lượng, không trung bình tỷ lệ; thiếu → `null`.
- Recommendation không có công thức phát thải riêng; tác động = chênh lệch hai lần tính
  `persist=False`; không benchmark.
- MRV: JSON là snapshot chuẩn lưu nguyên văn; XLSX/PDF render từ snapshot, không tính
  lại; hai digest `payload_sha256`/`file_sha256`; tải về kiểm SHA-256, không signed URL.
- Xuất MRV chỉ cho `cooperative_manager` còn hiệu lực của tổ chức sở hữu case.
- Flutter ghi thẳng Supabase dưới RLS; Farmer Web ghi qua FastAPI; web dùng Supabase
  client chỉ cho auth.
- Flutter chuyển thời gian sang UTC trước khi gửi; `recorded_by` lấy từ phiên; xoá mềm
  qua RPC `soft_delete_activity`.

## Chưa hoàn chỉnh

- Không có API soạn MRV case/bước/bằng chứng; chưa có gói ZIP kèm bytes bằng chứng.
- Flutter chưa nối Recommendation và CV; chưa có production release signing; iOS chưa build.
- Không có cấu hình triển khai, CI/CD, job nền.
- Các vấn đề B1–B12, M3, M7 (M7, B3, B7 đã sửa trong sprint P0 ngày 2026-09-15) trong [Giới hạn](limitations/current-limitations.md#5-backend-api-va-web-van-e-phat-hien-trong-audit-tai-lieu)
  và [Phát hiện kiểm toán mã nguồn](limitations/implementation-audit-findings.md).

## Thử nghiệm

- Computer Vision baseline (dataset công khai, **chưa xác thực thực địa**, OOD chưa robust,
  model `draft`).

## Blocker khoa học

- GWP CH₄/N₂O `PENDING_VERIFICATION` → không có CO₂e thật.
- Hệ số nhiên liệu/lưới điện chưa có.
- IPCC Tier 1 default thay vì hệ số quốc gia; chưa có QĐ 4801 → không MRV-compliant.
- Bộ hệ số chưa import vào DB hosted (theo ghi chú migration).

## Chỉ demo

- Tenant `DEMO-AGRICARBON-2026` và tài khoản QA do script tạo.
- Chế độ `VITE_USE_MOCK_DATA`.
- `backend/carbon/demo.py`, `tests/fixtures/demo_crop.json`, `tests/fixtures/test_factors.yaml` (TEST ONLY).
- Màn MRV ghi rõ "Bản mẫu / demo — chưa phải biểu mẫu chính thức".

## Tài liệu lịch sử trong `docs/`

Các file viết hoa (`PRD.md`, `SRS.md`, `CARBON_METHOD.md`, báo cáo từng round...) và
`docs/modules/0*-*.md` vẫn nằm trong repository nhưng **không** được build vào site.
Một số nội dung cũ đã lệch với code (ví dụ `docs/modules/05-ai-recommendation.md` và
`infra/README.md`); khi mâu thuẫn, bộ tài liệu này và code là chuẩn.

# Giới hạn hiện tại

Trang này liệt kê thẳng những gì **chưa xong, chưa xác minh, hoặc đang có vấn đề**,
theo code và cấu hình ở commit baseline `81a8e24`, kiểm tra lại tại `2f33972` (chỉ CSS
Farmer Web thay đổi). Không mục nào được làm nhẹ đi. Bằng chứng `file:dòng`, mức độ và
phân loại của các vấn đề trong code nằm ở
[Phát hiện kiểm toán mã nguồn](implementation-audit-findings.md).

## 1. Khoa học Carbon — blocker

| # | Giới hạn | Bằng chứng | Hệ quả |
|---|---|---|---|
| S1 | **GWP CH₄ / N₂O chưa xác minh** (OI-05) | `gwp.ch4.value: null`, `gwp.n2o.value: null` trong `emission_factors.yaml` | **Không có bản tính CO₂e thật nào thành công** — `422 missing_emission_factor`; `/health` báo `carbon_production_ready: false` |
| S2 | Hệ số nhiên liệu diesel/xăng/LPG và lưới điện chưa có (OI-06) | `factors.fuel.*.value: null` | Vụ có `fuel_usages` luôn `422`; điện bơm không vào tổng |
| S3 | Bộ tham số là **IPCC Tier 1 default**, không phải hệ số quốc gia; chưa có toàn văn QĐ 4801/QĐ-BNNMT (OI-02) | `methodology.tier: 1` | **Không được gọi là MRV-compliant**; `mrv_compliant` luôn `false` |
| S4 | Bộ hệ số chưa được import/publish vào DB hosted (theo ghi chú migration `20260913120000`) | 0 hàng `emission_factor_sets` tại thời điểm migration | Kể cả khi có GWP, lưu bản tính sẽ `503 factor_set_not_imported` cho tới khi import |
| S5 | Ranh giới hệ thống loại trừ: N₂O gián tiếp, N từ phân hữu cơ, CH₄ ngoài vụ, CO₂ từ đốt rơm, upstream thuốc BVTV và giống | `engine.py` cảnh báo; `straw_burning.co2_counted` PENDING | CO₂e (khi có) là ước tính có phạm vi hẹp |
| S6 | Giá trị tham chiếu 1,04 kg CO₂/kg và 2,29–3,72 kg CO₂e/kg mâu thuẫn (OI-01) | `reference_values.status: CONTESTED` | Không có benchmark hợp lệ |
| S7 | Chưa đối chiếu với FarMoRe (OI-03) | `open_issues` | Chưa có kiểm chứng chéo |
| S8 | Biến bắt buộc `pre_season_water_regime`, `dry_matter_fraction`, `days_before_cultivation` không suy được từ dữ liệu cũ | Migration `20260908000000` | Phải thu thập trực tiếp; thiếu thì `422 methodology_gap` |
| S9 | Test backend dùng `tests/fixtures/test_factors.yaml` — **TEST ONLY, NOT SCIENTIFIC VALUES** | Tên và chú thích fixture | Test xanh chứng minh logic, **không** chứng minh giá trị khoa học |

## 2. Computer Vision

| # | Giới hạn |
|---|---|
| C1 | **Chưa xác thực thực địa**: dataset công khai (Bangladesh, bán kiểm soát), chưa có ảnh HTX pilot |
| C2 | **OOD chưa robust**: không có benchmark cho ảnh không phải lá lúa/ảnh xấu; mô hình 4 lớp vẫn có thể gán nhãn khi đủ tự tin |
| C3 | Mô hình quá tự tin; tỷ lệ "không chắc chắn" 42,4 % trên test |
| C4 | `cv_model_versions.status = draft`, chưa `active` |
| C5 | Checkpoint `ml/runs/` không được git track; triển khai mới không có mô hình → CV `503` |
| C6 | Flutter chưa nối CV; nhãn trong app (`blast`, `bacterial_blight`) khác nhãn backend (`rice_blast`, `bacterial_leaf_blight`) |

## 3. MRV và Export

| # | Giới hạn |
|---|---|
| M1 | **Chưa có gói ZIP kèm bytes bằng chứng**; JSON/XLSX/PDF chỉ tham chiếu bằng chứng |
| M2 | Không có API tạo/sửa MRV case, cập nhật bước hay upload bằng chứng; bucket `mrv-evidence` chưa có luồng upload |
| M3 | Gói xuất lấy `CarbonService.latest()` **không lọc kịch bản** — có thể đưa bản tính giả định `awd`/`continuous_flooding` vào gói, trong khi Resource Metrics chỉ dùng `actual` (`CODE_BUG`, [chi tiết](implementation-audit-findings.md#m3)) |
| M4 | Sinh gói đồng bộ trong request (~8 giây tổng hợp trên hosted dev); không có job queue |
| M5 | PDF không phải PDF/UA; không có khái niệm gói "đã phê duyệt / đã nộp / đã xác minh" |
| M6 | `mrv_step_catalog.name` là tiếng Anh; nhãn tiếng Việt cố định trong `read_repo.py` |
| M7 | **Lỗ hổng quyền đọc:** policy Storage `mrv_files_storage_select` cho mọi người đọc được tổ chức (kể cả `farmer`, và `enterprise_viewer`/`regulator` qua data grant) đọc object `mrv-exports`, rộng hơn policy metadata `mrv_exports_select` (chỉ manager). Ứng dụng không gọi Storage trực tiếp, nhưng JWT hợp lệ vẫn gọi được Storage API (`CODE_BUG`, [chi tiết](implementation-audit-findings.md#m7)) |
| M8 | Gói xuất **không phải** chứng nhận; màn MRV ghi rõ "Bản mẫu / demo" |

## 4. Flutter Mobile

| # | Giới hạn |
|---|---|
| F1 | **Production release signing chưa có**: release dùng khoá debug, không có `key.properties` |
| F2 | iOS chưa build (cần macOS + Xcode + signing) |
| F3 | `integration_test/` cần thiết bị/emulator |
| F4 | Khuyến nghị chưa nối (`UnavailableRecommendationRepository`); model Flutter khác `RecommendationResponse` |
| F5 | Ghi thẳng Supabase: không đi qua các kiểm tra của FastAPI (ví dụ "đúng một lô mở"); quyền là quyền RLS |

## 5. Backend, API và Web — vấn đề phát hiện trong audit tài liệu

Các mục dưới đây được xác nhận bằng đọc code và kiểm tra chéo read-only bởi Codex,
**chưa sửa**. Mức độ, phân loại (`CODE_BUG` / `CODE_GAP` / `PRODUCT_DECISION`) và bằng
chứng từng dòng: [Phát hiện kiểm toán mã nguồn](implementation-audit-findings.md).

| # | Vấn đề | Vị trí |
|---|---|---|
| B1 | Cờ `data_completeness.water` / `fertilizer` phụ thuộc **bản ghi cuối**; bản ghi thiếu lượng nước đứng trước bản ghi có số vẫn cho `water_per_kg` từ tổng thiếu. Test chỉ phủ trường hợp thiếu ở cuối | `backend/infrastructure/read_repo.py::_compute_metric_totals` |
| B2 | Web khai báo role `enterprise` thay vì `enterprise_viewer`; tài khoản chỉ có `enterprise_viewer` bị đưa vào khu Farmer | `web-dashboard/src/types.ts`, `src/api/me.ts`, `src/App.tsx` |
| B3 | Ghi activity qua Farmer Web **không** kiểm `farm_role` `owner`/`editor` (chỉ kiểm role `farmer` + đọc được vụ), khác quy tắc RLS mà Flutter phải tuân theo | `backend/service.py::ActivityWriteService` |
| B4 | `POST /v1/carbon/calculate` không kiểm role: ai đọc được vụ (kể cả `regulator`/`enterprise_viewer` qua data grant) cũng kích hoạt được bản tính **được lưu** | `backend/api.py::_require_caller` |
| B5 | Thiếu `nitrogen_percent` ném `ValidationError` gốc, không nằm trong bảng ánh xạ lỗi → sẽ thành `500 internal_error` khi GWP có giá trị | `carbon/models.py`, `api.py::_ERROR_STATUS` |
| B6 | `backend/requirements.txt` thiếu `torch`, `torchvision`, `pillow` dù `service.py` import `ml.infer` khi khởi động | `backend/service.py` |
| B7 | `/v1/me` gộp role từ membership mà không lọc `ended_at` (các helper RLS và kiểm tra MRV thì lọc) | `read_repo.py::me` |
| B8 | `AGRICARBON_REQUIRE_FACTOR_SET_IN_DB` được đọc nhưng không được dùng | `infrastructure/config.py` |
| B9 | Farmer Web ghi `occurred_at` là `YYYY-MM-DDT00:00:00Z` (chỉ ngày) | `src/farmer/ActivityForms.tsx` |
| B10 | Farmer Web không có form nhiên liệu; không route nào tạo farm/thửa/vụ/lô | `write_repo.py::_DETAILS`, `api.py` |
| B11 | Bảng/view baseline không được dùng (`recommendations`, `recommendation_rules`, `benchmark_*`, `resource_metric_snapshots`, `sync_batches`, `v_*`) | `supabase/migrations/20260907000000_baseline.sql` |
| B12 | Comment trong `schemas.py` nói form Farmer Web không thu thập `days_before_cultivation`/`dry_matter_fraction`, nhưng form hiện tại **có** các ô này (không bắt buộc) | `backend/schemas.py`, `src/farmer/ActivityForms.tsx` |

## 6. Triển khai và vận hành

| # | Giới hạn |
|---|---|
| D1 | Không có Dockerfile, CI/CD hay cấu hình hosting; nền tảng triển khai chưa chốt |
| D2 | Bucket Storage tạo thủ công; không migration nào seed hệ số hay mô hình |
| D3 | Không có job nền/cron; Carbon không tự tính lại khi dữ liệu đổi |
| D4 | Cache client và pool Postgres là theo từng process |
| D5 | `infra/README.md` liệt kê biến môi trường cũ không còn được code đọc |

## 7. Demo và QA

| # | Giới hạn |
|---|---|
| Q1 | Tenant demo `DEMO-AGRICARBON-2026` là dữ liệu mẫu do script tạo; script **không** ghi `carbon_calculations` nên màn Carbon demo hiển thị "chưa có dữ liệu tính toán" |
| Q2 | Tài khoản QA (`demo-manager@…`, `qa-farmer-fw1@…`) chỉ dùng cho demo/QA; lịch sử Git cũ còn mật khẩu demo trước đây (ghi nhận trong `AGENTS.md`) |
| Q3 | E2E thật tạo và dọn dữ liệu trên Supabase hosted dùng chung; chạy song song có thể để lại dữ liệu rác |
| Q4 | `VITE_USE_MOCK_DATA=true` hiển thị dữ liệu giả có nhãn "MOCK DATA — NOT PRODUCTION" |
| Q5 | Giá tín chỉ carbon `NOT_CONFIRMED`; không có quy đổi tiền trong sản phẩm |

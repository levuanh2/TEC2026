# AgriCarbon — Final MVP Gap Matrix

Ngày audit: 2026-09-09 · Deadline: 2026-09-20 · **11 ngày còn lại** (mốc cắt scope
1c theo PRD §4.3: 2026-09-15, tức **6 ngày**).

Nguồn: đọc trực tiếp `docs/PRD.md`, `docs/SRS.md`, và code thật trong `backend/`,
`app/`, `web-dashboard/`, `ml/`, `supabase/` — không dựa vào report cũ. Evidence
cột dưới là file/test/lệnh thật đã chạy trong audit này, không suy đoán.

## Functional Requirements

| FR | Module | Code location | Evidence | Status | Missing work |
|---|---|---|---|---|---|
| FR-1a-01 Plot CRUD | 01-mobile-app | `app/lib/screens/plot_screen.dart`, RLS `plots` | code viết đúng cú pháp | **CODED, UNVERIFIED** | Không có Flutter SDK trên máy — chưa `flutter analyze`/`test`/chạy thật |
| FR-1a-02 Giống | 01-mobile-app | `app/lib/screens/activity_form_screen.dart` (seeding) | code | CODED, UNVERIFIED | như trên |
| FR-1a-03 Phân bón (≥3 lần) | 01-mobile-app | activity_form_screen.dart (fertilizer) | code | CODED, UNVERIFIED | như trên |
| FR-1a-04 Chế độ nước AWD/liên tục | 01-mobile-app + Carbon Engine | activity_form_screen.dart + `backend/carbon/models.py` | backend: `test_no_double_counting_burned_straw` nhóm test PASS thật | Backend: **TESTED** · Flutter: CODED, UNVERIFIED | Flutter runtime |
| FR-1a-05 Thuốc BVTV + rơm rạ | 01-mobile-app | activity_form_screen.dart | code | CODED, UNVERIFIED | Flutter runtime |
| FR-1a-06 Offline nhập liệu | 01-mobile-app | `app/lib/db/local_database.dart`, `sync_service.dart` | 4 file test Dart viết sẵn (`app/test/*`) **chưa từng chạy** | CODED, UNVERIFIED | `flutter test` thật, test trên máy thật tắt mạng |
| FR-1a-07 Sync idempotent | 01-mobile-app | `activities_device_event_uidx` (unique index device_id+client_event_id), `sync_service.dart` upsert | DB constraint đã verify qua migration + hosted E2E trước đó (không phải qua Flutter) | Backend contract: **VERIFIED** · Client thực thi: UNVERIFIED | Chạy Flutter thật, gửi 20 bản ghi 2 lần, đối chiếu server |
| FR-1a-08 CO2e tổng + /kg | 02-carbon-engine | `backend/carbon/engine.py` | `backend/tests/test_carbon_engine.py::test_co2e_per_kg`, `test_breakdown_sums_to_total` — 136 test pytest PASS (chạy lại trong audit này) | **TESTED** (công thức) · **REAL CO2e NO** (GWP null) | Không phải "missing work" — đây là fail-closed đúng thiết kế |
| FR-1a-09 AWD vs continuous flooding | 02-carbon-engine | `engine.py` + `test_awd_vs_continuous_flooding_totals`, `test_scenario_is_not_a_flat_percentage_of_total` | test PASS | **TESTED** | — |
| FR-1a-10 Breakdown ≥4 dòng | 02-carbon-engine + Carbon UI | `test_breakdown_sums_to_total`; web `Carbon()` render breakdown + drill-down factors_used/provenance | test PASS; web verified qua API thật (round 2-5) | **TESTED** (backend+web) · Flutter: CODED, UNVERIFIED | — |
| FR-1a-11 Sản lượng = mẫu số, không bịa | 02-carbon-engine | `test_missing_yield_returns_none_not_zero`, migration `carbon_success_allows_unknown_yield` | test PASS + hosted E2E xác nhận `co2e_per_kg: null` thật | **TESTED, HOSTED VERIFIED** | — |
| FR-1a-12 ef_config_version trong kết quả | 02-carbon-engine | `CarbonResult.ef_config_version` | test + hosted E2E | **TESTED** | — |
| FR-1b-01 Phân loại 4 nhãn bệnh lá | 03-computer-vision | `ml/train.py`, `ml/model.py`, `ml/class_mapping.py` | MobileNetV2 fine-tune, accuracy 85.60% trên 125 ảnh test held-out, chạy thật trong session này | **TESTED (baseline, dataset public)** | Fine-tune ảnh thực địa (FR-1b-02), tích hợp Flutter (RR-05 chưa chốt on-device/server) |
| FR-1b-02 Fine-tune ảnh thực địa | 03-computer-vision | — | vẫn không có ảnh thực địa, không có HTX pilot (R1 PRD) | **NOT STARTED** (đúng như dự kiến — phụ thuộc HTX pilot) | Phụ thuộc R1 PRD chốt HTX pilot |
| FR-1b-03 Accuracy + confusion matrix | 03-computer-vision | `ml/evaluate.py`, `ml/reports/cv_baseline_report.md` | test set tách riêng (group-aware, aHash dedup) 125 ảnh, accuracy/precision/recall/F1/confusion matrix đầy đủ, chạy thật | **TESTED, PUBLIC DATASET — NOT FIELD VALIDATED** | — |
| FR-1b-04 Ngưỡng tin cậy → uncertain | 03-computer-vision | `ml/evaluate.py` (temperature scaling + Youden threshold), `ml/infer.py` | threshold=0.9398 (sau calibrate T=1.65) chọn từ validation set, test thật: `confidence<threshold → label=null, uncertain=true` | **TESTED** — nhưng uncertain rate cao (42.4% trên test) do model overconfident khi sai, xem Limitations trong report | Cải thiện cần nhiều dữ liệu hơn (ảnh thực địa), không phải bug |
| FR-1b-05 4 chỉ số hiệu suất | 04-resource-dashboard | `backend/infrastructure/read_repo.py::metrics/_aggregate_metrics`, `GET /v1/crop-seasons/{id}/metrics` + farm/org level | hosted E2E thật (58/58 + demo tenant verify), web `Organizations()`/Dashboard() render đủ 4 | **TESTED, HOSTED VERIFIED** (nước/kg, phân/kg, cost/kg thật; **CO2e/kg luôn null** vì GWP chặn — đúng, không phải bug) | Flutter: không có màn hình này (chỉ 1a) |
| FR-1b-06 So sánh lô/hộ trong HTX | 04-resource-dashboard | `GET /v1/organizations/{id}/farm-performance`, web `Organizations()` table | verify thật qua demo tenant (3 farm, `data_status` đúng) | **TESTED, HOSTED VERIFIED** | — |
| FR-1b-07 Khuyến nghị rule-based | 05-ai-recommendation | — | `recommendation_rules`/`recommendations` chỉ là bảng SQL trống, **zero dòng Python nào** tham chiếu "recommendation" trong toàn bộ `backend/` | **NOT STARTED** | Toàn bộ: rule engine, benchmark data, generation logic, API, UI |
| FR-1b-08 Ước tính impact mỗi khuyến nghị | 05-ai-recommendation | — | không có | **NOT STARTED** | phụ thuộc FR-1b-07 |
| FR-1b-09 Ghi rõ benchmark + nguồn | 05-ai-recommendation | — | không có | **NOT STARTED** | phụ thuộc FR-1b-07 |
| FR-1c-01 Duyệt Farm→Plot→Season→{...} | 06-web-dashboard | `web-dashboard/src/App.tsx` (Farms/FarmPage/PlotPage/Season) | click-path đúng route, API thật; **browser click-through KHÔNG chạy được** (không có tool) | **CODED + API VERIFIED**, browser UNVERIFIED | Cần browser thật (Playwright hoặc thao tác tay) |
| FR-1c-02 Tổng hợp ≥3 hộ cấp HTX | 06-web-dashboard | `GET /v1/organizations/{id}/summary`, demo tenant 3 farm | verify thật (curl + demo tenant) | **HOSTED VERIFIED** | — |
| FR-1c-03 Phân quyền 3 vai trò, chặn cả gọi API thẳng | 06-web-dashboard + RLS | `CropAccessChecker`, RLS policies, `docs/BACKEND_1A.md §10` | test tenant-isolation (unit, `test_read_repository.py`, ~20 test) + hosted E2E 2-user thật (round 2) | **TESTED, HOSTED VERIFIED** (farmer/coop_manager) · enterprise/regulator role tồn tại trong enum nhưng **chưa có ai thật test luồng đó** | Test thật với user role enterprise_viewer/regulator (đã tạo demo-enterprise nhưng chưa gọi API bằng token đó) |
| FR-1c-04 created_by/created_at/updated_at | 06-web-dashboard | schema cột `recorded_by`/`created_at`/`updated_at` trên mọi bảng | schema thật | **IMPLEMENTED** (schema), chưa hiện rõ trên UI mọi màn | UI có thể chưa show `updated_by` — không phải blocker MVP |
| FR-1c-05 Export PDF/Excel theo 6 bước MRV | 07-mrv-export | — | grep toàn `backend/` không có reportlab/openpyxl/weasyprint/xlsxwriter nào; `mrv_exports` table tồn tại + đọc được (`GET /v1/mrv/cases/{id}/exports`) nhưng **không có route tạo export** | **NOT STARTED** (generation) · read API: IMPLEMENTED | Viết job tạo file thật — PRD cho phép đây là phần "1c cắt được xuống mock" |
| FR-1c-06 ef_config_version + ngày trong báo cáo | 07-mrv-export | — | phụ thuộc FR-1c-05 | **NOT STARTED** | — |
| FR-1c-07 Đánh dấu số chưa chốt | 07-mrv-export | — | phụ thuộc FR-1c-05; UI Carbon/Metrics hiện tại đã tuân thủ nguyên tắc này (null → "Chưa đủ dữ liệu", không giá tiền) | Nguyên tắc: **ÁP DỤNG ĐÚNG** nơi đã có UI · Export file: NOT STARTED | — |

Tổng 28 FR (12+9+7). **Completed (TESTED/HOSTED VERIFIED):** 12 — Carbon Engine backend (FR-1a-08..12), CV baseline (FR-1b-01,03,04 — public dataset, not field validated), Resource Dashboard (FR-1b-05,06), org rollup + created_by (FR-1c-02,04).
**Partial (coded-unverified hoặc mixed):** 10 — gần hết phần Flutter-specific của 1a (FR-1a-01,02,03,04,05,06,07), hierarchy browser chưa click-through + role thiểu số chưa test + export-label-principle (FR-1c-01,03,07).
**Missing (NOT STARTED):** 6 — CV fine-tune ảnh thực địa (FR-1b-02, phụ thuộc HTX pilot chưa chốt), toàn bộ Recommendation (FR-1b-07..09, 3 FR), MRV export generation (FR-1c-05,06, 2 FR).

## NFR

| NFR | Status | Evidence | Remaining |
|---|---|---|---|
| NFR-01 Offline-first | **CODED, UNVERIFIED** | `local_database.dart`/`sync_service.dart` viết đúng thiết kế, unique index DB đúng | Không có Flutter SDK — chưa airplane-mode test thật |
| NFR-02 Truy vết CO2e | **PASS (backend)** | `docs/CARBON_METHOD_SOURCES.md` mọi tham số VERIFIED có trích dẫn IPCC bảng/công thức cụ thể; `test_breakdown_carries_parameter_status` | — |
| NFR-03 Không bịa số | **PASS** | `test_missing_yield_returns_none_not_zero`, `test_real_config_blocks_on_missing_gwp`, hosted E2E `co2e_per_kg: null` thật, seed_demo_data.py cố ý không seed carbon_calculations | — |
| NFR-04 Mở rộng giai đoạn 2/3/4 | **PASS (kiến trúc)** | `carbon/engine.py::calculate_carbon()` hàm thuần không phụ thuộc HTTP/DB | Chưa build What-if/Farm Map/Weather/RAG — đúng, đây là "ngoài phạm vi MVP" theo PRD §5 |
| NFR-05 <3s tính CO2e | **UNVERIFIED (chưa benchmark)** | Chưa từng đo trên "thiết bị demo thật" theo đúng tiêu chí | Đo 10 lần liên tiếp trên thiết bị demo thật trước ngày pitch |
| NFR-06 <2 phút nhập liệu, thuật ngữ khuyến nông | **UNVERIFIED** | Form Flutter dùng đúng thuật ngữ ("giống"/"phân bón"/"rút nước") theo review code, nhưng chưa test người ngoài nhóm | Cần Flutter chạy được trước, rồi mới test người thật |
| NFR-07 Bảo mật — hộ khác không đọc được | **PASS, HOSTED VERIFIED** | Tenant isolation test 2-user thật (round 2), 16+ route riêng biệt | — |
| NFR-08 Tiếng Việt 100% | **PASS phần lớn (web+backend message)**, UNVERIFIED (Flutter) | Web/backend rà thấy toàn tiếng Việt trong audit này | Flutter chưa chạy được để rà màn hình thật; `web-dashboard` còn vài label kỹ thuật (`Water/kg`, `Fertilizer/kg` tiếng Anh trong bảng farm-performance — sót nhỏ) |

## Success Metrics (M1–M7)

| # | Implemented? | Tested? | Actual value | Evidence |
|---|---|---|---|---|
| M1 <3s CO2e | Code có | NO | — | Chưa đo trên thiết bị thật |
| M2 <2 phút nhập liệu | Code có (Flutter) | NO | — | Chưa test người ngoài, Flutter chưa chạy |
| M3 0% mất dữ liệu offline/20 bản ghi | Code có | **PARTIAL** — verified ở tầng DB constraint + hosted E2E dùng script Python mô phỏng, **chưa qua Flutter app thật** | — | `activities_device_event_uidx` + `test_read_repository.py` |
| M4 CV ≥85% | Code có (`ml/`) | **YES, trên dataset public** | Accuracy 85.60% trên 125 ảnh test held-out | `ml/reports/cv_baseline_report.md` — PUBLIC DATASET, NOT FIELD VALIDATED (chưa có ảnh thực địa HTX pilot) |
| M5 Chênh lệch AWD vs liên tục | Code có | **YES (test factor, không phải production)** | Test PASS chứng minh 2 kịch bản ra 2 tổng khác nhau và giải thích được thành phần | `test_awd_vs_continuous_flooding_totals` — nhưng dùng TEST FACTOR, chưa phải hệ số production (GWP null) |
| M6 Before/After ≥1 kịch bản | KHÔNG | NO | — | Phụ thuộc M05 Recommendation, NOT STARTED |
| M7 Truy vết số → hệ số → nguồn | Code có | **YES** | `parameter_status`+`provenance` trong mọi breakdown entry, drill-down UI đã build (round 4) | `docs/CARBON_METHOD_SOURCES.md`, `emission_factors.yaml` |

## Scientific Blockers

| ID | Blocks | Due | Category |
|---|---|---|---|
| OI-05 GWP framework (AR4/5/6) | **CHẶN TOÀN BỘ real CO2e** — mọi tính toán 422 ngay tại `gwp.ch4` | 15/09 | BLOCKS real CO2e + BLOCKS demo (nếu muốn demo số thật, không chặn demo bằng test factor) |
| OI-06 Fuel EF (diesel/xăng/LPG) | Chặn riêng breakdown `fuel` — độc lập với OI-05, dù GWP xong vẫn lỗi nếu có hoạt động fuel | 18/09 | BLOCKS real CO2e cho mùa vụ có dùng nhiên liệu |
| OI-02 QĐ 4801 hệ số quốc gia | Chặn nhãn "MRV-compliant" | 15/09 | BLOCKS MRV claim — KHÔNG chặn UI, KHÔNG chặn CV |
| OI-01 Mâu thuẫn 1,04 vs 2,29–3,72 | Chặn `reference_values` (benchmark hiển thị, không phải engine) | 15/09 | DOES NOT BLOCK demo/UI/CV — chỉ chặn 1 khối tham chiếu không dùng trong tính toán |
| OI-03 Đối chiếu FarMoRe | Không blocking cứng, chỉ để tăng độ tin cậy khi pitch | 18/09 | DOES NOT BLOCK |
| OI-07 Tên 6 bước MRV | Đã dùng đúng tên trong code (`Chuẩn bị/Đăng ký/Thiết lập đường cơ sở/Đo đạc/Báo cáo/Thẩm định`) — verify lại với văn bản gốc | 15/09 | DOES NOT BLOCK demo, chỉ rủi ro thuật ngữ khi hội đồng đối chiếu |

## Security Blockers

| Vấn đề | Trạng thái |
|---|---|
| Leaked Postgres password (`f5c34e8`, project `dxfarbrvmbusebmaysng`) | **FOUND, UNRESOLVED** — vẫn nằm trong git history (đã push lên `origin/main`); project ref không còn trong danh sách project truy cập được bằng access token hiện tại (đã xóa, hoặc thuộc account khác — chưa xác nhận) |
| Service-role key trong code/commit hiện tại | NOT FOUND |
| Figma PAT trong code/commit | NOT FOUND (giữ trong session scratchpad, ngoài repo) |
| Demo credentials trong code/commit | NOT FOUND (sinh random lúc chạy script, in ra terminal, không ghi file) |
| `.env` thật bị track | NOT FOUND |

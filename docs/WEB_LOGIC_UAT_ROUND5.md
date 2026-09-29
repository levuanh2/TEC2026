# AgriCarbon Round 5 — Logic UAT & Carbon integrity

> Branch `fix/agricarbon-round5-logic-integrity`, tạo từ `origin/main` = **`b461d31`** (fetch ngày 2026-09-29, không stale). Commit local. **Chưa push, merge, tag hay deploy.**

**Kết luận: BLOCKED** — mọi lỗi P0 đã tái hiện và sửa, UAT trọn vẹn qua UI trên tài khoản mới đã chạy xong. Còn chặn: (1) hiệu năng tính Carbon p95 4,34 s > 3 s (PRD/SRS), (2) Management `/carbon`, `/seasons` settle ~10–11 s với request tăng tuyến tính theo số vụ, (3) 1 spec mock timeout do tải máy, (4) Flutter/device UAT chưa chạy, (5) MRV export chưa xác minh được factor version (hồ sơ demo không có vụ đã tính). Chi tiết §13.

**Carbon formula / factor / GWP / methodology: KHÔNG thay đổi.** `git diff b461d31..HEAD -- backend/carbon backend/config` = 0 dòng. Mọi con số là của engine; vòng này chỉ đổi cách chọn, lưu, gọi tên và trình bày kết quả, cùng một tối ưu đọc song song (cùng rows, cùng `input_hash`, cùng calculation id).

## 1. Commit

| Commit | Nội dung |
|---|---|
| `81bb32e` | fix(carbon): GET carbon mặc định actual; bản tính đã lưu có provenance + fingerprint |
| `9c504e3` | fix(validation): diện tích thu hoạch không vượt diện tích thửa (API) |
| `e3cafd5` | fix(web): actual trên mọi bề mặt, kịch bản mô phỏng bên cạnh, tên nguồn có nghĩa |
| `dadaa1a` | fix(web): chặn diện tích thu hoạch cạnh field; ngày vụ nói rõ nguồn |
| `a13fe7a` | fix(web): MRV association thật, cơ sở + làm mới khuyến nghị, precision policy |
| `884366f` | fix(web): header vụ lấy ngày từ nhật ký; không "Thửa Thửa" |
| `dd0536b` | fix(web): phát hiện UAT — panel phương pháp khớp readiness, kg CO₂e 2 chữ số, ngày dự kiến |
| `966f69b` | perf(carbon): đọc vụ song song, cache bộ hệ số đã publish |
| `c723cb1` | fix(web): một bộ từ vựng trạng thái vụ Farmer/Management |
| `d20c079` | fix(web): row action và tab nằm trong viewport; segmented 40px |
| `8d33621` | test(web): Round 5 real-data gate |
| `abcea93` | fix(web): tên nông hộ/thửa/vụ thực tế xuống dòng giữa từ để bảng ops vừa khung |
| `a39ea8f` | fix(web): kịch bản mô phỏng tính trên dữ liệu cũ được đánh dấu, không so như hiện tại |
| (commit này) | docs: báo cáo Round 5 + dòng ownership `AGENTS.md` |

Diffstat code (trước commit docs): 48 files, +1676 / −174.

## 2. Skill / công cụ

| Yêu cầu | Thực tế |
|---|---|
| Product Design Audit, Design QA | **Không có** skill tên này trong phiên. Thay bằng audit giao diện render thật bằng script Playwright (`.qa-screenshots/logic-uat-round5/*.mjs`), staging trước, local sau. |
| Playwright | 1.63 — script UAT qua UI + spec mock + spec real. |
| axe-core | 4.x, tag `wcag2a/2aa/21a/21aa`, không tắt rule. |
| Flutter/device | Có SDK (`C:\src\flutter`) và AVD `agri_qa`, **chưa chạy** — lượt `flutter analyze/test` đầu bị Claude Code dừng vì máy thiếu RAM; xem §11. |

## 3. Dữ liệu UAT

| Dữ liệu | Giá trị | Cách tạo |
|---|---|---|
| Tài khoản cũ (regression) | `uat-20260928-1353@…`, vụ `UAT Hè Thu 2026` (`5016a01f…`, đã kết thúc) | có sẵn, chỉ đọc |
| Tài khoản mới | `uat-r5-202609290717@agricarbon-demo.local`, "Nông hộ UAT R5 09290717" | **UI Quản lý → Thêm nông hộ** |
| Nông hộ / thửa | `UAT-R5-FARM-09290717` / `UAT-R5-PLOT-09290717` "Thửa UAT R5 01", **1,25 ha** | cùng form |
| Vụ | `UAT R5 Hè Thu 2026` (`18a3b685…`), OM5451, gieo 01/06, dự kiến thu 20/09 | UI Farmer → Bắt đầu vụ |
| Hoạt động | Gieo sạ, Bón phân (Urê 46N 125→130 kg), Tưới AWD (300→350 m³), Thuốc BVTV, Rơm vùi (2.500→2.600 kg), Thu hoạch 6.000 kg / 1,25 ha; + 1 bản ghi BVTV tạo rồi xoá | UI Farmer |
| Carbon | actual + AWD + ngập liên tục; tính lại sau mỗi sửa đầu vào | UI Farmer |
| MRV export | 3 bản (JSON/XLSX/PDF) trên hồ sơ demo `DEMO-MRV-2026` | UI Quản lý |

Không có thao tác SQL, không endpoint ẩn, không sửa/xoá dữ liệu demo. Dữ liệu còn lại: §15.

## 4. Lỗi đã tái hiện và sửa

### P0-1 — Kịch bản mô phỏng thay kết quả actual — **DONE**

Tái hiện trên staging (`agricarbon-web-staging` / `agricarbon-api-staging`), vụ UAT cũ:

| Request | scenario trả về | Tổng | kg/kg | calculated_at |
|---|---|---|---|---|
| `GET /carbon` (không scenario) | `continuous_flooding` | 9.278,74 | 1,784 | 15:20:04Z |
| `?scenario=as_recorded` | `actual` | 5.183,52 | 0,997 | 15:03:25Z |

Farmer Carbon hiện "9.278,74 · Kết quả mới nhất · Ngập liên tục"; Management `/carbon` hiện 9.278,74 + "Cần tính lại". Root cause: `get_crop_carbon(scenario=None)` → `latest_calculation` lấy bản mới nhất **mọi** kịch bản; mọi client web gọi `getCarbon(id)` không kèm scenario.

Sửa: API mặc định `as_recorded`, luôn lọc theo kịch bản; `calculation_kind: actual|scenario`; `getCarbon(id, scenario='as_recorded')` luôn gửi `?scenario=`. Kịch bản mô phỏng đọc theo tên, hiện trong khối "So sánh với kịch bản mô phỏng" (Farmer) và segmented "Kết quả vận hành / Mô phỏng: AWD / Mô phỏng: Ngập liên tục" + notice (Management).

Regression (tài khoản mới, qua UI): actual `e998af90…` 4.803,74 kg / 0,801 → tính AWD rồi ngập liên tục (8.588,22 kg / 1,431, `kind=scenario`) → actual **cùng id, tổng, timestamp**. Sau reload/đăng nhập lại (mỗi script là một phiên mới) Farmer Carbon, Management `/carbon`, tab Carbon vụ, `/performance` đều hiện actual. Spec `round5-real` giữ bất biến này.

### P0-2 — Provenance / breakdown — **DONE**

Before: breakdown 2 dòng "Nguồn khác"; Management `undefined · ch4`, "Kịch bản: actual", UUID vụ trong cảnh báo; `ef_config_version` rỗng (bản lưu chỉ có `factor_set_id`, breakdown chỉ có `category`).

After: `CarbonService.stored()` trả bản lưu theo từ vựng POST — `source` của engine (đảo `SOURCE_TO_CATEGORY`), `factors_used/provenance/parameter_status` nhấc từ `formula_metadata`, `ef_config_version` giải từ `factor_set_id` (null nếu không giải được — không bịa), `methodology` chỉ khi đúng bộ tham số đang chạy. Tên nguồn: "Phát thải methane (CH₄) từ ruộng lúa và quản lý nước", "Phát thải N₂O từ phân đạm", "Đốt rơm rạ (CH₄/N₂O)", "Nhiên liệu máy móc (…)". Mục **"Không có dòng số riêng trong bản tính"** liệt kê "Nhiên liệu hoặc điện bơm" và "Quản lý rơm rạ" với lý do từ engine (rơm vùi đã nằm trong dòng CH₄ qua SFo; điện bơm chưa có hệ số lưới) — không có dòng 0 kg giả. Disclosure "Phương pháp và hệ số sử dụng": loại kết quả, bộ hệ số `0.3.0-ipcc2019-tier1-ar5`, engine `0.2.0`, thời điểm, nguồn hệ số (citation), cảnh báo đã bỏ UUID/đường dẫn. Kết quả → phương pháp → hệ số/nguồn: **1 thao tác**. Tổng breakdown = tổng calculation (±0,01, test backend + real spec).

### P0-3 — Sửa chi phí làm Carbon stale — **DONE**

Root cause: stale = "có activity lưu sau `calculated_at`" (mọi sửa, kể cả chi phí); còn tính lại với input không đổi trả lại **bản cũ** (idempotent theo `input_hash`) nên `calculated_at` không đổi → stale mãi.

Sửa: readiness trả `input_hash` = hash engine sẽ ghi cho `as_recorded` của Activity Data hiện tại (không chứa chi phí/ghi chú). Stale ⇔ `result.input_hash ≠ readiness.input_hash` (hoặc bộ hệ số đổi). Timestamp chỉ còn là fallback khi server không có fingerprint.

Ma trận (tài khoản mới, qua UI, banner UI **và** so hash qua API):

| Thao tác | Kỳ vọng | UI | API | |
|---|---|---|---|---|
| Sửa chi phí gieo sạ | Không | Không | Không | PASS |
| Sửa ghi chú phân bón | Không | Không | Không | PASS |
| Tính AWD + ngập liên tục | Không | Không | Không | PASS |
| Sửa lượng nước 300→350 | Có | Có | Có | PASS |
| Tính lại | Hết | Hết | Hết | PASS |
| Sửa lượng phân 125→130 | Có | Có | Có | PASS |
| Sửa lượng rơm 2.500→2.600 | Có | Có | Có | PASS |
| Tính lại | Hết | Hết | Hết | PASS |

Phát hiện thêm (đúng sự thật, không phải lỗi): **Kết thúc vụ** ghi `actual_harvest_date` — một trường đầu vào engine — nên actual chuyển "Cần tính lại" ở cả Farmer và Management. Tính lại trên vụ đã đóng cho **đúng tổng cũ 4.877,77 kg** (vì `cultivation_days=111` đã khai), hết stale. Đề xuất (chưa làm): kết thúc vụ tự đề nghị tính lại.

### P1 — Validation & ngày vụ — **DONE**

- `harvested_area_ha` > diện tích thửa: API 422 `harvested_area_exceeds_plot` (create **và** edit, có `field`, `plot_area_ha`); form báo cạnh field "Diện tích thu hoạch không được lớn hơn diện tích thửa (1,25 ha)."; bằng đúng 1,25 ha lưu được; lỗi biến mất khi sửa. Staging trước đó chấp nhận. Giới hạn: Flutter ghi qua đường khác — cần CHECK/trigger DB (migration, chưa làm).
- Ngày vụ: before "Gieo sạ/Thu hoạch: Chưa ghi nhận" dù nhật ký có cả hai. After: mỗi ngày kèm nguồn — "(theo nhật ký)", "(khai báo khi tạo vụ)", "(dự kiến)", "(ngày kết thúc vụ)"; ngày khai báo không bị ghi đè, khác nhật ký thì hiện cả hai. `expected_harvest_date` trước đó bị mapper bỏ.
- Lượng 0 bị chặn cạnh field; sửa giá trị hợp lệ → lỗi mất.
- Readiness vẫn đòi "số ngày canh tác" dù nhật ký có gieo và thu hoạch: engine lấy ngày từ bản ghi vụ, không từ nhật ký — đổi là đổi đầu vào methodology → **không làm**, ghi nhận.

### P1 — Khuyến nghị — **DONE (phần UI) / ghi nhận hiện trạng**

Hiện trạng đúng: rule engine (AWD optimization + data-completeness), **không có RAG**. Copy: "Khuyến nghị dựa trên quy tắc và dữ liệu vụ"; mỗi thẻ có "Tạo lúc …", "Cơ sở: quy tắc … · phiên bản quy tắc … · công cụ tính …"; tối ưu không có mốc → "Chưa có mốc so sánh được xác minh"; có so sánh → "Ước tính theo kịch bản … Không phải tác động được chứng nhận." Data task có dữ liệu đã đủ (theo `/metrics`, từ bất kỳ thiết bị/phiên nào) bị ẩn và kích hoạt sinh lại. Vụ UAT mới: 0 khuyến nghị — đúng (dữ liệu đủ, chế độ ghi nhận đã là AWD). Backend chưa trả `evidence`/`input_hash` trong response khuyến nghị → hiển thị input version là **blocker nhỏ** (đề xuất thêm 2 trường vào `RecommendationResponse`).

### P1 — MRV — **DONE (association) / BLOCKED (factor version trong export)**

- Before: tab MRV "Vụ này tham gia hồ sơ MRV … thông qua các lô" (suy từ lô `default`), link `/mrv` mở hồ sơ demo đầu tiên. After: chỉ nói thuộc hồ sơ khi `/mrv/cases/{id}/batches` có đúng vụ; ngược lại "Vụ này chưa thuộc hồ sơ MRV nào." + bảng lô ("Lô mặc định của vụ", cột "Hồ sơ MRV: Chưa gắn"); link `/mrv?case=<id>` mở đúng hồ sơ. `/performance`: "Ước tính theo phương pháp hiện tại — … chưa phải kết quả MRV hay chứng nhận".
- Export qua UI (Quản lý, `DEMO-MRV-2026`): JSON 13.796 B, XLSX 19.916 B (11 sheet), PDF 55.641 B (5 trang); tải file thật; SHA-256 file khớp mã hiện trên UI cả 3; JSON có 6 bước (Chuẩn bị → Thẩm định), `generated_at`, 9 cảnh báo, `manifest_sha256`; PDF có 6 bước, "Không phải chứng nhận", mã snapshot. Mỗi lần bấm tạo **một snapshot riêng** (đúng mô tả UI), nên PDF/XLSX không cùng snapshot với JSON của lần khác.
- **BLOCKED:** `provenance.emission_factor_sets = []` và mọi vụ trong hồ sơ `carbon.status = unavailable` — hồ sơ demo không có vụ đã tính, vụ UAT không gắn vào hồ sơ được qua UI (không có luồng sản phẩm; không dùng endpoint ẩn). Chưa xác minh được factor version trong export.
- P2 (chưa sửa, backend render): PDF hiện UUID người tạo, raw `draft`, `cooperative_manager, owner`.

### P1 — Account lifecycle — **BLOCKED (backend)**

| Chức năng | Backend | UI |
|---|---|---|
| Tạo tài khoản nông hộ (+ nông hộ + thửa) | có (`POST …/farmers`) | có — dùng trong UAT |
| Gán nông hộ / thửa | có | có |
| Reset mật khẩu tạm | **không có** | — |
| Khoá / mở lại tài khoản | **không có** (danh sách chỉ đọc trạng thái `locked/ended`) | — |
| Chuyển tổ chức | **không có** | — |
| Xoá / cleanup tài khoản UAT | **không có** | — |

Đề xuất contract tối thiểu (manager của HTX, audit log, 404 ngoài phạm vi): `POST /v1/organizations/{org}/farmers/{user}/temporary-password` → `{temporary_password}` một lần; `PATCH /v1/organizations/{org}/farmers/{user}` `{account_status: "locked"|"active"}` + lý do; xoá = soft-end membership (`ended`), không xoá auth user. Không tự tạo thao tác nguy hiểm trong vòng này.

Route guard: nông hộ vào route quản lý → `applyRoleRedirect` chạy trên mỗi thay đổi `path` và đổi URL về `/farmer` (spec `farmer-real-data` "deep-linking to /mrv stays in the Farmer shell" pass).

### P2 — Copy / consistency — **DONE**

| Before | After |
|---|---|
| CO₂e/kg `1` (Operations, 2 chữ số) vs `0,997` | 3 chữ số mọi nơi |
| `1.090,385 ₫`/kg | `1.090 ₫` (đồng tròn) |
| kg CO₂e 1 / 2 / 3 chữ số tuỳ màn | `co2eKg()` 2 chữ số |
| "Đã kết thúc" (Farmer) vs "Đã thu hoạch" (Management) cùng vụ | cùng `vocab.seasonStatus` |
| "Thửa Thửa …" (sheet Bắt đầu vụ) | `plotTitle()` |
| Panel phương pháp "Chưa tính được carbon vì còn thiếu: Chế độ nước trong vụ" trong khi readiness nói khác | "Chưa khai báo trên vụ: …"; readiness quyết định có tính được hay không |
| Dashboard "Bộ hệ số … chưa được xác minh" (sai) | "Chưa công bố CO₂e/kg cấp HTX — cần mọi vụ có kết quả vận hành" |

Precision policy (`format.ts`): CO₂e/kg, nước/kg, phân/kg 3 chữ số; ₫ và ₫/kg đồng tròn; kg CO₂e 2 chữ số.

## 5. Ảnh before / after

Gitignored: `web-dashboard/.qa-screenshots/logic-uat-round5/`

- `before/` — staging (bản deploy hiện tại), tài khoản UAT cũ + Manager: `farmer-{home,season,carbon,performance}-1440`, `mgmt-{dashboard,carbon,seasons,season,season-carbon,season-mrv,performance}-1440`.
- `after/` — cùng route, cùng tài khoản, cùng viewport, local branch (backend local → Supabase hosted): cùng tên file; cộng luồng UAT tài khoản mới `new-*`, `matrix-*`, `mrv-*`, `resp-*` (1440/768/390).

Quan trọng nhất: `before/farmer-carbon-1440.png` ↔ `after/farmer-carbon-1440.png` (P0-1/P0-2), `before/mgmt-season-carbon-1440.png` ↔ `after/…`, `before/mgmt-season-mrv-1440.png` ↔ `after/…`, `after/new-carbon-with-simulations-1440.png`, `after/new-harvest-area-over-plot-error-1440.png`.

Không ảnh nào chụp ô mật khẩu có giá trị (helper từ chối chụp); màn "mật khẩu tạm" sau khi tạo tài khoản không được chụp.

Kịch bản mô phỏng cũ hơn actual (phát hiện trên ảnh cuối): AWD/ngập liên tục tính lúc 14:31, actual tính lại lúc 14:52 sau sửa nước/phân/rơm, nhưng copy nói "cùng dữ liệu". Nay cả Farmer lẫn Management đánh dấu "Tính trên dữ liệu cũ hơn kết quả vận hành — chưa so sánh được" + "Tính lại kịch bản" (`after/new-carbon-simulations-outdated-1440.png` → `…-current-1440.png`; sau tính lại AWD = actual 4.877,77, ngập liên tục 8.717,00 kg / 1,453).

## 6. Bảng PRD/SRS → bằng chứng

| Yêu cầu | Bằng chứng | Kết quả |
|---|---|---|
| FR-1a-09 hai kịch bản AWD / ngập liên tục, ra số khác nhau | UAT: AWD 4.877,77 vs ngập liên tục 8.717,00 kg | PASS |
| SRS §4.2 `as_recorded` là kết quả của vụ, 2 giá trị kia để so sánh | API mặc định actual; `calculation_kind`; ma trận §4 | PASS |
| SRS §5 Carbon Calculation có `ef_config_version`, `calculated_at`, breakdown | `stored()` + real spec | PASS |
| NFR-05 / M1 tính CO₂e < 3 s, 10 lần | median 2.581 ms, p95 **4.340 ms** | **FAIL** |
| Không fake số khi thiếu dữ liệu/hệ số | "Không có dòng số riêng" + lý do; không dòng 0 kg | PASS |
| Vụ đã kết thúc chỉ đọc | UI 0 nút ghi/sửa/xoá; API POST/PATCH 422 `invalid_crop_season_state` (vụ cũ + vụ mới) | PASS |
| Farmer không xem được dữ liệu Management | `farmer-real-data` "deep-linking to /mrv stays in the Farmer shell" | PASS |
| MRV 6 bước, export có cảnh báo, checksum | JSON/XLSX/PDF thật, SHA-256 khớp | PASS |
| MRV export có factor version | `emission_factor_sets: []` (hồ sơ không có vụ đã tính) | **BLOCKED** |
| M05 khuyến nghị không bịa tác động / benchmark | copy + 0 khuyến nghị đúng trên vụ AWD | PASS |
| Mobile offline-first (queue, exactly-once 20 bản ghi) | không chạy | **NOT TESTED** |

## 7. Test gate (kết quả thật)

| Gate | Lệnh | Kết quả |
|---|---|---|
| Typecheck | `npx tsc --noEmit` | pass |
| Unit | `npx vitest run` | **61 file / 499 test pass** (một lượt giữa chừng chỉ báo 46/331 không kèm lỗi — chạy lại cùng code cho 61/498; không dùng lượt đó làm kết quả) |
| Build | `npm run build` | pass |
| Backend | `pytest tests` trong venv giống CI (FastAPI mới, torch/torchvision CPU) | **795 passed, 276 skipped, 0 failed** |
| Backend (Python global của máy) | cùng lệnh | không hợp lệ làm gate: FastAPI 0.115 (inventory test cần ≥ 0.141) và torchvision hỏng → 4 lỗi môi trường **có sẵn trên `main`** |
| Playwright mock (8 worker) | `npx playwright test` | **101 passed / 1 failed** — `farmer-web.spec.ts` hết ngân sách 30 s ở 3 bước khác nhau trong 3 lần chạy full. Trên `main` cùng máy: pass với **26,6 s** (sát 30 s). Chạy riêng: branch 3,8–5,8 s, main 3,9–4,7 s. Không nới timeout, không chạy lại để lấy xanh → **BLOCKED** |
| Playwright real (1 worker, `playwright.real.config.ts`, backend local → Supabase hosted) | toàn bộ | **26 passed, 12 skipped, 0 failed** (lần cuối, code cuối). Lần trước đó 24/12/**2 failed** (`round41-real`: bảng ops cuộn ngang ở 1280 với tên UAT dài) → sửa code `abcea93` → `round41-real` 6/6 → chạy full lại |
| `farmer-real-data` (cờ `FARMER_REAL_E2E=true`) | riêng | 1 passed, 1 skipped (MRV export opt-in) |
| 12 skip của real | write / CV / khuyến nghị / quick-fix / straw / provisioning / MRV export | opt-in ghi dữ liệu hosted, do smoke script điều khiển — không bật vòng này; luồng ghi đã chạy bằng UAT qua UI |
| Responsive + axe | 9 route × 6 width (1440/1363/1280/1024/768/390), dữ liệu thật | **54/54**: overflow 0, control ngoài viewport 0, target < 40 px 0, axe **0 violation mọi mức**, console app error 0 |

Test mới: `backend/tests/test_round5_carbon_integrity.py` (19), `test_round5_harvest_area.py` (6), `test_round5_carbon_repo_concurrency.py` (3); `src/carbon/round5.test.ts`, `farmer/round5Harvest.test.ts`, `farmer/round5Recs.test.ts`, `farmer/seasonDates.test.ts`; `tests/e2e/round5-real.spec.ts`. Test cũ đổi theo copy mới, không hạ assertion: `metricsView.test.ts` (tên nguồn), `seasonMethodology.dom.test.tsx` (thêm assertion không mâu thuẫn readiness), `test_carbon_persist_authorization.py` (fake thêm `stored()`).

## 8. Hiệu năng

Backend local (venv) → Supabase hosted ap-northeast-2, cùng vụ, `POST /v1/carbon/calculate` actual, 10 lần liên tiếp (idempotent — cùng calculation id cả 10):

| | median | p95 | min | max | DB calls |
|---|---|---|---|---|---|
| Trước (`81bb32e`) | 4.851 ms | 8.929 ms | 3.529 | 8.929 | 16 tuần tự |
| Sau (`966f69b`) | **2.581 ms** | **4.340 ms** | 1.859 | 4.340 | 14, phần lớn song song |

UI "Tính Carbon" → hiện kết quả: 6.985 ms lần đầu; tính lại 5,4–7,5 s (trước tối ưu). p95 > 3 s → **chưa operational-ready**. Còn lại tuần tự: 2 lần kiểm quyền RLS (replay JWT) + insert idempotent (xung đột → select). Hướng tiếp: RPC/transaction một round-trip cho persist, cache kiểm quyền theo request.

Readiness: median 1.108 ms, p95 3.107 ms.

Management (Manager, 5 lượt, preview production, tenant demo + 2 vụ UAT = 8 vụ):

| Route | Dòng đầu (skeleton) | Settled median / max | Request |
|---|---|---|---|
| `/carbon` | 68 ms | 10.856 / 12.562 ms | 32 |
| `/seasons` | 70 ms | 10.212 / 13.293 ms | 32 |

Request theo endpoint: `/carbon/readiness` ×8 và `/carbon` ×8 (1 mỗi vụ), `farms/{id}/crop-seasons` ×5 và `/plots` ×5 (1 mỗi nông hộ) → **N+1, tăng tuyến tính**. Không thêm batch endpoint vòng này (route table đóng băng + inventory). Đề xuất: `GET /v1/organizations/{id}/carbon-status` trả `{season_id, readiness, actual:{calculation_id,total,per_kg,calculated_at,input_hash}}[]`, test tương đương với endpoint đơn.

## 9. Accessibility

axe-core, `wcag2a/2aa/21a/21aa`, không tắt rule: 54 lượt (§7) **0 violation**. Touch target: segmented Carbon 34 → 40 px. Drawer/dialog/menu focus trap & restore: `round43-real` (drawer 390px) và `round41-real` (Escape trả focus về nút chi tiết) pass; mock `round43-qa` pass. Không chỉ dựa màu: kết quả vận hành viền liền, kịch bản viền đứt + nhãn chữ "Kịch bản mô phỏng". Chưa kiểm bằng screen reader thật.

## 10. Flutter offline-first

**NOT TESTED / BLOCKED.** Có Flutter SDK và AVD `agri_qa`. Lượt `flutter analyze` + `flutter test` đầu tiên bị Claude Code dừng vì máy thiếu RAM khi phiên đang chờ; chưa được yêu cầu chạy lại. Chưa có: queue sống qua restart, 20 bản ghi offline → đúng 20 dòng sau 2 lần sync, `(device_id, client_event_id)`, ảnh thiết bị. Không tạo ảnh giả. Bộ ảnh trụ cột 01 (Mobile) vì vậy chưa có.

## 11. Bộ ảnh bốn trụ cột

| Trụ cột | Ảnh (`.qa-screenshots/logic-uat-round5/after/`) | Caption đề xuất |
|---|---|---|
| 01 Mobile offline-first | — | Chưa có (§10) |
| 02 Carbon Engine | `new-final-carbon-1440.png`, `new-carbon-simulations-current-1440.png`, `new-final-carbon-1440.png` (disclosure mở) | "Kết quả vận hành theo dữ liệu đã ghi; kịch bản mô phỏng đặt cạnh, không thay kết quả." |
| 03 Khuyến nghị | `new-season-overview-recommendations-1440.png` | "Khuyến nghị dựa trên quy tắc và dữ liệu vụ. RAG là định hướng tích hợp tương lai, chưa triển khai." |
| 04 Cloud & Web Dashboard | `new-ended-mgmt-carbon-1440.png`, `new-ended-mgmt-seasons-1440.png`, `mgmt-accounts-list-after-create-1440.png` | "Quản lý thấy Nông hộ → Thửa → Vụ của tài khoản mới, trạng thái dữ liệu và Carbon." |

## 12. Hạ tầng quan sát được

- 14:15:07: 7 request `/carbon/readiness` → 500 `httpx.ConnectError [Errno 11001] getaddrinfo failed` (DNS tới Supabase hosted) — hạ tầng, không lặp lại ở các lượt sau; gate ghi theo lần chạy cuối, không phải lượt được chọn.
- Staging: `/cv/inferences` 503 (Render không cài CV — đã biết).
- Real suite kết thúc bằng sign-out global (đã biết) → phiên lưu của script UAT bị thu hồi; không ảnh hưởng kết quả.

## 13. DONE / BLOCKED / NOT TESTED

| Hạng mục | Trạng thái |
|---|---|
| P0 actual vs scenario | DONE |
| P0 provenance/breakdown | DONE |
| P0 cost-only stale / fingerprint | DONE |
| P1 harvested area (web + API) | DONE (DB-level cho Flutter: chưa) |
| P1 ngày vụ | DONE |
| P1 khuyến nghị (copy, cơ sở, làm mới data task) | DONE; `evidence/input_hash` trong response: BLOCKED (backend) |
| P1 MRV association + copy | DONE |
| P1 MRV export tải & mở file | DONE; factor version trong export: BLOCKED |
| P1 account lifecycle | BLOCKED (backend chưa có endpoint; contract §4) |
| P2 copy / precision / trạng thái | DONE |
| Hiệu năng Carbon < 3 s | BLOCKED (p95 4,34 s) |
| Management N+1 | BLOCKED (cần batch endpoint) |
| Responsive / a11y | DONE |
| Playwright mock full | BLOCKED (1 timeout, §7) |
| Playwright real full | DONE (26/0 fail) |
| Flutter / device | NOT TESTED |
| RAG | OUT OF SCOPE (không có implementation; không quảng bá) |

## 14. Credential cleanup

- Mật khẩu chỉ đi qua file env tạm trong scratchpad phiên (ngoài repo), nạp bằng `set -a` cho từng lệnh; Manager và `qa-farmer-fw1` reset bằng script scratchpad do người dùng chạy qua `!` (không in mật khẩu); mật khẩu tạm của tài khoản UAT mới đọc từ DOM ghi thẳng vào file env, không in, không chụp.
- **Mật khẩu tài khoản UAT cũ đã được dán vào chat** → nên đổi mật khẩu tài khoản `uat-20260928-1353@…`.
- Quét 4 giá trị mật khẩu trong `test-results/`, `playwright-report/`, `.qa-screenshots/`, `docs/`, `AGENTS.md`, `src/`, `tests/`, `backend/`, log scratchpad và `git log -p b461d31..HEAD`: **0**. Quét JWT (`eyJ…`) trong artifact và log: **0**. Không có trace zip (real config `trace: 'off'`).
- Đã xoá: `qa.env`, script nhập/reset, session state Playwright, trace so sánh, worktree `main` (gỡ junction `node_modules` trước), preview 5173 và uvicorn 8010 đã dừng.
- Sự cố: một biến `UAT_STATE_DIR` dạng `/c/...` với `MSYS_NO_PATHCONV=1` làm node ghi session state vào `E:\c\...`; đã xoá cây đó. Lệnh xoá cũng xoá 3 ảnh PNG tạm (`s2-*.png`) mà một phiên Claude trước đã ghi lạc vào cùng cây `E:\c\...\4d00f875…\scratchpad` — không thuộc repo, nhưng đã xoá mà không liệt kê trước.

## 15. Dữ liệu UAT còn lại (hosted)

- Tài khoản `uat-r5-202609290717@agricarbon-demo.local` + nông hộ `UAT-R5-FARM-09290717` + thửa `UAT-R5-PLOT-09290717` + vụ `UAT R5 Hè Thu 2026` (đã kết thúc) + 6 hoạt động + các bản tính actual/AWD/ngập liên tục. Không xoá được qua sản phẩm (không có endpoint cleanup).
- 3 bản MRV export mới trên hồ sơ demo `DEMO-MRV-2026` (JSON/XLSX/PDF, 2026-09-29 ~14:46).
- Vụ UAT cũ: không đổi (chỉ đọc, 1 POST/PATCH bị từ chối 422).
- Mật khẩu `demo-manager` và `qa-farmer-fw1` đã được reset theo yêu cầu (mật khẩu cũ vô hiệu).

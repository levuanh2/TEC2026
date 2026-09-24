# Web UX Round 4.3 — Chỉ số có ý nghĩa & menu trượt Management

> Branch `fix/agricarbon-round4-3-meaningful-metrics`, tạo từ `origin/main` = `89d28b1`. Final gate §13 (2026-09-25); push/merge §14. **Không deploy, không tag.**

Phạm vi: chỉ lớp trình bày của `web-dashboard/`. **Không** sửa backend, Supabase, API contract, công thức, hệ số, Carbon methodology hay readiness rules. Không sửa file untracked có sẵn (`docs/*.jpg`, `docs/ChatGPT Image …png`, `.mcp.json`).

## 1. Skill / công cụ

| Yêu cầu | Thực tế |
|---|---|
| Product Design Audit | Không có skill tên này trong phiên. Audit thực hiện **trên giao diện render bằng dữ liệu thật** (ảnh before/after cùng tài khoản, cùng viewport), phát hiện ghi ở §2 và §7. |
| Accessibility | `axe-core` 4.13.0, tag `wcag2a/2aa/21a/21aa`, không tắt rule nào. **Thêm vào `devDependencies`** (Round 4.2 chỉ cài tạm) vì spec mới `round43-qa`/`round43-real` import nó qua `tests/e2e/axe-helper.ts`. |
| Playwright | `@playwright/test` 1.63 có sẵn; script chụp ảnh ở scratchpad, 2 spec mới. |

## 2. Audit trước khi sửa (render, dữ liệu thật, `89d28b1`)

Tài khoản QA Farmer `DEMO-HT-2026 · Thửa demo 1.1` (5.200 kg thóc, 330 m³ nước, 150 kg phân, 9 hoạt động, chưa có kết quả Carbon, thiếu 2 thông tin + 1 giới hạn hệ số) và Manager `AgriCarbon Demo Cooperative` (3 hộ, 6 vụ).

| # | Màn hình | Phát hiện |
|---|---|---|
| A1 | Farmer Performance | `0,063 m³/kg lúa`, `0,029 kg/kg lúa` không trả lời "cao hay thấp / từ đâu / làm gì". Không có năng suất, không có kg/ha. |
| A2 | Farmer Performance | Chi phí và Carbon "Chưa đủ dữ liệu" **không có hành động** nào; Carbon không dẫn tới quick-fix. |
| A3 | Farmer Performance | Thanh "Đang xem vụ" vỡ layout (icon trôi giữa trang, 1363 và 390px). |
| A4 | Farmer Home | "9 hoạt động" là tile KPI tô **xanh healthy** ngang hàng Nước/Phân/Carbon; Nước tô teal, Phân tô xanh — màu ngụ ý "tốt" dù không có mốc. |
| A5 | Management Performance | "Thiếu số liệu nước tưới" in to như một giá trị; không nói bao nhiêu vụ đứng sau, vụ nào thiếu. |
| A6 | Management menu 390px | Không backdrop; chạm workspace **không đóng** menu (đo: `backdrop tap closed menu: false`); focus ở lại nút mở; Tab thoát ra trang dưới; trang dưới vẫn cuộn. |

## 3. Quyết định cho từng chỉ số

| Chỉ số | Quyết định | Ý nghĩa / quyết định hỗ trợ | Nguồn dữ liệu |
|---|---|---|---|
| Sản lượng, diện tích, năng suất (t/ha) | **Mới** — khối "Bối cảnh vụ mùa", dạng danh sách sự kiện, không tile màu | Nắm quy mô vụ trước khi đọc tỷ lệ; nêu rõ **không phải đầu vào Carbon** | `metrics.yield_kg`; diện tích = tổng `harvest.harvested_area_ha` nếu **mọi** lần thu hoạch có, ngược lại `plot.area_ha` (ghi rõ nguồn nào) |
| Nước tưới | **Đổi cách trình bày**: chính = lít/kg lúa; phụ = m³/kg (giá trị server), tổng m³, m³/ha | Mỗi kg thóc cần bao nhiêu nước đã ghi; link "Xem hoạt động tưới" → `/farmer/journal?loai=irrigation` | `metrics.water_per_kg`, `water_m3`; ×1000 chỉ ở view |
| Phân bón | **Đổi**: chính = kg phân/ha (khi có diện tích), phụ = g/kg lúa, kg/kg lúa (server), tổng kg | Liều bón/ha để so với kế hoạch của nông hộ. Ghi rõ là **khối lượng sản phẩm, không phải N/P/K** | `metrics.fertilizer_kg`, `fertilizer_per_kg`, diện tích |
| Chi phí trực tiếp đã ghi | **Đổi tên + tách nhóm**: tổng ₫ đã ghi, ₫/kg (server), danh sách nhóm đã/chưa ghi, "Nhân công, thuê máy — chưa có ô nhập riêng" | Biết phần nào chưa ghi; CTA "Bổ sung chi phí trong Nhật ký". Không bao giờ `0 ₫/kg`; khi thiếu: "Chưa đủ dữ liệu chi phí" | `metrics.cost_per_kg` + tổng hợp `total_cost_vnd`/`cost_vnd` từ payload hoạt động (cùng bảng trường với `_COST_FIELD_BY_ACTIVITY`); tổng chỉ hiện khi server coi chi phí đủ |
| Carbon | **Giữ số server**, sắp lại: tổng (t hoặc kg CO₂e) → CO₂e/kg → nguồn lớn nhất → thời điểm tính → trạng thái (mới / cần tính lại) → "Cách tính và dữ liệu sử dụng" | Chưa sẵn sàng: "Còn thiếu N thông tin để tính Carbon", **một** CTA "Bổ sung N thông tin" → quick-fix; giới hạn hệ số tách riêng "không cần bạn nhập" | `metrics.total_co2e_kg/co2e_per_kg`, `/carbon` (breakdown, calculated_at), `/carbon/readiness` qua `carbonView` |
| Số hoạt động | **Hạ cấp** khỏi KPI: dòng chữ trung tính "Nhật ký: 9 hoạt động đã ghi" + "Xem nhật ký" | Thông tin nhật ký, không phải thành tích | `/activities` |
| Độ đầy đủ | Số lượng cụ thể ("Còn thiếu 2 thông tin…", "9 hoạt động chưa ghi chi phí"), **không dùng %** | Mẫu số required fields không do backend định nghĩa | readiness / payload |
| Management aggregates | **Giữ số server**, thêm: phạm vi, "Dựa trên X/Y nông hộ đủ dữ liệu", nút "N nông hộ thiếu dữ liệu" mở đúng danh sách hộ (link + lý do), dòng "Theo vụ: Chưa có dữ liệu tổng hợp — cần endpoint chỉ số theo lô.", "Mốc so sánh: Chưa có" | Người quản lý biết con số đại diện cho bao nhiêu hộ và phải đi xử lý hộ nào | `/organizations/{id}/metrics` + `/organizations/{id}/farm-performance` (trang vốn đã tải). **Đã sửa ở gate** — bản đầu gọi `/metrics` từng vụ (N+1), xem §13 |
| Management Overview | Thêm dòng phạm vi "Phạm vi: toàn HTX · N vụ … không phải điểm hiệu suất" | Ô "Vụ thiếu dữ liệu" đã mở đúng danh sách (`/data-gaps?loc=missing`, cùng tiêu chí `missing.length`) — đã xác minh | `useOperations` sẵn có |

Nguyên tắc chung (có test): mọi dòng chỉ số có tên, giá trị+đơn vị (không tách dòng: `white-space: nowrap` + NBSP), một câu ý nghĩa, cơ sở tính, trạng thái bằng chữ + icon, trạng thái so sánh, một hành động, disclosure `aria-expanded`.

## 4. Benchmark

| Mốc | Có thật? | Xử lý |
|---|---|---|
| Nước / phân / chi phí / CO₂e chuẩn ngành | **Không** có trong hệ thống | Hiện "Chưa có mốc để đánh giá cao hay thấp." — không có từ tốt/xấu/cao hơn/thấp hơn/tiết kiệm/lãng phí/đạt chuẩn (test `JUDGEMENT_WORDS`) |
| Cùng thửa, vụ trước | Không có endpoint; có thể ghép từ client nhưng **mùa vụ (Đông Xuân / Hè Thu) không phải trường có cấu trúc** nên không xác minh được tính tương đồng | Không làm; "Chưa có mốc so sánh" |
| Cùng giống / cùng mùa vụ | Không có | Không làm |
| Trung vị HTX nhóm tương đồng | Không có | Không làm |

**Không có dữ liệu giả, không hard-code ngưỡng.** Mọi quy đổi (m³→lít, kg→g, /ha, t/ha, kg→t) là phép trình bày trên số server hoặc số đã ghi; giá trị server luôn hiện nguyên bên cạnh.

## 5. Phần B — Menu trượt Management (≤768px)

`components/useMobileDrawer.ts` + `Sidebar` (prop `drawer` tùy chọn) + `AppShell`:

- Backdrop `.shell-backdrop` phủ workspace; chạm → đóng.
- Escape đóng; nút "Đóng menu" (44×44) có accessible name.
- Mở: focus vào nút Đóng; Tab/Shift+Tab bị giữ trong drawer; `aside` thành `role="dialog" aria-modal="true"`.
- `.main` nhận `inert`; `body { overflow: hidden }`.
- Đóng: focus về nút "Mở menu" (`aria-controls="app-drawer"`).
- Đổi route tự đóng; lớn hơn 768px tự trở về rail.
- Đóng trên điện thoại: `aside` có `inert` (không nhận Tab, thêm vào `visibility:hidden` sẵn có).
- Farmer không truyền `drawer` → không nút đóng, không inert, bottom nav nguyên vẹn. Desktop/tablet: `.sidebar__top` là block, rail không đổi.

## 6. Ảnh before / after

Cùng tài khoản thật, cùng viewport; before = worktree `89d28b1` build + `vite preview`, after = branch build. Lưu local (gitignored) tại `web-dashboard/.qa-screenshots/round4-3/{before,after}/`:

`farmer-home-1363.png`, `farmer-performance-1363.png`, `farmer-performance-390.png`, `farmer-carbon-1363.png` (missing-data state), `management-overview-1363.png`, `management-performance-1363.png`, `management-menu-closed-390.png`, `management-menu-open-390.png`, `management-menu-backdrop-390.png`.

Kết quả tương tác đo bằng script: before `backdrop tap closed menu: false` → after `true`.

## 7. Audit sau khi sửa (render) và các sửa phát sinh

| Phát hiện trên ảnh after | Sửa |
|---|---|
| Danh sách "N vụ thiếu dữ liệu" hiện sẵn dù nút `aria-expanded=false` (`display:grid` đè `hidden`) | `.agg__list[hidden]`, `.fw-mdisc__body[hidden] { display:none }`; spec real kiểm tra `toBeHidden` trước khi bấm |
| Tên dòng lặp tiêu đề nhóm ("Chi phí trực tiếp đã ghi" ×2, "Phát thải Carbon" ×2) | Đổi thành "Tổng chi phí đã ghi", "Tổng phát thải của vụ" |
| 9 hoạt động không có chi phí → 8 dòng "chưa ghi" rối | Khi 0 hoạt động có chi phí: một dòng "Chưa hoạt động nào có chi phí 0/N" |

## 8. Kiểm thử

| Bước | Kết quả |
|---|---|
| `npx tsc --noEmit` | OK |
| `npx vitest run` | **49 files, 402 tests passed** |
| `npm run build` | OK |
| Mock Playwright toàn bộ (`npx playwright test`, default config) | **76 passed, 41 skipped** (các spec real/redesign-qa tự skip khi thiếu env), 0 failed |
| Round 4.3 mock (`round43-qa.spec.ts`) | **35/35** — drawer 768/430/390 (closed không nhận Tab, backdrop phủ toàn chiều rộng, tap ngoài, Escape, focus vào/ra, trap Tab/Shift+Tab, route change, axe khi mở), rail 1363/1024 không đổi, Farmer bottom nav 390, Performance mock toàn null → 4 `.fw-metric__empty`, axe 5 màn hình × 2 viewport |
| Round 4.3 real (`round43-real.spec.ts`, dữ liệu thật) | **4/4** — Performance 4 nhóm đúng thứ tự, lít/kg + m³/kg + cơ sở tính, không từ đánh giá, không `0 ₫`, Carbon dẫn `/farmer/carbon`, disclosure `aria-expanded`, link tưới → journal lọc sẵn; Home dòng nhật ký, không tone positive; Management 4 aggregate đều có "Dựa trên X/Y", nút mở đúng N link; Overview dòng phạm vi; drawer 390 thật; axe trên 5 màn hình thật |
| Real gates có sẵn (read-only; không chạy `farmer-real-write`, MRV export tự skip vì thiếu `REAL_MRV_EXPORT_E2E`) | `sidebar-parity-real` **3/3** (lần chạy riêng cuối); `round4-real`, `round41-real` pass; `web-real-data` và `farmer-real-data`: 1 test mỗi file **fail từ trước** — đã sửa ở gate, xem §13.1. Lần chạy gộp đầu: 12 passed, 3 failed, 2 skipped, 2 did not run |
| Lỗi chập chờn phía backend (không phải UI) | 3 lần `sidebar-parity-real` fail trước khi pass, mỗi lần do **một** request backend trả 500 (không header CORS nên trình duyệt báo CORS): 2× `postgrest APIError PGRST303 'JWT issued at future'` (lệch đồng hồ máy local ↔ Supabase ngay sau đăng nhập), 1× `httpcore.ReadError [WinError 10038]` (socket httpx của backend). Log uvicorn lưu ở scratchpad. Lần chạy lại: 0 lỗi console app-origin cho cả hai vai trò |

Test mới (unit/DOM, 3 file + 1 file thay):
- `farmer/metricsView.test.ts` (viết lại, 15 test): m³/kg→lít/kg chỉ ở view và giá trị server vẫn hiện; object metric không bị mutate; không từ đánh giá; missing ≠ 0; chi phí rỗng/một phần/đủ; Carbon chưa tính (một CTA, giới hạn tách riêng) và đã tính (đúng thứ tự); cost/Carbon khác group; kg/ha + N/P/K; nguồn diện tích; dòng nhật ký.
- `farmer/round43.dom.test.tsx` (13): render thật Home strip (không `.fw-role--positive`, link nhật ký), CostPanel, MetricRow (NBSP value+unit, disclosure aria-expanded), AggregateMetric (3/10 nông hộ, "7 nông hộ thiếu" mở đúng 7 link, không hiện số vụ không suy ra được, đang đọc).
- `pages/coverage.test.ts` (5), `pages/performance.dom.test.tsx` (1, ngân sách request), `components/useMobileDrawer.dom.test.tsx` (10): backdrop, outside click, Escape, nút đóng, trap, focus return, route change, closed inert, desktop không modal, Farmer sidebar không đổi.
- `farmer/activityView.test.ts`: 3 test `metricViews` cũ chuyển sang API mới với cùng khẳng định (tỷ lệ server giữ nguyên, missing null, harvest CTA, không form shortcut cho cost/Carbon). Không hạ assertion, không skip.

## 9. Accessibility

- axe (serious/critical, WCAG 2.1 AA): **0** trên `/farmer`, `/farmer/performance`, `/farmer/carbon`, `/dashboard`, `/performance` (mock 1363 + 390; real ở viewport mặc định 1280) và với drawer mở ở 768/430/390.
- Touch target: nút Đóng menu, nút Mở menu 44×44; link hành động trong dòng chỉ số, disclosure, "Xem chi tiết" ≥ 40–44px; nút "N vụ thiếu dữ liệu" 40px.
- Focus-visible trên disclosure, nút aggregate, sidebar (sẵn có).
- Trạng thái luôn có chữ + icon (`Đủ dữ liệu để tính` / `Chưa đủ dữ liệu`), không chỉ màu; không mũi tên tăng/giảm.
- Loading ("Đang đọc độ phủ dữ liệu (n/Y vụ)"), thiếu dữ liệu, lỗi (`role="alert"`) đều có chữ.

## 10. Giới hạn đã biết

- Độ phủ Management chỉ chính xác ở **cấp nông hộ**; số vụ đủ dữ liệu chưa hiển thị được cho tới khi có endpoint theo lô (§11, §13).
- Tổng chi phí phía Farmer cộng lại từ payload hoạt động theo đúng bảng trường server; chỉ hiện khi server báo chi phí đủ, nên không thể lệch với ₫/kg của server.
- "Cần tính lại" dựa trên thay đổi trong phiên (`carbonInputsChangedAt`), như Carbon page hiện có.
- `pages/dashboard.tsx` (`DashboardPage`) là code chết (import nhưng không route) — không sửa.
- 2 real spec cũ fail **từ trước round này** — đã sửa ở gate (§13.1).

## 11. Yêu cầu backend / dữ liệu chưa triển khai

1. **Batch season metrics** (để hiện "X/Y vụ đủ dữ liệu"): nhận danh sách `crop_season_id` hoặc `organization_id`; số request **không tăng theo số vụ** (1 request); kết quả từng vụ **tương đương** `GET /crop-seasons/{id}/metrics` hiện tại (cùng `_compute_metric_totals`); partial failure trả về theo từng vụ (`{crop_season_id, metrics | error}`) để xác định được vụ nào lỗi. Backend đã có `metrics_for_seasons()` nội bộ (dùng cho MRV export) — chỉ thiếu route.
2. Baseline so sánh: trường mùa vụ có cấu trúc (Đông Xuân/Hè Thu/Thu Đông) trên `crop_seasons`, rồi endpoint "vụ trước cùng thửa" và "trung vị HTX theo nhóm tương đồng" kèm n.
3. Nutrient basis: lượng N/P/K nguyên chất đã bón (server tính từ `nitrogen_percent`…) nếu muốn chỉ số dưỡng chất.
4. Trường chi phí nhân công / thuê máy riêng.
5. Tổng chi phí (`total_cost_vnd`) trong `MetricResponse` thay vì chỉ `_total_cost_vnd` nội bộ.
6. Cờ `stale` do server tính cho kết quả Carbon.

## 12. Git

- Branch: `fix/agricarbon-round4-3-meaningful-metrics` (base `89d28b1`)
- Commit code: `491f5d3` (feat), `977e177` (docs); gate: `55e00bb`, `161d7e5`, `13032c2` và commit docs gate (§13, §14)
- Push/merge: xem §14. **Không deploy, không tag.**

## 13. Final engineering gate (2026-09-25)

Commit thêm trên branch (sau `977e177`):

| # | SHA | Commit |
|---|---|---|
| 3 | `55e00bb` | `test(web): align real-data assertions with current Farmer UI` |
| 4 | `161d7e5` | `fix(web): Management coverage without per-season /metrics fan-out` |
| 5 | `13032c2` | `test(web): align opt-in real specs with current Farmer UI; one real worker` |
| 6 | commit docs gate | `docs: Round 4.3 final engineering gate` |

### 13.1 Spec real-data lỗi thời

Chứng minh fail trên base `89d28b1` (worktree base, build + `vite preview`, cùng backend, cùng tài khoản QA):

| Spec | Fail trên base tại | Nguyên nhân (có từ trước 4.3) | Sửa |
|---|---|---|---|
| `web-real-data` | `getByRole('heading', { name: 'Tổng quan', level: 1 })` | Home Management là `Hôm nay cần xử lý gì?`; `DashboardPage` không còn được route | Assert: đúng vai trò (URL `/dashboard`), **đúng 1 `h1`** `Hôm nay cần xử lý gì?`, nav `Điều hướng chính` với `Tổng quan vận hành` `aria-current=page`, **không** có nav Farmer, **không** còn ô `Mật khẩu`, nội dung chính đã tải (`Danh sách công việc ưu tiên` + chip tổ chức, không `Chưa gán tổ chức`). Đi hierarchy qua link có tên (`Nông hộ & ruộng`, `Mở hồ sơ nông hộ …`, `Mở thửa …`, `Mở vụ …`) thay vì `tbody tr`; hoạt động chọn theo role button có tên kết thúc bằng giờ/ngày thay vì `.act` |
| `farmer-real-data` | `locator('.fw-ledger')` | Home Farmer không render `.fw-ledger` từ bản hybrid | Assert đúng vai trò, 1 `h1` `Hôm nay trên ruộng của bạn`, nav `Điều hướng nông hộ` (`Tổng quan` current), không nav Management, không form đăng nhập. Region **`Hoạt động gần đây`** (thêm `aria-labelledby` cho section — chỉ a11y) phải: không còn `aria-busy`, không có `role=alert`, có link `Xem toàn bộ nhật ký` → `/farmer/journal`, và **đúng một** trong hai trạng thái hợp lệ: ≥1 `listitem` **xor** empty state `Chưa có hoạt động nào được ghi nhận cho vụ này.`. Hierarchy qua link có tên; Carbon kiểm bằng heading/label thay vì `.fw-carbon-*` |
| `farmer-real-write`, `farmer-real-cv`, `farmer-real-recommendations` (opt-in, ghi dữ liệu QA) | `link 'Xem vụ'`, `button 'Kiểm tra lá lúa'`, `section 'Khuyến nghị'` trên Home | Hybrid redesign dời các khối này sang trang vụ (Home link: `Xem chi tiết vụ`); nút picker có tên kèm gợi ý; nhãn `Lượng nước (m³)` đổi thành `Nước tưới (m³)` ở `b360e33` | Chỉ sửa điều hướng/tên; giữ mọi assertion |

Không xoá, không skip, không hạ assertion, không thêm timeout dài, không UUID mới.

**Dữ liệu QA:** một lần `farmer-real-write` fail giữa chừng (nhãn cũ) để lại 1 bản ghi tưới `QA-FW2-1790271079487`; đã xoá qua `DELETE /v1/activities/{id}` thật (204) và kiểm lại 0 dòng `QA-FW2-*`. Sau các lần chạy pass: 0 dòng.

### 13.2 `/metrics` N+1 — regression mới của 4.3, đã sửa

Trace Playwright trên tenant thật (6 vụ, 3 hộ): `page.goto('/performance')` sau khi đăng nhập Manager, 3 lần mỗi build, `vite preview` + cùng backend local. *First meaningful render* = heading `Hiệu quả tài nguyên` và thẻ chỉ số đầu tiên hiển thị; *settled* = response API cuối cùng hoặc `networkidle` (gồm 500 ms idle của Playwright) và không còn skeleton / “Đang đọc độ phủ”.

| Build | Request API | `/crop-seasons/{id}/metrics` | First meaningful (3 lần) | Settled (3 lần) | Lỗi/timeout |
|---|---|---|---|---|---|
| base `89d28b1` | 5 | 0 | 1964 / 1921 / 1925 ms (median 1925) | 2464 / 2227 / 2072 ms (median 2227) | 0 |
| feature `977e177` | **18** | **6** | 1948 / 1924 / 1931 ms (median 1931) | 3945 / 3719 / 3577 ms (median **3719**) | 0 |
| fixed `161d7e5` | 5 | 0 | 1948 / 1921 / 1909 ms (median 1921) | 2604 / 2167 / 2264 ms (median 2264) | 0 |

5 request của base và fixed: `/v1/me`, `/v1/farmer/scope`, `/v1/organizations/{id}`, `/{id}/metrics`, `/{id}/farm-performance`. Feature thêm `/v1/farms` + `(crop-seasons + plots) × 3 hộ` + `metrics × 6 vụ` = **13**; tăng theo **1 + 2 × số hộ + số vụ**. Base và fixed: **hằng số 5**, không phụ thuộc số vụ.

Quyết định (ưu tiên A): `farm-performance`, payload trang vốn đã tải, cho độ phủ **chính xác ở cấp nông hộ** (chỉ số của một hộ null đúng khi một vụ của hộ thiếu dữ liệu — cùng quy tắc với rollup HTX). UI: `Dựa trên X/Y nông hộ đủ dữ liệu`, nút `N nông hộ thiếu dữ liệu` mở đúng các hộ đó. Cấp vụ **không** suy ra được → `Theo vụ: Chưa có dữ liệu tổng hợp — cần endpoint chỉ số theo lô.` (không số giả). Không thêm backend. Test chặn tái phát: `pages/performance.dom.test.tsx` (đúng 3 endpoint tổ chức, 0 `getResourceMetrics`, 0 `listFarms`/`getFarmCropSeasons`/`getPlotsForFarm`) và `round43-real` (0 request `/crop-seasons/*/metrics` trên `/performance` thật).

Ghi chú: Overview/Seasons/Data gaps (`useOperations`) fan-out readiness/carbon theo vụ **đã có từ trước 4.3**, không đổi trong round này. Yêu cầu backend: §11.1.

### 13.3 Presentation math & mẫu số diện tích

Test (`farmer/metricsView.test.ts`, khối “presentation math”): `0,063 m³/kg → 63 lít/kg`; `150 kg / 1,2 ha = 125 kg/ha` trên **diện tích thu hoạch** (thửa 1,3 ha sẽ cho 115); `5.200 kg / 1,2 ha → 4,3 tấn/ha` với nhãn `Diện tích thu hoạch`; không dùng số đã làm tròn cho bước sau (100 kg / 0,3333 ha → 300, không phải 303; m³/ha tính từ tổng m³ gốc); object server không đổi (so sánh với `structuredClone`). Quy tắc mẫu số: diện tích thu hoạch khi **mọi** bản ghi thu hoạch có `harvested_area_ha`, ngược lại diện tích thửa; UI luôn nói cái nào được dùng.

UI hiển thị (không chỉ trong disclosure): `Khối lượng sản phẩm phân bón (không phải lượng N/P/K) đã ghi trên mỗi ha diện tích thu hoạch đã ghi — …`; cơ sở tính `Tính từ 150 kg phân đã ghi, 1,2 ha diện tích thu hoạch đã ghi và 5.200 kg thóc.`

### 13.4 Dev dependency

- `axe-core` chỉ trong `devDependencies` (`^4.13.0`, cùng convention caret như các devDependency khác); lock `4.13.0` với `resolved` + `integrity` từ registry.npmjs.org, `"dev": true`. `package.json` và `package-lock.json` cùng trong commit `491f5d3`.
- Không dependency runtime mới; không file nào trong `src/` import axe.
- `npm ci` từ sạch: OK, lockfile không đổi.
- `npm run build`: `dist/` **không** chứa `axe-core` / `axe.run` / `Deque Systems` (grep); bundle chính 684 KB.

### 13.5 Full gate

| Bước | Kết quả |
|---|---|
| `npm ci` | OK |
| `npx tsc --noEmit` | OK |
| `npx vitest run` | **50 files, 411 tests passed** |
| `npm run build` | OK |
| Playwright mock toàn bộ | **76 passed, 45 skipped, 0 failed** (skip = spec real/redesign-qa khi không có credential) |
| `round43-qa` (trong mock) | 35/35 |
| Playwright real toàn bộ (1 worker, bật write/CV/recommendations) | **24 passed, 0 failed, 6 skipped** (8.4 min, lần chạy đầu với 1 worker, không retry). Skip: 2 `farmer-real-carbon-quickfix` + 2 `farmer-real-straw-quickfix` (thiếu credential `QF_*`/`SQF_*`), 2 MRV export (chưa opt-in `REAL_MRV_EXPORT_E2E`). Gồm `round43-real` 4/4, `sidebar-parity-real` 3/3, `web-real-data` 2/2, `farmer-real-data` 1/1, `farmer-real-write` 1/1, `farmer-real-cv` 1/1, `farmer-real-recommendations` 1/1, `round4-real` 5/5, `round41-real` 6/6. Sau suite: 0 dòng `QA-FW2-*` |
| `redesign-qa` (default config, `REDESIGN_QA=true`, real preview) | **15/15 passed** (10.6 min) |
| axe-core | 0 serious/critical (mock `round43-qa`: 5 màn hình × 2 viewport + drawer mở ở 3 viewport; real `round43-real`: Farmer Performance, Home, Carbon, Management Performance, Overview) |

**Hạ tầng vs app.** Lượt real đầu tiên chạy 8 worker: 2 fail “Phiên đăng nhập đã hết hạn” (`round43-real` Farmer, `sidebar-parity-real` Farmer). Log backend: Supabase `GET /auth/v1/user` → **403** rồi `/v1/me` → 401 lúc 16:38:08Z, 11 s sau khi suite bắt đầu, kèm 4× `PGRST303 JWT issued at future`. Nguyên nhân: các spec chạy song song trên **cùng tài khoản QA**, và `round4-real`/`sidebar-parity-real` kết thúc bằng Đăng xuất (Supabase `signOut` scope `global`) → thu hồi phiên của spec đang chạy bên cạnh. Không phải lỗi frontend, không phải lệch đồng hồ (đo: máy local chậm hơn Supabase ~1 s). Sửa: `workers: 1` trong `playwright.real.config.ts`; không bỏ qua 500/CORS nào.

Không chạy (spec tự skip đúng thiết kế): `web-real-data` › MRV export (cần `REAL_MRV_EXPORT_E2E=true` **và** script dọn storage sau đó); `farmer-real-carbon-quickfix`, `farmer-real-straw-quickfix` (cần tài khoản owner/viewer, season ID và API token riêng `QF_*`/`SQF_*`, không có trong phiên).

## 14. Push & merge

- Push feature branch `fix/agricarbon-round4-3-meaningful-metrics` sau khi §13.5 xanh.
- Trước merge: `git fetch origin`, kiểm `origin/main` vẫn là `89d28b1` và merge-base của branch = `89d28b1`; giữ nguyên file untracked (`docs/*.jpg`, `docs/ChatGPT Image …png`, `.mcp.json`).
- `git merge --no-ff fix/agricarbon-round4-3-meaningful-metrics`, rồi trên `main`: `npx tsc --noEmit`, `npx vitest run`, `npm run build`, `round43-qa` mock; chỉ push `main` khi tất cả pass.
- Không rebase, không force-push, không tag, không deploy. Không sửa backend, Supabase, công thức, hệ số hay methodology Carbon (`git diff 89d28b1 -- backend supabase` rỗng).
- SHA merge và `origin/main` sau push được báo trong phản hồi cuối của gate (commit này không thể tự chứa SHA merge của chính nó).

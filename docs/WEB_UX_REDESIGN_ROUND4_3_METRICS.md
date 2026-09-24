# Web UX Round 4.3 — Chỉ số có ý nghĩa & menu trượt Management

> Branch `fix/agricarbon-round4-3-meaningful-metrics`, tạo từ `origin/main` = `89d28b1` (đã kiểm tra `git ls-remote origin main`). Commit local, **chưa push, chưa merge, chưa deploy**. Dừng ở gate để người dùng duyệt.

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
| Management aggregates | **Giữ số server**, thêm: phạm vi, "Dựa trên X/Y vụ đủ dữ liệu", nút "N vụ thiếu dữ liệu" mở đúng danh sách vụ (link + lý do), "Mốc so sánh: Chưa có" | Người quản lý biết con số đại diện cho bao nhiêu vụ và phải đi xử lý vụ nào | `/organizations/{id}/metrics` + `/v1/farms` → `/farms/{id}/crop-seasons` → `/crop-seasons/{id}/metrics` (song song 4, hiện dần) |
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
| Real gates có sẵn (read-only; không chạy `farmer-real-write`, MRV export tự skip vì thiếu `REAL_MRV_EXPORT_E2E`) | `sidebar-parity-real` **3/3** (lần chạy riêng cuối); `round4-real`, `round41-real` pass; `web-real-data` và `farmer-real-data`: 1 test mỗi file **fail từ trước** (xem §10). Lần chạy gộp đầu: 12 passed, 3 failed, 2 skipped, 2 did not run |
| Lỗi chập chờn phía backend (không phải UI) | 3 lần `sidebar-parity-real` fail trước khi pass, mỗi lần do **một** request backend trả 500 (không header CORS nên trình duyệt báo CORS): 2× `postgrest APIError PGRST303 'JWT issued at future'` (lệch đồng hồ máy local ↔ Supabase ngay sau đăng nhập), 1× `httpcore.ReadError [WinError 10038]` (socket httpx của backend). Log uvicorn lưu ở scratchpad. Lần chạy lại: 0 lỗi console app-origin cho cả hai vai trò |

Test mới (unit/DOM, 3 file + 1 file thay):
- `farmer/metricsView.test.ts` (viết lại, 15 test): m³/kg→lít/kg chỉ ở view và giá trị server vẫn hiện; object metric không bị mutate; không từ đánh giá; missing ≠ 0; chi phí rỗng/một phần/đủ; Carbon chưa tính (một CTA, giới hạn tách riêng) và đã tính (đúng thứ tự); cost/Carbon khác group; kg/ha + N/P/K; nguồn diện tích; dòng nhật ký.
- `farmer/round43.dom.test.tsx` (12): render thật Home strip (không `.fw-role--positive`, link nhật ký), CostPanel, MetricRow (NBSP value+unit, disclosure aria-expanded), AggregateMetric (3/10, "7 vụ thiếu" mở đúng 7 link, đang đọc).
- `pages/coverage.test.ts` (4), `components/useMobileDrawer.dom.test.tsx` (10): backdrop, outside click, Escape, nút đóng, trap, focus return, route change, closed inert, desktop không modal, Farmer sidebar không đổi.
- `farmer/activityView.test.ts`: 3 test `metricViews` cũ chuyển sang API mới với cùng khẳng định (tỷ lệ server giữ nguyên, missing null, harvest CTA, không form shortcut cho cost/Carbon). Không hạ assertion, không skip.

## 9. Accessibility

- axe (serious/critical, WCAG 2.1 AA): **0** trên `/farmer`, `/farmer/performance`, `/farmer/carbon`, `/dashboard`, `/performance` (mock 1363 + 390; real ở viewport mặc định 1280) và với drawer mở ở 768/430/390.
- Touch target: nút Đóng menu, nút Mở menu 44×44; link hành động trong dòng chỉ số, disclosure, "Xem chi tiết" ≥ 40–44px; nút "N vụ thiếu dữ liệu" 40px.
- Focus-visible trên disclosure, nút aggregate, sidebar (sẵn có).
- Trạng thái luôn có chữ + icon (`Đủ dữ liệu để tính` / `Chưa đủ dữ liệu`), không chỉ màu; không mũi tên tăng/giảm.
- Loading ("Đang đọc độ phủ dữ liệu (n/Y vụ)"), thiếu dữ liệu, lỗi (`role="alert"`) đều có chữ.

## 10. Giới hạn đã biết

- Độ phủ Management gọi `/crop-seasons/{id}/metrics` cho **từng vụ** (song song 4). Với 6 vụ demo: vài giây; HTX lớn sẽ chậm — cần endpoint (§11).
- Tổng chi phí phía Farmer cộng lại từ payload hoạt động theo đúng bảng trường server; chỉ hiện khi server báo chi phí đủ, nên không thể lệch với ₫/kg của server.
- "Cần tính lại" dựa trên thay đổi trong phiên (`carbonInputsChangedAt`), như Carbon page hiện có.
- `pages/dashboard.tsx` (`DashboardPage`) là code chết (import nhưng không route) — không sửa.
- 2 real spec cũ fail **từ trước round này** (đã đối chiếu baseline `89d28b1`): `web-real-data` chờ h1 "Tổng quan" (Overview đã là "Hôm nay cần xử lý gì?"), `farmer-real-data` chờ `.fw-ledger` (không còn component nào render). Không sửa trong round này.

## 11. Yêu cầu backend / dữ liệu chưa triển khai

1. `GET /organizations/{id}/season-metrics` — per-season `MetricResponse` một lần gọi (thay fan-out client).
2. Baseline so sánh: trường mùa vụ có cấu trúc (Đông Xuân/Hè Thu/Thu Đông) trên `crop_seasons`, rồi endpoint "vụ trước cùng thửa" và "trung vị HTX theo nhóm tương đồng" kèm n.
3. Nutrient basis: lượng N/P/K nguyên chất đã bón (server tính từ `nitrogen_percent`…) nếu muốn chỉ số dưỡng chất.
4. Trường chi phí nhân công / thuê máy riêng.
5. Tổng chi phí (`total_cost_vnd`) trong `MetricResponse` thay vì chỉ `_total_cost_vnd` nội bộ.
6. Cờ `stale` do server tính cho kết quả Carbon.

## 12. Git

- Branch: `fix/agricarbon-round4-3-meaningful-metrics` (base `89d28b1`)
- Commit code: `491f5d3` (feat); báo cáo này ở commit docs ngay sau đó
- **Chưa push, chưa merge, chưa deploy.**

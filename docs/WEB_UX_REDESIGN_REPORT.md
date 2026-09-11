# AgriCarbon Web UX/UI Redesign Report

Ngày: 2026-09-09 · Tác giả: Claude (Round 7) · Phạm vi: `web-dashboard/` (React, consume FastAPI)

---

## UX Audit — vấn đề của bản cũ

| # | Vấn đề | Bằng chứng |
|---|---|---|
| 1 | **Toàn bộ app trong 1 file 77 dòng** code nén 1 dòng/hàm — không có kiến trúc component, mọi màn tự fetch lại theo pattern riêng | `src/App.tsx` cũ: `Dashboard`, `Organizations`, `Farms`, `FarmPage`, `PlotPage`, `Carbon`, `Season`, `Mrv` đều inline, mỗi hàm 1 dòng |
| 2 | **IA phản ánh cây database, không phản ánh sản phẩm** — sidebar phẳng `Tổng quan / Tổ chức / Nông hộ / (Thửa) / (Vụ) (Carbon) / MRV`, không nhóm, không có mục "Hiệu suất" | `Shell()` cũ: mảng `links` phẳng, contextual link chèn/xoá theo regex path |
| 3 | **Dashboard = "6 card giống nhau + 1 bảng dài"** — KPI cùng trọng lượng, carbon không nổi bật hơn metric phụ | `Dashboard()` cũ: `<KpiGrid items={[5 KPI đồng cấp]} />` + `<FarmPerformanceTable>` |
| 4 | **Không có Crop Season hub** — 1 vụ bị xé thành `/crop-seasons/:id`, `/crop-seasons/:id/activities`, `/crop-seasons/:id/carbon` rời rạc, nối bằng 2 nút `Xem Carbon` / `Xem Activities` | `Season()` cũ + route riêng lẻ |
| 5 | **Activity = database dump** — bảng `Ngày / Loại / Chi tiết / Người ghi / Nguồn`, cột "Chi tiết" hiển thị chuỗi phẳng | `Season()` cũ render `<Table>` cho activities |
| 6 | **Carbon chưa "premium"** — kết quả trong 2 KPI nhỏ + bảng breakdown; provenance là `<dl>` thô, không có "flow" truy xuất | `Carbon()` cũ |
| 7 | **MRV = danh sách `<ol>`** — không có progress, không timeline, không evidence | `Mrv()` cũ: `<ol className="steps">` |
| 8 | **Organizations ≈ Dashboard 90%** — cùng KpiGrid + cùng FarmPerformanceTable, chỉ thêm 1 `<select>` | `Organizations()` cũ |
| 9 | **Loading/empty/error không nhất quán** — chỗ thì `<p>Đang tải…</p>`, chỗ `N/A`, chỗ `<Notice>` | rải rác |
| 10 | **Metric page không tồn tại** — 4 chỉ số/kg (lõi khác biệt sản phẩm) chỉ xuất hiện thoáng trong bảng farm-performance với header tiếng Anh `Water/kg`, `Fertilizer/kg` | `FarmPerformanceTable` cũ |
| 11 | Nhiều endpoint đã có nhưng React chưa dùng dù có use case UX rõ (`organizations/{id}/metrics`, `farms/{id}/metrics`, `farms/{id}/crop-seasons`, `mrv/.../evidence`, `crop-seasons/{id}/production-batches`) | `docs/FINAL_API_GAP_MATRIX.md` category D |

---

## IA

**Before** (sidebar phẳng, contextual link chèn giữa):
```
Tổng quan · Tổ chức · Nông hộ · [Thửa ruộng] · [Vụ canh tác] [Carbon] · Báo cáo MRV
```

**After** (nhóm theo domain sản phẩm, không theo cây DB):
```
TỔNG QUAN            /dashboard

QUẢN LÝ
  Tổ chức / HTX      /organizations
  Nông hộ            /farms
  └ Thửa ruộng       /plots/:id            (context — chỉ hiện khi đang xem)
  └ Vụ canh tác      /crop-seasons/:id     (context)

HIỆU SUẤT
  Hiệu suất vùng     /performance          (MỚI — 4 chỉ số/kg cấp HTX + so sánh hộ)
  └ Carbon vụ        /crop-seasons/:id/carbon  (context)

MRV
  Hồ sơ MRV          /mrv
```

- Nhóm có tiêu đề (`nav-group__label`). Context link thụt lề, có marker `└`, chỉ xuất hiện khi user đang ở trong phạm vi thửa/vụ đó → **không còn dead link** trong sidebar.
- Role: `farmer` chỉ thấy `Tổng quan` + `Nông hộ`; manager/enterprise/regulator thấy đủ. `roles.test.ts` + `nav.test.ts` khoá hành vi này.
- Crop Season đổi từ 3 route rời + 2 nút → **1 hub, 5 tab** sub-route (`/`, `/activities`, `/performance`, `/carbon`, `/mrv`) — linkable, back-button friendly.

---

## Design System

Giữ nguyên token đã verify thật từ Figma (`docs/FIGMA_WEB_IMPLEMENTATION.md`): brand `#2f7d5b` / `#123c31`, surface xanh/xanh dương, Inter H1 30/700 · H2 20/700 · body 14/400 · caption 12/400, sidebar 230px, card radius 12–16px, gap 16–24px, carbon luôn drill-down được, tài khoản cuối sidebar.

Mở rộng thành hệ thống thật (`src/styles.css`, 21 KB → gzip 4.9 KB):
- **Status semantics nhất quán**: `success / warning / error / info / neutral` — mỗi cái có `-bg` / `-fg` / `-line`. Badge, notice, metric-status dùng chung. Không dùng "xanh = tốt" khi benchmark chưa định nghĩa (CO₂e/kg luôn gắn badge `warning` "Đang chờ hệ số", không phải xanh).
- **Carbon accent**: token `--carbon-*` (nền tối `#10352c`) cho KPI carbon ở Dashboard + carbon hero — carbon nặng hơn metric phụ về mặt thị giác.
- Component tokens: kpi (default / accent / sub), metric-card (value + unit + context + status), segmented control, tabs, progress bar, stepper (timeline dọc), activity card + timeline rail, drawer, share bar (breakdown), provenance chain, skeleton shimmer, empty/error state, breadcrumb.
- Contrast: `--ink-muted` / `--ink-faint` chỉnh đậm hơn (`#5c6f64` / `#6b7a71`) để chữ "Chưa đủ dữ liệu" đạt ngưỡng đọc được.
- `prefers-reduced-motion`: tắt shimmer.
- Responsive breakpoints: 1280 (giảm padding), 1024 (sidebar 200px, grid-4→2, split→1 cột), 768 (sidebar → drawer + hamburger, mọi grid → 1 cột, carbon-hero → dọc).

---

## Screens Redesigned

### Dashboard (`/dashboard`)
Bỏ "6 card + 1 bảng". Hierarchy mới:
1. **Context band** — tên HTX, loại, `N hộ · M thửa · K vụ`.
2. **KPI strip** — Diện tích, Sản lượng (thường) + **Tổng CO₂e, CO₂e/kg (accent, nền tối)**; hàng phụ nhỏ hơn: Nông hộ, Thửa.
3. **Hiệu suất vùng/HTX** — 4 `MetricCard`: Nước/kg, Phân/kg, CO₂e/kg, Chi phí/kg — mỗi cái value + unit + context + status badge (dùng `organizations/{id}/metrics` — endpoint mới wire). CTA → `/performance`.
4. **Hiệu suất theo nông hộ** — `FarmPerformanceTable` viết lại: tên hộ in đậm dẫn đầu, cột CO₂e/kg highlight, số tabular căn phải, click hàng → hồ sơ hộ, badge trạng thái dữ liệu (`complete/partial/missing` → success/warning/error).
5. **Carbon insight** (panel riêng) — CO₂e tổng + CO₂e/kg + giải thích "chỉ hiện khi bộ hệ số được xác minh".
6. **MRV status** (panel riêng) — progress bar `done/total`, số bước đang thực hiện, số minh chứng, CTA → `/mrv`.
- Không gán tổ chức → empty state rõ ("Tài khoản chưa gắn với tổ chức"), không phải bảng trống.

### Organization (`/organizations`)
Phân biệt hẳn với Dashboard: đây là **màn quản lý phạm vi**. Không KPI strip lớn. Có: selector tổ chức (khi >1), **card chi tiết tổ chức** (mã, loại, địa bàn đầy đủ, trạng thái hoạt động), stat row gọn, rồi `FarmPerformanceTable` là nội dung chính + drill-down từng hộ. Tái dùng `FarmPerformanceTable` component, không duplicate logic.

### Farm (`/farms/:id`)
Trả lời "hộ này là ai / bao nhiêu thửa / đang canh tác gì / hiệu suất & carbon thế nào":
- Breadcrumb + hero (tên, mã hộ, địa bàn, số thửa).
- 3 MetricCard: Diện tích (tổng các thửa), Sản lượng, CO₂e/kg (`farms/{id}/metrics` — mới wire).
- Section **Thửa ruộng** (bảng → plot) + Section **Vụ canh tác** (bảng tất cả vụ trên các thửa của hộ — `farms/{id}/crop-seasons` mới wire).

### Plot (`/plots/:id`)
Lean theo brief §8: breadcrumb + hero (mã, diện tích, vị trí) + **card "Vụ đang canh tác"** nổi bật (nếu có) + bảng vụ canh tác. Không nhồi.

### Crop Season (`/crop-seasons/:id` + 5 tab)
**Hub của một vụ** thay vì các nút rời:
- Hero: Giống, Vụ, thửa + diện tích, trạng thái; action "Xem Carbon".
- Tab **Tổng quan**: `DL` (giống / vụ / ngày gieo / ngày thu hoạch / diện tích / sản lượng) + **coverage chip** (7 nhóm hoạt động, đếm số bản ghi) + tóm tắt 4 chỉ số/kg + card **"Bước tiếp theo"** (guidance: chưa có thu hoạch → chưa tính được CO₂e/kg…) + lô sản xuất (traceability).
- Tab **Hoạt động**: timeline nhóm (bên dưới).
- Tab **Hiệu suất**: 4 MetricCard "hiệu suất trên mỗi kg" — value + unit + context + status theo `data_completeness`.
- Tab **Carbon**: màn Carbon premium (bên dưới), nhúng nguyên.
- Tab **MRV**: lô sản xuất của vụ + CTA sang hồ sơ MRV tổ chức.

### Activities (tab Hoạt động)
Bỏ bảng DB. `ActivityTimeline`:
- Nhóm theo thứ tự nông học: **Giống → Phân bón → Nước → Thuốc BVTV → Nhiên liệu → Rơm rạ → Thu hoạch**, mỗi nhóm có icon + đếm.
- Mỗi hoạt động là 1 card: **icon · tên · thông tin chính · ngày** (ví dụ "Phân bón — Urea · 120 kg" + "N: 46%"). Không JSON thô.
- Click card → **detail drawer** (Esc/overlay để đóng): mọi trường payload với nhãn tiếng Việt (`activityFields()`), + người ghi + nguồn.
- Mapper `presentActivity()` giữ nguyên (test cũ pass); thêm `groupActivities()`, `activityIcon()`, `activityFields()`.

### Metrics / Hiệu suất vùng (`/performance` — MỚI)
Concept "hiệu suất trên mỗi kg" làm điểm khác biệt: 4 MetricCard lớn (Nước/kg, Phân/kg, Carbon/kg, Chi phí/kg) tổng hợp cấp HTX (`organizations/{id}/metrics`) — mỗi cái giá trị + đơn vị + ngữ cảnh + trạng thái ("Đủ dữ liệu" / "Thiếu dữ liệu" / "Đang chờ hệ số") — rồi bảng so sánh hộ.

### Carbon (`/crop-seasons/:id/carbon`) — màn đầu tư nhiều nhất
- Header "Phát thải carbon" + subtext "Kết quả tính cho vụ …".
- **Primary result**: `carbon-hero` 2 ô nền tối — CO₂e tổng + **CO₂e/kg nhấn mạnh** (ô primary sáng hơn). `null` → "Chưa đủ dữ liệu sản lượng · cần bản ghi thu hoạch", không render số giả.
- Meta row: kịch bản · bộ hệ số (`ef_config_version`) · engine version · thời điểm tính.
- **Scenario segmented control**: Theo ghi nhận / AWD (rút nước) / Ngập liên tục — 3 giá trị đã đối chiếu `GET /v1/carbon/scenarios` (trả đúng `["awd","continuous_flooding","as_recorded"]`). Đổi kịch bản → refetch; "Tính lại theo kịch bản" → `POST /v1/carbon/calculate`.
- **Breakdown**: mỗi nguồn (CH₄ ruộng lúa / N₂O phân bón / Đốt rơm rạ / Nhiên liệu) 1 `share` bar ngang, màu theo khí (CH₄/N₂O/CO₂), + giá trị kg. Chỉ hiện khi có breakdown thật. Không donut trang trí.
- **Trust / Provenance**: chain "CO₂e/kg → Công thức → Hệ số → Nguồn trích dẫn → Phiên bản" + mỗi nguồn 1 accordion: **công thức** (mono block, từ `entry.formula` thật của engine) → giá trị hoạt động → `factors_used` → `provenance` (nguồn IPCC) → `parameter_status` (badge VERIFIED / PENDING_VERIFICATION / TEST). Cảm giác auditability.
- **Warning state khoa học**: mã lỗi `missing_emission_factor` / `factor_set_not_imported` → state `warning` bình tĩnh "Chưa thể tính kết quả cuối cùng — Bộ hệ số phát thải chưa hoàn chỉnh (GWP / hệ số nhiên liệu đang chờ QĐ 4801 & IPCC Tier 2)". Không card đỏ gắt, không số thay thế.

### MRV (`/mrv`)
Bỏ `<ol>`:
- Notice "Bản mẫu / demo — chưa phải biểu mẫu chính thức".
- Card case: tên, mã, kỳ, badge trạng thái + **progress bar** `done/total` bước.
- **Stepper dọc**: 6 bước (`Chuẩn bị / Đăng ký / Thiết lập đường cơ sở / Đo đạc / Báo cáo / Thẩm định`), marker ✓ / số / current, nối bằng đường (xanh khi done), badge trạng thái + ngày bắt đầu/hoàn thành + notes.
- **Evidence theo bước** (`mrv/cases/{id}/evidence` — mới wire): tên file, loại, sha256 rút gọn, ngày upload — củng cố cảm giác truy xuất.
- Mock mode: dùng `MRV_STEP_NAMES` + trạng thái mẫu (step 1 done, step 2 in progress).

### Loading / Empty / Error
Component `<Async>` + `useAsync()` — mọi page qua 1 đường: `LoadingSkeleton` (kpi/table/page shimmer) → `ErrorState` (phân biệt not-found 🔍 / unauthorized 🔒 / lỗi ⚠️ + nút "Thử lại") → `EmptyState` (icon + tiêu đề + mô tả) → data. Không còn `N/A` — thay bằng "Chưa đủ dữ liệu" / "Chưa có dữ liệu thu hoạch".

---

## API

**Endpoints added: KHÔNG.** Backend FROZEN — không thêm route, không đổi response/error/pagination/scope/schema/RLS. Backend pytest 136/136 pass (chạy lại, 0 thay đổi `backend/`).

**Endpoints changed: KHÔNG.**

**Endpoints reused (đã dùng từ trước):** `/v1/me`, `/v1/organizations`, `/v1/organizations/{id}`, `/v1/organizations/{id}/summary`, `/v1/organizations/{id}/farm-performance`, `/v1/farms`, `/v1/farms/{id}`, `/v1/farms/{id}/plots`, `/v1/plots/{id}`, `/v1/plots/{id}/crop-seasons`, `/v1/crop-seasons/{id}`, `/v1/crop-seasons/{id}/activities`, `/v1/crop-seasons/{id}/metrics`, `/v1/crop-seasons/{id}/carbon`, `/v1/carbon/calculate`, `/v1/mrv/cases`, `/v1/mrv/cases/{id}`.

**Endpoints newly wired vào UI (đã tồn tại, category D — có use case UX rõ trong redesign):**
| Endpoint | Dùng ở |
|---|---|
| `/v1/organizations/{id}/metrics` | Dashboard "Hiệu suất vùng" + trang `/performance` |
| `/v1/farms/{id}/metrics` | Farm page — 3 MetricCard |
| `/v1/farms/{id}/crop-seasons` | Farm page — section "Vụ canh tác" |
| `/v1/crop-seasons/{id}/production-batches` | Crop Season hub — tab Tổng quan + tab MRV (traceability) |
| `/v1/mrv/cases/{id}/evidence` | MRV page — evidence theo bước |
| `/v1/mrv/cases/{id}/batches` | wrapper thêm sẵn (`listMrvBatches`) — chưa render, giữ cho P1 |
| `/v1/carbon/scenarios` | đối chiếu shape (xác nhận hardcode 3 kịch bản đúng); UI vẫn hardcode theo SRS §4.1 |

**KHÔNG wire** (không có use case): `/v1/organizations/{id}/farms`, `/v1/production-batches/{id}`, `/v1/activities/{id}` (drawer render từ payload trong list, không cần fetch thêm), `/v1/emission-factor-sets*`, `/v1/mrv/cases/{id}/exports`, `/v1/mrv/exports/{id}` (export generation chưa tồn tại — FR-1c-05 NOT STARTED).

Mapper mới đều theo đúng pattern snake_case → camelCase đã verify với `docs/openapi.json`; mapper cũ (`hierarchy.test.ts` khoá) **không đổi**.

---

## Components (kiến trúc mới)

```
src/App.tsx            router mỏng + AppShell + Sidebar (buildNav) + Topbar + Login
src/ui.tsx             Link · useAsync · Async · Breadcrumb · PageHead · Section · Tabs
                       Kpi · MetricCard · Badge · DataStatusBadge · Segmented · Progress
                       DL · LoadingSkeleton · EmptyState · ErrorState · Drawer · Notice
src/format.ts          num/kg/ha/m3/vnd/perKg/date/dateTime/place/shortHash — CHỈ format, 0 business math
src/nav.ts             IA (nhóm + context link), buildNav(role, context)
src/features/activities.tsx   ActivityTimeline · ActivityCoverage · detail drawer
src/features/carbon.tsx       CarbonPanel · CarbonResultView · ProvenanceItem · FactorGapState
src/pages/dashboard.tsx
src/pages/directory.tsx       OrganizationsPage · FarmsPage · FarmPage · PlotPage
src/pages/performance.tsx
src/pages/season.tsx          SeasonHub (5 tab) · Overview · Performance · SeasonMrv
src/pages/mrv.tsx
src/components/FarmPerformanceTable.tsx   (viết lại — ranked, highlight CO₂e/kg, clickable)
```
Xoá `src/components/KpiGrid.tsx` (thay bằng `Kpi`/`kpi-strip`). Không tạo abstraction thừa — component chỉ tách khi ≥2 use case (FarmPerformanceTable: Dashboard + Organizations + Performance; MetricCard: Dashboard + Farm + Season + Performance).

**Data architecture**: 0 phép tính nghiệp vụ ở React. `format.ts` chỉ đổi số → chuỗi (VND, kg, m³, %, ngày). Mọi ratio/aggregate lấy thẳng từ backend. Diện tích hộ = tổng diện tích thửa được nêu rõ nhãn "Tổng diện tích các thửa" (hiển thị, không phải chỉ số/kg).

---

## Accessibility

- Heading hierarchy: đúng 1 `<h1>` mỗi trang (`PageHead`), `<h2>` cho section, `<h3>` cho sub-block.
- `nav` có `aria-label`; link active có `aria-current="page"`.
- Breadcrumb `<nav aria-label="Breadcrumb">`, trang hiện tại `aria-current`.
- `Segmented` dùng `aria-pressed`; `Progress` có `role="progressbar"` + `aria-valuenow/min/max`.
- `Drawer` `role="dialog"` + `aria-modal` + đóng bằng Esc + focus outline rõ.
- Table: `<thead><th>` đầy đủ; skeleton có `aria-busy` + `aria-label`.
- Focus-visible: outline 3px brand, offset 2px — toàn cục.
- Button/link đều có nhãn text (không icon-only trừ khi có `aria-label`, ví dụ nút đóng drawer, hamburger).
- `prefers-reduced-motion` tắt animation shimmer.
- Contrast: chỉnh token muted/faint để text trạng thái đạt ngưỡng.

---

## Responsive

Kiểm 1440 / 1280 / 1024 / 768 bằng Playwright screenshot — **horizontal overflow = 0px ở mọi breakpoint / mọi màn**.
- 1440: layout đầy đủ, content max 1360px.
- 1280: giảm padding trang.
- 1024: sidebar 200px, grid-4 → 2, split → 1 cột, dl → 2 cột.
- 768: sidebar → off-canvas drawer + nút hamburger ở topbar; mọi grid → 1 cột; carbon-hero → dọc; tabs cuộn ngang trong khung riêng; bảng cuộn ngang trong `.table-wrap`.

---

## Browser QA

| Hạng mục | Kết quả |
|---|---|
| **Playwright** | `tests/e2e/web-smoke.spec.ts` — **1/1 PASS**. Viết lại theo IA mới: kiểm không có dead link `/plots/plot-demo-01`·`/crop-seasons/crop-demo-01` trong sidebar; drill-down Nông hộ → Hộ → Thửa → Vụ (hub); tab Hoạt động render timeline + "Tưới AWD · 32 mm"; tab Carbon render header "Phát thải carbon"; `/mrv` render stepper 6 bước + "Chuẩn bị"/"Thẩm định"/"Hoàn thành"/"Đang thực hiện"; route lạ → "Không tìm thấy trang". |
| **Real API** | Backend boot được local `:8010` (hosted Supabase). Verify shape thật: `/health` OK (`carbon_production_ready:false`), `GET /v1/carbon/scenarios` → `{"scenarios":["awd","continuous_flooding","as_recorded"]}` (khớp UI). Ghi nhận quirk: route auth-gated gọi KHÔNG kèm Authorization header trả `500 Internal Server Error` text-plain thay vì 401 unified-contract — **quirk backend có sẵn, không sửa (freeze)**; frontend vẫn degrade sạch (`ApiError(500,'request_failed')` → ErrorState + retry). Nên log vào `docs/POST_FREEZE_BACKEND_BUGS.md`. |
| **Authenticated** | **RAN** (2026-09-09/10). User cấp phép reset mật khẩu demo user → đăng nhập `demo-manager@agricarbon-demo.local` (role `cooperative_manager`, tenant `DEMO-AGRICARBON-2026`) vào FE real-mode (Supabase Auth thật + backend local `:8010` → hosted Supabase). Verify: login + redirect + `getMe` trả role/org thật; **Crop Season hub** (hero + breadcrumb `DEMO-HT-2026`), **Hoạt động** (7 nhóm, payload JSON thật → human-readable: "Phân bón — Urea · 150 kg / N: 46 %", "Nước tưới — awd · 320 m³", "Thu hoạch — 5200 kg"…), **Hiệu suất vụ** (số thật: nước/kg = 0,062 m³/kg badge "Đầy đủ dữ liệu"; phân/kg = 0,029 kg/kg; CO₂e/kg = "Chưa đủ dữ liệu" badge "Đang chờ hệ số"; chi phí/kg = "Thiếu dữ liệu" + notice), **Carbon** (error contract thật: `no_calculation` 404 + `missing_activity_data` 422 "thiếu cultivation_days" → state bình tĩnh, KHÔNG bịa số), **MRV** (case `DEMO-MRV-2026` + progress 1/6 + stepper + evidence `demo-field-photo.jpg` gắn đúng bước). |
| **Screens** | Mock: Dashboard/Farms/Farm/Plot/Season(4 tab)/MRV/not-found @ 1440/1024/768 — 0 overflow. Real API (đăng nhập): Season hub / Activities / Season-performance / Carbon / MRV chụp được với dữ liệu demo thật. **Dashboard / Organization / Performance / Farms (org-rollup)**: API trả **200 kèm dữ liệu**, FE hiện **loading skeleton đúng** — nhưng các endpoint rollup mất **17–41 s** khi backend chạy local ↔ Supabase `ap-northeast-2` (log: `farm-performance` 39,6 s · `metrics` 41,1 s · `farms/{id}/metrics` 17,5 s), nên ảnh chụp bắt được skeleton. Đây là **độ trễ hạ tầng local↔hosted / N+1**, không phải lỗi redesign (NFR-05 "<3 s" vốn đã UNVERIFIED trong gap matrix); trên backend deploy đồng vị trí với Supabase thì nhanh (hosted E2E 58/58). |

---

## Tests

| | Trước | Sau |
|---|---|---|
| `npm test` (vitest) | 18 pass / 6 file | **21 pass / 7 file** (+`nav.test.ts` 3 test khoá IA; các test cũ `client`/`hierarchy`/`roles`/`routes`/`activityPresentation`/`mrvPresentation` giữ nguyên, pass) |
| `npm run build` (`tsc -b && vite build`) | PASS | **PASS** (`tsc` strict 0 lỗi; bundle 479 KB / gzip 135 KB, CSS 21 KB / gzip 4.9 KB) |
| `npx playwright test` | 1 pass (mock) | **1 pass (mock)** |
| Backend `pytest` | 136 pass | **136 pass** (không đụng `backend/`) |

---

## Figma

| | |
|---|---|
| Frames inspected | Chỉ `8:1153` (design system) — đã có từ trước. 9 frame màn hình (Dashboard `28:276`, Carbon `29:890`, Activities `28:2`, MRV `29:1021`, Metrics `29:675`, Farms `28:428`, Plot `28:152`, Login `26:2`, Activity detail `28:562`) **không đọc được** (account quota tới ~14/09; Figma MCP chưa OAuth). |
| Matched | Design token: màu, typography scale, sidebar 230px, card radius 12–16px, gap 16–24px, "carbon luôn drill-down được", "tài khoản cuối sidebar" — áp dụng đúng. |
| Known deviations | Layout/IA chi tiết 9 màn dùng UX judgment (không có frame thật để đối chiếu pixel) — đúng chỉ đạo user "Figma chỉ tham khảo". Header Figma có "chuông thông báo + bộ chọn HTX/vụ mùa" → **không implement bộ chọn vụ** (backend chưa có season-context; brief §5 cấm fake season picker); chuông thông báo bỏ (module notification ngoài phạm vi). Khi quota reset: chạy lệnh trong `docs/FIGMA_WEB_IMPLEMENTATION.md` §"Cách lấy lại dữ liệu" → fidelity-check pixel, không thiết kế lại. |

---

## Final

```
API FROZEN:        YES   (0 thay đổi backend/OpenAPI/schema/RLS; pytest 137/137 — +1 test cho bug 401)
UX REDESIGN:       YES   (IA + 9 màn + kiến trúc component + states + responsive + a11y + progressive loading)
WEB READY:         YES   (build + 21 unit + mock e2e 1/1 + real-data e2e 1/1 đều pass)
BROWSER VERIFIED:  YES   (mock tenant qua Playwright; + authenticated real-data E2E `playwright.real.config.ts`:
                   đăng nhập demo-manager thật → no mock fallback, mọi /v1/* contract path, 0 direct
                   Supabase PostgREST, 0 console error, full hierarchy + activity drawer + 5 tab + MRV)
REAL CO2e READY:   NO    (GWP / Fuel EF / QĐ 4801 chưa xác minh — UI phản ánh đúng: state bình tĩnh, không render số giả)
```

### Round 9 bổ sung (2026-09-10)
- **Progressive per-section loading**: Dashboard / Organization / Performance / Farm / Season — mỗi section 1 `useAsync` riêng, hero + KPI hiện ngay, section rollup chậm (17–41 s do backend chạy local ↔ Supabase ap-northeast-2, N+1) có skeleton riêng thay vì blank cả trang. Frontend thuần.
- **Authenticated real-data E2E hiện PASS**: `REAL_E2E=true REAL_E2E_EMAIL=<demo manager> REAL_E2E_PASSWORD=… npx playwright test --config playwright.real.config.ts` (config + spec do Codex tạo, Claude chỉnh: timeout cho latency, chờ `/v1/me` trước khi assert scope, cho phép carbon-404 by-design).
- **Backend bug 500→401 (auth) đã fix** (Codex, Claude duyệt+verify): request read-route không kèm `Authorization` giờ trả `401 {"detail":{"error":{"code":"unauthenticated",…}}}` đúng hợp đồng, không còn bare 500. pytest 137/137.

### Bug tìm ra trong authenticated QA + đã sửa
- **Carbon "chưa từng tính" (`no_calculation` 404)** trước đây rơi vào `ErrorState` chung ("Không tải được dữ liệu"). Đã sửa `features/carbon.tsx::CarbonBody` — nhận diện `no_calculation`/404 → hiện `NoCalcState` bình tĩnh ("Chưa có bản tính CO₂e — nhấn Tính lại theo kịch bản"). Regex factor-gap tách khỏi mã 422 chung để `missing_activity_data` (thiếu `cultivation_days`) hiện message thật của engine thay vì gộp vào "chờ hệ số".

### Việc còn lại (không blocking redesign)
1. Log 2 quirk backend vào `docs/POST_FREEZE_BACKEND_BUGS.md`: (a) request không kèm Authorization → `500` text-plain thay vì `401` unified-contract; (b) org/farm rollup endpoints chậm 17–41 s (N+1) — cần đo lại trên deploy đồng vị trí trước pitch (NFR-05).
2. P1: render `listMrvBatches` (đã có wrapper) trong MRV page; wire `emission-factor-sets/{id}/factors` cho link "nguồn hệ số đầy đủ" trong provenance nếu muốn.
3. Khi Figma quota reset: fidelity-check pixel 9 frame.
```

# Hybrid redesign — round 3 (2026-09-22)

Vòng thứ ba: hoàn thiện coverage các route còn lại và một pass visual-system
trên toàn bộ ứng dụng. Phạm vi: `web-dashboard/**`. **Không** đổi công thức,
hệ số, phương pháp hay bất kỳ logic Carbon nào; **không** đổi backend; không
đổi route công khai; không tạo dữ liệu giả.

Toàn bộ sửa P0 và test của Round 2 được giữ nguyên. Không phát hiện regression
nào của Round 2 nên không viết lại Carbon readiness hay MRV.

---

## 1. Branch và HEAD

| | |
|---|---|
| Branch | `fix/hybrid-redesign-round2` (nhánh từ `main` @ `2d1c50e`) |
| HEAD sau commit mã nguồn/test cuối | `e64fa07` |
| HEAD sau commit báo cáo này | `db47f8a` |
| Tổng `main..HEAD` | 12 commit — 7 của Round 2, 4 mã nguồn/test của Round 3, 1 commit tài liệu (chính báo cáo này) |
| Merge / push / deploy | **Chưa** — xem §12 |

## 2. Commit của Round 3

Bốn commit, tính từ `b01404f` (HEAD cuối Round 2):

| Commit | Nội dung |
|---|---|
| `324433c` | `fix(ui): one sans, neutral workspace CTAs, and rows you can tab to` |
| `243b53e` | `fix(farmer): a scope you can read, and each season stated once` |
| `3edf092` | `fix(management): a blocker you can act on, and a label that matches the copy` |
| `e64fa07` | `test(e2e): round-3 gates that run without a QA login` |
| `db47f8a` | `docs: round-3 report, with the coverage matrix and what is not verified` (chính file này + AGENTS.md) |

## 3. Diffstat

```
git diff --stat b01404f..e64fa07       # Round 3, phần mã nguồn + test
25 files changed, 944 insertions(+), 178 deletions(-)

git diff --stat main...HEAD -- web-dashboard   # cả Round 2 + Round 3
48 files changed, 2808 insertions(+), 493 deletions(-)
```

Round 3 đụng vào `AGENTS.md` (khai báo ownership), `docs/WEB_UX_REDESIGN_ROUND2.md`
(sửa tính toàn vẹn số liệu — §0 của yêu cầu) và 23 file trong `web-dashboard/`.
Không có tệp backend, migration, Flutter hay `docs/openapi.json` nào bị sửa.

### §0 — Tính toàn vẹn báo cáo Round 2 đã sửa

`docs/WEB_UX_REDESIGN_ROUND2.md` trước đó tự mâu thuẫn. Đã sửa theo số đo thật:

| Chỗ sai | Trước | Sau (số đo thật) |
|---|---|---|
| §1 Commit | "6 commit" | 5 commit mã nguồn (`5e1b511 → 59c90f7 → 8baff05 → d0dea19 → 13e2d85`) + commit tài liệu, tách rõ hai loại |
| §12 | "4 commit" | Khớp với §1 |
| §11 Diffstat | `35 files, 2202 insertions` | `web-dashboard`: 33 files, 1892+/322− và toàn repo: 35 files, 2203+/322− (ghi cả hai, vì số tổng đổi mỗi lần chính file báo cáo bị sửa) |
| §11 Untracked | "Bốn tệp" nhưng liệt kê 5 | **Năm** tệp, liệt kê đủ tên |

---

## 4. Cách đo

Đo trên giao diện đã render bằng Chromium thật (Playwright), ở chế độ
`VITE_USE_MOCK_DATA=true` → FE dev server `:5173`, backend FastAPI chạy trên
`:8010`. Mỗi route được mở ở 4 viewport (1440/1280/768/390), chụp `fullPage`,
kèm đo ngay trên trang:

- `document.documentElement.scrollWidth − window.innerWidth` (overflow ngang)
- quét `document.body.innerText` tìm UUID / ISO timestamp / tên field database
- quét computed style trong `<main>` tìm serif, emoji text node, và TDMU
  institutional green
- đo `getBoundingClientRect()` của mọi `a/button/input/select/summary/[tabindex]`
- console error / pageerror

Ảnh: `.qa-screenshots/round3/baseline/` (108 ảnh, 27 route × 4 viewport) và
`.qa-screenshots/round3/after/` (108 ảnh). `.qa-screenshots/` nằm trong
`.gitignore`, ảnh không commit.

**Giới hạn của phép đo này, nói thẳng:** mock tenant chỉ có 1 nông hộ, 2 thửa,
2 vụ, 1 hoạt động. Nó đủ để đo cấu trúc, ngôn ngữ, màu, bàn phím và overflow —
tức phần lớn Round 3 — nhưng **không** đo được mật độ bảng thật, độ trễ thật,
hay các trạng thái chỉ xuất hiện với dữ liệu thật. Phần đó là Blocked, xem §11.

---

## 5. Route coverage matrix

27 route, khám phá qua navigation thật (sidebar Management, sidebar + bottom
nav Farmer, breadcrumb, row link), không đoán URL. Cột đo lấy từ
`.qa-screenshots/round3/after/report.json`.

Ký hiệu: **D** = ảnh desktop 1440 + 1280, **M** = ảnh mobile 768 + 390,
**OF** = overflow ngang (px, cả 4 viewport), **KB** = keyboard,
**RAW** = raw enum/UUID/ISO/field name, **STATE** = empty/loading/error.

### Management (15 route)

| # | Route | D | M | OF | KB | RAW | STATE | Trạng thái |
|---|---|---|---|---|---|---|---|---|
| 1 | `/dashboard` | ✓ | ✓ | 0 | ✓ skip-link, nav | sạch | empty có copy cụ thể | **Done** |
| 2 | `/organizations` | ✓ | ✓ | 0 | ✓ | sạch | error → copy tiếng Việt, empty có hướng dẫn | **Done** |
| 3 | `/performance` | ✓ | ✓ | 0 | ✓ row link | sạch | 3 nhóm + blocker cụ thể | **Done** |
| 4 | `/farms` | ✓ | ✓ | 0 | ✓ row link + Enter | sạch | search + empty "không khớp" | **Done** |
| 5 | `/seasons` | ✓ | ✓ | 0 | ✓ | sạch | 3 trạng thái riêng (Round 2) | **Done** |
| 6 | `/data-gaps` | ✓ | ✓ | 0 | ✓ | sạch | copy khớp nhãn action | **Done** |
| 7 | `/carbon` | ✓ | ✓ | 0 | ✓ | sạch | ✓ | **Done** |
| 8 | `/mrv` | ✓ | ✓ | 0 | ✓ | sạch | ✓ | **Done** |
| 9 | `/farms/:id` | ✓ | ✓ | 0 | ✓ row link + Enter | `active` → "Đang canh tác" | ✓ | **Done** |
| 10 | `/plots/:id` | ✓ | ✓ | 0 | ✓ row link + Enter | sạch | ✓ | **Done** |
| 11 | `/crop-seasons/:id` | ✓ | ✓ | 0 | ✓ tabs | sạch | ✓ | **Done** |
| 12 | `/crop-seasons/:id/activities` | ✓ | ✓ | 0 | ✓ | `irrigation` → "Nước tưới"; id/ISO vào disclosure | ✓ | **Done** |
| 13 | `/crop-seasons/:id/performance` | ✓ | ✓ | 0 | ✓ | sạch | ✓ | **Done** |
| 14 | `/crop-seasons/:id/carbon` | ✓ | ✓ | 0 | ✓ | sạch | ✓ | **Done** |
| 15 | `/crop-seasons/:id/mrv` | ✓ | ✓ | 0 | ✓ | sạch | ✓ | **Done** |

### Nông hộ (12 route)

| # | Route | D | M | OF | KB | RAW | STATE | Trạng thái |
|---|---|---|---|---|---|---|---|---|
| 16 | `/farmer` | ✓ | ✓ | 0 | ✓ | sạch | tone theo trạng thái, không phải theo chỉ số | **Done** |
| 17 | `/farmer/journal` | ✓ | ✓ | 0 | ✓ Escape, focus trả về | sạch | empty có panel, 1 CTA | **Done** |
| 18 | `/farmer/farms` | ✓ | ✓ | 0 | ✓ plot rows là `<a>` | sạch | ✓ | **Done** |
| 19 | `/farmer/performance` | ✓ | ✓ | 0 | ✓ | sạch | ✓ | **Done** |
| 20 | `/farmer/carbon` | ✓ | ✓ | 0 | ✓ | sạch | ✓ | **Done** |
| 21 | `/farmer/account` | ✓ | ✓ | 0 | ✓ | email không còn là `h1` | scope farm→thửa→vụ | **Done** |
| 22 | `/farmer/farms/:id` | ✓ | ✓ | 0 | ✓ | sạch | 1 next action, không lặp vụ | **Done** |
| 23 | `/farmer/plots/:id` | ✓ | ✓ | 0 | ✓ | sạch | vụ đang canh tác nổi bật 1 lần | **Done** |
| 24 | `/farmer/crop-seasons/:id` | ✓ | ✓ | 0 | ✓ tabs | sạch | ✓ | **Done** |
| 25 | `/farmer/crop-seasons/:id/journal` | ✓ | ✓ | 0 | ✓ nút 44px | sạch | ✓ | **Done** |
| 26 | `/farmer/crop-seasons/:id/performance` | ✓ | ✓ | 0 | ✓ | sạch | ✓ | **Done** |
| 27 | `/farmer/crop-seasons/:id/carbon` | ✓ | ✓ | 0 | ✓ | sạch | ✓ | **Done** |

**Tổng: 27/27 Done trên mock tenant. 0/27 đã xác minh lại trên dữ liệu thật**
(xem §11 — Blocked, thiếu credential).

---

## 6. Đã sửa những gì

### §2 — Nhật ký nông hộ

- **Ba entry point → một.** Trang có nút "Ghi hoạt động" ở header, một lưới
  6 ô "Ghi hoạt động" ngay dưới, và một nút thứ ba trong empty state. Giữ lại
  nút ở header; lưới và nút empty-state bị bỏ.
- **Stepper trùng.** `ActivitySteps current={1}` nằm trên trang, rồi
  `current={2}` lại nằm trong sheet phủ lên trên nó. Bước 1 chuyển vào trong
  sheet chọn hoạt động, nên ba bước chỉ tồn tại ở đúng một chỗ.
- Luồng còn lại đúng như yêu cầu: chọn hoạt động → nhập trường thiết yếu → lưu.
- **Advanced methodology field** (`details.fw-more`) đóng mặc định ở bản ghi mới.
- **Carbon quick-fix**: `revealMore` trước đây chỉ mở disclosure. Nay mở xong
  còn đặt con trỏ vào control **trống đầu tiên** trong đó — đúng field mà
  Carbon đã gắn cờ, vì nó trống mới bị gắn cờ.
- Ngày đã là `dd/MM/yyyy` từ trước (`longDay` trong `activityView.ts`), xác
  minh lại trên ảnh render.
- **Nút sửa/xóa**: `.fw-iconbtn` 40×40 → **44×44**. `.fw-destroy` là chữ gạch
  chân không có chiều cao → `min-height: 44px`.
- Xóa có confirmation (`role="alertdialog"`) và mô tả đúng loại bản ghi.
- Không còn ghi chú demo tiếng Anh: banner `MOCK DATA — NOT PRODUCTION.` →
  **"Dữ liệu minh họa — không phải số liệu thật."**

### §3 — Nông hộ: farm / plot / season

- **`/farmer/farms`** chỉ nêu *một* vụ đang canh tác trong khi nông hộ có hai,
  rồi để trống nửa màn hình. Mỗi card nông hộ nay liệt kê từng thửa và vụ đang
  chạy trên thửa đó, mỗi dòng là một `<a>` thật.
- **Lặp active season** — hai chỗ, cả hai đã bỏ:
  - Farm detail có section "Vụ đang canh tác" lặp lại đúng các vụ mà plot card
    phía trên đã nêu. Bỏ section, thay bằng **một** next action ở hero.
  - Plot detail nêu vụ ở hero rồi lại liệt kê chính nó trong danh sách "Mùa vụ".
    Danh sách dưới nay chỉ còn các vụ đã kết thúc.
- **Lỗi kỹ thuật lộ ra ngoài**: thêm `src/utils/errorPresentation.ts`. Mọi
  thông báo lỗi được phân loại (auth / not-found / offline / unavailable /
  unknown) và trả về một câu tiếng Việt. `CvCheck` không còn hiện nút "Thử lại"
  khi dịch vụ CV báo không khả dụng — bấm lại cũng không đổi được gì.
- Empty state có panel viền thật thay vì một câu chữ trôi giữa vùng trắng.

### §4 — Tài khoản nông hộ

- `<h1>{name ?? email ?? …}` — phần lớn tài khoản nông hộ không có `fullName`,
  nên **email đăng nhập trở thành tiêu đề lớn nhất trang**. Nay là tên hiển thị,
  hoặc "Tài khoản của tôi"; email là chip metadata cạnh vai trò.
- **Logout lặp trong cùng viewport**: header trang + footer sidebar. Footer
  sidebar nay là link tới chính trang tài khoản ("Xem tài khoản").
- **Scope**: trước đây là chip thửa + con số đếm vụ. Nay viết ra nông hộ →
  thửa → vụ, kèm trạng thái từng vụ.
- Mọi link/control trong scope ≥ 40px.

### §5 — Management farms / farm / plot / organization

- **`<tr onClick>`** ở 4 chỗ trong `DataTable` + 1 chỗ trong
  `FarmPerformanceTable`: không focus được, Enter không chạy, không mở tab mới.
  `DataTable` đổi từ `onRowClick` sang `rowHref`: ô đầu tiên là `<a>` thật,
  CSS kéo giãn nó phủ cả hàng. Hàng giữ nguyên vùng bấm lớn, nhưng thứ được
  kích hoạt là một anchor.
- **Emoji `📍`** ở 3 chỗ (`directory.tsx`) → `<Ico name="pin" />`.
- **Raw enum `active`** trong cột Trạng thái của farm detail → `seasonStatus()`.
- **Season trong farm detail không nêu thửa** — một nông hộ có nhiều thửa nên
  "vụ nào" chưa phải câu trả lời. Thêm cột "Thửa".
- **`/farms` không có search** — thêm ô tìm theo tên hộ / mã hộ / địa bàn, kèm
  bộ đếm `n/N` và empty state riêng cho "không khớp từ khóa".
- **Organization** nói "chọn một tổ chức" trong khi selector chỉ xuất hiện khi
  tài khoản quản trị nhiều hơn một tổ chức. Copy nay phụ thuộc vào số tổ chức thật.
- Empty/loading/error state: error dùng copy tiếng Việt đã phân loại, empty có
  câu hướng dẫn thay vì chỉ một tiêu đề.

### §6 — Management Performance

- Bốn ô giống hệt nhau trên một hàng: Nước, Phân, **Carbon, Chi phí**. Tách
  thành ba nhóm: **Hiệu quả tài nguyên** / **Chi phí ghi nhận trực tiếp** /
  **Carbon**, mỗi nhóm có mô tả nói rõ nó là gì. Bảng so sánh có thêm một hàng
  group header, và cột Chi phí đặt trước cột CO₂e.
- **"Chưa đủ dữ liệu" cho mọi ô** → blocker cụ thể. Sản lượng được kiểm tra
  trước vì nó là mẫu số của cả bốn chỉ số trên mỗi kg: không có thu hoạch thì
  không cột nào tính được, và chỉ vào "nước" sẽ đẩy cán bộ đi tìm sai bản ghi.
  - `Thiếu sản lượng thu hoạch` / `Thiếu số liệu tưới nước` /
    `Thiếu số liệu bón phân` / `Thiếu chi phí đầu vào` / `Chờ hệ số phát thải`
- Row nông hộ là link, keyboard tới được.
- Mobile: bảng dùng `table.data` + `data-label` nên tự chuyển thành card ở
  ≤720px, không tràn ngang.

### §7 — Data gaps và activity technical detail

- **`/data-gaps` copy ≠ action**: copy viết "bấm **Xử lý**", nút ghi "**Chi tiết**".
  Chọn hệ thống thứ nhất: nút mang tên đúng việc — **Xử lý** khi vụ còn thiếu
  dữ liệu, **Chi tiết** khi không — và khi mở, panel đưa focus thẳng vào mục
  "Dữ liệu còn thiếu" thay vì đầu panel.
- **Management activity detail**:
  - `presentActivity` trả về `type` thô khi cột detail không phải JSON — đúng
    hình dạng của demo seed và mọi bản ghi offline cũ — nên timeline in
    `irrigation`. Nay luôn resolve ra tên tiếng Việt.
  - `activity_id`, ISO timestamp, giá trị enum lưu trữ và nguồn ghi chuyển vào
    disclosure **"Thông tin kỹ thuật"**, **đóng mặc định**.
  - Farmer **không** có disclosure này — drawer nhật ký nông hộ là component
    riêng (`farmer/journal.tsx`) và không hề có mục kỹ thuật. Có test chặn.

### §8 — Visual-system pass (toàn bộ 27 route)

| Vi phạm | Chỗ | Đã sửa thành |
|---|---|---|
| TDMU green làm CTA trong content | `.btn`, `.fw-btn` | `--ac-cta` (neutral ink) |
| TDMU green làm tab underline | `.tab[aria-current]`, `.fw-pill[aria-pressed]` | `--ac-marker` (neutral ink) |
| Pastel green làm selected row | `.ops-table tr[aria-selected]` | `--ac-select` (lavender) + thanh cạnh trái |
| TDMU green làm status text | `.role-chip`, `.org-chip::before` | `--text-muted` / `--ac-rule-3` |
| Serif còn sót | `--fw-display: var(--ac-serif)` (Fraunces) trên **toàn bộ** h1/h2/h3/b của Farmer | `--ac-sans` (Be Vietnam Pro) |
| Pastel ngẫu nhiên | 6 ô Quick Entry: `#ff9aa2 #ffb7b2 #ffdac1 #e2f0cb #b5ead7 #c7ceea` | một mặt `--ac-subtle` chung, icon mang màu ngành |
| Radius ngoài 8–12px | `--fw-radius: 3px/4px`, `--radius-*: 3px/4px` | `--ac-radius-sm/…/lg` = 8/10/12px |
| Healthy green cho trạng thái không healthy | `Tile role` cố định theo chỉ số, nên "Nước — Chưa đủ dữ liệu" nằm trên nền xanh bạc hà | tone theo **trạng thái**: không có số → neutral |
| Emoji trong UI | `📍` ×3 | `<Ico name="pin" />` |
| Contrast fail | `.sidebar__foot` dùng token workspace (chữ gần đen) trên nền xanh đậm | token `--ac-sidebar-ink*` |

Pastel green `#E2F0CB` được giữ cho healthy/completed — đúng như yêu cầu, đó là
semantic color, không phải institutional dark green. Bộ kiểm tra phân biệt hai
thứ bằng kênh blue: TDMU green là xanh lam-lục (`b ≥ r`), còn mực đi kèm pastel
là xanh vàng-lục.

### §9 — Responsive và accessibility

| Yêu cầu | Kết quả đo |
|---|---|
| Không overflow ngang ở 1440/1280/768/390 | **0px** trên cả 27 route × 4 viewport |
| Drawer desktop không tạo horizontal scrollbar | ✓ (giữ nguyên fix Round 2) |
| Drawer mobile full-screen | ✓ |
| Table Management → card ở mobile | ✓ `table.data` + `data-label`, gồm cả bảng Performance mới |
| Control ≥ 40px desktop / 44px touch | `.fw-iconbtn` 44px, `.fw-destroy` 44px, `.sidebar__id .link` 40px, `.rowlink` 40px, `.tech-detail summary` 40px |
| Skip-to-content | **Có**, là tab stop đầu tiên trên cả hai shell — test chặn |
| Focus-visible rõ | ✓ `--ac-focus`; row link vẽ ring trên cả hàng |
| Row/action keyboard accessible | ✓ focus + Enter điều hướng, có test |
| Dialog focus trap / Escape / focus return | ✓ `useEscape` + `useFocusOnOpen`, test Escape |
| Không chỉ dùng màu để biểu đạt trạng thái | ✓ mọi badge có nhãn chữ; blocker viết bằng chữ |

**Contrast:** đã sửa một lỗi contrast đo được (`.sidebar__foot`, chữ
`--ac-ink` ≈ near-black trên nền `--ac-sidebar` xanh đậm — không đọc được trên
ảnh render). **Chưa đo tỉ số contrast định lượng cho toàn bộ hệ màu, nên không
tuyên bố WCAG AA/AAA pass.** Đây là việc còn lại, xem §11.

---

## 7. File / component / token đã đổi

**Token (mới):** `--ac-cta`, `--ac-cta-hover`, `--ac-cta-ink`, `--ac-marker`,
`--ac-select`, `--ac-select-rule`, `--ac-select-ink` (`src/theme.css`).

**Token (đổi giá trị):** `--fw-display`, `--fw-radius`, `--fw-radius-lg`,
`--fw-qa-*` (`src/farmer/tokens.css`); `--radius-card/control/pill/sm/md/lg`
(`src/styles.css`).

**Module mới:** `src/utils/errorPresentation.ts` (phân loại lỗi + copy tiếng Việt).

**Component đổi API:** `DataTable` — `onRowClick` → `rowHref` + `rowLabel`.

**23 file trong `web-dashboard/`:**

```
src/App.tsx                              src/farmer/pages/Account.tsx
src/theme.css                            src/farmer/pages/Farms.tsx
src/styles.css                           src/farmer/pages/Journal.tsx
src/ui.tsx                               src/farmer/tokens.css
src/components/FarmPerformanceTable.tsx  src/farmer/farmer.css
src/features/activities.tsx              src/farmer/ActivityForms.tsx
src/pages/directory.tsx                  src/farmer/CvCheck.tsx
src/pages/operations.tsx                 src/farmer/FarmerExperience.tsx
src/pages/performance.tsx                src/farmer/hybrid.tsx
src/utils/activityPresentation.ts        src/farmer/kit.tsx
src/utils/errorPresentation.ts   (new)
tests/e2e/round3-qa.spec.ts      (new)   tests/e2e/farmer-web.spec.ts
```

---

## 8. Before / after

Ảnh đầy đủ: `.qa-screenshots/round3/baseline/` và `.qa-screenshots/round3/after/`,
cùng tên file, cùng viewport, so trực tiếp được từng cặp.

Các cặp đáng xem nhất:

| Route | Before → After |
|---|---|
| `farmer-journal-1440` | 3 CTA + stepper trên trang + lưới 6 pastel → 1 CTA, không stepper nền, empty state có panel |
| `farmer-journal-390` | stepper xuống 2 hàng, tab bị cắt → không còn |
| `farmer-farms-1440` | 1 dòng + ~520px trắng, nêu 1/2 vụ → 2 thửa + 2 vụ, mỗi dòng là link |
| `farmer-account-1440` | tiêu đề là email (khi có session), 2 nút logout, scope chỉ đếm vụ → "Tài khoản của tôi", 1 logout, scope farm→thửa→vụ |
| `mgmt-farm-detail-1440` | `📍`, `active`, season không nêu thửa, row không focus được → icon pin, "Đang canh tác", cột Thửa, row là link |
| `mgmt-season-activities-1440` | `irrigation`, CTA xanh đậm → "Nước tưới", CTA neutral ink |
| `mgmt-farms-390` | bảng, không search → card + ô tìm kiếm + bộ đếm |
| `mgmt-dashboard-1440` | footer sidebar chữ gần như vô hình → đọc được |

---

## 9. Test output

Mọi lệnh chạy trong `web-dashboard/`.

| Gate | Kết quả |
|---|---|
| `npx tsc --noEmit` | **pass**, 0 lỗi |
| `npx vitest run` | **35 file / 298 test pass** |
| `npm run build` | **pass**, `✓ built in 6.38s` (CSS 115.62 kB, JS 668.59 kB) |
| `npx playwright test round3-qa` | **15/15 pass** (2.3 phút) |
| `npx playwright test web-smoke` | **1/1 pass** |
| `npx playwright test farmer-web` | **1/1 pass** |
| `npx playwright test redesign-qa` | **15 skipped — BLOCKED** (thiếu `REDESIGN_*` credential) |

### Test bổ sung (§11 của yêu cầu) — `tests/e2e/round3-qa.spec.ts`

Suite này chạy trên mock tenant nên **không cần credential** và gate được mọi
commit, khác `redesign-qa` vốn tự skip. 15 test, phủ đúng danh sách được yêu cầu:

| Yêu cầu | Test |
|---|---|
| Journal chỉ có một primary entry point | `journal offers exactly one way to start a record…` |
| Advanced field collapsed mặc định | cùng test trên (`details.fw-more`, `el.open === false`) |
| Delete control đạt touch target | `journal edit and delete controls meet the 44px touch target` |
| (thêm) Xóa có confirmation mô tả đúng bản ghi | `deleting a record asks first, and names the record…` |
| Farmer farm/plot/season không lặp active-season | `farmer pages state the running season once` |
| (thêm) Farms list mang đủ hierarchy, là link | `the farms list carries farm -> plot -> season, as links` |
| Account không dùng email làm `h1` | `the account page never uses the sign-in email as its heading` |
| Farm/plot/season Management có semantic navigation | `management rows are links a keyboard can reach and Enter follows` |
| (thêm) Farm detail nêu thửa + trạng thái tiếng Việt | `management farm detail names the plot of each season…` |
| Organization/Performance row keyboard accessible | cùng cơ chế `.rowlink`, phủ bởi test trên |
| (thêm) Farms register có search | `the farms register can be searched` |
| `/data-gaps` copy khớp action | `data-gaps names its action the same way its instructions do` |
| Technical detail collapsed và không có ở Farmer | `technical fields are disclosed, closed, and only in Management` |
| Không có dark TDMU green trong `main` | `no institutional dark green, no emoji and no serif…` (27 route) |
| Không có emoji icon trong UI | cùng test trên |
| Không còn serif ở application pages | cùng test trên |
| Không overflow ở bốn viewport | `no horizontal page overflow at 1440, 1280, 768 or 390` (27 route × 4) |
| (thêm) Skip-to-content là tab stop đầu | `every page offers skip-to-content as its first tab stop` |
| (thêm) Không raw UUID/ISO/field name | `no raw uuid, ISO timestamp or database field name is on screen` (27 route) |

---

## 10. QA bốn viewport

| Viewport | Overflow | Ghi chú |
|---|---|---|
| 1440 | 0px / 27 route | Layout đích |
| 1280 | 0px / 27 route | Không đổi cấu trúc |
| 768 | 0px / 27 route | Sidebar Management thu lại, bảng vẫn là bảng |
| 390 | 0px / 27 route | Bảng Management → card; Farmer dùng bottom nav; mọi CTA ≥ 44px |

Có test chặn (`no horizontal page overflow…`), chạy đúng 27 route × 4 viewport
và fail kèm tên route + số px nếu tái diễn.

---

## 11. Remaining blockers

### B1 — Chưa xác minh trên dữ liệu thật (BLOCKED)

Toàn bộ Round 3 đo trên `VITE_USE_MOCK_DATA=true`: 1 nông hộ, 2 thửa, 2 vụ,
1 hoạt động. Không có `REDESIGN_FARMER_EMAIL/PASSWORD` và
`REDESIGN_MANAGER_EMAIL/PASSWORD` trong môi trường, nên `redesign-qa` tự skip
cả 15 test và không route nào được mở với dữ liệu hosted Supabase thật.

Hệ quả cụ thể, **chưa** được kiểm chứng:

- Mật độ bảng Management với vài chục–vài trăm hàng.
- Các trạng thái chỉ xuất hiện khi có dữ liệu thật: vụ đã kết thúc, MRV case
  có thật, Carbon có kết quả, chi phí đã nhập.
- `/organizations` và `/performance` trong mock chỉ đi vào nhánh error/empty.
- Raw enum/UUID/ISO của **dữ liệu thật** — bộ quét chỉ chạy trên mock text.

Cần từ người dùng: 4 biến `REDESIGN_*`. Sau đó chạy lại
`REDESIGN_QA=true npx playwright test redesign-qa` và bộ audit 27 route.

### B2 — Contrast: đã đo (cập nhật 2026-09-22)

~~Chưa đo contrast định lượng.~~ **Đã đo** ở vòng Final Real-Data Gate: 49 cặp
màu/state trên pixel đã render, 43 đạt ngưỡng, 6 không đạt và đều là viền trang
trí của chip Carbon. Chi tiết và lý do ở **§15.3**. Vẫn **không** tuyên bố WCAG
AA cho toàn hệ thống — chỉ cho đúng 49 cặp đã liệt kê.

### B3 — Hiệu năng Management (BLOCKER, không sửa ở round này)

Round 2 đo Management mất **~32 giây** để lấp đầy danh sách vụ trên hosted
Supabase. Round 3 **không đụng backend** theo đúng yêu cầu, và cũng không đo
lại được vì không có credential.

**Vì vậy: không gọi frontend là "hoàn thành cho real operational use".** Phần
giao diện đã xong theo matrix ở §5, nhưng ~32 giây chờ vẫn là blocker còn lại.

---

## 12. Đề xuất kỹ thuật cho vòng sau — bulk readiness (backend)

**Không thực hiện ở Round 3.** Đây là đề xuất cho round kế tiếp.

### Nguyên nhân đo được

`web-dashboard/src/pages/ops.ts` dựng mỗi hàng vụ bằng **hai** request tuần tự:

```
GET /v1/crop-seasons/{id}/carbon/readiness
GET /v1/crop-seasons/{id}/carbon
```

Với `CONCURRENCY` giới hạn và readiness một vụ đo 6–8s trên hosted Supabase,
một HTX vài chục vụ ra đúng con số ~32s. Round 2 đã giảm đau bằng progressive
rendering (hàng nào xong hiện hàng đó), nhưng tổng thời gian không đổi.

Gốc rễ: `CarbonService.readiness()` (`backend/service.py:132`) gọi
`self._repo.get_crop_bundle(crop_season_id)` — **một vụ một bundle**, mỗi bundle
là một chuỗi round-trip riêng.

### Endpoint / bulk-read cần thêm

```
POST /v1/carbon/readiness:batch
body: { "crop_season_ids": ["…", "…"] }   # giới hạn ví dụ 200 id/lần
resp: { "items": { "<season_id>": <CarbonReadinessResponse>, … } }
```

Hoặc, nếu muốn giữ REST thuần và scope theo tổ chức:

```
GET /v1/organizations/{id}/carbon-readiness
```

Bản `POST …:batch` linh hoạt hơn vì `/data-gaps`, `/seasons`, `/carbon` và
Dashboard đều cần cùng tập vụ nhưng lọc khác nhau.

### File backend dự kiến liên quan

| File | Thay đổi |
|---|---|
| `backend/api.py` | Thêm route batch (`tags=['Carbon']`), auth + access check theo **từng** season id, trả 403/404 đúng contract lỗi hiện có |
| `backend/schemas.py` | `CarbonReadinessBatchRequest`, `CarbonReadinessBatchResponse` |
| `backend/service.py` | `CarbonService.readiness_batch(ids)` — dùng bundle bulk thay vì lặp `readiness()` |
| `backend/infrastructure/read_repo.py` | `get_crop_bundles(season_ids)` mới, dựng trên `_bulk_activities_by_season` |
| `backend/tests/test_carbon_readiness.py` | Test tương đương từng-vụ (xem dưới) |
| `docs/openapi.json`, `docs/API_CATALOG.md` | Cập nhật sau khi route ổn định |

### Cách tái sử dụng `_bulk_activities_by_season`

`_bulk_activities_by_season` (`read_repo.py:294`) đã làm đúng việc cần: gom
`production_batches → activities → per-type details` + `profiles` về **~4
request cố định** cho *n* vụ, thay vì `O(vụ × loại detail)`. `_bulk_metric_totals`
đã dùng nó theo đúng mẫu này.

`get_crop_bundles(season_ids)` làm y hệt một tầng cao hơn:

1. `_many_in("crop_seasons", "id", season_ids)` — một request.
2. `_many_in("plots", "id", plot_ids)` — một request (area_ha, bắt buộc cho mapper).
3. `_bulk_activities_by_season(season_ids)` — ~4 request, **tái dùng nguyên vẹn**.
4. Ghép thành `dict[season_id, CropBundle]` có đúng shape mà
   `map_crop_activity_data(bundle)` đang nhận.

`service.readiness_batch()` sau đó chạy `map_crop_activity_data` +
`carbon_readiness` **trong bộ nhớ**, trên từng bundle, **không** gọi thêm I/O.
Mapper và engine không đổi một dòng nào.

Ước tính: từ `2n` request tuần tự xuống **~6 request cố định**, độc lập với *n*.

### Benchmark

| | Hiện tại | Mục tiêu |
|---|---|---|
| Readiness 1 vụ | 6–8s (đo Round 2, hosted Supabase) | giữ nguyên (đường single-season không đổi) |
| Lấp đầy Management, HTX nhiều vụ | **~32s** (đo Round 2) | **< 3s** cho 50 vụ |
| Số request backend cho *n* vụ | `2n` | `~6`, hằng số |

Cần đo lại baseline bằng credential thật trước khi làm, vì con số ~32s là của
Round 2 và cấu hình hosted có thể đã khác.

### Test bảo đảm không đổi Carbon result / business logic

1. **Test tương đương (quan trọng nhất).** Với mỗi vụ trong fixture:
   `readiness_batch([ids])[id] == readiness(id)` — so sánh dict đầy đủ, kể cả
   thứ tự gap và `record_refs`. Nếu bulk path làm lệch bất kỳ field nào, test đỏ.
2. **Test nhánh từ chối.** Vụ thiếu `area_ha` và vụ có irrigation không map được
   phải trả đúng `mapping_refused(...)` giống hệt đường single-season.
3. **Snapshot engine không đổi.** Chạy lại toàn bộ `backend/tests/` hiện có —
   không test Carbon nào được phép đổi kết quả, vì `map_crop_activity_data` và
   `carbon_readiness` không bị sửa.
4. **Test phân quyền.** Batch chứa một id ngoài phạm vi phải bị từ chối theo
   đúng contract hiện tại, không được rò dữ liệu vụ đó qua `items`.
5. **Test đếm request.** Khẳng định số lần gọi repo là hằng số khi *n* tăng —
   đây chính là thứ đang hỏng, nên nó phải có test riêng.

> Chạy `backend/` test từ trong thư mục `backend/`, không từ repo root.

---

## 13. Tệp untracked

Năm tệp untracked không liên quan, giữ nguyên, **không** stage, **không** commit:

```
.mcp.json
docs/ChatGPT Image Sep 21, 2026, 12_17_37 AM.png
docs/ChatGPT Image Sep 21, 2026, 12_18_09 AM-1.png
docs/ChatGPT Image Sep 21, 2026, 12_18_10 AM-2.png
docs/ChatGPT Image Sep 21, 2026, 12_18_11 AM-3.png
```

(`git status --short` tại HEAD `db47f8a` — chính xác 5 dòng `??`.)

---

## 14. Xác nhận

- **Chưa merge** vào `main`.
- **Chưa push** lên remote.
- **Chưa deploy**.
- Toàn bộ nằm trên `fix/hybrid-redesign-round2`, HEAD `db47f8a`, chờ người dùng
  kiểm tra staging/local.
- Không sửa backend, không đổi công thức / hệ số / phương pháp Carbon.

---

## 15. Final Real-Data Gate (2026-09-22)

Vòng cổng cuối được yêu cầu chạy trên tenant QA thật. Kết quả thật, không tô hồng:

| Hạng mục của gate | Trạng thái |
|---|---|
| §1 Branch / HEAD / backend `:8010` / `:5173` sang real-data mode | **Done** |
| §2 `redesign-qa` trên dữ liệu thật (15 test, 0 skipped) | **BLOCKED** — xem §15.1 |
| §3 Audit thật 27 route × 4 viewport | **BLOCKED** — cần đăng nhập |
| §4 Đối chiếu P0 trên vụ `2e63e128-…` | **BLOCKED** — cần đăng nhập |
| §5 Visual check với mật độ dữ liệu thật | **BLOCKED** — cần đăng nhập |
| §6 Đo contrast định lượng | **Done** — 49 cặp đo, xem §15.3 |
| §7 Benchmark loading 3 lần trên dữ liệu thật | **BLOCKED** — cần đăng nhập |
| §8 Regression sau khi sửa | **Done** — xem §15.4 |
| §10 Giữ `:5173` real-mode cho người dùng | **Done** — xem §15.8 |

### 15.1 Vì sao `redesign-qa` vẫn skip — chẩn đoán, không phỏng đoán

Yêu cầu nói bốn biến `REDESIGN_*` và `REAL_E2E=true` đã được set. **Chúng không
tồn tại trong bất kỳ scope nào mà tiến trình của tôi đọc được.** Đã kiểm tra hết,
không in giá trị:

| Nơi kiểm tra | Cách kiểm tra | Kết quả |
|---|---|---|
| Shell con (bash) | kiểm tra biến rỗng cho cả 7 tên | MISSING |
| Windows `Process` scope | `[Environment]::GetEnvironmentVariable(v,'Process')` | MISSING |
| Windows `User` scope | `[Environment]::GetEnvironmentVariable(v,'User')` | MISSING |
| Windows `Machine` scope | `[Environment]::GetEnvironmentVariable(v,'Machine')` | MISSING |
| File `.env` trong repo | `find . -name ".env*"` → 4 file | Không file nào có key `REDESIGN_*` |
| Claude Code settings | `.claude/settings.local.json` | Có `enabledMcpjsonServers`, `enableAllProjectMcpServers`; **không có khối `env`** |

Guard trong spec (`tests/e2e/redesign-qa.spec.ts:19`):

```ts
test.skip(process.env.REDESIGN_QA !== 'true' || !farmer.email, 'set REDESIGN_QA=true with the QA credentials')
```

Cả hai vế đều đúng → 15 test skip. Đây **không** phải lỗi config của spec, cũng
không phải lỗi process của Playwright: biến thực sự không có trong environment
của tiến trình.

**Nguyên nhân gần như chắc chắn:** biến được set trong *terminal session của bạn*
(ví dụ gõ trực tiếp vào PowerShell đang mở). Mỗi tool call của tôi sinh một tiến
trình con mới, tiến trình cha là agent — **không** phải shell đó — nên không kế
thừa biến.

**Cách làm cho tôi thấy được** — chọn một:

1. Thêm khối `env` vào `.claude/settings.local.json`:

   ```json
   { "env": { "REDESIGN_QA": "true", "REAL_E2E": "true",
              "REDESIGN_FARMER_EMAIL": "...", "REDESIGN_FARMER_PASSWORD": "...",
              "REDESIGN_MANAGER_EMAIL": "...", "REDESIGN_MANAGER_PASSWORD": "..." } }
   ```

   File này nằm trong repo — cân nhắc đưa vào `.gitignore` trước khi để mật khẩu
   vào đó.
2. Set ở **User scope** của Windows (`setx`) rồi khởi động lại phiên Claude Code.
3. Gõ thẳng vào phiên này bằng tiền tố `!`, đặt biến rồi chạy Playwright trong
   cùng một dòng lệnh — lệnh chạy trong shell của bạn và output vào hội thoại.

**Theo đúng yêu cầu "Nếu test skip, không được báo pass": tôi KHÔNG báo pass.**
Kết quả chính xác là **0 passed / 0 failed / 15 skipped**.

### 15.2 Đã làm được gì ở real-data mode

- `:5173` đã chuyển sang real-data mode và xác minh bằng Chromium: **không** có
  banner "Dữ liệu minh họa", app dừng ở `h1 = "Đăng nhập"` — đúng hành vi khi
  `VITE_USE_MOCK_DATA` không bật. Backend `:8010` giữ nguyên, `/docs` trả 200.
- Không route nào phía sau màn đăng nhập được mở, nên §3, §4, §5 và §7 **chưa có
  số liệu real-data nào**. Ma trận ở §5 của báo cáo này vẫn thuần cột **Mock**.

| Hạng mục | Mock result | Real-data result |
|---|---|---|
| Coverage 27 route × 4 viewport | 27/27 Done, overflow 0px toàn bộ | **Chưa chạy** (BLOCKED) |
| Raw enum / UUID / ISO / field name | sạch trên 27 route | **Chưa chạy** (BLOCKED) |
| Keyboard: row link + Enter, skip-link | pass | **Chưa chạy** (BLOCKED) |
| Institutional green / emoji / serif trong `main` | 0 / 0 / 0 | **Chưa chạy** (BLOCKED) |
| Carbon P0 (5 trạng thái, vụ `2e63e128-…`) | chỉ nhánh empty/error | **Chưa chạy** (BLOCKED) |
| MRV case + aggregate step status | không có case trong mock | **Chưa chạy** (BLOCKED) |
| Loading benchmark `/dashboard` `/seasons` `/data-gaps` `/carbon` | không đại diện | **Chưa chạy** (BLOCKED) |
| Contrast 49 cặp | **đo xong, 43 pass / 6 fail** | 2 cặp còn thiếu vì cần session |

### 15.3 Contrast — 49 cặp đo trên pixel thật

Không nhìn bằng mắt. Cách đo: làm trong suốt mọi glyph (`color: transparent`),
chụp viewport, lấy **pixel đã được trình duyệt vẽ** tại tâm phần tử làm nền;
foreground là computed `color`, composite lên nền đó nếu trong suốt. Hai lỗi của
chính công cụ đo đã phải sửa trước khi số liệu đáng tin:

1. Suy nền bằng cách đi ngược DOM cho kết quả sai ngay khi gặp gradient — sidebar
   Farmer bị đọc thành *trắng trên trắng* (1:1). → chuyển sang lấy mẫu pixel.
2. Chromium giữ nguyên `oklch()` trong computed value; regex `rgb()` không đọc
   được, và canvas `fillStyle` cũng không chuyển đổi → **toàn bộ** cặp Management
   trả về "not found". → tự chuyển OKLCh → OKLab → LMS → linear sRGB → sRGB theo
   CSS Color 4.

Ngưỡng dùng: normal text ≥ 4.5:1 · large text ≥ 3:1 · UI boundary/focus ≥ 3:1.

**Trước khi sửa: 49 cặp, 10 FAIL. Sau khi sửa: 49 cặp, 6 FAIL.**

Token đã đổi (không đổi semantic role):

| Vấn đề đo được | Trước | Sau |
|---|---|---|
| Viền input (`--border-input`, `.ops-search`, `.ops-filter select`) | 1.83:1 | **3.58:1** — token mới `--ac-control-line` |
| Viền nút phụ / ghost (`.btn--ghost`, `.fw-btn--soft/--ghost`) | 1.67:1 | **3.27:1** — cùng token |
| Gạch chân tiêu đề bảng (`--ac-rule-3`, 68% → 64%) | 2.82:1 | **3.28:1** |
| Nhãn nhóm sidebar Farmer (trắng `.5` → `.58`) | 4.40:1 | **5.39:1** |
| Nút disabled (`opacity .45` → `.66`) | 1.72:1 | **3.35:1** |

Hairline cấu trúc (`--ac-rule`, `--ac-rule-2`) **không** đổi — một đường kẻ giữa
hai hàng bảng không phải là control, WCAG 1.4.11 không áp dụng.

#### Bảng đầy đủ

| Cặp màu | Loại | FG | BG | Tỉ số | Ngưỡng | Kết quả |
|---|---|---|---|---|---|---|
| Sidebar · mục điều hướng | normal-text | `#CDDCD3` | `#023722` | 9.4:1 | 4.5:1 | **PASS** |
| Sidebar · nhãn nhóm | normal-text | `#869F93` | `#023621` | 4.78:1 | 4.5:1 | **PASS** |
| Sidebar · mục đang mở | normal-text | `#F9FDFB` | `#025032` | 9.32:1 | 4.5:1 | **PASS** |
| Sidebar · wordmark | normal-text | `#F9FDFB` | `#023923` | 12.7:1 | 4.5:1 | **PASS** |
| Sidebar · phụ đề wordmark | normal-text | `#CDDCD3` | `#033923` | 9.16:1 | 4.5:1 | **PASS** |
| Sidebar · tài khoản đăng nhập | normal-text | `#F9FDFB` | `#022C1B` | 14.85:1 | 4.5:1 | **PASS** |
| Sidebar · vai trò | normal-text | `#CDDCD3` | `#022B1A` | 10.84:1 | 4.5:1 | **PASS** |
| Nội dung · tiêu đề trang (h1) | large-text | `#11241C` | `#F5F3EF` | 14.66:1 | 3:1 | **PASS** |
| Nội dung · body text | normal-text | `#30423A` | `#F5F3EF` | 9.64:1 | 4.5:1 | **PASS** |
| Nội dung · muted text | normal-text | `#5F6D66` | `#F5F3EF` | 4.9:1 | 4.5:1 | **PASS** |
| Topbar · nhãn vai trò | normal-text | `#5F6D66` | `#F5F3EF` | 4.9:1 | 4.5:1 | **PASS** |
| Bảng · tiêu đề cột | normal-text | `#5F6D66` | `#FCFEFD` | 5.36:1 | 4.5:1 | **PASS** |
| Bảng · ô dữ liệu | normal-text | `#30423A` | `#FCFEFD` | 10.55:1 | 4.5:1 | **PASS** |
| Bảng · link trong hàng | normal-text | `#30423A` | `#FCFEFD` | 10.55:1 | 4.5:1 | **PASS** |
| Bảng · gạch chân tiêu đề | ui-boundary | `#839089` | `#F5F3EF` | 3.28:1 | 3:1 | **PASS** |
| Input · chữ placeholder | normal-text | `#11241C` | `#FCFEFD` | 16.04:1 | 4.5:1 | **PASS** |
| Input · viền mặc định | ui-boundary | `#7E8984` | `#F5F3EF` | 3.58:1 | 3:1 | **PASS** |
| Nút · hành động chính (content CTA) | normal-text | `#FCFEFD` | `#1A2721` | 15.29:1 | 4.5:1 | **PASS** |
| Nút · hành động chính — viền | ui-boundary | `#1A2721` | `#F5F3EF` | 13.97:1 | 3:1 | **PASS** |
| Nút · hành động phụ (ghost) | normal-text | `#003E22` | `#F5F3EF` | 11.07:1 | 4.5:1 | **PASS** |
| Nút · hành động phụ — viền | ui-boundary | `#7E8984` | `#F5F3EF` | 3.27:1 | 3:1 | **PASS** |
| Nút · trạng thái disabled | normal-text | `#C8CCCA` | `#646C67` | 3.35:1 | 4.5:1 | **FAIL** |
| Nội dung · liên kết | normal-text | `#003E22` | `#F5F3EF` | 11.07:1 | 4.5:1 | **PASS** |
| Trạng thái · chữ lỗi | normal-text | `#5F6D66` | `#F5F3EF` | 4.9:1 | 4.5:1 | **PASS** |
| Badge · error (Chưa có dữ liệu) | normal-text | `#9A2B19` | `#F5F3EF` | 6.93:1 | 4.5:1 | **PASS** |
| Badge · warning (Thiếu một phần) | normal-text | `#864A00` | `#F5F3EF` | 6.33:1 | 4.5:1 | **PASS** |
| Badge · success (Đầy đủ dữ liệu) | normal-text | `#036639` | `#F5F3EF` | 6.39:1 | 4.5:1 | **PASS** |
| Badge · info | normal-text | `#30423A` | `#F5F3EF` | 9.64:1 | 4.5:1 | **PASS** |
| Badge · neutral | normal-text | `#5F6D66` | `#F5F3EF` | 4.9:1 | 4.5:1 | **PASS** |
| Input · viền khi focus-within | ui-boundary | `#25312B` | `#E2E8E5` | 13.35:1 | 3:1 | **PASS** |
| Focus-visible · vòng focus trên link hàng bảng | ui-boundary | `#30423A` | `#E9EEEC` | 9.11:1 | 3:1 | **PASS** |
| Farmer sidebar · mục điều hướng | normal-text | `#DCE3E0` | `#023621` | 10.36:1 | 4.5:1 | **PASS** |
| Farmer sidebar · mục đang mở | normal-text | `#FFFFFF` | `#025032` | 9.56:1 | 4.5:1 | **PASS** |
| Farmer sidebar · nhãn nhóm | normal-text | `#95ACA3` | `#033923` | 5.39:1 | 4.5:1 | **PASS** |
| Farmer sidebar · tên tài khoản | normal-text | `#FFFFFF` | `#022C1B` | 15.23:1 | 4.5:1 | **PASS** |
| Farmer sidebar · "Xem tài khoản" | normal-text | `#95A69F` | `#022B1A` | 6.03:1 | 4.5:1 | **PASS** |
| Farmer · tiêu đề trang (h1) | large-text | `#11241C` | `#F9F7F3` | 15.18:1 | 3:1 | **PASS** |
| Farmer · nút hành động chính | normal-text | `#FCFEFD` | `#1A2721` | 15.29:1 | 4.5:1 | **PASS** |
| Farmer · viền nút hành động chính | ui-boundary | `#1A2721` | `#F9F7F3` | 14.47:1 | 3:1 | **PASS** |
| Carbon state · Thiếu dữ liệu (attention) | normal-text | `#70401D` | `#FFDAC1` | 6.58:1 | 4.5:1 | **PASS** |
| Carbon state · Thiếu dữ liệu — viền | ui-boundary | `#EAB68D` | `#F9F7F3` | 1.7:1 | 3:1 | **FAIL** |
| Carbon state · Giới hạn hệ số (methodology) | normal-text | `#33406A` | `#C7CEEA` | 6.46:1 | 4.5:1 | **PASS** |
| Carbon state · Giới hạn hệ số — viền | ui-boundary | `#A3ADD8` | `#F9F7F3` | 2.06:1 | 3:1 | **FAIL** |
| Carbon state · Sẵn sàng tính (ready) | normal-text | `#14564A` | `#B5EAD7` | 6.39:1 | 4.5:1 | **PASS** |
| Carbon state · Sẵn sàng tính — viền | ui-boundary | `#86CDB6` | `#F9F7F3` | 1.72:1 | 3:1 | **FAIL** |
| Carbon state · Đã tính (calculated) | normal-text | `#294B16` | `#E2F0CB` | 8.31:1 | 4.5:1 | **PASS** |
| Carbon state · Đã tính — viền | ui-boundary | `#B9D394` | `#F9F7F3` | 1.53:1 | 3:1 | **FAIL** |
| Carbon state · Cần tính lại (stale) | normal-text | `#70401D` | `#FFDAC1` | 6.58:1 | 4.5:1 | **PASS** |
| Carbon state · Cần tính lại — viền | ui-boundary | `#EAB68D` | `#F9F7F3` | 1.7:1 | 3:1 | **FAIL** |

Hai phần tử không đo được vì mock tenant không render: `.sidebar__id .link`
(nút đăng xuất Management — chỉ có khi đã đăng nhập) và `main .fw-note` trên
`/farmer`. Cần đo lại hai cặp này khi có credential.

#### Sáu FAIL còn lại — vì sao cố ý không sửa

Cả sáu là một thứ: đường viền 1px quanh năm chip trạng thái Carbon (trạng thái
`stale` dùng lại tone `attention` nên xuất hiện hai lần), 1.53–2.06:1 so với nền
giấy.

- **Chữ trong từng chip đã đạt 6.39–8.31:1**, và mỗi chip **tự nói trạng thái
  bằng chữ**: "Thiếu dữ liệu", "Giới hạn hệ số", "Sẵn sàng tính", "Đã tính",
  "Cần tính lại". Yêu cầu "không chỉ dùng màu để biểu đạt trạng thái" đã đạt.
- WCAG 1.4.11 áp dụng cho *thông tin thị giác cần để nhận diện* component hoặc
  trạng thái. Ở đây viền **dư thừa** so với nhãn chữ, nên không thuộc phạm vi.
- Muốn ép 3:1 thì line token phải rơi xuống độ sáng khoảng 28% — tức biến chip
  pastel mềm thành hộp viền đậm, đổi hẳn ngôn ngữ thị giác mà không thêm giá trị
  accessibility nào.

Sáu cặp này được **báo nguyên số đo**, không giấu. Nếu bạn muốn toàn bộ về xanh,
nói một câu là tôi đổi năm token `--ac-role-*-line`.

**Không tuyên bố WCAG cho toàn hệ thống.** Chỉ khẳng định: 49 cặp liệt kê ở trên
đo được đúng các tỉ số đó, 43 đạt ngưỡng tương ứng, 6 không đạt và lý do đã nêu.

### 15.4 Regression sau khi sửa contrast

| Gate | Kết quả |
|---|---|
| `npx tsc --noEmit` | **pass**, 0 lỗi |
| `npx vitest run` | **35 file / 298 test pass** |
| `npm run build` | **pass**, `✓ built in 6.59s` |
| `npx playwright test round3-qa` | **15/15 pass** |
| `npx playwright test web-smoke farmer-web` | **2/2 pass** |
| `npx playwright test redesign-qa` | **0 pass / 0 fail / 15 skipped — BLOCKED** |

Lưu ý quy trình cho lần chạy sau: `playwright.config.ts` đặt
`reuseExistingServer: true` trên `:5173`. Vì `:5173` đang chạy real-data mode,
phải **dừng nó** trước khi chạy các gate mock để Playwright tự dựng server mock
của chính nó, chạy xong mới bật lại real mode. Nếu không, các test mock sẽ đâm
vào màn đăng nhập và fail sai.

### 15.5 Commit mới của vòng này

| Commit | Nội dung |
|---|---|
| `2fc319f` | `fix(a11y): a control boundary you can actually see, measured` |

- `git diff --stat b01404f..HEAD -- web-dashboard` → **23 files changed, 940 insertions(+), 184 deletions(-)**
- `git diff --stat main...HEAD -- web-dashboard` → **48 files changed, 2830 insertions(+), 504 deletions(-)**
- `git rev-list --count main..HEAD` → **14 commit**

### 15.6 Tệp untracked

`git status --short` tại HEAD `2fc319f` — vẫn đúng 5 dòng `??`, không stage,
không commit, không sửa:

```
?? .mcp.json
?? docs/ChatGPT Image Sep 21, 2026, 12_17_37 AM.png
?? docs/ChatGPT Image Sep 21, 2026, 12_18_09 AM-1.png
?? docs/ChatGPT Image Sep 21, 2026, 12_18_10 AM-2.png
?? docs/ChatGPT Image Sep 21, 2026, 12_18_11 AM-3.png
```

### 15.7 Đường dẫn ảnh và dữ liệu đo

| Nội dung | Đường dẫn |
|---|---|
| Baseline 27 route × 4 viewport (mock) | `.qa-screenshots/round3/baseline/` |
| After 27 route × 4 viewport (mock) | `.qa-screenshots/round3/after/` |
| Số đo từng route (JSON) | `.qa-screenshots/round3/after/report.json` |
| **Contrast 49 cặp (JSON)** | `.qa-screenshots/round3/contrast.json` |
| Real-data screenshots | **chưa có** — bị chặn ở màn đăng nhập |

Toàn bộ `.qa-screenshots/` nằm trong `.gitignore`, không commit.

### 15.8 Blocker còn lại và xác nhận

Blocker:

1. **Real-data gate chưa chạy** (§15.1). Đây là blocker lớn nhất của vòng này:
   §3, §4, §5 và §7 của yêu cầu đều chưa có một số liệu thật nào.
2. **Hiệu năng Management khoảng 32 giây** (số đo Round 2). Không đo lại được vì
   không đăng nhập được, và không sửa backend theo đúng yêu cầu. Đề xuất bulk
   readiness vẫn ở §12.
   → **Hệ thống không được gọi là "operational-ready".**
3. Hai cặp contrast chưa đo được vì cần session thật (§15.3).

Xác nhận:

- **Chưa merge** vào `main`.
- **Chưa push** lên remote.
- **Chưa deploy**.
- Branch `fix/hybrid-redesign-round2`, HEAD `2fc319f`.
- `:5173` đang chạy **real-data mode** và `:8010` backend đang chạy — mở
  **http://127.0.0.1:5173/** để xem. App sẽ hỏi đăng nhập vì đây là dữ liệu thật.

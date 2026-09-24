# Web UX Round 4.2 — Đồng bộ sidebar Nông hộ với Quản lý

> Branch `fix/agricarbon-farmer-sidebar-parity`, tạo từ `origin/main` = `98676ac`. Commit local, **chưa push, chưa merge, chưa deploy**. Dừng ở gate để người dùng duyệt giao diện.

Phạm vi: chỉ lớp trình bày của sidebar và shell chứa nó. Không đổi backend, API contract, Carbon readiness, công thức/hệ số Carbon, MRV, business logic, nội dung hay thứ bậc workspace.

## 1. Skill / công cụ đã dùng

| Yêu cầu | Thực tế |
|---|---|
| Product Design Audit | **Không có** trong phiên này. Dùng skill `hallmark` ở chế độ `audit` (chỉ đọc, xếp hạng phát hiện theo mức độ) làm phương án tương đương; audit chạy trên giao diện render, không chỉ đọc source. |
| Design QA / accessibility | Không có skill Design QA riêng. Dùng axe-core 4.13.0 (cài tạm vào scratchpad, **không** thêm vào `package.json`), tag `wcag2a/2aa/21a/21aa`, không tắt rule nào. |
| Playwright | `@playwright/test` 1.63 có sẵn trong repo: script đo bounding box + chụp ảnh (scratchpad) và suite mới `tests/e2e/sidebar-parity.spec.ts`. |

## 2. Sai lệch đo được trước khi sửa (render, mock tenant)

Đo bằng `getBoundingClientRect` / `getComputedStyle` tại `/farmer` và `/dashboard`.

| Hạng mục | Nông hộ (trước) | Quản lý (chuẩn) |
|---|---|---|
| Chiều rộng 1440 / 1363 / 1280 | **232px** (hard-code riêng) | 240px (`--sidebar-w`) |
| Chiều rộng 1024 | **208px** (đổi ở 1100px) | 192px (đổi ở 1024px) |
| 768 / 390 | ẩn, bottom nav 6 mục | drawer ẩn ngoài màn hình |
| Padding trái/phải/trên | 20 / 20 / 24px | 14 / 14 / 22px |
| Icon trong hàng | **x = 0 so với mép hàng** — dính mép pill | lệch 11.5px |
| Nhãn trong hàng | 30px từ mép hàng | 38px |
| Cỡ chữ hàng | 14.5px / 550 | 13px / 550 |
| Chiều cao hàng | 40px | 40px |
| Active | nền + viền trong + 700; marker 3×18px đặt ở `left: 0` (**nằm trong pill**) | nền + viền trong + 700; marker 4×24px ở `left: -3px` |
| Hover | `scale(1.1)` + đổi weight 700 (hàng nhảy) | tô nền nhạt |
| Brand | `AgriCarbon` 21px và `Nông hộ` 12px **cùng một dòng**, cách 8px, không có đường kẻ; ở 1024px `Nông hộ` bị ép xuống 2 dòng trong ô 39px | `AgriCarbon` 18px, tagline 12px dòng dưới, đường kẻ dưới |
| Nhóm | 4 nhãn nhóm 11px, gồm "TỔNG QUAN" ngay trên hàng "Tổng quan" | nhóm đầu không có nhãn, nhãn 10.5px |
| Khoảng giữa nhóm | 20px | 20px |
| Footer | 192×57px, avatar 34px, vùng chữ 150px (1440) / 126px (1024); email QA hiện thành `qa-farmer-fw1@agr…` | 212×54.7px, avatar 32px |
| Workspace | bắt đầu ở x=232 | x=240 |
| Tràn ngang | 0 | 0 |
| Focus | 2px solid `oklch(.78 .16 140)` | như nhau |

**Nguyên nhân gốc của "active row bị bó":** `.fw-nav__item` dùng `padding-inline: var(--fw-space-10)` và marker `left: calc(var(--fw-space-10) * -1)`, nhưng `--fw-space-10` **không được định nghĩa** trong `farmer/tokens.css` (thang chỉ có 2/4/6/8/12/16/…). Cả hai khai báo trở thành không hợp lệ → padding 0, marker rơi về `left: auto` bên trong pill.

Phát hiện thêm ở Management (có từ trước, nằm trong phạm vi "sidebar dùng chung"):
- Ở 1024px (192px) hàng "Tổng quan vận hành" (chữ đậm 132px) dài hơn hàng và bị cắt.
- Ở ≤768px drawer chỉ bị `translateX(-100%)`: 3 lần Tab đầu tiên đi vào link nằm ngoài màn hình (x = −236) trước khi tới nút "Mở menu".

Audit theo định dạng `hallmark audit` (Tell · Where · Severity · Fix):

| Severity | Tell | Where | Fix |
|---|---|---|---|
| critical | design-system drift: sidebar thứ hai với độ rộng/lưới riêng | `farmer/farmer.css` `.fw-shell`, `.fw-side*`, `FarmerExperience.tsx` | dùng chung component + token |
| critical | token không tồn tại làm hỏng active row | `farmer.css` `--fw-space-10` | bỏ bản sao, dùng lưới Management |
| major | hover đổi kích thước (layout shift) | `.fw-nav__item:hover` | hover chỉ tô nền |
| major | brand và nhãn vai trò dính nhau | `.fw-brand` | xếp 2 dòng như Management |
| major | email bị cắt mạnh | `.fw-profile__id b` | xuống dòng sau "@", `title`, tên truy cập đầy đủ |
| major | nhãn Management bị cắt ở 1024px | `--sidebar-w: 192px` | 216px |
| major | tab stop vô hình ở drawer đóng | `.sidebar` ≤768px | `visibility: hidden` khi đóng |
| minor | nhãn nhóm lặp lại hàng duy nhất bên dưới | "TỔNG QUAN" | bỏ nhãn nhóm đầu, như Management |

`2 critical · 5 major · 1 minor` (đã sửa tất cả).

## 3. Quyết định thiết kế

1. **Sidebar Quản lý là chuẩn; không có sidebar thứ ba.** Nông hộ nhận nguyên lưới, kiểu chữ, hàng, marker, focus và footer của Quản lý.
2. **Một component, một token.** `src/components/Sidebar.tsx` render `aside.sidebar` (brand → nav → footer). Cả `AppShell` (Quản lý) và `FarmerShell` gọi nó; vai trò chỉ truyền *nội dung*: tagline (`Nông hộ` / `Hiệu suất tài nguyên · Carbon · MRV`), danh sách đích, khối tài khoản. Lưới shell của cả hai đọc `var(--sidebar-w)`. CSS sidebar riêng của Nông hộ (`.fw-side`, `.fw-brand`, `.fw-nav*`, `.fw-profile*`, `.fw-signout` không còn dùng) đã xoá — không còn chỗ để hai bên lệch nhau.
3. **Chiều rộng:** 240px khi > 1024px; **216px** ở 769–1024px (192px cắt nhãn dài nhất của Quản lý; 216px vừa đủ: 3 + 10 + 18 + 10 + 132 + 10 + 28 = 211px); ≤ 768px ẩn — Nông hộ dùng bottom nav (giữ nguyên), Quản lý dùng drawer (giữ nguyên, chỉ sửa tab order).
4. **IA giữ nguyên.** Nông hộ vẫn 6 đích theo đúng thứ tự: Tổng quan, Nhật ký, Ruộng / Vụ mùa, Hiệu suất, Carbon, Tôi; các nhãn nhóm "Canh tác", "Theo dõi", "Tài khoản" giữ nguyên. Chỉ bỏ nhãn "Tổng quan" của nhóm đầu (vốn đã `aria-hidden`, chỉ lặp lại hàng bên dưới) để hàng tổng quan nằm ngay dưới brand như Quản lý. Menu Quản lý không đổi.
5. **Active row:** nền + viền trong + marker 4×24px + weight 700 + icon đổi màu — không dựa vào màu. Cùng pattern ở hai vai trò (Playwright so khớp giá trị computed).
6. **Footer:** avatar 32px, cột chữ căn cùng lưới. Email dài xuống dòng **sau "@"** (`<wbr>`), tối đa 2 dòng; nội dung DOM giữ nguyên email, có `title`. Khối tài khoản Nông hộ là một link cao 44px, accessible name "Tài khoản của …". Quản lý giữ email + vai trò + nút "Đăng xuất".
7. **Kiểu chữ tự khai báo:** `.sidebar` đặt `font-family/size/line-height` của hệ thống, vì shell Nông hộ đặt body 15px/1.6 — sidebar không còn thừa hưởng khác nhau theo shell.
8. **Không thêm xanh TDMU vào workspace.** Token `--ac-sidebar*` chỉ xuất hiện trong selector điều hướng (guard `brandGreen.test.ts` vẫn pass).

## 4. Shared token / component

- `--sidebar-w` (`styles.css :root`, override ở `@media (max-width: 1024px)`) — dùng bởi `.shell` và `.fw-shell`.
- `src/components/Sidebar.tsx`: `Sidebar`, `AccountName`.
- Class dùng chung: `.sidebar`, `.brand`, `.nav`, `.nav-group`, `.nav-group__label`, `.nav__ico`, `.sidebar__foot`, `.avatar`, `.sidebar__id`, `.sidebar__name`, `.sidebar__acct` (mới). `fw-side` giữ lại trên `aside` Nông hộ chỉ làm hook cho test, không còn style.

## 5. Before / after (đo trên render)

| Viewport | Nông hộ trước | Nông hộ sau | Quản lý sau | Chênh lệch |
|---|---|---|---|---|
| 1440 | 232 | **240** | 240 | 0 |
| 1363 | 232 | **240** | 240 | 0 |
| 1280 | 232 | **240** | 240 | 0 |
| 1024 | 208 | **216** | 216 (trước 192) | 0 |
| 768 | ẩn + bottom nav | ẩn + bottom nav | drawer | — |
| 390 | ẩn + bottom nav | ẩn + bottom nav | drawer | — |

Sau khi sửa, ở mọi viewport desktop hai vai trò trùng nhau: padding 14/14, icon ở x = 28.5, nhãn ở x = 55, hàng 40px, chữ 13px, khoảng nhóm 20px, marker 4×24 @ −3px, weight 700, brand 64.5px (Quản lý 83.1px ở 1024 vì tagline dài xuống 2 dòng — khác biệt nội dung, wordmark và tagline cùng vị trí/cỡ), workspace bắt đầu đúng mép sidebar, tràn ngang 0, không nhãn nào bị cắt. Footer Nông hộ 212×59 (link 44px), Quản lý 212×52.1.

Ảnh (cùng mock data, cùng viewport, `vite` dev mock mode; before chụp từ worktree tại `origin/main`), lưu local (gitignored) tại `.qa-screenshots/round4-2/{before,after}/`:

| Ảnh | Ghi chú |
|---|---|
| `farmer-carbon-1363.png` | Carbon, sidebar đầy đủ + workspace |
| `farmer-carbon-1363-long-email.png` | cùng trang, footer với email QA thật (`qa-farmer-fw1@agricarbon-demo.local`): trước `qa-farmer-fw1@agr…`, sau 2 dòng đầy đủ |
| `farmer-home-1440.png` | |
| `farmer-journal-1280.png` | |
| `farmer-season-1024.png` | chi tiết vụ ở 216px |
| `farmer-home-768.png` | **giống hệt byte** trước/sau (sha256 `6a56b789…`) |
| `farmer-carbon-390.png` | **giống hệt byte** trước/sau (sha256 `69ff07e6…`) |
| `management-overview-1363.png` | khác biệt pixel **chỉ** trong vùng footer (bbox x 14–226, y 829–881): line-height dòng email 1.35 thay vì 1.55 thừa hưởng |

## 6. Route và viewport đã kiểm

- Nông hộ: `/farmer`, `/farmer/journal`, `/farmer/farms`, `/farmer/performance`, `/farmer/carbon`, `/farmer/account`, plot `/farmer/plots/plot-demo-01`, season `/farmer/crop-seasons/crop-demo-01` và tab `journal`, `performance`, `carbon` — ở 1363, 1024, 390 (suite) + 1440/1280/768 (đo và ảnh).
- Quản lý: `/dashboard`, `/seasons`, `/data-gaps`, `/carbon`, `/farms`, `/mrv` — ở 1363, 1024 (suite); `/dashboard` ở cả 6 viewport (đo); drawer ở 390.

## 7. Gate — lệnh và kết quả chính xác (trên HEAD `1cf4b58`, `web-dashboard/`)

| Lệnh | Kết quả |
|---|---|
| `npx tsc --noEmit` | pass |
| `npx vitest run` | **46 files, 365 passed** (trước 360; +5 trong `src/components/Sidebar.dom.test.tsx`) |
| `npm run build` | pass (`✓ built`; cảnh báo chunk > 500 kB có từ trước) |
| `npx playwright test sidebar-parity farmer-web web-smoke round3-qa round4-qa round41-qa redesign-qa` | **40 passed, 15 skipped** — 13/13 suite mới + 27 suite cũ; 15 skipped là `redesign-qa` (tự bỏ qua khi thiếu `REDESIGN_*`) |
| Real-data QA (`round4-real`, `round41-real`, `farmer-real-*`, `web-real-data`) | **Không chạy** — không có credential trong phiên này (tool call không thấy biến môi trường của terminal người dùng) |
| axe-core 4.13.0 | **36 lần quét** (12 màn hình × 1363/1024/390, gồm drawer Quản lý mở ở 390), **0 violation** |

Không hạ assertion, không skip test nào để gate pass. Một assertion trong suite mới được viết lại trong lúc làm: lần đầu so *tổng chiều cao* khối brand, fail ở 1024px vì tagline Quản lý dài xuống 2 dòng — đó là khác biệt nội dung chứ không phải lưới; assertion thay thế chặt hơn ở chỗ quan trọng (vị trí wordmark, vị trí tagline, cỡ chữ cả hai, tagline Nông hộ 1 dòng, wordmark và tagline khác dòng).

Suite mới fail trên code cũ theo số đo ở §2 (232 ≠ 240 ở desktop; 208 ≠ 192 ở 1024; icon lệch 5.5px; marker 3×18).

## 8. Accessibility

- axe: 0 violation. `incomplete` (axe không tự kết luận, không phải violation): ở 390px, `color-contrast` trên 6 link bottom nav Nông hộ (nền gradient — không đổi trong round này) và tab vụ đang active ("partially obscured"). Không node nào thuộc sidebar.
- Bàn phím: Nông hộ desktop — skip link → brand → 6 đích theo đúng thứ tự → khối tài khoản → topbar. Quản lý ≤768px — sau khi sửa, Tab đi thẳng skip link → "Mở menu" (`aria-expanded` false/true); mở drawer thì link tới được.
- Focus ring: 2px solid, marker sáng `oklch(.78 .16 140)`, offset 2px, cả hai vai trò (không dùng xanh workspace ~2:1 trên nền rừng).
- Active không chỉ bằng màu: nền + marker + weight + icon.
- Email: DOM giữ email đầy đủ, `title`, link tài khoản Nông hộ có accessible name đầy đủ; target 44px.
- Console: lỗi duy nhất là `404 /favicon.ico` ở lần tải đầu (app không khai báo favicon; có từ trước) — không phải lỗi app. Không có `pageerror` trên mọi route đã kiểm.

## 9. Những gì không thay đổi

Backend, API, Supabase, Flutter, Carbon engine/readiness/công thức/hệ số, MRV, `src/api`, `src/carbon`, `src/features`, `src/pages`, `src/farmer/pages` — `git diff origin/main --stat` trên các thư mục này: 0 dòng. Bottom nav Nông hộ và cơ chế drawer Quản lý giữ nguyên (chỉ thêm tab order đúng cho drawer). Nội dung và thứ bậc workspace không đổi. Menu Quản lý không đổi.

## 10. Known limitations

- Chạy trên mock tenant: shell Quản lý khi mock không có session hiển thị menu của viewer chưa gán tổ chức (2 mục). Phần được kiểm — rộng, padding, lưới hàng, brand, marker, footer — không phụ thuộc số hàng; menu đầy đủ của `cooperative_manager` chưa được chụp trên dữ liệu thật trong round này.
- Real-data QA chưa chạy (thiếu credential). Nếu cung cấp credential, chạy `round41-real`/`farmer-real-data`/`web-real-data` theo cách cũ.
- Email dài hơn 2 dòng × ~170px vẫn bị cắt ở dòng thứ 2 (có `title` và tên truy cập đầy đủ).
- Kiểm tra trên dev server local, không phải staging.
- Bottom nav Nông hộ (nền gradient) vẫn là `incomplete` với axe như trước.

## 11. Branch và commit

Branch `fix/agricarbon-farmer-sidebar-parity` (từ `origin/main` `98676ac`):

| SHA | Commit |
|---|---|
| `c328dc1` | fix(web): Farmer and Management render one sidebar on one width token |
| `022bd6c` | fix(web): tablet sidebar is 216px for both roles, so no row is clipped |
| `0270544` | fix(web): closed Management drawer is out of the tab order |
| `1cf4b58` | test(web): sidebar parity — width token, row grid, marker, footer, keyboard, mobile |
| (commit chứa báo cáo này) | docs: Round 4.2 sidebar parity report and ownership row |

**Xác nhận:** chưa push, chưa merge, chưa tag, chưa deploy. File untracked có sẵn (`.mcp.json`, ảnh trong `docs/`) không bị sửa, stage hay xoá.

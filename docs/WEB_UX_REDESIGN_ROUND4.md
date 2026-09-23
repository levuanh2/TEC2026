# AgriCarbon Web Redesign — Round 4

Hướng: **Hybrid — Guided Farmer Workspace + Cooperative Operations System** (đã chốt, không tạo lại concept).
Ngày: 2026-09-23 · Phạm vi: `web-dashboard/**` · Backend, API Carbon, công thức, hệ số, methodology: **không đổi**.

> Trạng thái chung: **PASS cho mọi mục đã kiểm tra**, có ghi chú. Chưa merge / push / deploy — dừng ở gate chờ duyệt giao diện.
> Mọi kiểm tra "real-data" chạy trên **bản build local** (vite preview :5173) + **backend local** (:8010) + **hosted Supabase**, không phải trên Render staging (staging chưa có code Round 4). Baseline "before" chụp trên staging thật.

---

## 1. Branch và base

| | |
|---|---|
| Branch | `fix/agricarbon-redesign-round4` (không upstream, không push) |
| Base | `origin/main` = `32fe933` (Merge branch 'fix/hybrid-redesign-round2') |
| Commit Round 4 | 6 (xem §15) |

File untracked có sẵn trước round (`.mcp.json`, 4 ảnh ChatGPT + 9 ảnh `.jpg` trong `docs/`) **giữ nguyên**, không sửa / stage / xoá.

## 2. Plugin / skill đã dùng

Môi trường **không có "Product Design plugin"** (đã kiểm tra danh sách skill; không tự bịa tên). Skill thực có và đã dùng:

| Skill / công cụ | Dùng ở đâu | Tác động tới quyết định |
|---|---|---|
| **hallmark** — `audit` | Chấm baseline trên ảnh render thật (không chỉ đọc source) | Phát hiện: nhãn nav 2 dòng ("Tổng quan vận hành"), gradient sidebar, nút-link bị gạch chân lẫn giọng nút, hàng bảng code bị ngắt dòng ("DEMO-FARM-\n01"), khoảng trắng chết trong drawer, card Home quá dài. |
| **hallmark** — `redesign` (multi-page flow) | Giữ design system hiện có (`theme.css` tokens) làm system khoá; không đổi theme giữa các trang (luật "inverted diversification") | Không thêm màu ngẫu nhiên; mọi màu mới là token (`--ac-sidebar-selected*`); bỏ gradient; một giọng nút cho `<button>` và `<a.btn>`; slide-over thay cột co; heading không italic. Không tạo `design.md` riêng: system đã khoá trong `theme.css` và prompt cấm đổi hướng. |
| **hallmark** — disciplines | Mobile 320–768, honest copy, locked tokens | Honest copy → bỏ nhãn "Đang chờ hệ số" trên thẻ CO₂e đã có kết quả; không tạo owner/deadline giả; không bịa diện tích. Mobile → bảng thành row-card ≤900px. |
| Visual target: `docs/ChatGPT Image *.png` (4 mockup) + `docs/*.jpg` (9 ảnh lỗi staging) | Nguồn visual target theo prompt | Home 4 vùng (mockup 1/2/3 ô 1), bộ chọn hoạt động bước 1 (mockup ô 2), repair hub + kết quả (ô 3), bảng Management theo nhiệm vụ (ô 4/5). |
| Playwright (browser QA) | Baseline + after + flow + gate | Đo overflow, cột bảng trước/sau drawer, focus, URL sau logout — mọi kết luận trong báo cáo này là số đo. |
| axe-core 4.13 (cài ở scratchpad, **không** thêm vào `package.json`) | §10 accessibility | Tìm 8 lỗi contrast + 1 progressbar thiếu tên → đã sửa → 0. |

Pre-emit self-critique (hallmark, 1–5): **P4 H4 E4 S4 R5 V4** — không trục nào < 3. Variety là tính nhất quán theo system (app, không phải landing).

## 3. Ảnh before / after đại diện

Thư mục gitignored: `web-dashboard/.qa-screenshots/round4/before/` (99 file) và `.../after/` (102 file), cùng tên route × viewport (`{role}-{route}-{1440|1280|768|390}.png`) + `flows/` (53 file) cho tương tác.

| Vấn đề | Before | After |
|---|---|---|
| Logout kẹt shell | `before/flows/farmer-after-logout-1440.png` | `after/flows/farmer-after-logout-1440.png` |
| Session hết hạn | `before/flows/farmer-session-expired-390.png` | `after/flows/farmer-session-expired-390.png` |
| Quick-fix "Không bắt buộc" | `before/flows/farmer-quickfix-1440.png` | `after/flows/farmer-quickfix-1440.png`, `...-invalid-1440.png` |
| Farmer Home dài | `before/farmer-home-1440.png` (2297px) | `after/farmer-home-1440.png` (1247px) |
| Home mobile | `before/farmer-home-390.png` (4169px) | `after/farmer-home-390.png` (1628px) |
| Journal disclaimer ×7 | `before/farmer-journal-1440.png` | `after/farmer-journal-1440.png` |
| Drawer co bảng | `before/flows/mgmt-season-drawer-1440.png` | `after/flows/mgmt-season-drawer-1440.png`, `...-390.png` |
| 3 route giống nhau | `before/mgmt-{seasons,data-gaps,carbon}-1440.png` | `after/mgmt-{seasons,data-gaps,carbon}-1440.png` |
| Carbon tab tự mâu thuẫn | `before/mgmt-season-carbon-1440.png` | `after/mgmt-season-carbon-1440.png` |
| Diện tích "—" | `before/mgmt-farms-1440.png` | `after/mgmt-farms-1440.png` |

## 4. File đã thay đổi (48 file, +1394 / −487)

- Auth: `src/App.tsx`, `src/api/auth.ts`, `src/api/client.ts`, `src/farmer/kit.tsx`, `src/farmer/pages/Account.tsx`
- Quick-fix / form: `src/farmer/ActivityForms.tsx`, `src/farmer/activityValidation.ts`, `src/farmer/CarbonRepair.tsx`
- Farmer: `src/farmer/pages/{Home,Season,Carbon}.tsx`, `src/farmer/{hybrid,CvCheck,journal,activityView}.tsx|ts`, `src/utils/activityPresentation.ts`, `src/features/activities.tsx`
- Management: `src/pages/{operations,ops,directory,dashboard,performance,season,mrv}.tsx|ts`, `src/features/{carbon,seasonMethodology}.tsx`, `src/vocab.ts`, `src/utils/area.ts` (mới)
- UI/tokens: `src/ui.tsx` (SideDrawer mới), `src/styles.css`, `src/theme.css`, `src/farmer/farmer.css`, `src/icons.tsx`
- Test mới: `src/api/{session.test,auth.dom.test}.ts(x)`, `src/farmer/{quickfix.dom.test,round4.test,cvAvailability.test}.ts(x)`, `src/utils/area.test.ts`, `tests/e2e/round4-qa.spec.ts`, `tests/e2e/round4-real.spec.ts`
- Test cập nhật theo hành vi mới (không nới assertion): `farmer-web.spec.ts`, `redesign-qa.spec.ts`, `Carbon.dom.test.tsx`, `carbon.dom.test.tsx`, `seasonMethodology.dom.test.tsx`, `hybrid.test.ts`, `ops.test.ts`, `activityPresentation.test.ts`
- Khác: `playwright.real.config.ts` (thêm `round4-real`), `AGENTS.md` (ownership), báo cáo này.

## 5. Route đã kiểm tra

**Farmer** (4 viewport, real data): `/farmer`, Journal, activity picker, form ghi hoạt động, danh sách ruộng/vụ, farm detail, plot detail, season overview, Carbon repair, Carbon quick-fix, Performance, Account, Logout, Session expired.
**Management** (4 viewport, real data): `/dashboard`, `/seasons`, `/data-gaps`, `/carbon`, `/farms`, farm detail, plot detail, season hub, Activities, Performance (vụ + vùng), Organizations, MRV (trang + tab), Carbon tab của vụ, season drawer, Logout.
Activity detail drawer: kiểm qua unit test presenter + `round3-qa` (mock); không chụp riêng trên real data (**NOT TESTED** ảnh chụp riêng).

## 6. P0 / P1 đã sửa thế nào

### P0.1 Logout / session-expired — **PASS**
Nguyên nhân gốc (đo được, không đoán): `signOut()` xoá session Supabase nhưng state `session` trong `App` vẫn giữ; effect theo `path` thấy `/login` + role cũ → `applyRoleRedirect` đẩy lại `/farmer` (baseline: URL `/farmer`, shell còn, không có form login — cả 2 vai trò). Token được Supabase tự refresh không bao giờ tới API client → sau ~1 giờ mọi request 401.
Sửa: một tín hiệu `onAuthEnded('signed_out'|'expired')` → trong cùng một render: xoá session/viewer/cache, `history.replaceState('/login')`. `onAuthStateChange` cập nhật token. 401 có token → refresh 1 lần + retry, hỏng → kết thúc phiên, các request sau bị chặn trước khi ra mạng. Login hiển thị "Bạn đã đăng xuất." / "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại." + nút "Đăng nhập lại", quay lại trang bị gián đoạn qua `next=`. Sign-out chờ revoke tối đa 1,5s rồi vẫn rời shell (đo: ở 390px request revoke > 3s). Lỗi đăng nhập tiếng Anh của Supabase → tiếng Việt.
**Real-data gate tìm ra 1 lỗi thật và đã sửa:** Supabase phát `SIGNED_OUT` sau refresh hỏng → shell nhận "ended" 2 lần → `next=/login`. Giờ tín hiệu chỉ phát 1 lần mỗi phiên, và không đổi URL khi đã ở `/login` → không redirect loop.

### P0.2 Carbon quick-fix — **PASS**
"Sửa ngay" truyền mã gap server báo cho **đúng bản ghi đó** (`straw_days_before_cultivation`, `straw_dry_matter`, …) → form bật `required` (dấu `*`, `aria-required`) cho đúng trường; hai trường rơm không bao giờ còn "Không bắt buộc" (khi không phải quick-fix: "Cần để tính phát thải"). Help text tiếng Việt gắn `aria-describedby`. Số ngày: số nguyên ≥ 0. Tỷ lệ chất khô: > 0 đến 1 (khớp ràng buộc backend `gt=0, le=1`), nhận `0,85` và `0.85`, chuẩn hoá về số trước khi gửi (contract hiện có). Lỗi nằm ngay dưới trường, có icon + chữ, hiện ngay khi gõ sai; trường trống bị chặn khi lưu. Focus rơi vào trường gap đầu tiên. Save hỏng → sheet giữ nguyên, giữ giá trị. Save xong → invalidate readiness; gap chỉ biến mất khi server trả readiness mới.

### Farmer (§6) — **PASS**
- Home còn 4 vùng: bối cảnh vụ · **một** CTA chính (bổ sung dữ liệu / ghi hoạt động hôm nay / tính Carbon / xem kết quả — theo state server) · tóm tắt (hoạt động, nước, phân bón, Carbon) + chi phí trực tiếp panel riêng ghi rõ "Không dùng để tính CO₂e" + link Hiệu suất · 5 hoạt động gần nhất + "Xem toàn bộ nhật ký". Đo: 1 nút primary trên Home ở cả 1440 và 390.
- Bỏ khỏi Home: lưới ghi nhanh, snapshot hiệu suất, "Cần chú ý", khuyến nghị, CV.
- "Kiểm tra lá lúa": ẩn khi server trả 503 `backend_not_configured` (probe = đọc lịch sử CV) hoặc `VITE_FEATURE_CV=false`; không flash khi đang tải.
- Disclaimer: chuỗi tiếng Anh của seed không còn trên từng dòng; ledger có **một** banner "Dữ liệu minh họa — …". Đo: 7 → 0 lần.
- Một entry point "Ghi hoạt động" → bộ chọn loại hoạt động (icon + nhãn + mô tả) là bước 1; trang vụ cũng chỉ còn nút này.
- Ngày: dưới ô date native có dòng đọc kiểu Việt ("Thứ Bảy, 06/09/2026") — native picker vẫn theo locale trình duyệt (xem §12).

### Carbon (§7) — **PASS**
- Không đổi readiness engine, công thức, hệ số, `factor_unavailable`, kết quả server. Factor limitation vẫn tách khỏi gap user sửa được (không có "Sửa ngay").
- Panel phương pháp: khi đã đủ → một dòng `details` đóng "Thông tin phương pháp tính — đã đủ", không còn CTA "Khai báo…" cạnh tranh.
- Farmer, có kết quả mới: kết quả dẫn đầu (tổng vụ → CO₂e/kg → nguồn → "Cách tính" trong disclosure); hub chỉ hiện khi kết quả cũ hoặc còn gap. Mã nguồn thô (`ch4_…`) không còn dưới nhãn.
- Management Carbon tab: không còn "Xem Carbon" trong tab Carbon; nút tính chỉ tồn tại khi chạy được và đặt tên theo state ("Tính Carbon" / "Tính theo kịch bản này" / "Tính lại"); còn gap → không có nút tính, có link tới nơi bổ sung; empty state chỉ nhắc control đang hiện và bật. Provenance vào disclosure.

### Management (§8) — **PASS** (drawer, route), **PASS có điều kiện** (diện tích)
- `/seasons`: toàn bộ vụ; cột Nông hộ · Thửa · Vụ · Giai đoạn · Gieo sạ · Thu hoạch · Carbon (phụ); lọc trạng thái vụ.
- `/data-gaps`: mặc định **chỉ** vụ có gap user sửa được (vụ chỉ vướng hệ số không được tính là gap, empty state trỏ sang Carbon); cột Cần bổ sung · Thông tin còn thiếu · Carbon · "Xử lý"; nhấn mạnh hàng bằng vạch trái.
- `/carbon`: Sẵn sàng · Kết quả · Độ mới · Tổng CO₂e · CO₂e/kg · hành động theo state; lọc trạng thái Carbon.
- Không có owner / deadline / số liệu nào server không trả.
- Drawer: slide-over 460px, full-screen ≤900px, dialog modal, focus trap, Esc/backdrop đóng, focus trả về nút đã mở. Đo real data: độ rộng cột trước/sau mở drawer **bằng nhau** (1440: 149,173,160,… = 149,173,160,…; baseline 159→98px).
- Sidebar: không gradient; active = nền sáng có viền + vạch + đậm, một dòng (sidebar 240px).
- Diện tích nông hộ: `/v1/farms` **không có** area. Danh sách giờ cộng `area_ha` các thửa — **cùng quy tắc** trang chi tiết và rollup server (`read_repo.py` farm-performance). Thửa thiếu diện tích không bị tính là 0; tổng được ghi "còn thửa chưa ghi". Chi phí: +1 request `/farms/{id}/plots` mỗi nông hộ (3 với tenant demo) — xem blocker B2.

### Dữ liệu / thuật ngữ (§9) — **PASS**
- Presenter chi tiết đọc `method` theo loại hoạt động: bản ghi rơm "Vùi vào đất" ở list **và** detail (trước: detail "Chưa rõ" vì tra từ điển tưới). Không sửa dữ liệu thật.
- Thuật ngữ: Nước tưới · Số ngày trước khi làm đất · Tỷ lệ chất khô của rơm · Phương pháp xử lý rơm · Dữ liệu minh họa · Ảnh · Tài liệu (loại minh chứng MRV `photo` → "Ảnh"; hash chuyển vào tooltip).
- Thẻ CO₂e/kg: bỏ nhãn "Đang chờ hệ số / Chờ GWP theo QĐ 4801" đặt cứng trên mọi thẻ (kể cả khi đã có kết quả).

## 7. Carbon logic integrity — **PASS**
Không file backend nào đổi (`git diff 32fe933 -- backend supabase` rỗng). Không công thức/hệ số/logic Carbon trong client. Client chỉ map `flow`/`code` do server trả sang control; gap map bằng bảng `GAP_FIELD` (hiển thị), readiness vẫn là nguồn sự thật duy nhất.

## 8. Test

| Lệnh | Kết quả |
|---|---|
| `npx tsc --noEmit` | **PASS** |
| `npx vitest run` | **PASS** — 41 file, 336 test, 0 fail (trước round: 306) |
| `npm run build` | **PASS** (cảnh báo chunk > 500 kB có từ trước) |
| Playwright mock: `round4-qa` 6, `round3-qa`, `web-smoke`, `farmer-web` | **PASS** — 23 passed, 0 failed, 20 skipped (skip = spec cần credential, chạy riêng bên dưới) |
| `round4-real` (real, REDESIGN_*) | **PASS** 5/5 — Farmer logout + Back, Management logout, session hết hạn (không loop), quick-fix, drawer 1440+390 |
| `redesign-qa` (real, REDESIGN_*) | **PASS** 15/15 qua các lượt: lượt đầu 12/15 (3 fail = heading đổi tên, race placeholder, nhãn search đổi) → sửa → 2/2; test 4-viewport lượt 2 phát hiện **tràn 99px ở `/seasons` 768px** → sửa → 2/2 pass (13,6 phút). |

Test không làm được trên mock (mock viewer không thuộc HTX nào, không có Supabase): logout/expiry/quick-fix/drawer → chuyển sang `round4-real` + DOM test.

## 9. Responsive — 0px overflow ngang

| Route (sweep real, 24 route) | 1440 | 1280 | 768 | 390 |
|---|---|---|---|---|
| Farmer (9 route) | PASS | PASS | PASS | PASS |
| Management (15 route) | PASS | PASS | PASS¹ | PASS |

¹ `/seasons` 768 tràn 99px ở lượt đầu (wrapper bảng không `min-width:0` sau khi bỏ `ops-split`) → sửa + bảng thành row-card ≤900px → probe 0px, `redesign-qa` 4-viewport pass. Drawer ≤900px = full-screen (đo: rộng đúng 390px). Mock gate `round4-qa` kiểm 18 route × 4 viewport: PASS.

## 10. Accessibility (đo, không tuyên bố "WCAG pass")

axe-core 4.13, tag `wcag2a/2aa/21a/21aa`, real data, 1440px, 16 bề mặt (7 Farmer, 7 Management, quick-fix sheet đang hiện lỗi, season drawer):

| | Lượt 1 | Sau sửa |
|---|---|---|
| color-contrast | 8 node (Home 3, Journal 1, Carbon 3 + 1 phát hiện sau) | **0** |
| aria-progressbar-name | 1 (MRV) | **0** |

Hành vi: tab đầu tiên = skip link trên 14/14 trang; mỗi trang 1 `h1`; drawer: focus vào trong, Tab không thoát, Esc đóng, focus trả về (gate tự động); quick-fix: `aria-required`, `aria-invalid`, lỗi gắn `aria-describedby`, lỗi không chỉ bằng màu (icon + chữ); nav active: nền + viền + vạch + đậm; `prefers-reduced-motion` tắt animation drawer. Touch target: không đo lại toàn bộ trong round này (**NOT TESTED** ngoài những gì `round3-qa` đã gate: 44px journal).
Phạm vi axe **không** gồm: 1280/768/390, trang login, form tạo mới từng loại hoạt động, Organizations/Performance vùng.

## 11. Performance (Management, real data, cùng backend local, 2 lượt)

| Route | Baseline `32fe933` first row / settled | Round 4 first row / settled |
|---|---|---|
| `/dashboard` | 5,9–6,8s / 10,4–12,3s | 6,5–7,7s / 10,8–16,0s |
| `/seasons` | 4,1–4,2s / 13,8–14,0s | 5,0–5,2s / 13,4–24,4s |
| `/data-gaps` | 7,0–8,8s / 14,2–15,9s | 2,9–5,6s / 13,6–16,3s |
| `/carbon` | 6,9s / 10,0–11,9s | 5,1–5,3s / 13,4–15,4s |

Round 4 **không đổi cách fetch** của ops (cùng `useOperations`); chênh lệch nằm trong biến thiên của backend (lượt 1 Round 4 là lượt "nguội"). Không false empty state, không "Chưa gán tổ chức" khi đang tải, skeleton giữ chỗ, cột không nhảy khi row stream. **Readiness vẫn tăng tuyến tính theo số vụ** → blocker B1.

## 12. Chưa làm / giới hạn

- Ô ngày: vẫn là `<input type=date>` native, hiển thị theo locale trình duyệt (Chrome tiếng Anh → `MM/DD/YYYY`); đã thêm dòng đọc ngày kiểu Việt ngay dưới. Thay bằng date picker riêng: chưa làm.
- Sau save quay lại đúng vị trí trong ledger: dựa vào hành vi sẵn có (không cuộn lại đầu); **NOT TESTED** riêng.
- Activity detail drawer (Farmer/Management) không chụp riêng trên real data.
- `QuickActions` (lưới chọn nhiều vụ) không còn trang nào dùng; giữ lại component + unit test, chưa xoá (xoá cần đồng ý).
- Management trên mock tenant không có HTX → drawer/route test chỉ chạy real.
- Không chạy trên Render staging (chưa deploy — đúng yêu cầu).
- Chưa tạo `design.md` riêng (system khoá trong `theme.css`).

## 13. Backend blockers (không sửa trong round này)

- **B1 — readiness N+1:** Management gọi `GET /v1/crop-seasons/{id}/carbon/readiness` + `GET /v1/crop-seasons/{id}/carbon` cho từng vụ (4 song song). 6 vụ → settle 10–24s. Đề xuất: endpoint bulk `GET /v1/organizations/{id}/carbon/readiness` trả readiness + tóm tắt kết quả cho mọi vụ (đã nêu ở `WEB_UX_REDESIGN_ROUND3.md` §12).
- **B2 — `/v1/farms` không có diện tích:** đề xuất thêm `area_ha` (tổng `plots.area_ha`) + `area_complete` vào list response, để bỏ N request plots.
- **B3 — response lỗi thiếu CORS header:** khi backend quá tải (lần tải 72s `/seasons` 390px), `GET /v1/crop-seasons/8681516d-…/carbon` trả lỗi **không có** `Access-Control-Allow-Origin` → trình duyệt báo CORS thay vì lỗi thật. Đề xuất: bảo đảm exception handler/timeout đi qua `CORSMiddleware` (hoặc middleware bọc ngoài cùng).
- **B4 — không có capability endpoint cho CV:** frontend đang dùng 503 của lịch sử CV làm probe. Đề xuất `/health` trả `cv_available`.

## 14. Git status (tại thời điểm viết)

Sạch ngoài file untracked có sẵn trước round (`.mcp.json`, `docs/*.jpg`, `docs/ChatGPT Image *.png`) — không đụng tới.

## 15. Commit list

```
3acfba7 fix(auth): logout and an expired session end at the login screen
fc53635 fix(carbon): the quick-fix form asks for what readiness says is missing
c925081 feat(farmer): a Home that says what to do next, and one story per record
97c3c7f feat(management): three routes, three jobs; Carbon actions follow state
4424af9 fix(ui): overlay drawer, flat sidebar with a readable active row
7da676a test(web): Round 4 gates, the fixes they found, and the report
```

Gate: **dừng tại đây** — không merge, không push, không deploy, không đổi `autoDeployTrigger`. Chờ duyệt giao diện.

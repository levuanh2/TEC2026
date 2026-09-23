# AgriCarbon Web — Round 4.1 (UX hotfix)

Ngày: 2026-09-23 · Phạm vi: `web-dashboard/**` (+ một dòng ownership trong `AGENTS.md`).
Backend, API contract, công thức Carbon, hệ số, GWP, readiness, methodology, MRV workflow, phân quyền, dữ liệu thật: **không đổi**.

> **Verdict: PASS WITH KNOWN LIMITATIONS.**
> Mọi mục bắt buộc đã sửa và có bằng chứng render + test. Các giới hạn nằm ở §11: axe-core không chạy lại, Farmer chỉ chụp 1440/390, kiểm tra trên build local chứ không phải staging, blocker hiệu năng backend giữ nguyên.
> Chưa push, chưa merge, chưa deploy. Round này dừng ở gate chờ duyệt giao diện.

---

## 1. Branch và base

| | |
|---|---|
| Branch | `fix/agricarbon-redesign-round4-1` (tạo từ `origin/main`, không push) |
| Base | `origin/main` = `b76734c0904914013b331cb08668393b8f24411e`, khớp SHA dự kiến |
| Môi trường kiểm tra | `vite preview` bản build local (:5173) + backend local (:8010) + **hosted Supabase**. Không kiểm trên Render staging. |
| Credential | Truyền qua biến môi trường `REDESIGN_*` của tiến trình. Không ghi vào source, test hay báo cáo. |

Các file untracked có sẵn trước round (`.mcp.json`, `docs/*.jpg`, `docs/ChatGPT Image *.png`) được giữ nguyên: không sửa, không stage, không xoá.

## 2. Skill / công cụ

| Yêu cầu | Thực tế |
|---|---|
| Product Design plugin / Product Design Audit | **Không có** trong môi trường này (đã kiểm tra danh sách skill). |
| Design QA | **Không có.** |
| Công cụ thay thế trước khi sửa | Playwright (Chrome) trên giao diện render thật: chụp ảnh "before", đo bounding box từng nút thao tác, đo overflow của wrapper, đọc computed style của CTA/tab, rồi soi ảnh bằng mắt. Script: `web-dashboard/.qa-screenshots/round4-1-capture.mjs` (gitignored). |
| `hallmark audit` | Có skill này. **Chỉ gọi sau khi sửa**, để audit ảnh "after" (xem §4.6). Round này không dùng nó cho audit trước khi sửa. |

## 3. File thay đổi

`git diff --stat b76734c..4d4b6b2`: 19 file, +874 / −71. Tính cả commit báo cáo thì có thêm file này và `AGENTS.md`.

- `/carbon`: `src/pages/operations.tsx`, `src/styles.css`
- Token màu: `src/theme.css`, `src/styles.css`, `src/farmer/tokens.css`, `src/farmer/farmer.css`
- Form: `src/farmer/ActivityForms.tsx`, `src/farmer/farmer.css`
- Demo marker: `src/utils/activityPresentation.ts`, `src/farmer/activityView.ts`, `src/api/activities.ts` (PATCH bỏ key `note` khi ghi chú không đổi)
- Test mới: `src/pages/carbonRows.test.ts`, `src/farmer/round41.dom.test.tsx`, `src/utils/demoMarker.test.ts`, `tests/e2e/round41-helpers.ts`, `tests/e2e/round41-qa.spec.ts`, `tests/e2e/round41-real.spec.ts`
- Test cập nhật theo thiết kế mới (không hạ assertion): `src/farmer/ActivityForms.dom.test.tsx` (nhãn disclosure mới), `tests/e2e/farmer-web.spec.ts` (tìm "Không bắt buộc" trong disclosure, vì ghi chú giờ đứng trước), `tests/e2e/round4-qa.spec.ts` (header `/carbon` mới), `playwright.real.config.ts` (thêm `round41-real`)

## 4. Vấn đề, quyết định thiết kế, before/after

Ảnh nằm trong thư mục gitignored `web-dashboard/.qa-screenshots/round4-1/{before,after}/`: 37 ảnh "before" và 41 ảnh "after", cùng tên file, cùng route, state và viewport. Số đo gốc nằm trong `measure.json` của từng thư mục.

### 4.1 P1: `/carbon` bị cắt thao tác

**Before (đo được).** Bảng có 9 cột (Nông hộ, Thửa, Vụ, Sẵn sàng, Kết quả, Độ mới, Tổng CO₂e, CO₂e/kg, thao tác). Wrapper `.ops-table__wrap` rộng hơn khung nhìn 45px ở 1363px và 112px ở 1280px, trong khi `document.scrollWidth` vẫn báo **0**. Với dữ liệu thật hiện tại (6 vụ đều "Thiếu dữ liệu"), 5 cột kết quả chỉ hiện "—" hoặc "Chưa tính".

| Viewport | Nút bị cắt (before) | Nút bị cắt (after) | Wrapper tràn (before → after) |
|---|---|---|---|
| 1440 | 0/12 | 0/12 | 0 → 0 |
| **1363** | **6/12** (6 nút "Chi tiết": right 1361 > giới hạn 1331) | **0/12** | **45 → 0** |
| 1280 | **12/12** (cả nút chính "Bổ sung dữ liệu": right 1307 > 1256) | **0/12** | **112 → 0** |
| 768 | 0/12 | 0/12 | 0 → 0 |
| 390 | 0/12 | 0/12 | 0 → 0 |

Ảnh: `before/mgmt-carbon-1363.png` (nút "Chi tiết" chỉ còn một lát mỏng ở mép phải) và `after/mgmt-carbon-1363.png`. Tương tự cho `-1280`, `-768`, `-390`, và bản `-full` (chụp cả trang).

**Quyết định.** Sửa bằng cách thiết kế lại hierarchy của bảng, không dùng `overflow: hidden`:
- Còn **6 cột**: Nông hộ · Thửa · Vụ · **Trạng thái Carbon** (một badge có chữ + icon) · **Cần xử lý · Kết quả** · thao tác.
- Cột "Cần xử lý · Kết quả" hiển thị theo trạng thái:
  - thiếu dữ liệu: "Thiếu N thông tin" kèm danh sách mục thiếu;
  - giới hạn hệ số: tên giới hạn, kèm dòng "Nhập thêm dữ liệu không giải quyết được";
  - sẵn sàng: "Đủ dữ liệu, chưa tính";
  - đã tính: "X kg CO₂e" kèm dòng "Y kg CO₂e / kg lúa";
  - cần tính lại: "Dữ liệu đã đổi sau lần tính" kèm dòng "Kết quả cũ: X kg CO₂e".
  Không có số nào do client tự tính; tất cả lấy nguyên giá trị server trả về.
- Mỗi hàng có **đúng một** nút có nhãn, nhãn theo trạng thái. Nút tô đặc khi hàng cần hành động (sẵn sàng tính / cần tính lại), nút viền ở các trạng thái còn lại. "Chi tiết" là nút icon (chevron) 40×40, accessible name đầy đủ (`Chi tiết vụ …, Thửa …, Hộ …`), có `title` để hiện tooltip.
- **Dưới 1180px** mỗi hàng thành một card. Dòng đầu gồm Nông hộ, Thửa, Vụ (ở 390px chia 2 cột: Nông hộ + Thửa, rồi Vụ + trạng thái). Tiếp theo là trạng thái và vấn đề, cuối cùng là hàng thao tác rộng hết card, nút 44px trên mobile.
- `/seasons` (lệch 4px) và `/data-gaps` (lệch 1px) cũng bị tràn wrapper ở 1280px. Nút không bị cắt, nhưng wrapper vẫn cuộn ngang. Mình giảm padding ngang của ô từ 14px xuống 10px trong khoảng 901–1320px, và giữ mã code không ngắt dòng. After: 0px.

### 4.2 P1: xanh TDMU tràn vào workspace

**Before.** CTA dùng `oklch(26% 0.022 165)`, một màu gần đen nhưng ngả xanh lá trên diện tích lớn. Accent của workspace (link, tab đang chọn, "Xuất PDF", "Mở vụ mùa", "Xem hoạt động cần bổ sung", thanh tiến độ) trỏ thẳng vào `--ac-accent*`, tức xanh rừng TDMU. Focus ring cũng là xanh lá.

**Quyết định.** Chỉ đổi token dùng chung, không sửa từng nút:
- Token workspace mới `--ac-work`, `--ac-work-strong`, `--ac-work-soft`. CTA `oklch(28% 0.035 257)` (graphite navy). Marker tab `oklch(33% 0.045 257)`. Focus ring xanh dương `oklch(50% 0.17 257)`. Trên sidebar, focus ring đổi sang marker sáng, vì vòng xanh dương trên nền xanh rừng chỉ đạt khoảng 2:1.
- `--accent`, `--brand*` (Management) và `--fw-accent*` (Farmer) trỏ sang slate.
- Xanh lá chỉ còn nghĩa ngữ nghĩa: bước MRV đã hoàn thành (`--ac-success`), dấu "ok" của Farmer (`--fw-ok`), role `#E2F0CB`. Card "sẵn sàng tính" của Farmer chuyển sang role nước (`#B5EAD7`), khớp với Management.
- Sidebar và logo giữ nguyên. Thanh điều hướng dưới của Farmer trên mobile là primary navigation, nên giữ xanh.

Ảnh: `before|after/farmer-home-1440.png` ("Bổ sung ngay"), `mgmt-season-carbon-tab-1440.png` (tab "Carbon" + "Xem hoạt động cần bổ sung"), `mgmt-mrv-1440.png`, `mgmt-season-drawer-1440.png` ("Mở vụ mùa"), `farmer-quickfix-1440.png` ("Lưu thay đổi"), `farmer-journal-1440.png`. Ảnh focus: `after/focus-carbon-primary-1363.png`, `after/focus-sidebar-1363.png`.

### 4.3 P2: form Nước tưới

**Before.** Thứ tự là: disclosure "Thông tin bổ sung +" đang đóng, rồi "Ghi chú" nằm ngay bên dưới, ngoài disclosure. Nhìn vào, người dùng không biết disclosure đang ẩn gì (`before/farmer-form-irrigation-1440.png`).

**Quyết định.** Chọn phương án 2 của brief: đặt tên disclosure theo đúng nội dung của nó. Ghi chú là lời của nông hộ, nên giữ ở màn chính (quyết định từ các round trước).
- Summary giờ là "**Thông tin kỹ thuật và chi phí**", dòng thứ hai liệt kê các trường bên trong: "Thời gian tưới, mực nước, máy bơm · chi phí". Form gieo sạ chỉ ẩn chi phí, nên summary là "Chi phí".
- Disclosure chuyển xuống **cuối form**, sau Ghi chú. Sau summary đang đóng chỉ còn footer.
- Trường thiết yếu (Ngày thực hiện, Hình thức tưới, Lượng nước) và Ghi chú luôn hiện. Payload và logic không đổi.

### 4.4 P2: validation của quick-fix

**Before.** Gõ `-1` thì lỗi đã nằm cạnh trường và có `aria-invalid` + `aria-describedby`. Nhưng nút "Lưu thay đổi" vẫn trông hoàn toàn hợp lệ (`before/farmer-quickfix-invalid-*.png`, đo được `aria-disabled=null`).

**Quyết định.** Khi form có lỗi đang hiển thị, nút lưu mang `aria-disabled="true"`: nền trũng, viền nét đứt, con trỏ `not-allowed`. Nút không dùng `disabled`, để vẫn nhận focus; bấm vào thì focus nhảy tới trường sai đầu tiên. Nút được mô tả bằng `aria-describedby` trỏ tới dòng "Chưa lưu được — còn N ô cần sửa." nằm trong footer, cạnh nút. Form mới mở chưa có lỗi thì nút trông bình thường. `0,85` và `0.85` vẫn hợp lệ, cả hai gửi đi `0.85`. Quy tắc readiness và logic Carbon không đổi.

### 4.5 P2: demo marker

**Before.** Mở record seed (rơm, từ "Sửa ngay"), ô Ghi chú chứa sẵn `DEMO / SYNTHETIC DATA — NOT FIELD DATA, NOT OFFICIAL MRV DATA`, trông như ghi chú do nông hộ tự nhập. Lưu thì chuỗi này bị gửi lại. Nếu người dùng xoá nó thì marker mất (`before/farmer-quickfix-note-{1440,390}.png`, chụp từ worktree baseline).

**Quyết định.**
- `splitDemoMarker()` tách marker khỏi note. Marker hiện thành badge "**Dữ liệu minh họa**" kèm dòng giải thích tiếng Việt, ô Ghi chú chỉ chứa lời của người dùng (`after/farmer-quickfix-note-*.png`).
- Ghi chú không đổi thì **không gửi** key `note` trong PATCH. Backend (`service.py:247`, `update_note="note" in model_fields_set`) giữ nguyên giá trị đã lưu, marker còn nguyên.
- Người dùng viết ghi chú thì gửi `"<ghi chú>\n\n<marker>"`, nên marker vẫn được giữ.
- Timeline và drawer chi tiết hiện lời của người dùng, không bao giờ hiện chuỗi tiếng Anh.
- Dữ liệu backend không bị xoá hay sửa. Round này không lưu gì lên hosted.

### 4.6 Audit sau khi sửa (`hallmark audit`, chỉ đọc)

0 critical · 0 major · 4 minor:
- minor: ở `/carbon`, badge "Thiếu dữ liệu" và dòng "Thiếu N thông tin" nói hai lần cùng một ý. Chấp nhận được: badge là trạng thái, dòng kia là số lượng + danh sách.
- minor (có từ trước): thanh điều hướng dưới của Farmer trên mobile dùng `linear-gradient` giữa hai tông xanh. Round này không đụng tới.
- minor (có từ trước): banner trong tab Carbon của vụ có cả chấm lẫn icon trước "Thiếu dữ liệu".
- minor: ở 1440px, giữa cột vấn đề và nút thao tác còn khoảng trống rộng. Chấp nhận được, vì đổi lại thao tác không bao giờ bị đẩy ra ngoài.

Tự chấm trước khi nộp: P4 H4 E4 S4 R5 V4.

**Soi bằng mắt (§10 của brief):** thao tác nhìn thấy trọn vẹn ở cả 5 viewport. Hierarchy rõ hơn: mỗi hàng có một trạng thái, một vấn đề, một nút. Card chỉ xuất hiện dưới 1180px. Hai CTA không cạnh tranh nhau, vì nút phụ là icon không viền. Pastel đúng ngữ nghĩa. Xanh TDMU đã rời workspace. Card mobile vẫn có đủ Nông hộ, Thửa và Vụ.

## 5. Viewport đã kiểm

| | 1440 | **1363** | 1280 | 768 | 390 |
|---|---|---|---|---|---|
| `/carbon`: bounding box + overflow | ✓ | ✓ | ✓ | ✓ | ✓ |
| `/seasons`, `/data-gaps`: overflow + nút | ✓ | ✓ | ✓ | ✓ | ✓ |
| Management: season tab / drawer / MRV (ảnh) | ✓ | — | — | — | MRV ✓ |
| Farmer: Home, Journal, form Nước tưới, Carbon, quick-fix, demo marker (ảnh) | ✓ | — | — | — | ✓ |
| `redesign-qa` (sweep 4 viewport có sẵn: 1440/1280/768/390) | ✓ | — | ✓ | ✓ | ✓ |

## 6. Kết quả bounding box `/carbon` (real data, 6 vụ, 12 control)

Cách đo: `measureRowActions` trong `tests/e2e/round41-helpers.ts`. Mọi `scrollLeft` được đặt về 0 trước khi đo, chỉ cuộn cửa sổ theo chiều dọc. Với từng control kiểm tra `right ≤ min(containerRight, viewportWidth)`, `left ≥ containerLeft`, `w > 0`, `h > 0`, và phần tử trên cùng tại tâm control phải là chính nó (`elementFromPoint`). Phép đo không dựa vào `document.scrollWidth`.

After: **60/60 phép đo pass** (12 control × 5 viewport), wrapper 0px, trang 0px. Ở 768 và 390px mọi control cao ≥ 40px (nút mobile 44px). Lượt đo đầu tiên trên baseline dùng `scrollIntoView`, làm wrapper tự cuộn ngang và che mất lỗi. Mình phát hiện điều đó và sửa cách đo trước khi ghi kết quả before ở §4.1.

## 7. Contrast định lượng (token/nút/tab vừa đổi)

Tính theo WCAG 2.x, chuyển oklch sang sRGB (`.qa-screenshots/round4-1-contrast.mjs`). **26/26 cặp vượt ngưỡng**:

| Cặp | Tỷ lệ | Ngưỡng |
|---|---|---|
| Chữ CTA trên nền CTA | 14.38:1 | 4.5 |
| Chữ CTA trên nền hover | 17.47:1 | 4.5 |
| Mép CTA so với nền Management / Farmer | 13.14 / 13.61:1 | 3 |
| Marker tab đang chọn so với paper / ground | 11.40 / 11.00:1 | 3 |
| Chữ link/accent trên paper / sheet | 10.97 / 11.61:1 | 4.5 |
| Chữ nút ghost trên nền hover | 10.02:1 | 4.5 |
| Accent workspace (bar, bước hiện tại) so với paper | 7.90:1 | 3 |
| Focus ring so với paper / sheet | 5.71 / 6.04:1 | 3 |
| Focus ring trên sidebar (marker sáng) | 6.73:1 | 3 |
| Chữ tab Farmer đang chọn | 15.19:1 | 4.5 |
| Bước MRV đã hoàn thành (success) | 6.57:1 | 3 |
| Nút lưu bị chặn: chữ / viền nét đứt | 8.62 / 3.57:1 | 4.5 / 3 |
| Dòng "Chưa lưu được" | 7.58:1 | 4.5 |
| Dòng liệt kê trường của disclosure (muted) | 5.38:1 | 4.5 |
| Badge demo: chữ / viền | 6.46 / 4.64:1 | 4.5 / 3 |
| Chevron chi tiết | 10.58:1 | 3 |
| Card Farmer "sẵn sàng": chữ / viền | 6.39 / 3.74:1 | 4.5 / 3 |
| Badge attention `/carbon` | 6.58:1 | 4.5 |

## 8. Accessibility đã kiểm (không tuyên bố đạt chuẩn WCAG)

- Bàn phím + focus-visible: nút chính và nút chi tiết của `/carbon` đều có `:focus-visible` với vòng 2px `oklch(0.5 0.17 257)`. Link sidebar có vòng marker sáng (đo computed style + ảnh). `redesign-qa` cũng kiểm tra bàn phím tới được primary action.
- Drawer: mở từ nút chi tiết ở 1363px, Escape đóng, focus trở về đúng nút đã mở (`round41-real`). Focus trap được `round4-real` kiểm tra.
- Icon button: accessible name đầy đủ (assert `^Chi tiết vụ `).
- Trạng thái không chỉ dựa vào màu: badge có chữ, và icon ở các trạng thái thiếu dữ liệu / giới hạn / cũ / đã tính. Nút bị chặn có viền nét đứt kèm dòng chữ.
- Target: control ở `/carbon` cao ≥ 40px (desktop 40px, mobile 44px). `redesign-qa` kiểm tra mọi control của Farmer ≥ 40px.
- Lỗi inline nằm trong cùng `[data-field]` với trường, gắn bằng `aria-describedby`, có `aria-invalid`.
- **Chưa làm:** axe-core không chạy lại trong round này.

## 9. Test (số thật, chạy trên HEAD `4d4b6b2`)

| Lệnh | Kết quả |
|---|---|
| `npx tsc --noEmit` | PASS |
| `npx vitest run` | PASS: **44 file, 354 test**, 0 fail, 0 skip (Round 4 báo 336; +18 test mới) |
| `npm run build` | PASS (cảnh báo chunk > 500 kB có từ trước) |
| Playwright mock: `round4-qa`, `round3-qa`, `web-smoke`, `farmer-web`, `round41-qa` (+ các spec real tự skip khi thiếu credential) | **27 passed, 0 failed, 26 skipped**. 26 skip là các spec cần credential, chạy riêng ở dòng dưới. |
| `round41-real` + `round4-real` (real, `playwright.real.config.ts`) | **11/11 passed** (6 Round 4.1 + 5 Round 4) |
| `redesign-qa` (real, config mặc định, dùng lại preview real) | **15/15 passed** (10,0 phút) |

Trong lúc làm, một test fail và đã sửa: `round41-real` quick-fix fail vì Playwright từ chối click nút có `aria-disabled`. Test chuyển sang `click({ force: true })`, assertion "không có request ghi nào" giữ nguyên. Detector xanh TDMU ban đầu dùng ngưỡng chroma 0.04, nên không bắt được CTA cũ (0.022). Mình hạ ngưỡng xuống 0.015 cho nền và viền, và thêm test chứng minh detector nhận ra đúng các màu của Round 4.

Test chứng minh không mất dữ liệu (DOM, `round41.dom.test.tsx` + `demoMarker.test.ts`): ghi chú không đổi thì PATCH không có key `note`; ghi chú mới được lưu thành `"<ghi chú>\n\n<marker>"`; split/join round-trip không mất marker hay ghi chú; record không có marker thì xoá ghi chú vẫn gửi `null` như trước.

## 10. Carbon / scientific logic: xác nhận không đổi

`git diff b76734c..HEAD -- backend supabase app ml` rỗng (0 dòng). Client không thêm công thức, hệ số hay quy tắc readiness nào. Cột "Cần xử lý · Kết quả" chỉ đổi cách trình bày trạng thái (`view model`) và tổng CO₂e mà server đã trả về. Payload của Carbon quick-fix không đổi. Thay đổi duy nhất ở tầng API là PATCH bỏ key `note` khi ghi chú không đổi; hành vi này đúng với contract hiện có (`model_fields_set`).

## 11. Chưa kiểm / giới hạn

- Chưa chạy trên Render staging (chưa deploy, theo yêu cầu). Mọi kết quả trên là bản build local + backend local + hosted Supabase.
- Dữ liệu thật hiện có 6 vụ, tất cả "Thiếu dữ liệu". Các trạng thái sẵn sàng / đã tính / cần tính lại / giới hạn hệ số của `/carbon` chỉ được kiểm bằng unit test (`carbonRows.test.ts`), chưa có ảnh real.
- Ảnh Farmer chỉ chụp ở 1440 và 390. 1280/768 được `redesign-qa` sweep kiểm (overflow, target), không chụp riêng cho round này.
- axe-core không chạy lại.
- Ô ngày vẫn là `<input type=date>` native, hiển thị theo locale của trình duyệt (Chrome tiếng Anh ra `MM/DD/YYYY`). Dòng đọc ngày kiểu Việt ngay bên dưới giữ nguyên. **Native picker chưa được Việt hoá.**
- Thanh điều hướng dưới của Farmer trên mobile vẫn dùng gradient giữa hai tông xanh sidebar (có từ trước, ngoài phạm vi).
- Chưa đo lại hiệu năng. Cách fetch không đổi.

## 12. Blocker backend còn lại (không sửa trong round này)

- **B1: readiness N+1.** `/carbon`, `/seasons`, `/data-gaps` vẫn gọi readiness + carbon cho từng vụ (4 request song song), nên mất 10–24s mới ổn định. Đề xuất: endpoint bulk `GET /v1/organizations/{id}/carbon/readiness`.
- B2 (`/v1/farms` không có diện tích), B3 (response lỗi thiếu CORS header khi backend quá tải), B4 (không có endpoint capability cho CV): giữ nguyên như `WEB_UX_REDESIGN_ROUND4.md` §13.

## 13. Commit

```
4d4b6b2 test(web): Round 4.1 gates — /carbon action geometry, brand green, form semantics
55ebea0 fix(management): /seasons and /data-gaps no longer scroll sideways at 1280px
3078290 fix(farmer): forms say what they hide, refuse invalid saves visibly, keep the demo marker out of notes
14a3906 fix(ui): institutional green stays in the sidebar; the workspace speaks slate
2197aeb fix(management): /carbon fits its actions — six columns, one issue cell, cards below 1180px
```

Commit báo cáo (file này + `AGENTS.md`) đứng ngay trên `4d4b6b2`; SHA xem `git log -1`. Báo cáo không tự ghi SHA của chính nó, vì SHA phụ thuộc nội dung file. Mọi gate ở §9 đã chạy trên `4d4b6b2`; commit báo cáo chỉ đổi tài liệu.

## 14. `git status --short` cuối

Chỉ còn các file untracked có từ trước round (`.mcp.json`, 9 ảnh `docs/*.jpg`, 4 ảnh `docs/ChatGPT Image *.png`), không đụng tới. Không có file tracked nào bị sửa.

## 15. Chạy local để xem

```
# backend (cổng 8010, khớp web-dashboard/.env)
cd backend && uvicorn main:app --host 127.0.0.1 --port 8010
# frontend real-data
cd web-dashboard && npm run build && npx vite preview --host 127.0.0.1 --port 5173
# mở http://127.0.0.1:5173/carbon và thử ở độ rộng 1363px
```

Gate real: đặt `REDESIGN_FARMER_EMAIL/PASSWORD` và `REDESIGN_MANAGER_EMAIL/PASSWORD` rồi chạy
`npx playwright test --config playwright.real.config.ts tests/e2e/round41-real.spec.ts`.

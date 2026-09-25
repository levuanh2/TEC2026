# Web UX Round 4.4 — Management metrics truth & clarity

> Branch `fix/agricarbon-round4-4-management-metrics-truth`, tạo từ `origin/main` = `70af50c` (merge Round 4.3; `origin/main` không đổi khi bắt đầu, branch không stale). Commit local. **Chưa push, merge, tag hay deploy** — chờ duyệt giao diện.

Phạm vi: chỉ lớp trình bày `web-dashboard/`. **Không** sửa backend, Supabase, API contract, công thức, hệ số, GWP, readiness, methodology hay MRV state machine.

**Kết luận: PASS WITH KNOWN LIMITATIONS** (giới hạn ở §16).

## 1. Branch, commit

| Commit | Nội dung |
|---|---|
| `8a2d1bb` | fix(management): represent partial harvest truthfully; say coverage once |
| `a9008eb` | fix(ui): remove the unused Fraunces webfont request |
| `2afe2f7` | test(web): Round 4.4 metrics truth, copy, layout and font gates |
| `4d37164` | test(web): count distinct endpoints in the real Performance budget |
| (commit này) | docs(web): Round 4.4 audit and QA report + dòng ownership `AGENTS.md` |

## 2. Skill / công cụ

| Yêu cầu | Thực tế | Ảnh hưởng tới quyết định |
|---|---|---|
| Product Design Audit, Design QA | **Không có** skill tên này trong phiên. | Thay bằng audit trên giao diện render (script Playwright, §4). |
| Hallmark | Có, nhưng không gọi: đây là vòng sửa copy/bố cục trên hệ thống đã có token, không phải thiết kế mới. | — |
| Browser / rendered UI | Playwright + Chrome thật trên **staging**, **local `main`** (baseline) và **local branch**, cùng tài khoản QA. | Phát hiện lặp nguyên khối "Phạm vi/Độ phủ/…" ×4 ở 390px (không thấy được từ source) → gộp thành một khối cho cả trang. |
| axe-core | 4.13.0, tag `wcag2a/2aa/21a/21aa`, không tắt rule. | §11. |
| Playwright | 1.63: 1 spec mock mới, 1 spec real mới. | §12. |

## 3. Root cause "Chưa ghi thu hoạch"

`backend/infrastructure/read_repo.py` `farm_performance` (dòng 551): `yield_kg` của một nông hộ = tổng các vụ **chỉ khi mọi vụ đều có sản lượng**, ngược lại `null`. Frontend đọc `null` thành "Chưa ghi thu hoạch".

Xác minh trên dữ liệu thật (Manager QA, local FastAPI → Supabase hosted, chỉ đọc):

| Nông hộ | `yield_kg` farm-performance | Từng vụ `/metrics.yield_kg` |
|---|---|---|
| Hộ demo 1 | `null` · partial | vụ A `null`, vụ B **5 200** |
| Hộ demo 2 | `null` · partial | vụ A `null`, vụ B **5 300** |
| Hộ demo 3 | 10 800 · partial | 5 400 + 5 400 |

Farmer (Hộ demo 1) thấy 5.200 kg ở vụ của mình; Management thấy "Chưa ghi thu hoạch" cho cùng nông hộ → mâu thuẫn. Payload farm-performance **không** có tổng đã ghi hay số vụ, nên frontend không thể hiện "5.200 kg đã ghi · 1/2 vụ" mà không gọi thêm `/metrics` từng vụ (N+1, bị cấm).

## 4. Contract ba trạng thái (chỉ từ payload hiện có)

`harvestState()` trong `src/pages/coverage.ts`:

| Trạng thái | Điều kiện payload | Hiển thị |
|---|---|---|
| `recorded` (C) | `yieldKg != null` → mọi vụ có sản lượng | tổng, vd `10.800 kg` |
| `incomplete` (B, hoặc A chưa phân biệt được) | `yieldKg == null`, `dataStatus` ≠ `missing` | **Có vụ chưa ghi sản lượng thu hoạch** |
| `none` (A chắc chắn) | `dataStatus == 'missing'` → nông hộ không có vụ nào | **Chưa có sản lượng thu hoạch** |

Không đổi thiếu thành 0, không suy số vụ, không bịa 5.200 kg, không cộng nguồn khác phạm vi. Nông hộ `incomplete` không bao giờ hiện "Đầy đủ dữ liệu" (badge từ `data_status` server). Bốn ô chỉ số/kg của hàng đó ghi "Chờ sản lượng" (trỏ về ô sản lượng) thay vì lặp "Thiếu sản lượng thu hoạch" 4 lần.

**Backend requirement (không làm trong vòng này):** `farm-performance` cần thêm `recorded_yield_kg` (tổng các vụ đã ghi) và `season_count` / `seasons_with_yield` để hiện được "5.200 kg đã ghi · 1/2 vụ có sản lượng", và danh sách season id thiếu để CTA mở thẳng đúng vụ.

## 5. Before / after copy

| Vị trí | Before | After |
|---|---|---|
| Ô sản lượng Hộ demo 1, 2 | Chưa ghi thu hoạch | Có vụ chưa ghi sản lượng thu hoạch |
| 4 ô /kg khi thiếu sản lượng | Thiếu sản lượng thu hoạch (×4/hàng) | Chờ sản lượng |
| Lý do trong danh sách thiếu | Có vụ thiếu sản lượng thu hoạch | Có vụ chưa ghi sản lượng thu hoạch |
| Nông hộ không có vụ | Chưa có vụ nào có dữ liệu | Chưa có vụ mùa nào |
| Trạng thái aggregate (3 câu) | badge "Chưa tính được cho toàn HTX" + "Chưa tính được" + "Dựa trên 0/3 nông hộ đủ dữ liệu — chỉ số toàn HTX chỉ tính khi mọi vụ đủ dữ liệu." | **một câu**: "Chưa công bố chỉ số toàn HTX — 3/3 nông hộ còn thiếu dữ liệu." / "… — mới có 1/3 nông hộ đủ dữ liệu." / đã công bố: số + "Tính trên 3/3 nông hộ đủ dữ liệu." |
| Theo vụ | Chưa có dữ liệu tổng hợp — **cần endpoint** chỉ số theo lô. | Độ phủ: Tính theo nông hộ; chưa có tổng hợp chi tiết theo từng vụ. |
| Phạm vi / Độ phủ / Điều kiện / Mốc so sánh | lặp trong **mỗi** thẻ (×4) | một khối "Cách đọc các chỉ số" đầu trang; thẻ chỉ giữ câu trạng thái + Cách tính + nút danh sách thiếu |
| Mốc so sánh | Chưa có mốc so sánh | Chưa có mốc so sánh — không đánh giá cao hay thấp. |

Không còn badge xanh/cam trên aggregate: `0/3`, `1/3` là độ phủ, không phải điểm. Không có số tổng HTX khi server trả `null` (business rule "mọi vụ đủ dữ liệu" giữ nguyên).

## 6. Bố cục `/performance`

- Nước + Phân bón: 2 cột (`.perf-grid`); Chi phí + Carbon: **hai section riêng** (tiêu đề, mô tả riêng) chung một hàng (`.perf-pair`) từ 1100px; dưới 1100px (1024 rail 216px, 768, 390) một cột.
- Không thêm chart, gradient, màu mới. Link nông hộ thiếu cao 40px (trước 32px).
- Chiều cao trang (full-page, cùng dữ liệu):

| | Before | After |
|---|---|---|
| 1348 | 1637px | **1216px** |
| 1348, mở hết danh sách | 2072px | **1554px** |
| 1024 | 1812px | 1674px |
| 390 | 2652px | 2420px |

## 7. Ảnh before / after

Local, gitignored: `web-dashboard/.qa-screenshots/round4-4/{staging,before,after}/` — `farmer-home-1348`, `farmer-performance-1348`, `management-dashboard-1348`, `management-performance-1348`, `management-performance-details-open-1348`, `management-performance-1024`, `management-performance-390`, `management-menu-open-390` (`.png`). `staging/` = bản deploy Round 4.3; `before/` = local `70af50c`; `after/` = branch. Before/after cùng tài khoản, cùng backend local, cùng tenant. Không ảnh nào chụp khi đang loading hay có ô mật khẩu.

Lưu ý: ảnh full-page khi trang đã cuộn vẽ sidebar/topbar sticky và skip-link ở giữa ảnh — xảy ra **cả before lẫn after**, là hiện vật của `fullPage` capture, không phải lỗi app. Ảnh `details-open` được chụp lại sau `scrollTo(0,0)` + blur cho cả hai bản.

## 8. Audit render (staging → before → after)

Script `.qa-screenshots/round4-4/audit.mjs`: Farmer 3 route × 5 viewport, Management 5 route × 5 viewport (1440/1348/1024/768/390), quét text trong `main`.

| Kiểm tra | Staging | Before (local main) | After |
|---|---|---|---|
| "Chưa ghi thu hoạch" trên `/performance` | có (mọi width) | có | **0** |
| "endpoint" / developer term | 4/trang | 4/trang | **0** |
| raw UUID / ISO date / enum trong text | 0 | 0 | 0 |
| Horizontal overflow (45 lượt) | 0 | 0 | 0 |
| Sidebar ra ngoài viewport | 0 | 0 | 0 |
| `h1` mỗi trang | 1 | 1 | 1 |
| Console | chỉ log trình duyệt của `404 /v1/crop-seasons/{id}/carbon` (vụ chưa có kết quả Carbon — đúng contract) + `/v1/farmer/scope` cho Manager | như staging | như before; **0 trên `/performance`**; 0 lỗi JS/app-origin (sidebar-parity-real: `app-origin console errors: []`) |

## 9. Request count (N+1)

`/performance`, Manager, production preview, full page load:

| | Before | After |
|---|---|---|
| API request (median 3 lượt audit) | 5 | 5 |
| `/crop-seasons/{id}/metrics` | 0 | 0 |
| Endpoint | `/v1/farmer/scope`, `/v1/me`, `/v1/organizations/{id}`, `…/metrics`, `…/farm-performance` | giống hệt |

Staging (Round 4.3 deploy) cũng 5 / 0. Unit test `round44.dom.test.tsx`: 1 nông hộ và 40 nông hộ gọi cùng 3 endpoint, 0 `/metrics` theo vụ, 0 lời gọi farms/seasons/plots. Real spec kiểm đúng tập 5 endpoint (đếm distinct vì dev server StrictMode gọi đôi).

## 10. Performance (cùng backend local, cùng tenant, production preview)

5 lượt mỗi bản, `/performance` 1348px, median:

| | Before `70af50c` | After |
|---|---|---|
| Thẻ aggregate đầu tiên hiển thị | 2426 ms | 2431 ms |
| Settled (bảng + networkidle) | 2579 ms | 2629 ms |

Bằng nhau trong nhiễu — vòng này không đổi luồng dữ liệu. (Chỉ số "first meaningful content" chung của script audit hạ còn ~110 ms sau sửa, nhưng chỉ vì khối "Cách đọc" tĩnh render trước dữ liệu; không dùng số đó để so sánh.) Staging (Render) 3 lượt: first content 2090–2607 ms, settled 3044–4003 ms — không so với local.

## 11. Accessibility

axe-core (serious + critical là gate; ghi nhận mọi impact):

| Lượt | Viewport | Violation |
|---|---|---|
| Farmer Performance | 1348, 390 | 0 |
| Management Performance | 1348, 1024, 768, 390 | 0 |
| Management Performance, mọi danh sách thiếu đang mở | 1348 | 0 |
| Management drawer mở | 390 | 0 |
| round43-qa (mock) | 5 route × 1363/390 | 0 |
| round44-real | 1348 + 1024 + 390 | 0 serious/critical |

Drawer (768 và 390, dữ liệu thật): backdrop có; chạm backdrop đóng; Escape đóng; nút đóng 44×44; mở → focus vào nút đóng; 40 lần Tab không thoát khỏi drawer; `main` nằm trong `[inert]`; `body` overflow hidden; đóng → focus về nút mở; đổi route tự đóng; drawer 0–250px trong viewport; không overflow. Farmer bottom nav không đổi (round43-qa pass).

Khác: disclosure có `aria-expanded` + `aria-controls`, mở/đóng bằng Enter (real spec); tên nút cố định "N nông hộ thiếu dữ liệu"; bảng giữ `th scope`; card mobile cùng nội dung với bảng desktop (cùng markup `data-label`); skip link là tab stop đầu (round3-qa pass). axe 0 **không** có nghĩa là đạt WCAG — chưa kiểm bằng screen reader.

## 12. Kiểm thử

| Gate | Kết quả |
|---|---|
| `npm ci` | OK, 0 vulnerabilities |
| `npx tsc --noEmit` | pass |
| `npx vitest run` | **52 file / 427 test pass** |
| `npm run build` | pass |
| Playwright mock (toàn bộ, default config) | lần cuối **90 passed / 48 skipped / 0 failed**. Trong 3 lần chạy full, 1 lần `farmer-web.spec.ts` (Farmer shell, không bị vòng này đụng) fail rồi pass khi chạy lại riêng và ở lần full kế tiếp — flaky, không lấy được log lỗi lần đó. 48 skip = spec real/opt-in không có credential. |
| Round 4.4 mock `round44-qa` | 14/14 |
| Round 4.3 regression `round43-qa` | pass (trong suite mock) |
| Real suite (`playwright.real.config.ts`, 1 worker) | 21 passed, 9 skipped (write/CV/recommendations/export opt-in — **không bật**), 1 failed + 2 không chạy (serial) — lỗi ở **test** `round44-real` (đếm request thô trên Vite dev, StrictMode gọi đôi: 7 thay vì 5). Sửa assertion (`4d37164`), chạy lại `round43-real` + `round44-real`: **7/7 pass**. |
| `redesign-qa` (REDESIGN_QA, real-data preview) | **15/15** |
| sidebar parity real | pass (trong real suite) |
| axe | §11 |

Test cũ đổi theo copy mới (không hạ assertion, copy là yêu cầu của vòng này): `round43.dom.test.tsx`, `performance.dom.test.tsx`, `coverage.test.ts`, `round43-real.spec.ts` — trước đây khẳng định chính các chuỗi "Dựa trên …" và "cần endpoint …" mà §4–5 của brief yêu cầu bỏ. Test mới: `round44.dom.test.tsx` (fixture 1 farm / 2 vụ: A 5 200 kg, B thiếu — không "Chưa ghi thu hoạch", trạng thái một phần, không "Đầy đủ dữ liệu", không số tổng HTX, danh sách thiếu đúng nông hộ + lý do + link; quét developer term; request không tăng theo quy mô), `fonts.test.ts`, `round44-qa.spec.ts`, `round44-real.spec.ts` (gồm kiểm Farmer/Manager thống nhất trên Hộ demo 1). Không thêm `skip` cho lỗi app. Không chạy test ghi dữ liệu → không có QA record cần dọn.

## 13. Farmer Round 4.3 giữ nguyên

Text `main` của Farmer Performance **giống hệt byte** before/after, có đủ: 5.200 kg, 1,2 ha, 4,3 tấn/ha, 330 m³, 63 lít nước/kg lúa, 275 m³/ha, 150 kg, 125 kg phân/ha, "không phải lượng N/P/K", không `0 ₫`, "Chưa có mốc để đánh giá cao hay thấp.", `aria-expanded` trên "Cách tính và dữ liệu sử dụng" (round43-real pass). "Chưa ghi thu hoạch" ở Farmer vẫn giữ — nó mô tả **một vụ**, nên đúng. Không file Farmer nào bị sửa ngoài comment trong `farmer/tokens.css`.

## 14. Backend / Carbon diff

```
git diff 70af50c..HEAD -- backend supabase app ml | wc -l   →   0
```

## 15. Font

`rg` toàn repo: `Fraunces` chỉ còn ở token `--ac-serif` (không nơi nào dùng) và URL Google Fonts. Computed `font-family` của `main h1` và `body`, cả hai vai trò, trên staging/before/after: `"Be Vietnam Pro", …`. Đã bỏ Fraunces khỏi request và bỏ token; `fonts.test.ts` + `round44-qa` chặn nó quay lại.

## 16. Known limitations / chưa làm

1. **Chưa hiện được "5.200 kg đã ghi · 1/2 vụ"** — payload farm-performance không có tổng một phần hay số vụ (§4, backend requirement). UI nói thật "Có vụ chưa ghi sản lượng thu hoạch", không bịa số.
2. CTA dẫn tới **hồ sơ nông hộ** (`/farms/{id}`), chưa tới đúng vụ — payload không có season id thiếu; `/data-gaps` là danh sách readiness Carbon, không bao gồm sản lượng nên không phải đích đúng.
3. Tổng hợp độ phủ theo **vụ** chưa có (cần endpoint batch — chỉ ghi ở đây, không ghi trên UI).
4. `/dashboard`, `/seasons`, `/data-gaps`, `/carbon` vẫn gọi readiness + carbon theo từng vụ (24 request / 6 vụ) — có từ trước, ngoài phạm vi `/metrics` của vòng này; `404 /carbon` cho vụ chưa có kết quả hiện thành log console của trình duyệt.
5. 1 lần flaky `farmer-web` (mock) trong 3 lần chạy full, không tái hiện.
6. Chưa kiểm bằng screen reader thật; chưa kiểm trên staging sau sửa (chưa deploy).
7. Tên nông hộ ở cột đầu bảng vẫn xuống dòng ở 1348px ("Hộ demo / 1") — có từ trước, không sửa.

## 17. Untracked giữ nguyên (không sửa/stage/xoá)

`.mcp.json`, `docs/01-home.jpg`, `docs/01-overview.jpg`, `docs/02-journal.jpg`, `docs/04-irrigation-form.jpg`, `docs/08-carbon-repair.jpg`, `docs/08-mrv-state.jpg`, `docs/09-carbon-quick-fix.jpg`, `docs/12-logout-stuck.jpg`, `docs/16-season-carbon.jpg`, `docs/ChatGPT Image Sep 21, 2026, 12_17_37 AM.png`, `… 12_18_09 AM-1.png`, `… 12_18_10 AM-2.png`, `… 12_18_11 AM-3.png`.

## 18. Credential cleanup

- Mật khẩu QA chỉ đi qua biến môi trường, nạp từ một file `qa.env` tạm trong scratchpad phiên (ngoài repo) cho từng lệnh; file đã xoá sau gate.
- Real config chạy `trace: 'off'`; `signIn` xoá ô mật khẩu trước khi rethrow.
- Quét chuỗi mật khẩu trong `test-results/`, `playwright-report/`, `.qa-screenshots/`, `docs/`, `AGENTS.md`, `src/`, `tests/`, log scratchpad, output task nền và `git log -p 70af50c..HEAD`: **0 kết quả**. Log real/redesign/uvicorn và script probe đã xoá.
- Baseline worktree: xoá junction `node_modules` trước (kiểm `LinkType = Junction`), rồi `git worktree remove` + `prune`. Preview 5173 và uvicorn 8010 đã dừng.

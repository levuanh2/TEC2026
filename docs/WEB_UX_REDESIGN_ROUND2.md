# Hybrid redesign — round 2 (2026-09-21)

Vòng sửa thứ hai cho web AgriCarbon sau đợt audit UX trên staging. Phạm vi:
`web-dashboard/**`. **Không** đổi công thức, hệ số, phương pháp hay bất kỳ
logic Carbon nào; không đổi backend; không đổi route công khai; không tạo dữ
liệu giả.

## 1. Branch và commit

| | |
|---|---|
| Branch | `fix/hybrid-redesign-round2` (nhánh từ `main` @ `2d1c50e`) |
| Commit | `5e1b511` → `59c90f7` → `8baff05` → `d0dea19` → `9b06b61` → `13e2d85` (6 commit) |
| Merge / push / deploy | **Chưa** — xem §12 |

## 2. Cách đo (không đánh giá bằng source code)

Mọi phát hiện dưới đây đo trên giao diện đã render, bằng Chromium thật, đăng
nhập bằng tài khoản QA thật (`REDESIGN_*` qua biến môi trường), FE dev server
`:5173` ở chế độ dữ liệu thật → backend `:8010` → hosted Supabase.

- **Baseline**: 84 ảnh, 21 route × 4 viewport (1440/1280/768/390), kèm đo
  overflow ngang, console error, thời gian tải, và quét raw enum/UUID/ISO
  ngay trên `document.body.innerText`. → `.qa-screenshots/baseline/`
- **After**: cùng bộ đo, 84 ảnh. → `.qa-screenshots/after/`
- **QA suite**: 78 ảnh từ `tests/e2e/redesign-qa.spec.ts`.
  → `.qa-screenshots/redesign/`

Thư mục `.qa-screenshots/` nằm trong `.gitignore` (ảnh không commit).

## 3. Route đã sửa

**Nông hộ** — `/farmer`, `/farmer/journal` (gián tiếp qua presenter),
`/farmer/performance`, `/farmer/carbon`.

**Quản lý** — `/dashboard`, `/seasons`, `/data-gaps`, `/carbon` (chung
`SeasonsWorkspace`), `/mrv`, `/crop-seasons/:id` và tab `carbon`, cộng toàn bộ
shell (sidebar, topbar) và mọi bảng dùng `DataTable`.

## 4. Component / token mới hoặc đổi

| Tệp | Vai trò |
|---|---|
| `src/carbon/readiness.ts` *(mới)* | View model Carbon dùng chung — xem §5 |
| `src/carbon/readiness.test.ts` *(mới)* | 30 test ma trận trạng thái |
| `src/carbon/useCarbonView.ts` *(mới)* | Hook đọc readiness cho một vụ |
| `src/vocab.ts` *(mới)* | Từ điển tiếng Việt cho mọi enum — xem §6 |
| `src/api/engine.ts` *(mới)* | `/health` (cache 1 lần/phiên) để so `ef_config_version` |
| `src/farmer/metricsView.ts` | Thêm `group` + `metricGroups()` (tài nguyên / chi phí / carbon) |
| `src/utils/mrvPresentation.ts` | Tách case status khỏi step status — xem §7 |
| `.role--methodology` (styles.css) | Alias ngữ nghĩa của lavender `#C7CEEA` |
| `.carbon-readiness` (styles.css) | Khối trạng thái readiness dùng chung |
| `.fw-mgroup*`, `.fw-snap-group*` (farmer.css) | Ba nhóm chỉ số |
| `.fw-ctxbar__dates`, `.fw-ctxbar__go` (farmer.css) | Context bar gộp hero |

Palette đã đúng brief từ trước (`src/theme.css` §82-97): `#E2F0CB` /
`#B5EAD7` / `#FFDAC1` / `#FFB7B2` / `#C7CEEA`. Round này chỉ **gán lại đúng
ngữ nghĩa**, không đổi giá trị màu.

## 5. Thống nhất Carbon readiness

**Nguyên nhân gốc (đo được).** Năm chỗ tự suy luận readiness từ cùng một
payload `/v1/crop-seasons/{id}/carbon/readiness`, mỗi chỗ một kiểu:
`farmer/activityView.ts:180`, `farmer/CarbonRepair.tsx:41`,
`farmer/hybrid.tsx:73,148`, `pages/ops.ts:81`, và `features/carbon.tsx`
**không đọc readiness gì cả**.

Hệ quả đo trên màn hình cho vụ `2e63e128-f53d-4f70-9bb4-62b9efc048e3`:

- Farmer Carbon: thiếu tỷ lệ chất khô của rơm + vướng hệ số nhiên liệu
- Management Overview: *"Đã đủ dữ liệu vụ. Chạy Carbon Engine…"*
- Management Carbon tab: nút "Tính lại theo kịch bản" bật, dù chắc chắn lỗi
- Management Carbon list: *"Giới hạn hệ số"*

`ops.ts` đặt `data: missing.length ? 'missing' : 'complete'` — chỉ đếm gap
người dùng sửa được, nên vụ chỉ vướng hệ số vẫn ra `complete` → "đã đủ dữ
liệu". Còn "Bước tiếp theo" ở season hub suy từ `hasHarvest`, hoàn toàn không
liên quan tới Carbon.

**Cách sửa.** `src/carbon/readiness.ts` là nơi *duy nhất* quyết định trạng
thái Carbon của một vụ nghĩa là gì. Nó chỉ nhóm lại câu trả lời của server
(`backend/carbon/readiness.py` vẫn giữ toàn bộ methodology) thành các trường
brief yêu cầu:

`userFixableGaps` · `methodologyLimitations` · `optionalGaps` ·
`calculationStatus` · `isReady` · `isStale` · `nextAction` · `nextActionTarget`
· `label` · `detail` · `tone` · `icon`

Thứ tự ưu tiên (một payload → đúng một trạng thái):

```
readiness == null            → unknown
userFixableGaps.length       → missing_data          (1. Thiếu dữ liệu)
methodologyLimitations.length→ methodology_limited   (2. Giới hạn hệ số)
isStale                      → stale                 (5. Cần tính lại)
hasResult                    → calculated            (4. Đã tính)
isReady                      → ready                 (3. Sẵn sàng tính)
```

Các quy tắc brief, mỗi quy tắc có test riêng:

| Quy tắc | Thực thi tại |
|---|---|
| `factor_unavailable` không tính là dữ liệu người dùng thiếu | `isLimitation()` lọc riêng |
| Không "Sửa ngay" nếu nhập thêm không giải quyết được | `methodology_limited` → `nextAction.kind === 'none'` |
| Không "đã đủ dữ liệu" khi còn user-fixable gap | `dataCompletenessLabel()` |
| Không "sẵn sàng tính" khi methodology limitation chặn | `isReady = can_calculate && limitations.length === 0` |
| Không enable CTA tính Carbon nếu chắc chắn thất bại | `CarbonPanel` `disabled={… || blocked}` |
| Không đổi logic tính toán API/backend | Không file backend nào bị sửa |

**`isStale` lấy từ đâu.** Chỉ từ sự thật đã có trên dây:
`max(activity.recordedAt) > result.calculated_at`, hoặc
`result.ef_config_version !== /health.ef_config_version`. Không có tín hiệu
nào → `false`. Báo nhầm "cần tính lại" là nói dối; bỏ sót chỉ là hiển thị số
cũ kèm mốc thời gian của chính nó. Xem giới hạn ở §10.

**Các màn đã nối vào**: `pages/ops.ts` (Overview, Seasons, Data gaps, Carbon
list), `features/carbon.tsx` (Carbon tab), `pages/season.tsx` (Bước tiếp
theo), `farmer/hybrid.tsx` (next action + Summary tile).

## 6. Raw enum / technical field đã xử lý

`src/vocab.ts` là từ điển duy nhất, không có fallback về giá trị thô (giá trị
lạ ra "Chưa rõ", không bao giờ ra `in_review`).

| Enum nguồn | Ví dụ |
|---|---|
| `crop_status` | `active` → Đang canh tác · `planned` → Dự kiến · `harvested` → Đã thu hoạch |
| `batch_status` | dùng chung `crop_status` |
| `irrigation_method` | `awd` → Tưới ngập–khô xen kẽ (AWD) · `continuous_flooding` → Ngập liên tục |
| `straw_management_method` | `incorporated` → Vùi vào đất · `burned` → Đốt tại ruộng |
| `fuel_type` | `diesel` → Dầu diesel · `lpg` → Khí hoá lỏng (LPG) |
| `activity_type` | `pesticide` → Thuốc bảo vệ thực vật |
| `data_source` | `web` → Ứng dụng web · `mobile_offline` → Ứng dụng di động (ngoại tuyến) |
| `mrv_case_status` | `draft` → **Bản nháp** · `ready_for_verification` → Chờ thẩm định |
| `mrv_step_status` | `not_started` → Chưa bắt đầu … |
| `ipcc_water_regime`, `ipcc_pre_season_regime`, `carbon_scenario` | đã map đủ |

Baseline quét được raw enum trên **11/21 route**; after là **0** (test
Playwright `no raw enum, id or ISO timestamp reaches a farmer` canh giữ).

Trường kỹ thuật đã gỡ khỏi màn nông hộ: `duration_minutes` (bỏ khỏi dòng tóm
tắt tưới), UUID và ISO timestamp (không route nông hộ nào còn).

**Hai rò rỉ chỉ lộ ra khi chạy trên dữ liệu thật**, không đọc source mà thấy:

1. Seed demo ghi tiếng Anh vào cột free-text → `"Demo pesticide"` hiện làm tên
   sản phẩm. Nay khớp đúng hình dạng của seeder (`Demo <activity type>`) và
   thay bằng badge **"Dữ liệu minh họa"**. Tên sản phẩm thật hay ghi chú thật
   của nông hộ **không bao giờ** bị nuốt (có test).
2. `CarbonMissingRecord.label` do server đặt theo phương thức đã lưu, nên
   `incorporated` vào thẳng chip quick-fix. Nay dịch qua `vocab`.

## 7. Thống nhất MRV status

**Nguyên nhân.** `utils/mrvPresentation.ts` chỉ có bảng nhãn của
`mrv_step_status` (`not_started`/`in_progress`/`completed`/`blocked`) nhưng
`pages/mrv.tsx:55` truyền vào **case status** (`draft`/`in_progress`/
`ready_for_verification`/`verified`/`closed`). `draft` trượt bảng, rơi vào
fallback `not_started` → **"Chưa bắt đầu"** trong khi 1/6 bước đã xong và 1
bước đang chạy.

**Cách sửa.** Hai khái niệm tách hẳn:

- `presentMrvCaseStatus()` — trạng thái hồ sơ, `draft` → "Bản nháp".
- `presentMrvAggregate(steps)` — trạng thái tổng **suy từ 6 bước**:
  có bước blocked → "Bị chặn"; 6/6 → "Hoàn thành"; có bước đang chạy *hoặc*
  đã có tiến độ → "Đang thực hiện"; 0/6 và chưa bước nào → "Chưa bắt đầu".
- `currentMrvStep()` — bước cần xem tiếp, hiển thị dưới thanh tiến độ.

**Review/approve**: backend **không có** endpoint duyệt hồ sơ MRV (chỉ
`POST /v1/mrv/cases/{id}/exports` và `…/exports/{id}/render`). Đúng chỉ dẫn
brief, CTA "Duyệt MRV" trên Dashboard đổi thành **"Mở hồ sơ MRV"**, và trang
`/mrv` nói rõ đang ở chế độ chỉ đọc. Không dựng nút giả.

Ngoài ra `exceptionsOf` lọc hồ sơ "còn mở" bằng `status !== 'approved' &&
status !== 'exported'` — **hai giá trị không hề tồn tại** trong
`mrv_case_status`, nên mọi hồ sơ luôn nằm trong hàng đợi vĩnh viễn. Nay là
`!== 'verified' && !== 'closed'`.

## 8. Kết quả từng lệnh test

| Lệnh | Baseline | Sau |
|---|---|---|
| `npx tsc --noEmit` | 0 lỗi | **0 lỗi** |
| `npx vitest run` | 33 file / 245 test pass | **35 file / 298 test pass** |
| `npm run build` | pass | **pass** (cảnh báo chunk >500 kB có sẵn từ trước) |
| `npx playwright test redesign-qa` (thật, 2 vai trò, 4 viewport) | — | **15/15 pass** (11,1 phút) |
| `npx playwright test web-smoke farmer-web` (mock, suite có sẵn) | 2/2 pass | **2/2 pass** |

`farmer-web.spec.ts` phải sửa một assertion: nó khẳng định `.fw-ledger` — đúng
cái hero mà brief yêu cầu bỏ. Nay kiểm tra context bar thay thế, và khẳng định
thêm `.fw-ledger` **không còn tồn tại**. Các spec `farmer-real-*` và
`web-real-data` vẫn tự skip khi không có `REAL_E2E=true`, không đụng tới.

Test mới bắt buộc theo brief, đều có:

- ma trận trạng thái Carbon readiness — 30 test (`carbon/readiness.test.ts`)
- `factor_unavailable` không bị tính là user-fixable — có
- plot identifier trong Management season rows — có (e2e, so chữ ký từng hàng)
- không raw `active`/`planned`/`draft`/`incorporated`/`activity_id`/`created_at`
  trên Farmer UI — có (e2e quét `innerText` 6 route)
- Management clickable rows keyboard accessible — có (focus + Enter)
- một primary CTA trên Farmer Home — có
- MRV aggregate status — 20 test unit + 1 e2e
- không horizontal overflow — có (mọi ảnh, 4 viewport)
- date `dd/MM/yyyy` — có
- deep link `/farmer/carbon` — có
- empty / loading / error states — có
- không application console error — có (baseline 0, sau 0)

## 9. Kết quả QA từng viewport

Overflow ngang (`scrollWidth - clientWidth`), đo trên 21 route:

| | 1440 | 1280 | 768 | 390 |
|---|---|---|---|---|
| Baseline | 0 | 0 | 0 | **308px** (`/crop-seasons/:id`) |
| Sau | 0 | 0 | 0 | **0** |

Nguyên nhân 308px, đo bằng cây ancestor chứ không đoán: `.stack` là grid có
track ngầm `auto`, nên nở theo con rộng nhất (682px) rồi card lấp đầy track đó
thay vì lấp viewport 390px. Một cột `minmax(0, 1fr)` sửa cho mọi màn dựng trên
nó.

**Một hồi quy do chính round này gây ra, và đã bắt được bằng cách đo lại.**
Việc bỏ `overflow` của `.table-wrap` (để bảng thành card trên điện thoại) làm
các bảng **không** thuộc `table.data` (hiệu suất nông hộ, rollup tổ chức, lô
MRV) thoát khỏi wrapper và đẩy **5 route Management lệch 306px** ở 390px. Đã
thu hẹp rule bằng `:has(table.data)`; đo lại cả 5: `scrollW == 390`.

Touch target: baseline có control 19–38px (nút workspace 38px, "Đăng xuất"
19–22px, ô tìm kiếm 24px). Nay desktop ≥ 40px, touch ≥ 44px, lấy từ token
`--ac-control-h-sm` / `--ac-control-h` vốn đã có. Test e2e canh giữ mọi
control trong `main` của Farmer.

## 10. Known limitations (thật)

1. **`/dashboard`, `/seasons`, `/data-gaps`, `/carbon` vẫn tải 26–35 giây.**
   Round này song song hoá được phần client (plots + MRV + `/health` chạy
   cạnh chuỗi farm→season thay vì nối đuôi) nhưng **không cải thiện đáng kể**
   (dashboard 32,6s → 32,0s), vì nút thắt nằm ở backend.

   **Blocker, có số đo**: `/v1/crop-seasons/{id}/carbon/readiness` mất
   **10–16 giây/vụ** (log backend). Nguyên nhân:
   `SupabaseCarbonRepository.get_crop_bundle` là chuỗi round-trip PostgREST
   **tuần tự** cho mỗi vụ — crop_seasons → plots → farms → production_batches
   → **một request cho mỗi batch** để lấy activities → **một request cho mỗi
   loại chi tiết**. Khoảng 10+ vòng tuần tự × ~1s qua Internet.

   Repo **đã có sẵn lời giải cho đúng pattern này**:
   `read_repo._bulk_activities_by_season` ("a fixed ~4 requests total instead
   of `O(seasons × detail types)` — this is what actually made the
   organization/farm rollups take 12-15s"). Đường Carbon readiness chưa được
   áp dụng. Cần một trong hai, đều là việc backend nên **không** làm trong
   round này (brief: không đổi backend/logic Carbon):
   - endpoint gộp readiness theo tổ chức (một lần đọc bulk cho mọi vụ), hoặc
   - cho `get_crop_bundle` dùng bulk-batched reads như rollup đã làm.

   Trong lúc chờ: hàng hiện dần từng dòng, mỗi ô chưa tải có skeleton riêng,
   và số đang chờ được nói rõ — **không** dùng `…` làm giá trị nghỉ.

2. **`isStale` không thấy được sửa đổi tại chỗ.** Endpoint danh sách hoạt động
   trả `recorded_at` (lúc nhập) chứ không trả `updated_at`, dù DB có bump
   `updated_at` khi sửa (`write_repo.update`). Nên sửa một bản ghi cũ mà không
   thêm bản ghi mới thì web chưa báo "cần tính lại" (trừ khi `ef_config_version`
   đổi). Đây là **bỏ sót có chủ ý**, không phải báo sai. Muốn triệt để thì read
   view cần trả thêm `updated_at` — một thay đổi backend.

3. **`/farmer` vẫn còn CTA "Cập nhật khuyến nghị" trong một số trường hợp.**
   Nút chỉ biến mất khi một lần generate **đã chạy xong và trả 0 khuyến nghị**
   (`lastGeneratedCount === 0`). Nếu chưa lần nào chạy, nút vẫn hiện — vì lúc
   đó hệ thống thật sự *có thể* tạo ra kết quả, nên ẩn đi sẽ là nói sai.

4. **Chưa làm trong round này** (xem §11 để biết vì sao dừng ở đây):
   `/farmer/journal` (entry point đôi, advanced field collapse, nút xóa 44px),
   `/farmer/farms` + farm/plot/season detail, `/farmer/account`, Management
   `/farms` + farm/plot detail + `/organizations` + `/performance`, copy
   "bấm Xử lý" ở `/data-gaps`, mục "Thông tin kỹ thuật" collapsed trong
   activity detail, và pass rà soát toàn bộ visual system (TDMU green còn dùng
   cho tab underline và một số CTA trong workspace).

5. Topbar nông hộ vẫn nhắc mã vụ bên cạnh context bar (2 lần, xuống từ 3).
   Giữ lại vì trên các trang khác (journal, carbon) nó là ngữ cảnh duy nhất.

## 11. Diffstat

```
35 files changed, 2202 insertions(+), 322 deletions(-)
```

`AGENTS.md` (khai báo ownership round này), `docs/WEB_UX_REDESIGN_ROUND2.md`
(báo cáo này) + phần còn lại trong `web-dashboard/`.
Không có tệp backend, migration, Flutter hay `docs/openapi.json` nào bị sửa.
Bốn tệp untracked không liên quan trong worktree (`.mcp.json`, 4 ảnh trong
`docs/`) được giữ nguyên, không commit.

## 12. Xác nhận

- **Chưa merge** vào `main`.
- **Chưa push** lên remote.
- **Chưa deploy**.
- Toàn bộ nằm trên `fix/hybrid-redesign-round2`, 4 commit, chờ người dùng duyệt.

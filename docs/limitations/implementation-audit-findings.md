# Phát hiện kiểm toán mã nguồn

Trang này ghi lại các **vấn đề thật trong code** (và các lỗi tài liệu đã sửa) phát
hiện khi đối chiếu bộ tài liệu với mã nguồn. Mọi mục đều có bằng chứng `file:dòng`
và đã được agent Codex kiểm tra chéo **read-only** qua Herdr. Không mục nào được
đoán; không mục nào được sửa trong đợt tài liệu. Ba mục P0 (M7, B7, B3) được sửa
trong [sprint P0 ngày 2026-09-15](#sprint-p0-2026-09-15) và chỉ được đánh dấu
`RESOLVED` sau khi có code, test và kiểm chứng trên Supabase hosted. Năm mục P1 (B4, M3, B5,
B1, B2) được sửa trong [sprint P1](#sprint-p1-2026-09-15) theo cùng tiêu chí.

- Code đối chiếu: commit `2f33972` (`main`). Kể từ baseline `81a8e24` chỉ có CSS của
  Farmer Web thay đổi (`farmer.css`, `tokens.css`), không ảnh hưởng các phát hiện.
- Số dòng có thể lệch nhẹ khi code thay đổi; tên hàm/policy là mốc chính.
- Kế hoạch sửa nằm ở `docs/BUG_FIX_PLAN_FROM_DOCS_AUDIT.md` trong repository (không
  build vào site).

## Phân loại

| Mã | Ý nghĩa |
|---|---|
| `CODE_BUG` | Code chạy sai so với quy tắc đã định (quyền, dữ liệu, mã lỗi) |
| `CODE_GAP` | Thiếu hoặc thừa trong code/cấu hình, chưa sai hành vi nghiệp vụ trực tiếp |
| `PRODUCT_DECISION` | Cần quyết định sản phẩm trước khi coi là lỗi |
| `ENV_BLOCKED` | Không kiểm tra được vì thiếu môi trường/credential |
| `SCIENTIFIC_BLOCKER` | Chặn bởi dữ liệu/phương pháp khoa học, không phải code |
| `DOC_ERROR` → `RESOLVED_DOC` | Tài liệu từng sai, đã sửa trong đợt này |

Mức độ: **High** — ảnh hưởng quyền truy cập hoặc tính toàn vẹn của dữ liệu/gói bằng
chứng; **Medium** — sai số liệu, sai mã lỗi hoặc sai luồng giao diện; **Low** — cấu hình,
dependency, comment.

## Tóm tắt

| ID | Module | Severity | Loại | Evidence | Impact | Status | Codex |
|----|--------|----------|------|----------|--------|--------|-------|
| [M7](#m7) | Storage / RLS | High | `CODE_BUG` | `baseline.sql:2837-2842` | Người không phải manager có thể đọc artifact MRV qua Storage API | **RESOLVED** 2026-09-15 | CONFIRMED |
| [B3](#b3) | Activities (Farmer Web) | High | `CODE_BUG` | `service.py:128-150` | `farm_role = viewer` vẫn ghi được activity qua FastAPI | **RESOLVED** 2026-09-15 | CONFIRMED |
| [B7](#b7) | Auth (`/v1/me`) | High | `CODE_BUG` | `read_repo.py:157-167` | Membership đã kết thúc vẫn qua cổng role `farmer` | **RESOLVED** 2026-09-15 | CONFIRMED |
| [M3](#m3) | MRV Export | High | `CODE_BUG` | `service.py:589` | Gói MRV có thể chứa bản tính giả định thay vì `actual` | **RESOLVED** 2026-09-15 | CONFIRMED |
| [B4](#b4) | Carbon API | Medium | `CODE_GAP` | `api.py:116-137` | Người chỉ có quyền đọc tạo được bản tính được lưu | **RESOLVED** 2026-09-15 | CONFIRMED |
| [B5](#b5) | Carbon API | Medium | `CODE_BUG` | `models.py:193-205`, `api.py:149-158` | Thiếu `nitrogen_percent` → `500` thay vì `422` | **RESOLVED** 2026-09-15 | CONFIRMED |
| [B1](#b1) | Resource Metrics | Medium | `CODE_BUG` | `read_repo.py:380-387` | `water_per_kg` từ tổng thiếu nhưng báo đầy đủ | **RESOLVED** 2026-09-15 | CONFIRMED |
| [B2](#b2) | Web routing | Medium | `CODE_BUG` | `types.ts:1`, `me.ts:7,13` | `enterprise_viewer` bị đưa vào khu Farmer | **RESOLVED** 2026-09-15 | CONFIRMED |
| [B6](#b6) | Backend dependency | Medium | `CODE_GAP` | `service.py:50`, `requirements.txt` | Cài theo `backend/requirements.txt` không khởi động được API | OPEN | CONFIRMED |
| [B8](#b8) | Config | Low | `CODE_GAP` | `config.py:42,95` | Biến môi trường không có tác dụng | OPEN | CONFIRMED |
| [B12](#b12) | Activities schema | Low | `CODE_GAP` | `schemas.py:175-181` | Comment sai lệch với form | OPEN | CONFIRMED |
| [B9](#b9) | Farmer Web | Low | `PRODUCT_DECISION` | `ActivityForms.tsx:349` | Mất giờ trong ngày của activity | OPEN | CONFIRMED |
| [B10](#b10) | Farmer Web / API | — | `PRODUCT_DECISION` | `write_repo.py:25-35` | Không có form nhiên liệu, không route tạo farm/thửa/vụ | OPEN | CONFIRMED |
| [B11](#b11) | Database | — | `PRODUCT_DECISION` | `baseline.sql` | Bảng/view baseline không dùng | OPEN | CONFIRMED |

"Tiềm ẩn" nghĩa là hiện chưa xảy ra trên dữ liệu thật vì mọi bản tính CO₂e đang dừng ở
`422 missing_emission_factor` (GWP null), nhưng sẽ xảy ra ngay khi GWP có giá trị.

## Chi tiết `CODE_BUG` / `CODE_GAP`

### M7 — Policy đọc Storage `mrv-exports` rộng hơn metadata {#m7}

| Trường | Nội dung |
|---|---|
| Module | Supabase Storage / RLS, MRV Export |
| Severity | High |
| Loại | `CODE_BUG` |
| Source | `supabase/migrations/20260907000000_baseline.sql:2837-2842` (`mrv_files_storage_select`); `supabase/migrations/20260913150000_mrv_xlsx_export_artifacts.sql:97-99` (`mrv_exports_select`); `backend/service.py:638` (đường dẫn object) |
| Evidence | `mrv_files_storage_select` cho `select` trên `storage.objects` khi `bucket_id in ('mrv-evidence','mrv-exports')` **và** `private.user_can_read_organization(<thư mục đầu>)`. Backend lưu artifact tại `{organization_id}/{mrv_case_id}/{filename}`. Trong khi đó `mrv_exports_select` đã được siết về `private.user_can_manage_mrv_case` |
| Impact | Mọi thành viên còn hiệu lực của tổ chức (kể cả `farmer`) và `enterprise_viewer`/`regulator` qua data grant có thể dùng JWT + publishable key gọi trực tiếp Supabase Storage API để liệt kê/tải XLSX/PDF gói MRV — vượt qua quy tắc "chỉ manager" mà API và metadata áp dụng |
| Hành vi hiện tại | Quyền đọc object rộng hơn quyền đọc metadata; ứng dụng không gọi Storage trực tiếp nhưng policy không phụ thuộc ứng dụng |
| Hành vi mong đợi | Quyền đọc object `mrv-exports` khớp `mrv_exports_select` (manager của tổ chức sở hữu), hoặc client không có quyền đọc và chỉ backend (service role) đọc |
| Status | **RESOLVED** — leak được tái hiện trên hosted qua Storage API thật trước khi sửa; migration `20260915100000` (commit `3af4205`); smoke hosted 50/50 sau khi áp. Xem [sprint P0](#sprint-p0-2026-09-15) |
| Codex | CONFIRMED |

### B3 — Ghi activity qua Farmer Web không kiểm quyền ghi farm {#b3}

| Trường | Nội dung |
|---|---|
| Module | Activities — `ActivityWriteService` |
| Severity | High |
| Loại | `CODE_BUG` |
| Source | `backend/service.py:128-132` (`_actor_and_farmer_scope`), `backend/service.py:135-150` (`_write_batch`); so với `baseline.sql:1554-1564` (`user_can_read_farm`), `1586-1603` (`user_can_write_farm`), `1859-1863` (`activities_insert`) |
| Evidence | Service chỉ yêu cầu `"farmer" in me["roles"]` và đọc được vụ/lô qua RLS. `user_can_read_farm` đúng với **mọi** `farm_role` (kể cả `viewer`), còn policy ghi `activities` yêu cầu `user_can_write_batch` → `farm_role` `owner`/`editor` hoặc manager. Bước ghi dùng kết nối psycopg bỏ qua RLS |
| Impact | Người có role tổ chức `farmer` nhưng chỉ là `viewer` của một farm có thể tạo activity (và sửa/xoá activity do chính mình tạo) cho vụ của farm đó qua Farmer Web; Flutter với cùng tài khoản bị RLS từ chối |
| Hành vi hiện tại | Quyền ghi qua FastAPI = quyền đọc + role `farmer` |
| Hành vi mong đợi | Quyền ghi qua FastAPI không rộng hơn `private.user_can_write_batch` của lô đích |
| Status | **RESOLVED** — repository kiểm `private.user_can_write_batch` trong transaction ghi (commit `f9056fb`); viewer bị từ chối trên cả FastAPI và PostgREST (hosted); UI ẩn nút ghi. Xem [sprint P0](#sprint-p0-2026-09-15) |
| Codex | CONFIRMED |

### B7 — `/v1/me` không lọc membership đã kết thúc {#b7}

| Trường | Nội dung |
|---|---|
| Module | Auth — `SupabaseReadRepository.me` |
| Severity | High (vì là đầu vào của cổng quyền) |
| Loại | `CODE_BUG` |
| Source | `backend/infrastructure/read_repo.py:157-167`; người dùng `roles`: `backend/service.py:128-132` (activity), `:229` (recommendation), `:303` (CV); helper RLS lọc `ended_at` tại `baseline.sql:1491`, `1507`, `1528` |
| Evidence | `roles` = hợp của `organization_memberships.role` và `farm_members.farm_role`, không có điều kiện `ended_at is null or ended_at > now()` |
| Impact | Người có membership `farmer` đã kết thúc vẫn qua cổng role `farmer` của ActivityWriteService, RecommendationService, CvService (phần đọc vẫn bị RLS giới hạn). Web cũng phân giải shell theo role đã hết hạn. Xuất MRV **không** bị ảnh hưởng vì `_manages` tự lọc `ended_at` |
| Hành vi hiện tại | Role hết hạn vẫn nằm trong `roles` |
| Hành vi mong đợi | `roles` chỉ gồm membership còn hiệu lực, cùng quy tắc với helper RLS |
| Status | **RESOLVED** — `infrastructure/memberships.py` dùng trong `me()` và `_manages` (commit `202fb80`); `/v1/me` trên hosted không còn báo role của membership đã kết thúc. Xem [sprint P0](#sprint-p0-2026-09-15) |
| Codex | CONFIRMED |

### M3 — Gói MRV lấy bản tính Carbon mới nhất bất kể kịch bản {#m3}

| Trường | Nội dung |
|---|---|
| Module | MRV Export — `MrvExportService._create_snapshot` |
| Severity | High (toàn vẹn nội dung gói bằng chứng) |
| Loại | `CODE_BUG` |
| Source | `backend/service.py:589` (`self._carbon.latest(sid)` không truyền `scenario`); `backend/infrastructure/supabase_repo.py:151-163` (chỉ lọc kịch bản khi được truyền); `backend/mrv/manifest.py:577` (ghi `scenario`); so với `backend/infrastructure/read_repo.py:390` (metrics chỉ dùng `scenario == "actual"`) |
| Evidence | Management Web lưu được bản tính `awd`/`continuous_flooding` qua `POST /v1/carbon/calculate`; bản thành công mới nhất (bất kỳ kịch bản) đi vào mục `carbon` của manifest và `mrv_export_calculations` |
| Impact | Cùng một gói có `resource_metrics` theo `actual` nhưng `carbon` có thể là kịch bản giả định; trường `scenario` có ghi, nhưng người đọc gói dễ hiểu nhầm là số liệu thực tế |
| Hành vi hiện tại | Chọn bản `succeeded` mới nhất của vụ, mọi kịch bản |
| Hành vi mong đợi | Mục `carbon` của gói dùng kịch bản ghi nhận (`as_recorded` ↔ DB `actual`), nhất quán với Resource Metrics |
| Status | **RESOLVED** — chỉ lấy kịch bản ghi nhận (commit `ef2424f`); kèm migration `20260915120000` sửa trigger chặn liên kết bản tính theo crop season; smoke hosted chọn đúng bản và `unavailable` khi chỉ có kịch bản giả định. Xem [sprint P1](#sprint-p1-2026-09-15) |
| Codex | CONFIRMED |

### B4 — `POST /v1/carbon/calculate` không có cổng role {#b4}

| Trường | Nội dung |
|---|---|
| Module | Carbon API |
| Severity | Medium |
| Loại | `CODE_GAP` (kèm quyết định sản phẩm về role được phép) |
| Source | `backend/api.py:116-137` (`_require_caller`), `backend/api.py:174-211`; `carbon_calculations` chỉ có policy SELECT cho client (`baseline.sql:1907-1908`) |
| Evidence | `_require_caller` chỉ kiểm JWT + đọc được vụ; bản tính được lưu bằng service role |
| Impact | `regulator`/`enterprise_viewer` (đọc qua data grant) hoặc `viewer` của farm tạo được hàng `carbon_calculations` — thứ DB không cho chính họ ghi trực tiếp. Hàng mới trở thành "mới nhất" cho metrics (`actual`) và cho gói MRV (xem [M3](#m3)) |
| Hành vi hiện tại | Ai đọc được vụ đều lưu được bản tính |
| Hành vi mong đợi | Chỉ các role được sản phẩm cho phép (ví dụ manager của HTX, người ghi được farm) mới lưu được; role chỉ đọc nhận `404`/`403` theo quy ước lỗi |
| Status | **RESOLVED** — quyết định sản phẩm: `private.user_can_write_crop`; kiểm trước engine (commit `7de5bf7`); hosted: viewer/regulator/enterprise bị `404`, owner/editor/manager qua cổng. Xem [sprint P1](#sprint-p1-2026-09-15) |
| Codex | CONFIRMED |

### B5 — Thiếu `nitrogen_percent` trả `500` {#b5}

| Trường | Nội dung |
|---|---|
| Module | Carbon Engine / Carbon API |
| Severity | Medium |
| Loại | `CODE_BUG` |
| Source | `backend/carbon/models.py:193-205` (`total_nitrogen_kg` ném `ValidationError`), `backend/carbon/errors.py:12`, `backend/api.py:149-158` (`_ERROR_STATUS`) |
| Evidence | `_ERROR_STATUS` ánh xạ các lớp con `InvalidWaterRegimeError`, `ConflictingWaterRegimeError`, `MissingActivityDataError`, nhưng không ánh xạ `ValidationError` gốc → nhánh `500 internal_error` |
| Impact | Khi GWP có giá trị, vụ có lần bón thiếu hàm lượng đạm nhận `500` chung chung thay vì lỗi `422` nêu rõ cần bổ sung dữ liệu; client không hiển thị được lý do |
| Hành vi hiện tại | `500 internal_error` (tiềm ẩn vì dòng CH₄ dừng ở GWP trước) |
| Hành vi mong đợi | `422 missing_activity_data` kèm thông điệp của engine |
| Status | **RESOLVED** — `422 missing_activity_data` trước mọi tra cứu hệ số (commit `182d0ba`); hosted API trả `422` ngay cả khi GWP còn null. Xem [sprint P1](#sprint-p1-2026-09-15) |
| Codex | CONFIRMED |

### B1 — Cờ đầy đủ nước/phân bón phụ thuộc bản ghi cuối {#b1}

| Trường | Nội dung |
|---|---|
| Module | Resource Metrics |
| Severity | Medium |
| Loại | `CODE_BUG` |
| Source | `backend/infrastructure/read_repo.py:380-387` (`_compute_metric_totals`); test `backend/tests/test_read_repository.py:251-265` |
| Evidence | Mỗi bản ghi tưới gán `has_water = True` rồi mới gán `False` nếu thiếu `water_volume_m3` (tương tự `has_fertilizer`). Giá trị cuối chỉ phản ánh bản ghi duyệt sau cùng. Test hiện có chỉ thêm bản ghi thiếu **sau** dữ liệu sẵn có |
| Impact | Vụ có một bản ghi tưới thiếu lượng nước đứng trước bản ghi có số: `completeness.water = true`, `water_m3` và `water_per_kg` tính từ tổng thiếu (thấp hơn thực tế); lan sang tổng hợp farm/tổ chức, farm performance, khuyến nghị bổ sung dữ liệu và mục `resource_metrics` của gói MRV. Phân bón ít khả năng xảy ra vì `fertilizer_applications.amount_kg` là `NOT NULL` |
| Hành vi hiện tại | Kết quả phụ thuộc thứ tự bản ghi |
| Hành vi mong đợi | Chỉ cần một bản ghi thiếu → cờ `false`, tổng và chỉ số trên kg là `null` |
| Status | **RESOLVED** — cờ không phụ thuộc thứ tự, cùng hàm cho đường đơn vụ và tổng hợp (commit `4c6c53b`); hosted: thiếu-trước và thiếu-sau đều `null`/`false`. Xem [sprint P1](#sprint-p1-2026-09-15) |
| Codex | CONFIRMED |

### B2 — Web không nhận role `enterprise_viewer` {#b2}

| Trường | Nội dung |
|---|---|
| Module | Web routing |
| Severity | Medium |
| Loại | `CODE_BUG` |
| Source | `web-dashboard/src/types.ts:1`, `web-dashboard/src/api/me.ts:7,13`, `web-dashboard/src/App.tsx:22`; enum DB `organization_role` tại `baseline.sql:37-38` |
| Evidence | Web so khớp `'enterprise'`, DB và `/v1/me` trả `'enterprise_viewer'`; không khớp thì mặc định `'farmer'` |
| Impact | Tài khoản chỉ có `enterprise_viewer` vào khu Farmer. Server vẫn chặn ghi (không có role `farmer`), nên đây là lỗi luồng giao diện, không phải leo thang quyền |
| Hành vi hiện tại | Hiển thị shell Farmer |
| Hành vi mong đợi | Nhận đúng `enterprise_viewer` và đưa vào shell chỉ đọc phù hợp |
| Status | **RESOLVED** — web dùng đúng `enterprise_viewer` (commit `8a1aeb6`); `/v1/me` hosted trả `enterprise_viewer`, ánh xạ vào Management Web chỉ đọc. Xem [sprint P1](#sprint-p1-2026-09-15) |
| Codex | CONFIRMED |

### B6 — `backend/requirements.txt` thiếu dependency của `ml/` {#b6}

| Trường | Nội dung |
|---|---|
| Module | Backend dependency |
| Severity | Medium |
| Loại | `CODE_GAP` |
| Source | `backend/service.py:49-50`, `ml/infer.py:18-20`, `ml/requirements.txt:3-5`, `backend/requirements.txt` |
| Evidence | `service.py` import `ml.infer` ở cấp module; `ml/infer.py` import `torch`, `PIL`; `backend/requirements.txt` không có `torch`, `torchvision`, `pillow` |
| Impact | Môi trường chỉ cài `backend/requirements.txt` không import được `service.py` → cả API không khởi động (không chỉ route CV). Hướng dẫn chạy local ghi rõ cách khắc phục |
| Hành vi hiện tại | Phải cài thêm `ml/requirements.txt` thủ công |
| Hành vi mong đợi | Manifest dependency của backend đủ để khởi động, hoặc CV import lười và chỉ CV trả `503` |
| Status | OPEN |
| Codex | CONFIRMED |

### B8 — `AGRICARBON_REQUIRE_FACTOR_SET_IN_DB` không được dùng {#b8}

| Trường | Nội dung |
|---|---|
| Module | Config |
| Severity | Low |
| Loại | `CODE_GAP` |
| Source | `backend/infrastructure/config.py:42`, `:95` |
| Evidence | Giá trị được đọc vào `Settings.require_factor_set_in_db`; không có chỗ nào khác đọc thuộc tính này |
| Impact | Người vận hành đặt biến nhưng không đổi hành vi |
| Hành vi hiện tại | Không có tác dụng |
| Hành vi mong đợi | Hoặc hiện thực đúng ý nghĩa, hoặc xoá biến và tài liệu liên quan |
| Status | OPEN |
| Codex | CONFIRMED |

### B12 — Comment trong `schemas.py` lệch với form {#b12}

| Trường | Nội dung |
|---|---|
| Module | Activities schema |
| Severity | Low |
| Loại | `CODE_GAP` (comment lỗi thời) |
| Source | `backend/schemas.py:175-181`; `web-dashboard/src/farmer/ActivityForms.tsx:289-290`, `:303` |
| Evidence | Comment nói form Farmer Web cố ý không thu thập `days_before_cultivation`/`dry_matter_fraction`; form hiện có hai ô này (không bắt buộc) |
| Impact | Gây hiểu nhầm cho người sửa code; không ảnh hưởng runtime |
| Hành vi hiện tại | Comment sai |
| Hành vi mong đợi | Comment mô tả đúng form hiện tại |
| Status | OPEN |
| Codex | CONFIRMED |

## Sprint P0 (2026-09-15) {#sprint-p0-2026-09-15}

Nhánh `feature/p0-security-auth-fixes`, merge vào `main`. Chỉ sửa **M7, B7, B3**; mọi mục
P1/P2 còn lại vẫn `OPEN`. Mỗi mục chỉ được đánh dấu `RESOLVED` sau khi có code, test và
kiểm chứng trên Supabase hosted.

| ID | Nguyên nhân gốc (đã xác nhận) | Sửa | Commit |
|---|---|---|---|
| M7 | Bốn policy baseline `mrv_files_storage_*` phủ cả `mrv-evidence` lẫn `mrv-exports`; migration `20260913150000` chỉ siết metadata `mrv_exports_select` | Migration `20260915100000_restrict_mrv_exports_storage_client_access.sql`: bốn policy được thay bằng bản giống hệt nhưng chỉ cho `mrv-evidence`; không còn policy client nào cho `mrv-exports`, nên mọi thao tác list/tải/upload/ghi đè/xoá từ client bị từ chối. Backend (service role) và đường tải qua FastAPI không đổi; bucket vẫn private | `3af4205` |
| B7 | `SupabaseReadRepository.me()` gộp mọi dòng `organization_memberships` mà RLS trả về cho chính người dùng, kể cả dòng đã kết thúc | `backend/infrastructure/memberships.py` — bản Python duy nhất của quy tắc `ended_at is null or ended_at > now()` — dùng trong `me()` (cả `roles` lẫn danh sách membership) và trong `MrvExportService._manages` | `202fb80` |
| B3 | Service chỉ xác lập quyền **đọc** qua JWT rồi ghi bằng kết nối bỏ qua RLS; quyền đọc farm gồm cả `viewer`. Đường ghi trực tiếp của Flutter vốn đã bị RLS từ chối (xác nhận lại trên hosted) | `PostgresActivityWriteRepository` gọi `private.user_can_write_batch` (helper của policy `activities` và RPC `soft_delete_activity`) trong chính transaction ghi, trước mọi thao tác, với `auth.uid()` là actor đã xác thực; từ chối → `404 not_found` như quy ước cũ. Farmer Web ẩn nút ghi/sửa/xoá trên ruộng mà `/v1/me` không báo `owner`/`editor` | `f9056fb` |

Test và script kiểm chứng: `92fa4f6`.

| Kiểm chứng | Kết quả |
|---|---|
| Tái hiện M7 trên hosted **trước** khi áp migration, qua Storage API thật | Farmer (owner, viewer), regulator và enterprise_viewer qua data grant, manager đều liệt kê và tải được XLSX; manager upload được object lạ. Smoke: 44/50, đúng 6 check M7 fail |
| Áp migration lên hosted dev | `20260915100000` ghi vào `supabase_migrations.schema_migrations`; 0 policy `storage.objects` nhắc `mrv-exports`; 3 bucket vẫn private |
| `backend/scripts/hosted_p0_security_smoke.py` sau migration (tenant + user tạm, Storage API, PostgREST, FastAPI thật) | **PASS** 50/50 |
| `backend/tests/test_p0_security_policies.py` (hosted, transaction rollback) | **PASS** 13/13 |
| `backend/tests/test_activity_rls_policies.py` (hosted, rollback — hợp đồng M01) | **PASS** 19/19 |
| Backend `python -m pytest tests -q` | **PASS** 510 passed (trước sprint: 463) |
| Web Vitest / `tsc -b` / `npm run build` | **PASS** 160 passed / PASS / PASS |
| Playwright mock Farmer + Management | **PASS** 2 passed (8 spec dữ liệu thật bị gate, skipped) |
| Playwright dữ liệu thật | **NOT RUN** — cần mật khẩu QA do người dùng cấp theo phiên; phần Storage/RLS/API thật do smoke script phủ |
| Flutter test | **NOT RUN** — không đổi code hay policy mà Flutter dùng; RLS ghi trực tiếp đã kiểm trên hosted |

Dữ liệu QA: mỗi lần chạy smoke tạo tenant `P0-SECURITY-SMOKE-<run>` và user Auth tạm với mật
khẩu ngẫu nhiên, rồi xoá; số dòng của 17 bảng, số object `mrv-exports` và số user tạm trở
về đúng như trước (0 dòng còn lại). Test rollback không để lại dữ liệu. `audit.change_log`
giữ các dòng do trigger audit ghi (86 dòng/lần chạy) vì bảng audit là append-only.

## Sprint P1 (2026-09-15) {#sprint-p1-2026-09-15}

Nhánh `feature/p1-correctness-fixes`, merge vào `main`. Chỉ sửa **B4, M3, B5, B1, B2**.
Không điền GWP, không import bộ hệ số, không đổi phương pháp luận Carbon; các mục P2
(B6, B8, B12) vẫn `OPEN`.

**Quyết định sản phẩm cho B4** (chủ dự án chốt trong sprint): chỉ **người ghi được vụ**
mới được lưu bản tính — đúng helper sẵn có `private.user_can_write_crop` (farm
`owner`/`editor` hoặc `cooperative_manager` còn hiệu lực của HTX). Xem kết quả, và chạy
giả định `persist=False` của Recommendation, không đổi.

| ID | Nguyên nhân gốc (đã xác nhận) | Sửa | Commit |
|---|---|---|---|
| B4 | Cổng của `POST /v1/carbon/calculate` chỉ kiểm JWT + quyền **đọc** vụ, rồi lưu bằng service role | `infrastructure/persist_access.py`: sau cổng đọc và **trước** khi engine chạy, đánh giá `private.user_can_write_crop` với `auth.uid()` là người dùng đã được Auth xác thực; từ chối → `404 crop_not_found` như cũ; thiếu cấu hình → `503` (fail closed). Management Web ẩn nút "Tính lại" với `regulator`/`enterprise_viewer` | `7de5bf7` |
| M3 | `MrvExportService` gọi `CarbonService.latest(sid)` không truyền kịch bản | Gói xuất chỉ lấy kịch bản ghi nhận (`as_recorded` ↔ DB `actual`); không có thì `carbon` = `unavailable` + cảnh báo `carbon_unavailable`, không bao giờ lấy kịch bản khác. Cột `scenario` sẵn có đủ để phân biệt — **không** thêm cột mới | `ef2424f` |
| M3 (blocker phát hiện khi kiểm hosted) | Trigger baseline `private.validate_mrv_export_calculation` vẫn đòi `carbon_calculations.production_batch_id` thuộc `mrv_case_batches`, trong khi bản tính theo crop season có `production_batch_id = NULL` → gói MRV đầu tiên có bản tính thật sẽ lỗi | Migration `20260915120000_mrv_export_calculation_crop_season_scope.sql`: giữ luật bộ hệ số, đổi luật phạm vi thành "crop season của bản tính có lô thuộc hồ sơ"; vụ ngoài hồ sơ vẫn bị từ chối. Hosted có 0 dòng `carbon_calculations`/`mrv_export_calculations` → không diễn giải lại dữ liệu cũ | `ef2424f` |
| B5 | `total_nitrogen_kg` ném `ValidationError` gốc, API không ánh xạ | Engine kiểm hàm lượng đạm cùng nhóm kiểm tra dữ liệu, **trước** mọi tra cứu hệ số, ném `MissingActivityDataError` → `422 missing_activity_data`; không mặc định, không đoán; `0` là giá trị hợp lệ | `182d0ba` |
| B1 | Cờ đầy đủ bị gán lại `True` ở mỗi bản ghi → phụ thuộc bản ghi cuối | Tách "đã thấy bản ghi" và "có bản ghi thiếu": chỉ một giá trị thiếu là cả nhóm thiếu, tử số `null`, bất kể thứ tự. Công thức không đổi | `4c6c53b` |
| B2 | Web so khớp `enterprise` thay vì role DB `enterprise_viewer` | Kiểu role của web dùng đúng giá trị backend; `enterprise_viewer` vào Management Web chỉ đọc, không thành `cooperative_manager`; hint cũ mang alias bị bỏ qua | `8a1aeb6` |

Test và script kiểm chứng: `76bb8a2`.

| Kiểm chứng | Kết quả |
|---|---|
| Tái hiện blocker trigger trên hosted trước migration (test rollback) | Bản tính theo crop season trong phạm vi hồ sơ bị từ chối "MRV export calculation batch must be inside the MRV case scope" |
| Áp migration `20260915120000` lên hosted dev | Ghi vào `supabase_migrations.schema_migrations`; hàm trigger dùng phạm vi crop season |
| `backend/scripts/hosted_p1_correctness_smoke.py` (tenant + user tạm, bộ hệ số **draft**, FastAPI + Supabase thật) | **PASS** 30/30 — B2 `/v1/me` trả `enterprise_viewer`; B5 `422 missing_activity_data` trước cổng hệ số; B4 viewer/regulator/enterprise xem được nhưng lưu bị `404`, cross-scope `404`, không token `401`, owner/editor/manager qua cổng, không dòng nào được lưu; M3 chọn bản ghi nhận thay vì bản AWD mới hơn, liên kết đúng bản, bản ghi nhận mới hơn thay thế, chỉ có kịch bản giả định → `unavailable` + cảnh báo, không liên kết; B1 thiếu-trước và thiếu-sau đều `null`/`false`, tổng hợp farm `null` |
| `backend/tests/test_p1_correctness_policies.py` (hosted, rollback) | **PASS** 9/9 — `user_can_write_crop` cho owner/editor/viewer/manager còn và hết hiệu lực/grant reader/người ngoài; trigger mới |
| Backend `python -m pytest tests -q` | **PASS** 567 passed (trước sprint: 510) |
| Web Vitest / `tsc -b` / `npm run build` | **PASS** 171 passed / PASS / PASS |
| Playwright mock Farmer + Management | **PASS** 2 passed (8 spec dữ liệu thật bị gate, skipped) |
| Playwright dữ liệu thật | **NOT RUN** — cần mật khẩu QA do người dùng cấp; không có tài khoản enterprise QA |
| Flutter test | **NOT RUN** — không đổi code Flutter. Lưu ý hành vi: farm `viewer` bấm "Tính" trên app nay nhận `404 crop_not_found` |

Dữ liệu QA: mỗi lần chạy smoke tạo tenant `P1-CORRECTNESS-SMOKE-<run>`, user tạm và bộ hệ số
draft rồi xoá; số dòng của 21 bảng, object `mrv-exports` và user tạm trở về như trước (0 dòng
còn lại). `audit.change_log` giữ dòng do trigger audit ghi (append-only).

**Carbon sau sprint:** độ đúng kỹ thuật (quyền lưu, chọn bản tính chuẩn, mã lỗi, tổng hợp
metrics) đã được sửa và kiểm trên hosted; **mức sẵn sàng khoa học vẫn BLOCKED** (GWP, hệ số
nhiên liệu/lưới điện, hệ số quốc gia, import bộ hệ số — xem S1–S9).

## `PRODUCT_DECISION`

| ID | Nội dung | Evidence | Cần quyết định |
|---|---|---|---|
| <span id="b9"></span>B9 | Farmer Web gửi `occurred_at = YYYY-MM-DDT00:00:00Z` — form chỉ chọn ngày. `00:00Z` là 07:00 giờ Việt Nam cùng ngày nên không lệch ngày, nhưng mất giờ trong ngày | `web-dashboard/src/farmer/ActivityForms.tsx:349` | Chấp nhận độ chính xác theo ngày, hay thu thập giờ/múi giờ |
| <span id="b10"></span>B10 | Farmer Web không có form nhiên liệu (`fuel` không nằm trong `_DETAILS`); không route nào tạo farm/thửa/vụ/lô | `backend/infrastructure/write_repo.py:25-35`, danh sách route `backend/api.py` | Có mở rộng Farmer Web/API hay giữ phạm vi FW-2 |
| <span id="b11"></span>B11 | Bảng/view baseline không được code dùng: `recommendations`, `recommendation_rules`, `benchmark_snapshots`, `benchmark_snapshot_members`, `resource_metric_snapshots`, `sync_batches`, `ingestion_batches`, `data_quality_flags`, các view `v_*` | `supabase/migrations/20260907000000_baseline.sql`; grep toàn bộ `backend/`, `app/lib/`, `web-dashboard/src/`, `ml/` | Giữ cho lộ trình sau hay xoá bằng migration |

## `SCIENTIFIC_BLOCKER`

Không phải lỗi code; chi tiết ở [Giới hạn hiện tại](current-limitations.md) (S1–S9):
GWP CH₄/N₂O `null`, hệ số nhiên liệu/lưới điện chưa có, IPCC Tier 1 default thay vì
hệ số quốc gia, bộ hệ số chưa import vào DB hosted.

## `ENV_BLOCKED` và trạng thái test

Trạng thái trong lượt kiểm toán tài liệu (trước sprint P0). Chỉ ghi PASS cho test **đã thực sự
chạy**. Kết quả của sprint P0 nằm ở [mục riêng](#sprint-p0-2026-09-15).

| Nhóm test | Trạng thái |
|---|---|
| Backend `python -m pytest tests -q` (repository giả/fixture, không gọi Supabase) | **PASS** — 463 passed |
| Kiểm tra RLS/Storage trên Supabase hosted (cần cho M7, B3, B4, B7) | **BLOCKED** — Supabase environment/credential unavailable |
| Playwright dữ liệu thật (`playwright.real.config.ts`) | **NOT RUN** — environment dependency unavailable |
| Web Vitest, Playwright mock | **NOT RUN** — không chạy trong lượt tài liệu |
| ML `pytest ml/tests` | **NOT RUN** — không chạy trong lượt tài liệu |
| Flutter `flutter test`, `integration_test/` | **NOT RUN** — không chạy trong lượt tài liệu; integration test cần thiết bị/emulator |

Test backend xanh chứng minh logic trên dữ liệu giả, **không** chứng minh policy RLS
hosted hay giá trị khoa học (`tests/fixtures/test_factors.yaml` là TEST ONLY).

## `RESOLVED_DOC` — lỗi tài liệu đã sửa trong đợt này

| ID | Trang | Nội dung sai | Đã sửa thành |
|---|---|---|---|
| D1 | [Carbon Engine](../modules/carbon-engine.md) | Bảng input ghi thiếu `nitrogen_percent` → `422` | `ValidationError` → hiện là `500 internal_error` (B5) |
| D2 | [Authentication và RLS](../security/authentication-and-rls.md) | "FastAPI chỉ thu hẹp thêm trên nền RLS, không bao giờ nới rộng" | Ghi rõ đó là ý đồ thiết kế; nêu ngoại lệ B3, B4, B7, M7 |
| D3 | [Hướng dẫn Quản lý](../user-guide/management.md) | "Doanh nghiệp xem được hồ sơ" trong Management Web | Tài khoản `enterprise_viewer` hiện bị đưa vào khu Nông hộ (B2) |
| D4 | [Database](../database/schema.md), [Giới hạn](current-limitations.md) | Policy Storage `mrv-exports` được mô tả như đường không dùng | Ghi là lỗ hổng quyền đọc đang mở (M7) |

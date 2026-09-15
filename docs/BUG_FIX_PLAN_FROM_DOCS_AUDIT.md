# Bug-fix plan từ đợt kiểm toán tài liệu

> **Chỉ là kế hoạch.** Không mục nào dưới đây được sửa trong đợt tài liệu. Nguồn và
> bằng chứng đầy đủ: `docs/limitations/implementation-audit-findings.md`.
> Code đối chiếu: commit `2f33972` (`main`). Mọi ID đã được Codex kiểm tra chéo read-only.

Phạm vi kế hoạch: mọi mục `CODE_BUG` / `CODE_GAP`. Các mục `PRODUCT_DECISION`
(B9, B10, B11) và `SCIENTIFIC_BLOCKER` (S1–S9) nằm ở cuối, không lên lịch sửa code.

Quy ước chung cho mọi fix:

- Một nhánh / một PR cho mỗi nhóm; không trộn fix với refactor.
- Test backend hiện dùng repository giả — **mọi fix đụng quyền truy cập phải có thêm
  kiểm tra trên Supabase thật** trước khi coi là DONE.
- Không ghi PASS cho test chưa chạy.

## Tổng quan ưu tiên

| Priority | ID | Severity | Module | Cần Supabase/runtime |
|---|---|---|---|---|
| P0 | M7 | High | Storage / RLS | Có (migration + kiểm tra hosted) |
| P0 | B7 | High | Auth `/v1/me` | Có cho xác nhận cuối |
| P0 | B3 | High | Activities (Farmer Web) | Có cho xác nhận cuối |
| P1 | M3 | High | MRV Export | Không bắt buộc (unit); nên có E2E |
| P1 | B4 | Medium | Carbon API | Có cho xác nhận cuối |
| P1 | B5 | Medium | Carbon API | Không |
| P1 | B1 | Medium | Resource Metrics | Không |
| P1 | B2 | Medium | Web routing | Không bắt buộc (mock E2E); nên có tài khoản thật |
| P2 | B6 | Medium | Backend dependency | Không |
| P2 | B8 | Low | Config | Không |
| P2 | B12 | Low | Activities schema | Không |

---

## P0 — Bảo mật / toàn vẹn quyền truy cập

### M7 — Policy đọc Storage `mrv-exports` rộng hơn metadata

- **Severity:** High · **Loại:** `CODE_BUG`
- **Module:** Supabase Storage RLS, MRV Export
- **Source:** `supabase/migrations/20260907000000_baseline.sql:2837-2842`
  (`mrv_files_storage_select`); `supabase/migrations/20260913150000_mrv_xlsx_export_artifacts.sql:97-99`;
  `backend/service.py:638`
- **Root cause:** Migration `20260913150000` siết `mrv_exports_select` về
  `user_can_manage_mrv_case` khi artifact trở thành object thật, nhưng không siết
  policy `storage.objects` tương ứng; policy baseline vẫn dùng
  `user_can_read_organization` cho cả `mrv-evidence` lẫn `mrv-exports`.
- **Repro / observation:** Đọc policy SQL. Kịch bản cần xác nhận trên hosted: đăng
  nhập tài khoản `farmer` (hoặc `regulator` có data grant) của tổ chức sở hữu case đã
  có XLSX/PDF → dùng supabase-js với publishable key + JWT gọi
  `storage.from('mrv-exports').list('<organization_id>/<mrv_case_id>')` rồi `download`.
- **Expected:** Người không phải manager của tổ chức không liệt kê/tải được object
  `mrv-exports`; manager tải qua API như hiện tại.
- **Proposed fix:** Migration mới tách policy theo bucket: `mrv-exports` SELECT chỉ khi
  `private.user_is_org_manager(<org>)` (hoặc bỏ hẳn quyền SELECT của `authenticated`,
  vì backend đọc bằng service role). Giữ nguyên `mrv-evidence` cho tới khi có quyết định
  sản phẩm về ai được xem bằng chứng. Xem lại luôn policy INSERT/UPDATE/DELETE của
  `mrv-exports` cho client (backend là bên ghi duy nhất).
- **Tests required:** (1) SQL/RLS test trên Supabase: farmer, regulator (grant),
  enterprise_viewer (grant), manager tổ chức khác, manager hết hạn → không đọc được;
  manager đúng tổ chức → theo chính sách mới. (2) Gated E2E download MRV hiện có vẫn
  chạy (backend service role không bị ảnh hưởng). (3) Backend pytest không đổi.
- **Risk:** Thấp cho luồng ứng dụng (không client nào đọc Storage trực tiếp); rủi ro
  chính là migration hosted — cần review diff policy và thứ tự `drop policy`/`create`.
- **Dependencies:** Quyền chạy migration trên Supabase hosted; quyết định cho
  `mrv-evidence`.
- **Supabase/runtime:** **Bắt buộc.**

### B7 — `/v1/me` không lọc membership đã kết thúc

- **Severity:** High · **Loại:** `CODE_BUG`
- **Module:** Auth — `SupabaseReadRepository.me`
- **Source:** `backend/infrastructure/read_repo.py:157-167`; người dùng role:
  `backend/service.py:128-132`, `:229`, `:303`; web `web-dashboard/src/api/me.ts:13`
- **Root cause:** `me()` đọc toàn bộ `organization_memberships` của user rồi gộp `role`,
  không áp điều kiện `ended_at is null or ended_at > now()` mà mọi helper RLS dùng.
- **Repro / observation:** Tài khoản có membership `farmer` với `ended_at` trong quá khứ
  (và còn dòng `farm_members`) → `GET /v1/me` vẫn trả `farmer` trong `roles` →
  `POST /v1/crop-seasons/{id}/activities` qua được cổng role.
- **Expected:** `roles` chỉ gồm membership còn hiệu lực.
- **Proposed fix:** Lọc `ended_at` trong `me()` (tại query hoặc khi gộp), giữ nguyên
  `organization_memberships` trả về nhưng có thể đánh dấu hết hạn. Không thay đổi
  `MrvExportService._manages` (đã lọc riêng).
- **Tests required:** Unit test `test_read_repository.py`: membership hết hạn không vào
  `roles`; membership `ended_at` tương lai vẫn vào. Test service: farmer hết hạn → 404
  cho write/recommendation/CV. Xác nhận trên hosted bằng tài khoản QA có membership hết hạn.
- **Risk:** Người dùng đang dựa vào membership hết hạn (dữ liệu seed sai) sẽ mất quyền
  ghi — đúng ý đồ, nhưng cần kiểm tra dữ liệu demo/QA trước khi deploy.
- **Dependencies:** Làm cùng hoặc trước B3 (cùng cổng quyền).
- **Supabase/runtime:** Unit test không cần; **xác nhận cuối cần Supabase.**

### B3 — Ghi activity qua Farmer Web không kiểm quyền ghi farm

- **Severity:** High · **Loại:** `CODE_BUG`
- **Module:** Activities — `ActivityWriteService`
- **Source:** `backend/service.py:128-150`; RLS tham chiếu
  `baseline.sql:1554-1564`, `1586-1603`, `1667-1678`, `1859-1866`
- **Root cause:** Service xác lập phạm vi bằng **đọc** qua RLS (`season`,
  `production_batches`) rồi ghi bằng kết nối psycopg bỏ qua RLS. Quyền đọc farm rộng
  hơn quyền ghi (`viewer` đọc được, không ghi được), và service không kiểm lại quyền ghi.
- **Repro / observation:** Tài khoản có `organization_role = farmer` và
  `farm_members.farm_role = viewer` trên farm X; vụ `active` với đúng một lô mở →
  `POST /v1/crop-seasons/{season}/activities` trả `201`. Cùng tài khoản ghi qua
  PostgREST (Flutter) bị `42501`.
- **Expected:** FastAPI trả `404 not_found` (quy ước hiện tại cho ngoài phạm vi) khi
  người gọi không có `private.user_can_write_batch` trên lô đích; áp cho create, update, delete.
- **Proposed fix:** Hỏi RLS thay vì tự tái hiện quy tắc trong Python: thêm RPC
  `security definer` chỉ đọc (ví dụ `public.can_write_batch(uuid) returns boolean`
  gọi `private.user_can_write_batch`) và gọi bằng JWT người gọi qua
  `SupabaseReadRepository` trước bước ghi. Phương án thay thế (không migration): đọc
  `farm_members` của người gọi qua RLS và kiểm `owner`/`editor` hoặc manager — nhưng dễ
  lệch với helper SQL về sau.
- **Tests required:** Unit test service với read repository giả: viewer → 404,
  editor/owner → 201, manager không có role farmer → giữ hành vi hiện tại (404). Test
  update/delete tương tự. Real E2E Farmer (gated) với tài khoản viewer.
- **Risk:** Trung bình — đổi cổng ghi của Farmer Web; tài khoản QA Farmer phải có
  `owner`/`editor`, nếu không real E2E hiện có sẽ fail. Thêm một round trip mỗi lần ghi.
- **Dependencies:** B7; nếu chọn RPC thì cần migration + deploy hosted.
- **Supabase/runtime:** **Bắt buộc** cho xác nhận cuối (và cho migration nếu chọn RPC).

---

## P1 — Tính đúng đắn

### M3 — Gói MRV lấy bản tính Carbon mới nhất bất kể kịch bản

- **Severity:** High · **Loại:** `CODE_BUG`
- **Module:** MRV Export
- **Source:** `backend/service.py:589`; `backend/infrastructure/supabase_repo.py:151-163`;
  `backend/mrv/manifest.py:577`; đối chiếu `backend/infrastructure/read_repo.py:390`
- **Root cause:** `_create_snapshot` gọi `self._carbon.latest(sid)` không truyền
  `scenario`; repository chỉ lọc kịch bản khi được truyền.
- **Repro / observation:** (khi GWP có giá trị hoặc với repository in-memory) lưu bản
  `as_recorded`, sau đó lưu bản `awd` cho cùng vụ → tạo gói JSON → `carbon[].scenario = awd`,
  trong khi `resource_metrics` dùng bản `actual`.
- **Expected:** Mục `carbon` dùng kịch bản ghi nhận (`as_recorded` ↔ DB `actual`); nếu
  không có thì `status: unavailable` + cảnh báo `carbon_unavailable` như hiện tại.
- **Proposed fix:** Gọi `self._carbon.latest(sid, "as_recorded")`. Không thêm kịch bản
  giả định vào gói trừ khi có quyết định sản phẩm (nếu có thì phải ở mục riêng, gắn
  nhãn giả định).
- **Tests required:** Test MRV snapshot với repository in-memory có cả bản `actual` và
  `awd` mới hơn → manifest chọn `actual`; `mrv_export_calculations` liên kết đúng bản.
  Kiểm tra `payload_sha256` của snapshot fixture có đổi hay không và cập nhật fixture có chủ đích.
- **Risk:** Thấp; gói cũ đã lưu không đổi (snapshot bất biến).
- **Dependencies:** Không. **Phải xong trước khi GWP được điền.**
- **Supabase/runtime:** Không bắt buộc; nên chạy gated E2E MRV export sau khi sửa.

### B4 — `POST /v1/carbon/calculate` không có cổng role

- **Severity:** Medium · **Loại:** `CODE_GAP` (+ quyết định sản phẩm)
- **Module:** Carbon API
- **Source:** `backend/api.py:116-137`, `backend/api.py:174-211`; `baseline.sql:1907-1908`
- **Root cause:** Cổng của route chỉ kiểm JWT + quyền đọc vụ; route ghi bằng service role.
- **Repro / observation:** Tài khoản `regulator` có data grant (hoặc `viewer` của farm)
  gọi `POST /v1/carbon/calculate` cho vụ đọc được → qua cổng, engine chạy; hiện dừng ở
  `422 missing_emission_factor`, khi GWP có giá trị sẽ lưu hàng `carbon_calculations`.
- **Expected:** Chỉ role sản phẩm cho phép mới lưu được bản tính; role chỉ đọc bị từ chối.
- **Proposed fix:** (1) Chốt danh sách role (đề xuất: manager của HTX sở hữu farm và
  người ghi được farm). (2) Thêm kiểm tra trong route/`CarbonService` dùng cùng cơ chế
  với B3 (quyền ghi qua RLS). (3) Cân nhắc cho phép chạy `persist=False` cho role chỉ
  đọc nếu sản phẩm cần xem thử.
- **Tests required:** Test API: regulator/enterprise_viewer/viewer → từ chối;
  manager/editor → qua cổng. Test Flutter `carbon_api_service_test.dart` vẫn parse lỗi.
  Xác nhận trên hosted.
- **Risk:** Trung bình — Flutter hiện gọi route này; farmer `viewer` sẽ mất nút tính.
- **Dependencies:** Quyết định sản phẩm; nên dùng chung cơ chế với B3. **Phải xong trước
  khi GWP được điền.**
- **Supabase/runtime:** **Bắt buộc** cho xác nhận cuối.

### B5 — Thiếu `nitrogen_percent` trả `500`

- **Severity:** Medium · **Loại:** `CODE_BUG`
- **Module:** Carbon Engine / Carbon API
- **Source:** `backend/carbon/models.py:193-205`; `backend/carbon/errors.py:12`;
  `backend/api.py:149-158`
- **Root cause:** `total_nitrogen_kg` ném `ValidationError` gốc; bảng `_ERROR_STATUS`
  chỉ chứa các lớp con.
- **Repro / observation:** Test engine/API với YAML test có GWP (fixture TEST ONLY) và
  một lần bón `nitrogen_percent = null` → `POST /v1/carbon/calculate` trả `500`.
- **Expected:** `422 missing_activity_data` kèm thông điệp engine.
- **Proposed fix:** Ném `MissingActivityDataError` trong `total_nitrogen_kg` (ưu tiên —
  đúng ngữ nghĩa), hoặc thêm `(ValidationError, 422, ...)` **sau** các lớp con trong
  `_ERROR_STATUS`.
- **Tests required:** Test API với `tests/fixtures/test_factors.yaml` + phân bón thiếu
  N → `422 missing_activity_data`; test engine khẳng định lớp lỗi.
- **Risk:** Thấp.
- **Dependencies:** Không.
- **Supabase/runtime:** Không.

### B1 — Cờ đầy đủ nước/phân bón phụ thuộc bản ghi cuối

- **Severity:** Medium · **Loại:** `CODE_BUG`
- **Module:** Resource Metrics
- **Source:** `backend/infrastructure/read_repo.py:380-387`;
  `backend/tests/test_read_repository.py:251-265`
- **Root cause:** Cờ được **gán lại** `True` ở mỗi bản ghi thay vì chỉ khởi tạo khi gặp
  bản ghi đầu tiên và chỉ có thể chuyển sang `False`.
- **Repro / observation:** Vụ có bản ghi tưới A (`water_volume_m3 = null`) trả về trước
  bản ghi B (`water_volume_m3 = 100`) → `water_m3 = 100`, `completeness.water = true`.
- **Expected:** `water_m3 = null`, `water_per_kg = null`, `completeness.water = false`
  bất kể thứ tự; tương tự cho phân bón.
- **Proposed fix:** Tách "có bản ghi" (`seen_water`) và "thiếu giá trị" (`missing_water`);
  `has_water = seen_water and not missing_water`.
- **Tests required:** Test tham số hoá thứ tự (thiếu-trước, thiếu-sau) cho nước và phân
  bón; test tổng hợp farm/tổ chức propagate `null`; test manifest MRV
  `resource_metric_incomplete`.
- **Risk:** Thấp–trung bình: một số vụ đang hiển thị số sẽ chuyển sang "Chưa đủ dữ
  liệu" — đúng ý đồ, cần báo trước cho người dùng demo.
- **Dependencies:** Không.
- **Supabase/runtime:** Không.

### B2 — Web không nhận role `enterprise_viewer`

- **Severity:** Medium · **Loại:** `CODE_BUG`
- **Module:** Web routing
- **Source:** `web-dashboard/src/types.ts:1`, `web-dashboard/src/api/me.ts:7,13`,
  `web-dashboard/src/App.tsx:22`
- **Root cause:** Chuỗi role phía web (`enterprise`) không khớp enum DB (`enterprise_viewer`).
- **Repro / observation:** Mock `/v1/me` trả `roles: ["enterprise_viewer"]` → web mở `/farmer`.
- **Expected:** Nhận `enterprise_viewer` và mở shell chỉ đọc (Management không có nút
  xuất MRV), hoặc trang "chưa hỗ trợ" rõ ràng theo quyết định sản phẩm.
- **Proposed fix:** Đổi `Role` sang `enterprise_viewer`, cập nhật `rolePriority`, nhãn
  trong `App.tsx`, `roles.ts`/`nav.ts` nếu có phân quyền menu; không mặc định
  `farmer` cho role lạ.
- **Tests required:** Vitest cho `me.ts` (mọi role DB); Playwright mock cho tài khoản
  `enterprise_viewer`; real E2E nếu có tài khoản doanh nghiệp.
- **Risk:** Thấp.
- **Dependencies:** Quyết định sản phẩm về shell của doanh nghiệp.
- **Supabase/runtime:** Không bắt buộc.

---

## P2 — Vận hành / dọn dẹp

### B6 — `backend/requirements.txt` thiếu dependency của `ml/`

- **Severity:** Medium · **Loại:** `CODE_GAP`
- **Module:** Backend dependency
- **Source:** `backend/service.py:49-50`, `ml/infer.py:18-20`, `ml/requirements.txt:3-5`
- **Root cause:** `ml.infer` được import ở cấp module của `service.py`.
- **Repro / observation:** venv mới chỉ `pip install -r backend/requirements.txt` →
  `uvicorn main:app` lỗi `ModuleNotFoundError: torch`.
- **Expected:** API khởi động; CV trả `503` nếu thiếu torch/checkpoint.
- **Proposed fix:** Import `ml.infer` lười trong nhánh dựng `CvService`
  (`main.py::_build_cv_service`) **hoặc** thêm `-r ../ml/requirements.txt` vào backend
  requirements. Ưu tiên import lười để image backend không bắt buộc kèm torch.
- **Tests required:** Test import `service`/`main` khi `torch` không có (monkeypatch
  `sys.modules`); backend pytest đầy đủ.
- **Risk:** Thấp.
- **Dependencies:** Không.
- **Supabase/runtime:** Không.

### B8 — `AGRICARBON_REQUIRE_FACTOR_SET_IN_DB` không được dùng

- **Severity:** Low · **Loại:** `CODE_GAP`
- **Module:** Config
- **Source:** `backend/infrastructure/config.py:42`, `:95`
- **Root cause:** Cờ được thêm vào `Settings` nhưng chưa nối vào `CarbonService`/repository.
- **Repro / observation:** Grep `require_factor_set_in_db` chỉ thấy trong `config.py`.
- **Expected:** Cờ có hành vi được mô tả, hoặc không tồn tại.
- **Proposed fix:** Xoá cờ và dòng tài liệu (`docs/deployment/environment.md`) nếu hành
  vi hiện tại (luôn yêu cầu bộ hệ số trong DB khi lưu) là đúng; chỉ hiện thực nếu có
  nhu cầu chạy không cần DB.
- **Tests required:** Test `Settings` không còn thuộc tính (nếu xoá).
- **Risk:** Thấp.
- **Dependencies:** Không.
- **Supabase/runtime:** Không.

### B12 — Comment trong `schemas.py` lệch với form

- **Severity:** Low · **Loại:** `CODE_GAP`
- **Module:** Activities schema
- **Source:** `backend/schemas.py:175-181`; `web-dashboard/src/farmer/ActivityForms.tsx:289-303`
- **Root cause:** Form được bổ sung hai ô sau khi comment được viết.
- **Repro / observation:** Đọc hai file.
- **Expected:** Comment đúng với form (ô có, không bắt buộc; engine fail-closed khi thiếu).
- **Proposed fix:** Sửa comment.
- **Tests required:** Không (chỉ comment); chạy backend pytest.
- **Risk:** Không.
- **Dependencies:** Không.
- **Supabase/runtime:** Không.

---

## Không lên lịch sửa code

| ID | Loại | Việc cần làm |
|---|---|---|
| B9 | `PRODUCT_DECISION` | Chốt độ chính xác thời gian cho Farmer Web (ngày hay giờ + múi giờ) |
| B10 | `PRODUCT_DECISION` | Chốt có thêm form nhiên liệu / route tạo farm-thửa-vụ cho web |
| B11 | `PRODUCT_DECISION` | Chốt giữ hay xoá bảng/view baseline không dùng (cần migration nếu xoá) |
| S1–S9 | `SCIENTIFIC_BLOCKER` | GWP, hệ số nhiên liệu/lưới điện, hệ số quốc gia, import bộ hệ số — việc của nhóm phương pháp luận |

## Thứ tự đề xuất

1. **M7** — lỗ hổng đọc dữ liệu đang khai thác được ngay hôm nay; một migration nhỏ.
2. **B7 → B3** — cùng cổng quyền ghi của FastAPI; B7 là tiền đề (role phải còn hiệu lực).
3. **B4** — sau khi chốt role; tái dùng cơ chế kiểm quyền ghi của B3.
4. **M3** — toàn vẹn nội dung gói MRV; một dòng code + test.
5. **B5** — mã lỗi đúng cho Carbon.
6. **B1** — số liệu Resource Metrics.
7. **B2** — luồng giao diện doanh nghiệp.
8. **B6, B8, B12** — dọn dẹp.

**Cổng trước khi điền GWP:** M3, B4 và B5 hiện tiềm ẩn chỉ vì mọi bản tính dừng ở
`422 missing_emission_factor`. Chúng **phải** xong trước khi `gwp.ch4`/`gwp.n2o` có giá trị.

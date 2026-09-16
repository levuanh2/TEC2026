# Herdr Multi-Agent Protocol — AgriCarbon/TEC2026

Claude và Codex cùng chạy trong cùng workspace Herdr, cùng làm repo này. Không
có kênh tự động khác — mọi phối hợp qua Herdr pane messaging + file này.

Pane ID (`w1:pF`, `w1:pG`, ...) đổi mỗi lần agent/Herdr restart — KHÔNG hardcode.
Luôn discover động bằng `herdr agent list` lọc theo `cwd` = repo root, hoặc dùng
script trong `.herdr/` (xem mục "Giao tiếp qua Herdr" bên dưới).

Codex-internal state / Claude Code `ListAgents` KHÔNG phải nguồn phát hiện agent
kia — chúng chỉ thấy agent cùng loại. Muốn biết Claude/Codex bên cạnh có gì,
phải dùng Herdr (`herdr agent list`, `.herdr\status.ps1`).

## Roles

- **Claude**: supervisor / kiến trúc / review / quyết định cross-cutting (error
  contract, auth pattern, methodology correctness).
- **Codex**: implementer / test runner / mechanical changes.

Roles là mặc định, không phải giới hạn cứng — ai rảnh trước, việc rõ ràng thì
làm, miễn khai báo ownership trước khi sửa.

## Golden rule

Không sửa file agent khác đang sở hữu. Trước khi sửa:
1. `git status --short` xem file có đang dirty không.
2. Xem mục "File ownership" dưới đây / hỏi qua Herdr pane message.
3. Khai báo ownership tại đây trước khi bắt đầu.

## File ownership (cập nhật liên tục — sửa xong thì release)

| `backend/api.py`, `backend/main.py`, `backend/schemas.py`, `backend/service.py`, `backend/infrastructure/config.py`, `backend/infrastructure/write_repo.py` (new), `backend/tests/test_activity_writes.py` (new), `supabase/migrations/20260910080441_farmer_web_activity_idempotency.sql`, `docs/FARMER_WEB_WRITE_CONTRACT.md`, `docs/API_CATALOG.md`, `docs/openapi.json` | — (released) | FW-2 Part 1 FastAPI Farmer online activity writes for fertilizer/irrigation/harvest only: authorization, atomic persistence, idempotency and tests. No React write UI. | DONE: backend 165 passed; web 23 passed/build passed; mock Playwright Farmer + Management passed; no hosted mutation or migration deployment. |

| `backend/scripts/create_farmer_qa_identity.py` (new), `web-dashboard/tests/e2e/farmer-real-data.spec.ts`, `web-dashboard/playwright.real.config.ts`, `docs/FARMER_WEB_FW1_REPORT.md` | — (released) | FW-1 real Farmer QA identity, scoped RLS verification and authenticated browser QA. No schema/API/UI/write-feature changes. | DONE: `/v1/me` Farmer scope verified; negative farm read normalized 404; real Farmer Playwright 1/1 passed; Vitest 23 passed; build passed; mock Farmer + Management Playwright passed. |

| `web-dashboard/src/App.tsx`, `web-dashboard/src/routes.ts`, `web-dashboard/src/roles.ts`, `web-dashboard/src/nav.ts`, `web-dashboard/src/styles.css`, `web-dashboard/src/farmer/**` (new), `web-dashboard/tests/e2e/farmer-web.spec.ts` (new), `docs/FARMER_WEB_FW1_REPORT.md` (new) | — (released) | FW-1 read-only Farmer Web shell, routes, API-backed pages, responsive/a11y, tests and bounded report. No activity write API/UI; no backend change. | DONE: Vitest 23 passed, build passed, Farmer + Management mock Playwright 2 passed; real Farmer spec gated pending authorized Farmer identity |

| `backend/infrastructure/read_repo.py`, `backend/tests/test_read_repository.py`, `app/lib/services/carbon_api_service.dart`, `app/test/carbon_api_service_test.dart`, `docs/FARMER_WEB_WRITE_CONTRACT.md` | — (released) | Resource-metric P1 fixes; frozen Flutter Carbon error-envelope parser; Farmer Web online write-contract proposal. No Farmer UI/API runtime implementation. | DONE: backend 145 passed; web 21 passed/build passed; Flutter SDK unavailable for execution |

| Files | Owner | Task | Trạng thái |
|---|---|---|---|
| `backend/api.py`, `backend/main.py`, `backend/infrastructure/read_repo.py` | — (released) | Error contract unify + pagination + production-batches/emission-factor-sets routes + request-id middleware + OpenAPI tags/security scheme — DONE bởi Claude, 114/114 test pass | released, ai cần sửa tiếp thì khai báo lại ownership |
| `backend/infrastructure/api_errors.py`, `backend/infrastructure/pagination.py`, `backend/infrastructure/request_context.py` | Claude | Error envelope / pagination / request-id helpers | done |

Codex: available cho review/test nhỏ, không nhận task cross-cutting lớn (quota thấp).

## Round 2 (2026-09-08, tiếp)

| Files | Owner | Task |
|---|---|---|
| `backend/api.py`, `backend/main.py`, `backend/infrastructure/read_repo.py`, `backend/schemas.py` | — (released) | DONE: MRV sub-resource (steps/batches/evidence/exports), Pydantic response models, organizations/farm rollup endpoints, unified validation-error handler, hosted E2E 58/58 pass (SMOKE-TEST-REST). 134/134 test pass. Migration `20260908134822_grant_private_schema_service_role.sql` đã push hosted. |

Codex: không cần làm gì trên các file trên trong round này trừ khi Claude nhắn patch-intent.

## Round 3 (2026-09-08) — React web-dashboard audit

| Files | Owner | Task |
|---|---|---|
| `web-dashboard/src/api/client.ts`, `client.test.ts`, `farms.ts`, `.env.example` | Claude | Fix bug: error contract parse (`detail.error` giờ là object {code,message}, code cũ đọc như string), fix `usingMockData` default sai (mock bật mặc định, phải tắt mặc định) — DONE |
| `web-dashboard/src/App.tsx`, `api/me.ts`, `api/organizations.ts`, `api/mrv.ts`, `routes.ts`, `roles.ts` | — (released) | DONE bởi Codex, verify lại bởi Claude: /v1/me role thật, Organizations page (list/summary/farm-performance), MRV real data — 15/15 test + build pass (mock=true/false đều build được) |

## Round 4 — Figma (2026-09-09)

Figma quota tài khoản chết cứng ~4.6 ngày (Retry-After thật, không phải lỗi cấu hình) —
xem `docs/FIGMA_WEB_IMPLEMENTATION.md`. Đã lấy được design system thật (màu/font/layout
rule) trước khi hết quota, CHƯA lấy được 9 frame chi tiết từng màn hình.

Claude đã làm: token hoá `styles.css` (CSS custom properties đúng hex/size thật từ Figma),
avatar trong sidebar footer (`App.tsx::Shell`), release lại — 15/15 test + build pass.

| Files | Owner | Task |
|---|---|---|
| `web-dashboard/src/App.tsx` (chỉ hàm `Carbon`), `web-dashboard/src/styles.css` | — (released) | DONE bởi Codex: drill-down factors_used/provenance/parameter_status, aria-expanded/aria-controls, status badge dùng token màu — 15/15 test + build pass, verify lại bởi Claude |

Không đụng phần còn lại của `web-dashboard/` — 9 screen chưa có Figma detail giữ nguyên
structure hiện tại (đã token hoá đúng màu/font), không tự vẽ lại layout.

## Round 5 (2026-09-09) — Demo tenant + Dashboard org context

Đã pushed lên GitHub (origin/main, 6 commit tới bf7d52d). Đã seed xong tenant demo
`DEMO-AGRICARBON-2026` trên hosted (backend/scripts/seed_demo_data.py, idempotent,
verified qua 2 lần chạy + qua API thật) + cleanup_demo_data.py tương ứng.

| Files | Owner | Task |
|---|---|---|
| `web-dashboard/src/App.tsx` (hàm `Dashboard`) | — (released) | DONE bởi Codex: KPI thật qua /v1/organizations/{id}/summary + farm-performance, loading/error/no-org state, không hardcode — verify lại bởi Claude qua API thật (curl với demo tenant) + npm test/build |

Không đụng backend (đã freeze) — chỉ React.

Không sửa `web-dashboard/src/api/carbon.ts`, `crops.ts`, `metrics.ts`, `types.ts` trong round này (Claude có thể còn động vào).

## Round 4 (2026-09-09) — Figma-driven UI rebuild

Codex có Figma MCP, Claude không có. User bảo đẩy toàn bộ task này qua Codex.

| Files | Owner | Task |
|---|---|---|
| `web-dashboard/src/**` (toàn bộ), `docs/FIGMA_WEB_IMPLEMENTATION.md` (mới), `docs/WEB_BACKEND_BUGS.md` (mới, nếu phát hiện bug backend) | Codex | Figma MCP audit → rebuild UI theo Figma, giữ API contract/mock-gate/error-contract đã đúng từ round 3. Xem message Herdr đầy đủ. |

Claude: không đụng `web-dashboard/` cho tới khi Codex release. Chờ + verify (npm test/build) khi Codex báo DONE.

Claude: không đụng 3 file trên cho tới khi Codex release (dòng trên đổi thành
"released" hoặc file được commit).

## Round 6 (2026-09-09) — P0 UX/UI remediation (giao qua Herdr)

User giao task này cho Codex qua Herdr bridge (`.herdr/send-codex.ps1`). Task
đầy đủ: sidebar dead link, activity presentation mapper, MRV status mapper,
loading/empty/error states, reusable KpiGrid/FarmPerformanceTable, browser
smoke test nếu Playwright khả dụng. Xem message Herdr đầy đủ Codex nhận được
(brief lưu tạm — không lưu lại full text ở đây để tránh trùng lặp).

| Files | Owner | Task |
|---|---|---|
| `web-dashboard/src/**` (App.tsx sidebar/activities/MRV/dashboard, `src/utils/activityPresentation.ts` mới, `src/utils/mrvPresentation.ts` mới, `components/KpiGrid`, `components/FarmPerformanceTable` mới), `web-dashboard/tests/e2e/*` nếu Playwright cài được | Codex | P0-1..P0-4 UX remediation, xem Phase 1-16 trong brief Herdr. KHÔNG đụng backend/OpenAPI. |

Codex báo DONE (2026-09-09): P0-1..P0-4 fixed, npm test 18/18, build PASS,
playwright smoke 1/1 PASS (mock mode), backend pytest 136/136 PASS, không đổi
API/backend. Real authenticated network E2E chưa chạy (thiếu credential test).
Owner đổi thành released — Claude verify khi cần trước khi merge/commit.

## Round 7 (2026-09-09) — Product-level UX/UI redesign (user giao trực tiếp cho Claude)

User yêu cầu redesign toàn bộ Web Dashboard ở cấp sản phẩm (không phải tweak màu).
Files round 6 đã "released" → Claude nhận.

| Files | Owner | Task | Trạng thái |
|---|---|---|---|
| `web-dashboard/src/**` (rewrite `App.tsx` thành router mỏng; mới: `ui.tsx`, `format.ts`, `nav.ts`, `pages/*`, `features/*`; rewrite `components/FarmPerformanceTable.tsx`; xoá `components/KpiGrid.tsx`), `src/api/*` (chỉ THÊM wrapper: `getOrganizationMetrics`, `getFarmMetrics`, `getFarmCropSeasons`, `listMrvEvidence`, `listMrvBatches`, `getProductionBatches` — mapper cũ giữ nguyên, `hierarchy.test.ts` vẫn pass), `src/roles.ts`+`routes.ts` (IA mới), `tests/e2e/web-smoke.spec.ts` (viết lại theo IA mới), `.gitignore`, `docs/AI_TOOLING_PLAN.md` | Claude | IA nhóm theo domain (Tổng quan/Quản lý/Hiệu suất/MRV), Dashboard hierarchy, Crop Season hub 5 tab, Carbon premium + provenance, Activity timeline + drawer, MRV stepper, loading/empty/error nhất quán, breadcrumb, responsive 1440/1280/1024/768, a11y. **KHÔNG đụng backend/OpenAPI/schema/RLS** (freeze giữ nguyên). | released |

DONE (2026-09-09): build PASS, vitest 21/21 (thêm 3 test IA `nav.test.ts`), playwright
mock smoke 1/1 PASS, backend pytest 136/136 PASS (không đụng backend). REAL CO2e READY = NO
giữ nguyên. Authenticated real-API browser test = NOT RUN (không có credential đăng nhập
demo tenant; reset password demo user bị chặn). API FROZEN giữ nguyên.

## Round 8 (2026-09-10) — Auth error-contract bug fix (Codex đề xuất, Claude duyệt)

Bug (cả Claude round 7 QA lẫn Codex audit độc lập cùng tìm ra): request tới read
route KHÔNG kèm `Authorization` → `500` text-plain thay vì `401` unified-contract.
Root cause: `main.py::_read_repo` override (dòng ~107-108) gọi thẳng
`extract_bearer_token()` không bắt `MissingAuthError`; bản gốc `api.py::_read_repo`
(dòng 73-79) đã xử lý đúng. Đây là override **drift khỏi bản gốc**, KHÔNG phải đổi
contract — fix = khôi phục đúng hợp đồng lỗi thống nhất (OpenAPI freeze ngụ ý mọi
route trả `{detail:{error:{code,message}}}`, kể cả auth fail). **Claude duyệt fix.**

| Files | Owner | Task | Trạng thái |
|---|---|---|---|
| `backend/main.py` (chỉ hàm `_read_repo` override + import `HTTPException`/`MissingAuthError`), test regression (`backend/tests/`), `docs/POST_FREEZE_BACKEND_BUGS.md` | Codex | Wrap `extract_bearer_token` trong `try/except MissingAuthError` → `HTTPException(401, error_detail("unauthenticated", str(exc))) from exc` — **giống hệt `api.py:78`**, code = `"unauthenticated"`. KHÔNG đụng `api.py`, route logic, `_service`/`_access_checker` override, hay path `missing_authorization` của carbon. Test: `main.app` không header → 401 + envelope đúng. Full suite 136 + test mới phải xanh (chạy từ `backend/`). | **DONE** — Claude verify: `main.py` diff đúng như duyệt, `test_missing_authorization_uses_unified_401_error_contract` pass, pytest **137/137**, live check `GET /v1/farms` no-auth → `401 {"detail":{"error":{"code":"unauthenticated",...}}}`. |

Không gộp: latency rollup endpoint 17–41s (N+1) Claude tìm ở round 7 — perf, không
phải contract, để task riêng. Claude KHÔNG đụng backend (task = web-dashboard).

## Round 9 (2026-09-10) — Progressive loading + authenticated real-data E2E (Claude)

User: "kết nối supabase, vẫn tk demo trên CSDL thật" → user cấp phép (qua `!` bash)
reset mật khẩu demo user `demo-manager@agricarbon-demo.local`. Mật khẩu KHÔNG ghi ở đây — cung cấp qua biến môi trường (xem khối "QA credentials" ngay dưới).

> **QA credentials — DEMO/QA ONLY. DO NOT reuse these credentials for production.**
>
> Mật khẩu không bao giờ được ghi vào file tracked, script, log, screenshot, trace hay commit;
> luôn truyền qua biến môi trường của tiến trình. Script real-data phải báo lỗi rõ ràng khi
> thiếu biến, không có giá trị fallback.
>
> | Tài khoản | Email | Mật khẩu |
> |---|---|---|
> | Manager QA — `cooperative_manager`, org demo | `demo-manager@agricarbon-demo.local` (`MANAGER_EMAIL`) | supplied through `MANAGER_PASSWORD` |
> | Farmer QA — `farmer`, `DEMO-FARM-01` | `qa-farmer-fw1@agricarbon-demo.local` (`QA_EMAIL`) | supplied through `QA_PASSWORD` |
>
> Playwright real specs dùng tên riêng: Management `REAL_E2E_EMAIL` / `REAL_E2E_PASSWORD`,
> Farmer `FARMER_REAL_E2E_EMAIL` / `FARMER_REAL_E2E_PASSWORD`. Chạy real spec với trace và
> screenshot tắt — trace giữ lại giá trị của `fill()`.
>
> Lịch sử Git cũ vẫn chứa mật khẩu demo trước đây: chấp nhận được vì đây là tài khoản demo,
> không phải production, và không rewrite history. Nếu tài khoản này từng được dùng ngoài
> demo/QA thì PHẢI đổi mật khẩu trước.

| Files | Owner | Task | Trạng thái |
|---|---|---|---|
| `web-dashboard/src/pages/{dashboard,directory,performance,season}.tsx` | Claude | Tách 1 `Promise.all`/trang → nhiều `useAsync` độc lập/section: hero/PageHead + KPI render ngay, section rollup chậm (17–41s do backend local↔Supabase ap-northeast-2, N+1) có skeleton riêng thay vì blank cả trang. Frontend thuần, không đụng API. | done |
| `web-dashboard/src/features/carbon.tsx` | Claude | `no_calculation`/404 GET carbon → state "Chưa có bản tính" bình tĩnh (trước rơi vào ErrorState chung). | done |
| `web-dashboard/playwright.real.config.ts`, `web-dashboard/tests/e2e/web-real-data.spec.ts` (Codex tạo, released) | Claude | timeout 180s/expect 60s cho latency; chờ `/v1/me` resolve trước khi assert scope manager (fix race); cho phép carbon 404 by-design (demo cố ý không seed carbon_calculations). | done |

DONE (2026-09-10): build PASS · vitest **21/21** · mock playwright **1/1** · **real-data
playwright 1/1** (đăng nhập demo-manager thật → verify no mock, mọi `/v1/*` contract path,
0 direct Supabase PostgREST, 0 console error, full hierarchy + drawer + 5 tab + MRV) ·
backend pytest **137/137**. Blocker "no credential mechanism" của Codex → RESOLVED: cơ chế
= `REAL_E2E=true REAL_E2E_EMAIL/PASSWORD=<demo tenant manager> npx playwright test --config playwright.real.config.ts`.
API FROZEN giữ nguyên · REAL CO2e READY = NO giữ nguyên.

## Round 10 (2026-09-11) — FW-2 Part 2 Farmer Activity Write UI (Claude)

Codex xác nhận FW-2 Part 1 DONE (idle, backend 165 passed), bàn giao "READY FOR
FW-2 PART 2". Codex báo còn <5% quota tuần — không nhận task lớn round này.

| Files | Owner | Task | Trạng thái |
|---|---|---|---|
| `web-dashboard/src/farmer/**`, `web-dashboard/src/api/activities.ts` (mới), `web-dashboard/src/features/activities.tsx`, `web-dashboard/src/ui.tsx` (Sheet/ConfirmDialog), `web-dashboard/src/mocks/data.ts`, `web-dashboard/tests/e2e/farmer-web.spec.ts`, `web-dashboard/tests/e2e/farmer-real-write.spec.ts` (mới), `web-dashboard/playwright.real.config.ts` (testMatch), `docs/FARMER_WEB_FW2_REPORT.md` (mới), `backend/main.py` (CHỈ CORS `allow_methods` — genuine blocker, xem report §G), `supabase/migrations/20260910080441_farmer_web_activity_idempotency.sql` (đã apply hosted, xem report §G) | — (released) | FW-2 Part 2 Farmer Web write UI cho fertilizer/irrigation/harvest (create/edit/soft-delete), idempotency client, read-after-write refresh, real Farmer E2E. | **DONE**: Vitest 58 passed, build passed, Management + Farmer mock Playwright 2 passed, backend pytest 165 passed, **real Farmer write E2E 1 passed** (fertilizer/irrigation/harvest create+edit+delete qua API thật, hosted Supabase). Real E2E phát hiện + fix 2 blocker backend thật (migration `web_idempotency_key` chưa deploy hosted; CORS `allow_methods` thiếu PATCH/DELETE) + 1 bug frontend thật (Postgres `numeric` → chuỗi JSON trong write-response, số 0 khi edit/toast). Chi tiết đầy đủ: `docs/FARMER_WEB_FW2_REPORT.md`. |

## Round 11 (2026-09-11) — M05 Recommendation Engine (Claude)

Sau khi commit sạch milestone Farmer Web FW-2 (2 commit: `feat(backend): add
transactional farmer activity write API`, `feat(web): add farmer web read
experience and activity write UI`), user giao M05 tiếp theo — KHÔNG trộn vào
commit FW-2.

| Files | Owner | Task | Trạng thái |
|---|---|---|---|
| `backend/recommendation/**` (mới), `backend/infrastructure/recommendation_repo.py` (mới), `backend/service.py` (chỉ `RecommendationService`), `backend/schemas.py` (chỉ recommendation models), `backend/api.py`/`main.py` (chỉ 3 route recommendations + wiring), `supabase/migrations/20260911120000_season_recommendations.sql` (mới, đã apply hosted), `backend/tests/test_recommendation_*.py` (mới), `web-dashboard/src/api/recommendations.ts`+test (mới), `web-dashboard/src/farmer/Recommendations.tsx` (mới), `FarmerExperience.tsx` (chỉ thay placeholder khuyến nghị), `web-dashboard/tests/e2e/farmer-real-recommendations.spec.ts` (mới), `docs/modules/05-ai-recommendation.md`, `docs/M05_RECOMMENDATION_REPORT.md` (mới) | Claude | Deterministic rule engine, quantified impact tái dùng Carbon Engine thật (as_recorded vs awd, persist=False), 2 rule family thật (AWD optimization + data-completeness), không fake benchmark/impact. | **DONE**: backend 196 passed, Vitest 60 passed, build passed, mock Playwright (Farmer+Management) 2 passed, **real Farmer recommendations E2E 1 passed** (hosted, QA identity mới, 0 khuyến nghị carbon thật vì REAL CO2e vẫn blocked OI-05 — đúng kỳ vọng; 1 data_task thật "Bổ sung chi phí vật tư" accept qua UI thật). Real E2E phát hiện + fix 2 bug thật: (1) exception hạ tầng không phải CarbonEngineError làm crash toàn bộ generate endpoint; (2) psycopg trả UUID object thay vì string cho response. Chi tiết đầy đủ: `docs/M05_RECOMMENDATION_REPORT.md`. **CHƯA COMMIT** — chờ user yêu cầu rõ (theo git policy). |

## Round 12 (2026-09-11) — M03 CV Farmer Web Integration (Claude)

Baseline CV (`ml/`) đã verify trước đó (85.60% acc, threshold 0.939849,
temperature 1.65, uncertain rate 42.4% trên test) — task này KHÔNG train lại,
chỉ nối model đã có vào backend + Farmer Web. Schema (`plant_images`,
`cv_inferences`, `cv_model_versions`) đã tồn tại từ baseline migration nhưng
0% được dùng ở backend trước round này.

| Files | Owner | Task | Trạng thái |
|---|---|---|---|
| `backend/infrastructure/cv_repo.py` (mới), `backend/service.py` (chỉ `CvService` + bootstrap sys.path), `backend/schemas.py` (chỉ `CvInferenceResponse`/`DiseaseLabel`), `backend/api.py`/`main.py` (chỉ 3 route CV + wiring load-once model), `backend/tests/test_cv_service.py` + `test_cv_real_model_smoke.py` (mới), `ml/infer.py` (chỉ tách `predict_with_model()` khỏi `predict()`, không đổi logic), `web-dashboard/src/api/cv.ts`+test (mới), `web-dashboard/src/api/client.ts` (chỉ FormData Content-Type), `web-dashboard/src/farmer/CvCheck.tsx` (mới), `FarmerExperience.tsx` (chỉ thêm CV entry point ở Home + Season Overview), `web-dashboard/src/styles.css` (chỉ `.cv-*`), `web-dashboard/tests/e2e/farmer-web.spec.ts` (chỉ thêm assertion CV mock), `web-dashboard/tests/e2e/farmer-real-cv.spec.ts` (mới), `playwright.real.config.ts` (testMatch), `docs/API_CATALOG.md` (chỉ thêm route CV), `docs/CV_FARMER_INTEGRATION_REPORT.md` (mới) | Claude | Backend CV integration (upload validate/infer/persist/list, reuse `ml.infer` preprocessing — không path preprocessing thứ 2), Farmer Web upload + confident/uncertain UX đúng copy, real model E2E. | **DONE**: backend 223 passed (27 mới), `ml/tests` 9/9, Vitest 64 passed, build sạch, mock Playwright Farmer+Management 2 passed, **real Farmer CV E2E 1 passed** (upload thật, model thật, backend thật, không mock/intercept). Real E2E tự phát hiện 1 lỗi locator Playwright của chính spec (nút "Đóng" trùng accessible name với nút đóng Sheet) — đã sửa, không phải bug app. Chạy song song 2 real-E2E khác trên cùng QA identity gây rác 2 harvest 5kg (tự dọn qua `DELETE /v1/activities/{id}` đã authorize, không đụng DB trực tiếp) — không phải regression CV, chi tiết ở report §K.1. Chi tiết đầy đủ: `docs/CV_FARMER_INTEGRATION_REPORT.md`. **CHƯA COMMIT** — chờ user yêu cầu rõ (theo git policy). |

## Round 13 (2026-09-11) — Stabilize dirty tree: commit M05 + M03 (Claude)

User yêu cầu audit/stabilize riêng (không thêm feature mới) trước khi làm
FW-2 seeding/pesticide/straw. Round 11/12 để lại "CHƯA COMMIT" — task này
verify lại từ đầu (không tin lại nhãn DONE cũ mà không kiểm) rồi commit.

Kết quả audit: M05 Recommendation và M03 CV đều hoàn chỉnh nội bộ (rule
engine tái dùng Carbon Engine thật qua `persist=False`, không công thức
CH4/N2O riêng, có test AST chặn identifier methodology; CV baseline
85.60% acc trên public dataset, tự khai KHÔNG field-validated và OOD/non-
rice reject KHÔNG robust — đúng như đã ghi, không bị thổi phồng). Phát
hiện thêm 1 nhóm file không liên quan cả hai (Herdr tooling, Flutter
error-envelope fix, vài báo cáo audit cũ) cũng chưa commit từ trước.

`backend/api.py`/`main.py`/`schemas.py`/`service.py` + `docs/openapi.json`
+ `docs/API_CATALOG.md` + `FarmerExperience.tsx`/`styles.css` chứa CẢ HAI
feature trộn trong cùng hàm/file (không có cách tách hunk an toàn không
rủi ro cho JSON generated) — tách riêng thành 1 commit "wiring" cuối,
không gộp bừa vào 1 commit lớn.

| Files | Owner | Task | Trạng thái |
|---|---|---|---|
| Toàn bộ cây dirty tại thời điểm bắt đầu round (xem `git log` 4 commit `8ada8ca`/`44fff22`/`a13e342`/`82ac04d`) | — (released) | Audit + verify + 4 commit tách theo feature: (1) housekeeping không liên quan (Herdr/.agents/CLAUDE.md/Flutter fix/demo scripts/báo cáo cũ), (2) M05 recommendation, (3) M03 CV, (4) FastAPI wiring chung (không tách được, giải thích trong commit message). | **DONE**: backend pytest 223/223, `test_activity_writes.py` 20/20 (FW-2 regression), web vitest 64/64, web build sạch, mock Playwright Farmer+Management 2/2 passed. Không chạy real-E2E hosted trong round này (đã pass ở round 11/12, tránh tạo thêm rác demo). Không đổi Carbon methodology/scientific factors/Management Web/FW-1/FW-2 write contract. |

## Round 14 (2026-09-11) — FW-2 Part 3: seeding/pesticide/straw writes (Claude)

Sau round 13 (stabilize M05/M03), user giao tiếp FW-2 Part 3 — mở rộng write
API sang 3 activity type còn lại. Audit trước khi code: `activity_type` DB
enum thật có `seeding`/`pesticide`/`straw_management` (không phải "straw"),
`ActivityWriteService`/routes đã hoàn toàn generic (không type-specific
branch) nên chỉ cần mở `schemas.ActivityType` + 3 model + 3 entry trong
`write_repo.py::_DETAILS`. Read/Journal/cost-completeness (`read_repo.py`)
đã hỗ trợ sẵn cả 6 type từ round M05 — không đụng. Carbon mapping
(`straw_management` -> SFo/đốt đồng, cột `days_before_cultivation`/
`dry_matter_fraction`/`returned_to_field`) đã tồn tại từ migration
`20260908000000_carbon_methodology_alignment.sql` + test
`tests/test_carbon_engine.py` — không sửa, chỉ verify.

| Files | Owner | Task | Trạng thái |
|---|---|---|---|
| `backend/schemas.py` (3 model + enum), `backend/infrastructure/write_repo.py` (`_DETAILS` +3), `backend/tests/test_activity_writes.py` (mở rộng parametrize), `backend/tests/test_activity_writes_expansion.py` (mới), `docs/openapi.json`, `docs/API_CATALOG.md`, `docs/FARMER_WEB_WRITE_CONTRACT.md`, `docs/FARMER_WEB_FW2_REPORT.md` | — (released) | Backend write API cho seeding/pesticide/straw_management, cùng route/service/transaction/idempotency đã có, không route mới. | **DONE**: backend pytest 258 passed (223+35). |
| `web-dashboard/src/api/activities.ts`+test, `web-dashboard/src/farmer/ActivityForms.tsx`+test, `activityValidation.ts`+test, `web-dashboard/src/utils/activityPresentation.ts` (chỉ thêm label), `web-dashboard/tests/e2e/farmer-web.spec.ts` | — (released) | Farmer Web form Gieo sạ/Thuốc BVTV/Rơm rạ, bỏ 3 nút "Sắp có". Không SFo/CFOA/emission factor trong UI; chọn "Đốt" hiện thông báo trung tính, không CO2e giả. | **DONE**: Vitest 86 passed (64+22), build sạch, mock Playwright Farmer+Management 2 passed. |

Không chạy real hosted E2E round này (tránh tạo thêm rác demo, mock +
integration-level fake-cursor test đã đủ chứng minh SQL đúng cột/bảng thật —
xem `test_activity_writes_expansion.py::test_postgres_repository_inserts_into_the_correct_detail_table`).
Không đụng M05/M03/Carbon methodology/Management Web.

## Round 15 (2026-09-12) — Farmer Web V2: full redesign + loading architecture (Claude)

User feedback sau round 14 là UX acceptance feedback, không phải bug report:
Farmer Web "nhìn gần như không đổi", navbar/icon xấu, vẫn thấy chậm.
Không tính round trước là PASS.

Đo BEFORE bằng `git worktree` tại `5fbebc5` (không stash đè cây đang dirty),
junction `node_modules`, build + `vite preview` cả hai bản, chạy cùng một
script screenshot/perf → so sánh thật, không ước lượng.

Phát hiện ngoài dự kiến: sau khi bỏ hết waterfall, thứ chặn first paint lớn
nhất còn lại là stylesheet Google Fonts render-blocking (~200ms mỗi cold
load). Sửa bằng `media="print"`/`onload` + noscript, không bỏ font.

| Files | Owner | Task | Trạng thái |
|---|---|---|---|
| `backend/api.py`, `backend/schemas.py`, `backend/infrastructure/read_repo.py`, `backend/tests/test_read_repository.py`, `docs/API_CATALOG.md`, `docs/openapi.json` | — (released) | `/v1/farmer/scope` read-composition (gộp farms+plots+crop_seasons cho đúng RLS scope). Composition thuần: không business logic mới, không công thức Carbon/resource. | **DONE**: backend 263 passed (258+5). Verified trên hosted: own scope 200 chỉ trả DEMO-FARM-01, unauth 401. |
| `web-dashboard/src/farmer/**`, `src/App.tsx`, `src/api/{farms,me,auth}.ts`, `src/styles.css`, `index.html`, `tests/e2e/*` | — (released) | Farmer V2: shell/nav/icon system (Lucide), recompose toàn bộ page, SWR read-cache + dedupe + bounded prefetch, viewer hint, webfont non-blocking. Không đổi API contract/payload/auth/RLS. | **DONE**: vitest 117 (từ 90), tsc sạch, build sạch, mock Playwright 2/2, real Farmer E2E 1/1. |

Kết quả đo thật (local backend :8010 → hosted Supabase, production preview,
identity `qa-farmer-fw1`, scope DEMO-FARM-01):

| | BEFORE | AFTER |
|---|---|---|
| login → shell | 7866ms | 2884ms |
| login → complete | 22377ms | 12653ms |
| Home shell paint | 2389ms | 154ms |
| Home useful content | 2405ms | 170ms |
| Farm detail useful | 9365ms | 2009ms |
| API request Home/Farms/Farm | 13/9/11 | 7/2/2 |
| Duplicate API call mỗi màn | 4–6 | **0** |

StrictMode: dev cũng dupApi=0 — in-flight dedupe nuốt double-effect, nên
không đổ lỗi cho StrictMode nữa (đúng như §31 yêu cầu chứng minh).

Management: 5/5 screenshot **pixel-identical** (sha256) trước/sau — chỉ xoá
rule `.farmer-*` chết khỏi `styles.css`, không đụng style Management.
Các class `.farmer-farm-card`/`.farmer-plot-card`/`.cv-*`/`.recommendation-card`
GIỮ LẠI trong JSX vì là selector hook của real E2E spec, dù không còn style.

Security regression (hosted, token thật): own scope 200, cross-scope
DEMO-FARM-02/03 → 404 (không phải 403, không lộ tồn tại), unauth → 401.

Không tạo QA user mới (user chỉ định dùng identity đã verify sẵn). Không
chạy write E2E round này — không sinh thêm rác QA trên hosted.

## Round Farmer Performance 4 (2026-09-12) — full-content latency

Báo cáo đầy đủ: `docs/FARMER_PERFORMANCE_ROUND4.md`. Chỉ sửa orchestration /
read-path. KHÔNG đụng resource-metric math, Carbon math, Recommendation rule
logic, CV inference, activity write semantics, và không redesign gì.

| Files | Owner | Task | Trạng thái |
|---|---|---|---|
| `backend/infrastructure/{profiling,supabase_clients,pg_pool}.py` (new), `backend/infrastructure/{read_repo,recommendation_repo,cv_repo,write_repo,supabase_repo,auth,request_context,config}.py`, `backend/{main,service,requirements.txt}`, `backend/tests/test_read_performance.py` (new), `backend/tests/test_recommendation_api.py` | — (released) | Profiling (`Server-Timing`, mặc định TẮT), reuse Supabase client theo token, pool psycopg, gộp 1 transaction cho generate, giảm fan-out read. | **DONE**: backend 275 passed (263 → 275). |
| `web-dashboard/src/farmer/{data,scope,Recommendations,journal,farmer.css}`, `src/App.tsx`, `src/mocks/data.ts`, `tests/e2e/{farmer-web,farmer-real-recommendations,farmer-real-write}.spec.ts`, `docs/FARMER_PERFORMANCE_ROUND4.md` (new) | — (released) | Bỏ generate khỏi page load (staleness + nút thủ công), fix lost-update trong `useQuery`, fix drawer nhật ký giữ snapshot cũ, prefetch scope song song `/v1/me`, fixture 2 vụ. | **DONE**: vitest 126 (117 → 126), tsc sạch, build sạch, mock Playwright 2/2, real E2E 6/6. |

Kết quả đo thật (local backend :8010 → hosted Supabase, production preview,
identity `qa-farmer-fw1`, cùng máy — 5 lần chạy):

| | BEFORE | AFTER |
|---|---|---|
| Home full content | 11379ms | **960ms** |
| Season full content | 9051ms | **1237ms** |
| Home useful content | 2040ms | 427ms |
| login → shell | 3928ms | 2430ms |
| login → complete | 15109ms | 2963ms |
| Supabase round trip / màn | 64 | **34** |
| API request / màn | 7 | 6 |
| Duplicate API call / màn | 0 | 0 |

Nguyên nhân số 1 đo được: mỗi lần mở Home/Season đều chạy
`POST .../recommendations/generate` (31 round trip, 7.2–9.5s). Giờ page chỉ
GET bản đã lưu; generate chạy khi user bấm "Cập nhật khuyến nghị" hoặc nền sau
khi page đã dùng được, và chỉ khi dữ liệu thật sự cũ. Nguyên nhân số 2: mỗi
request tự dựng lại Supabase client (~800ms) và mỗi câu lệnh psycopg tự mở
connection mới (~700ms).

Hai bug thật phát hiện khi đo (không phải bug hiệu năng):
1. `useQuery` subscribe trong effect → mất notification nếu prefetch resolve
   trước khi component mount (Home hero kẹt skeleton ~1/5 lần login). Đã
   chuyển sang `useSyncExternalStore`.
2. Drawer chi tiết nhật ký giữ snapshot activity → sửa xong vẫn hiện giá trị
   cũ vĩnh viễn. Đã đổi sang resolve theo id từ list hiện tại.

Thêm một fix an toàn có sẵn từ trước (không do round này gây ra):
`SupabaseCropAccessChecker` là singleton gọi `.auth(token)` trên MỘT client
dùng chung ngay trước mỗi query → hai request song song có thể interleave
`auth(A) → auth(B) → execute(A)`. Đã chuyển sang client theo từng token.

Security (hosted, token thật): own scope 200, cross-scope DEMO-FARM-02/03 →
404, unauth → 401, và 40 request `/v1/farmer/scope` xen kẽ farmer/manager chạy
song song (12 luồng) — mỗi identity chỉ thấy đúng scope của mình.

Composition endpoint `/v1/farmer/home` + `/crop-seasons/{id}/overview`: đã
đánh giá bằng số đo, **KHÔNG thêm** — không chứng minh được lợi ích latency khi
Home đã ~1s. Lý do đầy đủ ở §6 của báo cáo.

Đã dọn sạch rác QA trên hosted (0 activity có note `QA-`).

## Uncommitted changes rule

Không `git reset --hard` / `git checkout -- <file>` / `git restore` / stash
đè lên thay đổi CHƯA COMMIT của agent khác nếu không được agent đó/user đồng ý
rõ ràng.

## Giao tiếp qua Herdr

Không hardcode pane ID trong file này — pane ID đổi mỗi session. Discover động:

- List toàn bộ agent: `herdr agent list` (JSON, lọc theo `cwd` == repo root để
  tìm agent của repo này, `agent` == `claude`/`codex` để lọc loại)
- Hoặc dùng helper có sẵn trong `.herdr/` (PowerShell, tự discover bằng
  cwd + agent kind, không nhận pane ID cứng):
  - `.\.herdr\status.ps1` — liệt kê mọi pane Claude/Codex đang mở cho repo này
  - `.\.herdr\read-claude.ps1` / `.\.herdr\read-codex.ps1 [-Lines N]` — đọc
    output gần nhất của agent kia
  - `.\.herdr\send-claude.ps1 "<text>" [-Wait]` / `.\.herdr\send-codex.ps1 "<text>" [-Wait]`
    — gửi prompt (thêm `-Wait` để đợi agent kia idle/done/blocked)
  - Nếu có >1 pane cùng loại trùng repo, script báo lỗi liệt kê ứng viên thay
    vì đoán bừa — lúc đó chỉ đích danh `herdr agent prompt <pane_id> "..."`.
- Lệnh thô tương đương: `herdr agent read <pane_id> --source recent-unwrapped --lines <N>`,
  `herdr agent prompt <pane_id> "<text>" --wait --timeout <ms>`

## Completion protocol

Xong việc thì báo (qua Herdr prompt hoặc note ở đây):
```
STATUS: DONE
CHANGED FILES: ...
TESTS: ...
RESULT: ...
FILES RELEASED: ...
```

## Git policy

Không tự commit/push trừ khi user yêu cầu rõ. Luôn `git status --short`
trước khi sửa gì trong vùng đang share.

## P0 security sprint (2026-09-15) — M7 → B7 → B3

| Files | Owner | Task | Trạng thái |
|---|---|---|---|
| `supabase/migrations/20260915100000_restrict_mrv_exports_storage_client_access.sql` (new), `backend/infrastructure/memberships.py` (new), `backend/infrastructure/read_repo.py` (`me`), `backend/infrastructure/write_repo.py`, `backend/service.py` (`ActivityWriteService`, `MrvExportService._manages`), `backend/tests/test_p0_security_policies.py`, `test_memberships.py`, `test_me_active_memberships.py`, `test_activity_write_permissions.py` (new), `backend/scripts/hosted_p0_security_smoke.py` (new), `web-dashboard/src/api/me.ts`, `web-dashboard/src/farmer/writeAccess.tsx` (new), `FarmerExperience.tsx`, `pages/Home.tsx`, `pages/Season.tsx`, `pages/Journal.tsx`, `pages/Performance.tsx` | — (released) | P0 fixes only: MRV export Storage client access, ended memberships in `/v1/me`, farm viewer read-only writes. No P1/P2. Branch `feature/p0-security-auth-fixes`. | DONE: migration `20260915100000` applied to hosted dev; backend 510 passed (incl. 19 + 13 hosted rolled-back RLS/Storage tests); hosted smoke 50/50; web Vitest 160 passed, tsc + build passed, mock Farmer + Management Playwright passed; 0 QA rows left. |

## P1 correctness sprint (2026-09-15) — B4 → M3 → B5 → B1 → B2

| Files | Owner | Task | Trạng thái |
|---|---|---|---|
| `backend/infrastructure/persist_access.py` (new), `backend/api.py`, `backend/main.py` (B4), `backend/service.py` (M3), `backend/carbon/engine.py`, `backend/carbon/models.py` (B5), `backend/infrastructure/read_repo.py` (B1), `supabase/migrations/20260915120000_mrv_export_calculation_crop_season_scope.sql` (new, M3 blocker), `backend/tests/test_integration_supabase.py` + new P1 tests, `backend/scripts/hosted_p1_correctness_smoke.py` (new), `web-dashboard/src/types.ts`, `src/api/me.ts`, `src/App.tsx`, `src/pages/season.tsx`, `src/features/carbon.tsx` (B2 + B4 affordance) | — (released) | P1 only; B4 policy = `private.user_can_write_crop` (decided by user). No GWP/factor sets, no P2. Branch `feature/p1-correctness-fixes`. | DONE — released: migration `20260915120000` applied to hosted dev; backend 567 passed (incl. hosted rolled-back P0/P1 RLS + trigger tests); hosted P1 smoke 30/30; web Vitest 171, tsc + build passed; mock Farmer + Management Playwright passed; 0 QA rows left. |

## Carbon factor readiness sprint (2026-09-15)

| Files | Owner | Task | Trạng thái |
|---|---|---|---|
| `backend/config/emission_factors.yaml`, `backend/carbon/factor_register.py` (new), `backend/scripts/import_factor_set.py` (new), `backend/scripts/hosted_carbon_factor_smoke.py` (new), `backend/scripts/hosted_p1_correctness_smoke.py`, `backend/main.py` (`/health`), `backend/mrv/manifest.py`, `backend/infrastructure/repository.py` + `supabase_repo.py` (idempotent save), `backend/tests/` (factor register, real factors, MRV provenance, idempotent save, GWP fixture updates), `docs/CARBON_METHOD*.md`, `README.md`, `backend/README.md` | Claude | AR5 GWP + IPCC 2019 Tier 1 factor set, fail-closed importer, hosted import, hosted E2E. No P2, no fuel factors. Branch `feature/carbon-factor-readiness`. | DONE — released: factor set `0.3.0-ipcc2019-tier1-ar5` imported + published on hosted dev (27 factors, `--verify` identical); backend 610 passed; hosted carbon smoke 43/43; hosted P1 smoke 30/30; web Vitest 171, tsc + build passed; mock Playwright passed; 0 QA rows left. Scientific readiness READY_FOR_DEMO, domain expert review PENDING. |

## Carbon input UX sprint (2026-09-16)

| Files | Owner | Task | Trạng thái |
|---|---|---|---|
| `backend/api.py`, `backend/schemas.py`, `backend/service.py`, `backend/infrastructure/write_repo.py` + `read_repo.py` (season methodology read/write), `backend/tests/test_crop_season_methodology.py` (new), `backend/scripts/hosted_carbon_input_ux_smoke.py` (new), `web-dashboard/src/features/seasonMethodology.tsx` (new) + test, `src/api/crops.ts` + test, `src/types.ts`, `src/pages/season.tsx`, `src/styles.css`, `src/farmer/ActivityForms.tsx` (straw burning notice), `tests/e2e/farmer-web.spec.ts`, `docs/CARBON_INPUT_GUIDE.md` (new) | Claude | Đóng CARBON UX BLOCKER: Farmer Web không có đường nào khai `ipcc_water_regime` / `pre_season_water_regime` / `cultivation_days` (chỉ Flutter ghi được, qua PostgREST). Thêm `PATCH /v1/crop-seasons/{id}/methodology` (RLS `private.user_can_write_crop`, không cần migration) + panel "Thông tin phương pháp tính". Không đổi công thức/hệ số Carbon, không đụng P2. Branch `feature/carbon-input-ux`. | CHƯA MERGE — chờ review. Backend 626 passed; hosted input-UX smoke 44/44 (0 QA rows left); web Vitest 185, tsc + build passed; mock Playwright 2/2. |

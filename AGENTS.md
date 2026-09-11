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
reset mật khẩu demo user `demo-manager@agricarbon-demo.local` = `DemoQA-2026!Aa1`.

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

# Herdr Multi-Agent Protocol — AgriCarbon/TEC2026

Claude (pane `w1:pF`, this repo) và Codex (pane `w1:pG`, this repo) cùng chạy
trong workspace Herdr `w1`, cùng làm backend REST API. Không có kênh tự động
khác — mọi phối hợp qua Herdr pane messaging + file này.

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

Không sửa `web-dashboard/src/api/carbon.ts`, `crops.ts`, `metrics.ts`, `types.ts` trong round này (Claude có thể còn động vào).

## Round 4 (2026-09-09) — Figma-driven UI rebuild

Codex có Figma MCP, Claude không có. User bảo đẩy toàn bộ task này qua Codex.

| Files | Owner | Task |
|---|---|---|
| `web-dashboard/src/**` (toàn bộ), `docs/FIGMA_WEB_IMPLEMENTATION.md` (mới), `docs/WEB_BACKEND_BUGS.md` (mới, nếu phát hiện bug backend) | Codex | Figma MCP audit → rebuild UI theo Figma, giữ API contract/mock-gate/error-contract đã đúng từ round 3. Xem message Herdr đầy đủ. |

Claude: không đụng `web-dashboard/` cho tới khi Codex release. Chờ + verify (npm test/build) khi Codex báo DONE.

Claude: không đụng 3 file trên cho tới khi Codex release (dòng trên đổi thành
"released" hoặc file được commit).

## Uncommitted changes rule

Không `git reset --hard` / `git checkout -- <file>` / `git restore` / stash
đè lên thay đổi CHƯA COMMIT của agent khác nếu không được agent đó/user đồng ý
rõ ràng.

## Giao tiếp qua Herdr

- List agent/pane: `herdr agent list`
- Đọc pane: `herdr agent read <pane_id> --lines <N> --format text`
- Gửi prompt: `herdr agent prompt <pane_id> "<text>"` (thêm `--wait` để đợi
  agent kia rảnh)
- Pane hiện tại: Claude = `w1:pF`, Codex = `w1:pG`

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

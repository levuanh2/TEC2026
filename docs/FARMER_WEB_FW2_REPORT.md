# Farmer Web FW-2 Part 2 — Activity Write UI

Builds the Farmer Web write experience on top of the frozen FW-2 Part 1 FastAPI
contract (`POST/PATCH/DELETE .../activities`, verified against runtime
`backend/schemas.py` + `backend/service.py`, not prior prose). The write
contract itself, Carbon, and MRV code are unchanged; two narrow backend fixes
were made only because real integration testing proved them to be genuine
blockers (never-deployed migration, stale CORS method list) — see §G.

## A. UI Architecture

```text
FORM SHELL:   Sheet (centered modal desktop / full-screen sheet mobile,
              web-dashboard/src/ui.tsx) + ActivitySheetForm
              (web-dashboard/src/farmer/ActivityForms.tsx) — one component,
              switched by activityType, sharing date/note/actions/error UI.
API CLIENT:   web-dashboard/src/api/activities.ts — createActivity /
              updateActivity / deleteActivity, camelCase input types mapped
              to the exact snake_case runtime fields.
MUTATION STATE: useActivityMutations() hook (ActivityForms.tsx) owns which
              create/edit/delete surface is open, the post-mutation toast,
              and a `version` counter used to close the read-only Drawer
              after a mutation lands. One instance per page/data scope
              (Home, Season journal tab, /farmer/journal).
IDEMPOTENCY:  web-dashboard/src/farmer/idempotency.ts — nextIdempotencyKey()
              pure state machine (open -> mint, retry -> reuse, success/close
              -> clear). Never rendered in the UI.
REFETCH:      onMutated() callback passed into useActivityMutations() calls
              the page's existing useAsync().reload() for activities/metrics;
              no client-side recomputation anywhere.
```

## B. Quick Entry

| Type | Home | Create | Edit | Delete |
|---|---|---|---|---|
| Bón phân (fertilizer) | Active | Yes | Yes | Yes |
| Tưới nước (irrigation) | Active | Yes | Yes | Yes |
| Thu hoạch (harvest) | Active | Yes | Yes | Yes |
| Giống (seeding) | `Sắp có`, disabled | No | No | No |
| Phun thuốc (pesticide) | `Sắp có`, disabled | No | No | No |
| Rơm rạ (straw) | `Sắp có`, disabled | No | No | No |

Entry points: Home Quick Entry (`QuickEntryPanel`), the Season Journal
`+ Ghi hoạt động` CTA (`AddActivityCta`, only lists the three supported
types), and edit/delete from the Journal activity drawer
(`ActivityRowActions`, gated by `isSupportedActivityType`). Season target:
Home computes the farmer's `status === 'active'` seasons (the exact backend
write-eligibility literal, confirmed against `backend/scripts/seed_demo_data.py`)
and opens a "Chọn vụ cần ghi" picker only when more than one exists; zero
active seasons disables the three buttons with an inline message instead of
opening a form. Season/Journal-page entry points already have one fixed
season and skip the picker.

## C. Fertilizer UX

Fields: Ngày bón, Loại phân (`fertilizer_name`), Lượng bón kg (`amount_kg`),
Hàm lượng đạm % (`nitrogen_percent`), expandable "Thông tin dinh dưỡng khác"
(lân/kali), Chi phí vật tư đ (`total_cost_vnd`, optional), Ghi chú.
`fertilizer_type` is intentionally not exposed as a second field — the single
"Loại phân" input maps to `fertilizer_name`, matching the brief's simple
one-field UX.

Validation (client-side, mirrors `backend/schemas.py` Field constraints
exactly): amount `> 0`, N/P/K `0–100`, cost `>= 0`, farmer-language messages
only (`Lượng phân phải lớn hơn 0.`, etc. — `activityValidation.ts`).

API evidence: `POST /v1/crop-seasons/{id}/activities` with
`activity_type: "fertilizer"`; `PATCH /v1/activities/{id}` sends the full
`data` object, which the backend merges (`{**existing, **request.data}` in
`service.py::update`) — sending the complete form state produces an exact
replace of the matching keys.

## D. Irrigation UX

Fields: Ngày thực hiện, Hình thức tưới (`method`: awd / continuous_flooding /
alternate / other), Lượng nước m³ (`water_volume_m3`, optional), "Sử dụng máy
bơm" checkbox revealing Năng lượng bơm kWh (`pump_energy_kwh`), expandable
"Thông tin khác" (Thời gian tưới phút = `duration_minutes`, Mực nước ruộng cm
= `water_level_cm`), Chi phí vật tư, Ghi chú. The brief's suggested "Số lần
rút nước" field does not exist in the runtime `IrrigationActivityData` schema
and was not added — only fields the backend actually accepts are shown.

Blank-vs-zero: `blankToNumber()` (`activityValidation.ts`) maps an empty
input to `null`, never `0`; an explicit `0` stays `0`. `api/activities.ts`
sends `water_volume_m3: null` verbatim when left blank — unit-tested in
`api/activities.test.ts`. Verified live in the real E2E: a blank-create shows
`—` in the read-back drawer, an edited `0` shows `0`.

API evidence: same POST/PATCH routes with `activity_type: "irrigation"`.

## E. Harvest UX

Fields: Ngày thu hoạch, Sản lượng thu hoạch kg (`yield_kg`, required `> 0`),
Diện tích thu hoạch ha (`harvested_area_ha`, optional, `> 0` when present —
matches `Field(gt=0)`), Độ ẩm % (`moisture_percent`, optional 0–100), Chi phí
đ, Ghi chú. No Carbon figure is shown or implied in this form.

Denominator behavior: `harvest_events.yield_kg` is the metrics denominator
(`backend/infrastructure/read_repo.py` sums it per crop season); an edit
PATCHes the same row the backend atomically keeps in sync
(`service.py::update` + `write_repo.py`), so a harvest edit changes every
per-kg ratio through a plain refetch, never client math. After create, a
calm confirmation replaces any Carbon claim:
`"Đã ghi nhận thu hoạch {kg} kg. Các chỉ số hiệu suất đã được cập nhật."`
— it never claims Carbon updated.

API evidence: `POST/PATCH .../activities` with `activity_type: "harvest"`;
real E2E compares two raw `GET .../metrics` JSON responses before/after an
edit and asserts the backend-reported `yield_kg` delta matches the edit —
no ratio recomputed in the browser.

## F. Error UX

```text
401 (unauthenticated):        "Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại."
404 (not_found, normalized):  "Không tìm thấy bản ghi hoặc bạn không còn quyền truy cập."
422 (validation_error):       "Dữ liệu chưa hợp lệ. Vui lòng kiểm tra lại các trường đã nhập."
422 (invalid_crop_season_state): "Vụ này hiện không thể ghi hoạt động (đã đóng hoặc chưa sẵn sàng)."
409 (duplicate_event):        "Yêu cầu này đã được ghi nhận với dữ liệu khác. Vui lòng tải lại và thử lại."
5xx / offline:                "Không thể lưu hoạt động. Dữ liệu chưa được xác nhận là đã lưu." + Thử lại
```

All mapping lives in `farmer/activityErrors.ts` (`mapActivityError`), keyed
on the frozen envelope's `code`, never on raw Pydantic/API JSON text. Retry
reuses the same in-flight idempotency key (`nextIdempotencyKey(key, 'retry')`
returns the existing key unchanged). Unit-tested in `activityErrors.test.ts`.

## G. Real Write QA

```text
REAL FARMER AUTH:                 PASS — fresh DEMO-FARM-01 QA identity
                                   created via backend/scripts/create_farmer_qa_identity.py
                                   (user-authorized), real Supabase Auth login
FERTILIZER CREATE/EDIT/DELETE:    PASS
IRRIGATION CREATE/EDIT/DELETE:    PASS (blank-vs-zero verified: blank reads
                                   back as "—", explicit 0 reads back as 0)
HARVEST CREATE/EDIT/DELETE:       PASS (metrics delta verified against two
                                   raw backend /metrics responses, +5 on
                                   create, +8 net on edit, back to baseline
                                   on delete)
CLEANUP:                          confirmed 0 leftover QA rows in hosted DB
                                   after the passing run
```

`web-dashboard/tests/e2e/farmer-real-write.spec.ts` runs the full
create → verify → edit → verify → delete → verify-gone flow for all three
types against the real hosted API (§35-38), a UI-level double-submit guard
check (§8/§36), console/network/direct-Supabase-business-read assertions
(§40), and a backend-response-only metrics delta check for the harvest edit
(§21/§37). It self-skips unless
`REAL_E2E=true FARMER_REAL_E2E=true FARMER_REAL_WRITE_E2E=true` plus
`FARMER_REAL_E2E_EMAIL`/`FARMER_REAL_E2E_PASSWORD` are set. §39 cross-scope
smoke was intentionally left out (optional per brief, needs a second farmer
identity + would touch `DEMO-FARM-02`); the backend cross-scope tests
already cover it.

### Real integration blockers found and fixed

Real browser E2E reached parts of the write path unit tests structurally
cannot (real psycopg/Postgres, real browser CORS preflight, real Decimal
JSON serialization). Three genuine issues surfaced, all fixed and verified:

1. **Hosted migration never deployed.** FW-2 Part 1 wrote
   `supabase/migrations/20260910080441_farmer_web_activity_idempotency.sql`
   (adds `activities.web_idempotency_key` + its unique index) but never
   pushed it to hosted Supabase — backend pytest uses a fake write
   repository, so it never touched real Postgres. First real `POST
   .../activities` failed `500` with `psycopg.errors.UndefinedColumn`. Fixed
   by applying the migration directly via `SUPABASE_DB_URL` (user-approved,
   scope-limited to this exact migration, re-verified column/index/history
   before and after, no reset/drop/truncate).
2. **CORS `allow_methods` predated PATCH/DELETE.** `backend/main.py`'s
   `CORSMiddleware` still listed `["GET", "POST"]` from before FW-2 Part 1
   added the PATCH/DELETE activity routes, so every real browser PATCH/DELETE
   was blocked client-side by a failed preflight — no request ever reached
   the backend, so backend pytest (which doesn't exercise browser CORS)
   never caught it. Fixed: `allow_methods=["GET", "POST", "PATCH", "DELETE"]`.
3. **Numeric write-response fields serialize as JSON strings.** Every
   fertilizer/irrigation/harvest detail column is Postgres `numeric`. The
   read endpoint (PostgREST) serializes it as a JSON number, but the write
   response (psycopg → Python `Decimal` → FastAPI's `Any`-typed
   `ActivityWriteResponse.data` dict) serializes the same field as a JSON
   *string* to avoid float precision loss. The harvest-create toast used
   `typeof y === 'number'`, which silently rejected the string form and
   rendered `"Đã ghi nhận thu hoạch  kg."` (empty). Fixed in
   `web-dashboard/src/farmer/ActivityForms.tsx::numOrUndef` to accept either
   representation; covered by `ActivityForms.test.ts`. Edit-prefill draws
   from the read endpoint (already numbers), so it was not affected — only
   the write-response-derived toast was.

None of these are Farmer Web UI bugs the brief's change boundary would have
called out as "unsupported" — they're exactly the "real integration reveals
a genuine blocker" case the brief allows fixing narrowly (§0). No write
contract shape changed; no Carbon/MRV code touched.

## H. Metrics Refresh

Every mutation success calls the page's existing `useAsync().reload()` for
`activities` and, where relevant, `metrics` (Season hub always reloads both,
since a fertilizer/irrigation/harvest write can change any per-kg ratio; Home
and the standalone `/farmer/journal` route reload journal + metrics as their
`current` season needs). No `SeasonMetrics` field is ever computed from a
previous value plus the new form input — every number rendered comes from
the next `GET .../metrics` response.

## I. Idempotency

```text
DOUBLE SUBMIT:  Save button + "Đang lưu…" label disable while a request is
                in flight (activity-form__actions); verified in the real
                E2E by asserting the pending label appears before the
                dialog closes.
RETRY:          nextIdempotencyKey(current, 'retry') returns the existing
                key unchanged — a retried submission reuses the same UUID,
                only a fresh sheet mount (or a completed success) mints a
                new one. Unit-tested (idempotency.test.ts).
DUPLICATE ROWS: Backend remains the source of truth
                (unique(recorded_by, web_idempotency_key), already covered
                by backend pytest — test_same_key_same_payload_returns_
                original_activity_without_duplicate,
                test_same_key_different_payload_conflicts). UI never
                generates a second key for what the farmer intends as the
                same submission.
```

## J. Tests

```text
Vitest:              58 passed (23 pre-existing + 35 new: idempotency,
                      activityValidation, activityErrors, api/activities
                      payload-shape tests, ActivityForms numOrUndef)
Build:                tsc -b && vite build — PASS
Farmer mock (Playwright, VITE_USE_MOCK_DATA=true): 1 passed — navigation,
                      Quick Entry active/disabled state, all three create
                      sheets open/close, journal edit/delete affordances,
                      delete confirmation dialog, 1440/1024/768/390
                      responsive, screenshots captured
Farmer real write (Playwright): 1 passed — fertilizer/irrigation/harvest
                      create/edit/delete against the real hosted API with a
                      freshly created DEMO-FARM-01 QA identity; 0 leftover
                      QA rows after the run (see §G)
Management regression (Playwright, web-smoke.spec.ts): 1 passed — rerun
                      after these UI/shared changes, not assumed from a
                      prior report
Backend:              165 passed — rerun twice: once before any backend
                      change, once after the CORS allow_methods fix (§G)
```

## K. Responsive

```text
1440: Sheet is a centered ~560px modal; forms readable, no stretch.
768:  Sheet becomes a full-bleed bottom sheet (0 radius, 100dvh);
      farmer-quick buttons already wrap to full width at this breakpoint.
390:  Verified no horizontal scrollWidth overflow (existing carbon-flow
      check extended); numeric fields use inputMode="decimal"; forms scroll
      within the sheet body when content exceeds viewport height; Save/Hủy
      remain reachable by scroll (no sticky footer — content height did not
      warrant one for these three forms).
```

## L. Screenshots

`web-dashboard/test-results/` (gitignored):
`farmer-home-1440.png`, `farmer-fertilizer-form-1440.png`,
`farmer-irrigation-form-1440.png`, `farmer-harvest-form-1440.png`,
`farmer-journal-1440.png`, `farmer-journal-detail-1440.png`,
`farmer-delete-confirm-1440.png`, `farmer-farms-1440.png`,
`farmer-plot-1440.png`, `farmer-season-1440.png`,
`farmer-performance-1440.png`, `farmer-carbon-1440.png`,
`farmer-carbon-390.png`, `farmer-home-390.png`,
`farmer-fertilizer-form-390.png`, `farmer-harvest-form-390.png`.

## M. Remaining Gaps

```text
Seeding                → not implemented
Pesticide               → not implemented
Straw                   → not implemented
Recommendation          → M05 backend missing
CV integration          → later
REAL CO2e                → scientific blocker
Flutter runtime test    → pending if SDK still unavailable
```

## N. Final Status

```text
FW-2 PART 2 FARMER WRITE UI: DONE
```

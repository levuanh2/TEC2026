# Flutter-Android integration audit

Date: 2026-09-13
Audited: `origin/Flutter-Android` @ `13ce50f` ("Android hoan thanh")
Against: `main` @ `d136fff`
Integration branch: `integration/flutter-android`

## Branch topology

```
common base   bf7d52d  2026-09-09  "feat(web): finalize MVP dashboard integration"
Flutter-Android   +1 commit
main             +56 commits
```

The branch is a single squashed commit on a base that is 56 commits behind. It
therefore predates the transactional activity write API (`b817c3d`), the
six-type activity expansion (`ac070f3`), M05 recommendation (`44fff22`), M03 CV
(`a13e342`), `/v1/farmer/scope` (`5c3447e`), all of Round 4's security and
performance work, the malformed-bearer 401 fix (`e3f06de`), and the Hallmark UI
phase. Everything below was therefore read against **current** schema and
backend, never against the branch's own base or its own docs.

`app/` already existed on main with 27 files. The branch takes it to 190:
96 new Dart files, 25 modified, plus tests and the Android project.

## What was NOT imported

- `web-dashboard/package-lock.json` — lockfile drift from the teammate's local
  install, predating every dependency decision on main since. Excluded.

Nothing outside `app/` crosses over. No backend or web file is touched.

## Verified correct against current contracts

These were checked against current code and schema, not against the branch's
documentation, and they hold:

- **No service-role key.** `config.dart` and `auth_service.dart` mention
  `SUPABASE_SERVICE_ROLE_KEY` only to assert its absence. Config is entirely
  `String.fromEnvironment` (`--dart-define`); publishable key only; RLS remains
  the authorization boundary, same as the web client.
- **No hardcoded credentials, farm IDs, season IDs or user IDs.** The single
  UUID literal in `device_service.dart` is the RFC 4122 DNS namespace, used to
  derive a stable `device_id` — correct use.
- **No `/v1/sync` dependency.** The only backend routes the app calls are
  `/v1/carbon/calculate`, `/v1/carbon/scenarios` and `/v1/me`. Writes go direct
  to Supabase under RLS, which is the intended mobile architecture.
- **Idempotency is `(device_id, client_event_id)`** and is implemented as
  find-then-insert-or-update rather than `ON CONFLICT`. The stated reason —
  that `activities`' unique index is *partial* (`where device_id is not null and
  client_event_id is not null`) so Postgres cannot infer it for `ON CONFLICT`
  (42P10) — was verified against
  `supabase/migrations/20260907000000_baseline.sql:486`. The claim is accurate
  and the workaround is the right one.
- **All six activity types** are present (plus `fuel`, which is a real table in
  the read path), and the straw methodology fields
  (`days_before_cultivation`, `dry_matter_fraction`, `returned_to_field`) are
  already collected — the branch is *not* stale here; it matches what Farmer Web
  only gained in `ea50656`.
- **Straw method enum** is exactly `incorporated / removed / burned / composted /
  other`.
- **`yield_kg > 0` is enforced** — the spec carries `positive: true` and the
  shared validator rejects `value <= 0`.
- **Units are correct.** `water_volume_m3` is m³ with an explicit hint refusing
  mm conversion "until an approved formula exists"; yield in kg; area in ha;
  `amount_liter` belongs to the fuel spec, not to a field the DB stores in m³.
  No tonne/kg confusion anywhere.
- **`production_batch_id NOT NULL`** — the app creates one default batch per
  season to satisfy it, and documents that Carbon is still scoped to Crop
  Season. Verified still true in the current baseline schema and in the backend
  write repository. Not stale, and not a Carbon-scope violation.
- **Business-logic boundary is clean.** Resource metrics are read from the
  server response (`_numOrNull(json['water_per_kg'])`) and never recomputed;
  there is no GWP, SFo, SFw, EF or emission factor anywhere in Dart; carbon
  screens render backend results and an honest unavailable state.
  `UnavailableRecommendationRepository` explicitly never returns a fixture.
- **No mock/demo fallback in production code. No TODO/FIXME.**
- **Soft delete** is implemented (`softDeleteActivity` with `deleted_at`),
  matching the web contract; detail rows use `upsert onConflict: 'activity_id'`,
  so no orphan or duplicated subtype rows.

## Findings

### P1-1 · `occurred_at` is sent without a timezone

`sync_service.dart:139` sends `activity.occurredAt.toIso8601String()`, and
`activity_form.dart:157` builds that value as
`DateTime(date.year, date.month, date.day, t.hour, t.minute)` — a **local**
`DateTime`. Dart emits a naive ISO string for it (no `Z`, no offset), and
Postgres `timestamptz` then reads it in the session zone (UTC). A 23:00 ICT
operation is stored as 23:00 UTC and reads back as 06:00 ICT the next day: the
farmer's operation date moves.

Farmer Web sends `${date}T00:00:00Z` — an explicit instant. Mobile should match.

Fix: `occurredAt.toUtc().toIso8601String()` at the sync boundary, with the
picker's local wall-clock intent decided deliberately (either normalise to local
midnight-as-UTC like the web, or carry the real instant — but pick one and test
it around the 17:00–07:00 ICT window where the day flips).

### P1-2 · A permanently-failed item is retried forever

`sync_errors.dart` classifies failures correctly and comments that an RLS
denial is pointless to retry. But the sync loop selects
`where sync_state in ('pending','failed')`, so a `failed` row is re-picked on
every run regardless of kind, and `retry_count` is incremented (three sites in
`local_database.dart`) without ever being compared to a cap.

The classification exists and is good; it simply is not used as a gate.

Fix: exclude permanent kinds (`rlsDenied`, `auth`, `validation`) from re-queue
and surface them as "needs attention" instead, and cap attempts for transient
kinds with a bounded backoff.

### P2-1 · A breakdown line defaults a null to 0

`carbon_result.dart:22` — `co2eKg: (json['co2e_kg'] as num?)?.toDouble() ?? 0`.
The headline figures (`totalCo2eKg`, `yieldKg`, `co2ePerKg`) are correctly
`double?` with no defaulting, so this is not a fake-zero on anything a farmer
reads as a total; it only affects a line item inside a breakdown the backend
has already computed. Still worth making `double?` for consistency with the
rest of the model.

### GAP · No conflict-resolution contract

There is no formal last-writer / version policy for editable records. Activities
are log-style and protected by idempotency, so this is not currently harmful.
Reporting it as a gap rather than inventing a policy, per the brief.

### GAP · Recommendation not wired

M05 landed on main after this branch's base. The app ships
`UnavailableRecommendationRepository`, which is the honest behaviour, but mobile
is not yet connected to the endpoint that now exists.

## Runtime verification (2026-09-13, emulator + hosted Supabase)

The toolchain was installed after the audit above was written, so the section
that previously said "not verifiable" no longer applies. Recorded here instead
is what was actually executed.

Environment: Flutter 3.47.4 / Dart 3.13.3, OpenJDK 17, Android SDK 36,
AVD `agri_qa` (`sdk_gphone64_x86_64`, API 35) with the device clock set to
`Asia/Ho_Chi_Minh`. Hosted project `awazhdqzkktekbwaqiic`, publishable key only
— no service-role key ever reached the device.

| Gate | Result |
| --- | --- |
| `dart format --set-exit-if-changed lib test integration_test` | clean |
| `flutter analyze` | No issues found |
| `flutter test` | 365 passed |
| `flutter build apk --debug` | PASS, 158.0 MB |
| `flutter build apk --release` | PASS, 56.1 MB (debug-signed — release signing BLOCKED) |

`integration_test/hosted_runtime_smoke_test.dart` runs the real stack on the
emulator against hosted Supabase. Network is cut and restored from the host with
`adb shell svc wifi|data`; the test only observes the transition with a real
request, so "offline" means offline. One pass covers: login, scope, offline
create, reopening the persisted sqlite file, reconnect, sync, forced re-sync,
timezone round trip through `timestamptz`, permanent-failure handling and QA
cleanup accounting.

Measured, from the run that passed:

- own scope only — 1 farm (`DEMO-FARM-01`), 2 plots, 0 plots outside it;
  `DEMO-FARM-02` returns 0 rows;
- offline create → `sync_state = failed`, `sync_error = network`, row kept;
- reopening the database returns the same `client_event_id`, still queued;
- reconnect → `sync1` wrote exactly **1** remote row; `sync2` wrote 0; forcing
  the same record back to `pending` and syncing again still leaves exactly
  **1** row, same `id`, same `device_id`, same `client_event_id`;
- `occurred_at` 23:00 ICT stored as `2026-09-13T16:00:00+00:00`, read back as
  23:00 on 13/09 — P1-1 confirmed fixed against a real Postgres `timestamptz`;
- an activity pointing at an out-of-scope season fails `rlsDenied` once and is
  **not** re-queued — P1-2 confirmed fixed against the real server.

### P1-3 · Mobile cannot soft-delete a synced activity (NEW, found at runtime)

`SupabaseSyncGateway.softDeleteActivity` sets `deleted_at` through PostgREST.
The server rejects it with `42501 new row violates row-level security policy for
table "activities"`, every time, for the row the same user has just inserted.

Isolated with psql against the hosted database, same user, same row:

```
private.user_can_write_batch(batch) -> true
update activities set deleted_at = null  -> OK, 1 row
update activities set deleted_at = now() -> FAIL 42501
```

So `activities_update`'s own `WITH CHECK` is satisfied; what rejects the row is
`activities_select`'s `deleted_at is null`, which Postgres applies as a check on
the updated row. Any row a client soft-deletes becomes invisible to itself and
the statement aborts. Farmer Web is unaffected because its delete goes through
`DELETE /v1/activities/{id}` on FastAPI, which uses a privileged connection.

Effect on the farmer: deleting a synced entry on the phone never succeeds. It is
not data loss — the tombstone is preserved locally and, because of P1-2, it is
classified permanent and stops being retried instead of hammering the server.

Not fixed here. Both candidate fixes cross the line the brief drew: changing the
RLS policy is a database contract change, and routing mobile deletes through the
FastAPI endpoint is a new client-server dependency. Recommended direction, for a
decision rather than a silent change:

1. route mobile delete through `DELETE /v1/activities/{id}` (matches Farmer Web,
   no schema change) — but see P1-4, which blocks it today; or
2. add a policy that permits an update whose only effect is setting `deleted_at`.

### P1-4 · Mobile activities carry `recorded_by = null` (NEW, found at runtime)

`sync_service.dart` never sends `recorded_by`, so every mobile row lands with it
null. `activities_insert` permits that (`recorded_by is null or = auth.uid()`),
so nothing fails — but two things follow:

- `ActivityWriteRepository.soft_delete` scopes its update with
  `and recorded_by = %s`, so the backend delete endpoint cannot remove a mobile
  row either; option 1 of P1-3 does not work until this is fixed;
- an audit trail that identifies who recorded an entry is empty for mobile.

The fix is client-side and allowed by the existing policy — send
`recorded_by: auth.currentUser.id` — but it changes what lands in a column the
backend and Management read, so it is reported, not applied.

### QA data created and removed

All rows created by the smoke were tagged `QA-RUNTIME-SMOKE` in `note`.

| | created | cleaned | remaining |
| --- | --- | --- | --- |
| `activities` (+ `irrigation_events`) | 4 | 4 | 0 |
| `devices` | 7 | 7 | 0 |
| `production_batches` | 0 | 0 | 0 |

The default `production_batch` on season `2e63e128` was created 2026-09-08, before
this work, and was left alone. Cleanup had to run from the host with a privileged
connection: `authenticated` has no `delete` grant on `activities` or `devices`,
and soft delete is blocked by P1-3.

## What was not verifiable


**Release signing** — `android/app/build.gradle.kts:36` still points the release
build at `signingConfigs.getByName("debug")` and there is no `key.properties`, so
`app-release.apk` is debug-signed. A real release signature is **BLOCKED** until
a keystore exists; it is not a pass.

**A physical device** — everything above ran on an emulator. Camera capture
(`camera_cv_screen`), runtime permission prompts and real cellular hand-off were
not exercised.

**The app's own UI flow** — the smoke drives the service and database layers that
the screens call, not the widgets. Login, scope and logout were verified at the
service layer; tapping through the six activity forms on the device was not.

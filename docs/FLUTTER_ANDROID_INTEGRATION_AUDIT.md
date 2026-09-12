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

## Not verifiable in this environment

No Flutter SDK, no Dart SDK, no JDK and no Android SDK are installed on this
machine. `flutter pub get`, `dart format`, `flutter analyze`, `flutter test`,
`flutter build apk` and any device or emulator run are therefore **BLOCKED**,
not passed. No Dart source was edited in this integration, because a change that
cannot be compiled or tested should not be committed.

The two P1 fixes above are specified precisely enough to be applied and verified
by whoever next has a Flutter toolchain.

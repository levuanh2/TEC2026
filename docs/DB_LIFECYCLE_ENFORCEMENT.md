# P1: season lifecycle + active membership, enforced in the database (2026-09-26)

Branch `feat/agricarbon-db-lifecycle-enforcement`. Migrations:
- `20260926090000_db_lifecycle_enforcement.sql`
- `20260926100000_activity_update_denies_loudly.sql`
- `20260926110000_batch_lifecycle_and_detail_delete.sql` (a follow-up from the independent review)

**All three are applied on hosted** and recorded in `supabase_migrations.schema_migrations`.
The user approved the lifecycle migration; the two follow-ups were applied under the same
approval.

Scope limits held in this work:
- Flutter writes still go straight to PostgREST; they were not moved behind FastAPI.
- The Carbon engine and Resource Metrics are unchanged.
- No screen was redesigned. Two small additions were made: a "Kết thúc vụ" action, and a
  "Vụ đã kết thúc" message in the Flutter activity form.

## 1. Write paths reachable through PostgREST (before → after)

| Operation | Table | Policy / entry | Helper | Season state | Active membership | Ownership |
|---|---|---|---|---|---|---|
| INSERT | activities | `activities_insert` WITH CHECK | `user_can_write_batch` → **`user_can_write_activity_batch`** | none → **active season, open batch** (+ trigger 55000) | none → **required** | `recorded_by` null or `auth.uid()` |
| UPDATE | activities | `activities_update` | USING write → **USING read, WITH CHECK `user_can_write_activity_batch`** | none → **active** (trigger 55000, also for the OLD row) | none → **required** | recorder rule; `recorded_by`, type, device key immutable; **`production_batch_id` immutable** |
| soft delete | activities | RPC `soft_delete_activity` | `user_can_delete_activity` | none → **active** (55000) | none → **required** | recorder only |
| INSERT | 7 detail tables | `*_insert` | → `user_can_write_activity_batch` of the parent | none → **active** (+ trigger) | **required** | via parent |
| UPDATE | 7 detail tables | `*_update` | USING read, WITH CHECK `user_can_write_activity_batch` | none → **active** (trigger) | **required** | **`activity_id` immutable** |
| DELETE | 7 detail tables | `*_delete` → **privilege revoked** | — | **not a client operation** (42501) | — | parents are removed via the RPC |
| INSERT | crop_seasons | `crop_seasons_insert` | `user_can_write_farm` | client may create only `planned`/`active` (trigger) | none → **required** | — |
| UPDATE | crop_seasons | `crop_seasons_update` | `user_can_write_crop` | **legal transitions only** (trigger) | none → **required** | — |
| INSERT/UPDATE | production_batches | unchanged policies | `user_can_write_crop` / `_batch` | none → **season live and planned/active** (trigger 55000) | **required** (inherited) | **`crop_season_id` immutable** |

- **Membership:** `user_can_write_farm` and `user_can_manage_farm_members` now require an
  ACTIVE membership in the farm's cooperative, and a farm that is not deleted.
  Every helper built on them inherits this.
- **Reads are unchanged.** A former member can still read.
- **Where the triggers apply:** only in client sessions (`row_security_active`). Backend,
  seed, import and cleanup paths behave as before.

## 2. Reproduction, before the fix

Evidence: `docs/evidence/lifecycle-rls-probe-before.txt`, from
`backend/scripts/hosted_lifecycle_rls_probe.py`. It uses the same calls as Flutter, with
real JWTs, on a disposable tenant.

Result: 14 of 32 operations matched the contract.
- In `harvested`, `closed` and `planned` seasons the owner could insert, update, change
  detail rows and soft-delete.
- A former member (farm role still `owner`) could insert activities and **create seasons**.
- Unauthorized updates matched 0 rows **without an error**.

The probe's "upsert detail 23505" lines were a flaw in the probe itself: it was missing
the `resolution=merge-duplicates` header that the supabase clients send.

## 3. Lifecycle rules

| Status | Activity create / update / delete | Season setup and methodology | Carbon | Reads |
|---|---|---|---|---|
| planned | **no** (same as FastAPI since FW-2) | yes | yes (writer) | yes |
| active | yes (writer with an active membership) | yes | yes | yes |
| harvested / closed / cancelled | **no** (55000 `crop_season_not_open`) | yes (methodology edit keeps working, same as the Web rule) | yes | yes |
| soft-deleted season | no mutation | no | — | hidden |

**Transitions** are defined in one place, `private.crop_season_transition_allowed`, which
the client trigger and FastAPI both use:
- allowed: `planned → active | cancelled`, `active → harvested | closed | cancelled`,
  `harvested → closed`, and any same-status edit;
- never allowed: reopening a finished season.

## 4. Flutter: the chosen lifecycle, and why

Old sequence: the season was created `planned`, the `default` batch was created during
sync, then activities were synced. Nothing ever moved a season to `active`.

Chosen resolution: **A, with B as a safety net.**
- **A.** The Flutter form now creates a season as **`active`**. Creating a season on the
  phone is "starting" it: the farmer records work immediately afterwards. This matches Web
  ("Bắt đầu vụ" creates `active`).
- **B.** A `planned` season from an older app version that has pending activities is
  switched to `active` locally at the start of sync (`planned → active` is a legal
  transition). It is pushed before its activities, in the same offline queue: there is no
  second sync architecture and idempotency is unchanged.
- **Why not C** (accepting activities in `planned`): it would contradict the FastAPI rule
  that has existed since FW-2, and it would make "planned" meaningless.

Closed-season behaviour on the phone:
- The DB answers `55000`, which Flutter classifies as `SyncErrorKind.seasonClosed`.
- That error is **permanent**: the queue does not pick the item again.
- The item stays `failed` with a readable message. It is never silently dropped, and the
  season is not reopened.
- If a local season edit would reopen a finished season, the server wins: the season is
  marked as matching the server and the next pull brings the real status down.
- The shared activity form refuses a finished season with "Vụ đã kết thúc".

## 5. Ending a season (Web)

- API: `PATCH /v1/crop-seasons/{id}/status`, with `{status: harvested|closed, actual_harvest_date?}`.
- The season row is locked `FOR UPDATE`; authorization is `user_can_write_crop`; legality
  is checked with the same transition function. Any other caller gets 404, and an illegal
  move gets 409.
- UI: "Kết thúc vụ" with a confirmation step.
  - Farmer: in the season header, for a writer on an active season.
  - Management: on the season page, for a `cooperative_manager`.
- After the season ends:
  - the journal becomes history (no "Ghi hoạt động");
  - metrics and Carbon stay available;
  - methodology stays editable, as before.

## 6. Migration safety

Hosted data audit before applying:
- 6 live seasons, all `active`;
- no non-active season holding activities;
- 0 owner/editor roles without an active membership.

Nothing historical is rewritten. Both migrations were first verified inside rolled-back
transactions (`backend/tests/test_db_lifecycle_rls.py` applies them in-transaction when
they are missing).

**Deployment order:** the migrations must be in place before this backend. FastAPI's write
guard now calls `private.activity_batch_open` and relies on the DB helpers for membership.

## 7. Verification

- **DB/RLS:** `test_db_lifecycle_rls.py` runs against real Postgres as `authenticated`.
  It covers the lifecycle, detail tables, batch/activity immutability, membership
  revocation, transitions and backend exemptions.
- **Hosted PostgREST probe after the fix:** 36/36
  (`docs/evidence/lifecycle-rls-probe-after.txt`). The probe also covers the default-batch
  upsert and direct detail deletes.
- **Flutter emulator + hosted:** `backend/scripts/hosted_flutter_lifecycle_e2e.py`
  (drives `app/integration_test/hosted_season_lifecycle_test.dart`), 6/6.
  1. Start a season on the phone.
  2. Record an activity with the emulator really offline (`adb svc`), then sync online:
     exactly one remote activity, in the default batch.
  3. End the season through FastAPI.
  4. Queue a late activity on the phone, which does not know the season ended.
  5. Sync: the DB refuses it; the item is failed/`seasonClosed` with `retry_count` stable,
     and it is not re-queued.
  6. The next pull brings the season down as `harvested`.
  7. Cleanup restores the row counts.

## 8. Independent review (Codex, read-only)

Round 1 verdict: `CODEX REVIEW: NO BLOCKER`, with two findings. Both are fixed by `20260926110000`.

| Severity | Finding | Fix |
|---|---|---|
| MEDIUM | Flutter's `ensureDefaultBatch` upsert could create or update a batch in a finished season before the activity was refused | client batch writes need a live `planned`/`active` season (55000); `crop_season_id` is immutable |
| LOW | a non-writer's direct detail DELETE matched 0 rows silently | `DELETE` on the detail tables is revoked from `authenticated` (explicit 42501); no client uses it |

## 9. Remaining (not in this work)

- Reads by a former member are unchanged. They were not a business write, so they were
  out of scope.
- A Flutter build released before this change creates `planned` seasons. Until the app is
  updated, the DB refuses its activity writes (55000, shown as a permanent failure, never
  lost).
- Carried over from before: forced temporary-password change, membership reactivation,
  attaching an existing farm, email invitation.

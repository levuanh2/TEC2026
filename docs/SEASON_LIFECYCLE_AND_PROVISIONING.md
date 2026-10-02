# Season lifecycle and farmer provisioning (2026-09-25)

Branch `feat/agricarbon-season-lifecycle`. Carbon engine, factor config, MRV,
Flutter sync, and Render config are unchanged. Resource Metrics formulas are
unchanged too.

## 1. Canonical hierarchy

```
auth.users ─ profiles ─ organization_memberships (role in the cooperative)
                      └ farm_members (owner | editor | viewer) ─ farms ─ plots
                          ─ crop_seasons ─ production_batches ─ activities (+ detail row)
```

* `activities.production_batch_id` is NOT NULL, and so is `production_batches.crop_season_id`.
  **An activity cannot exist outside a crop season.**
* Web journal writes (`ActivityWriteService._write_batch`) need two things:
  `crop_seasons.status = 'active'` and **exactly one** production batch whose status is not `closed`/`cancelled`.

## 2. Season status semantics

The `public.crop_status` enum defines five states: `planned | active | harvested | closed | cancelled`.
A soft-deleted season has `deleted_at` set; RLS hides it and every read filters it out.

| Action | Allowed on | Source |
|---|---|---|
| Create / edit / delete activities (Web) | `active` only | `service.ActivityWriteService._write_batch` → 422 `invalid_crop_season_state` |
| Edit IPCC methodology inputs | any status (farm writer) | `update_crop_season_methodology` |
| Calculate Carbon | any status (`user_can_write_crop`) | B4 persist gate |
| View history (journal, metrics, Carbon) | any non-deleted status | RLS `user_can_read_crop` |

Flutter creates seasons as `planned`, and nothing in the app moves them to `active`.
**Starting a season on the Web creates it as `active`** ("Bắt đầu vụ" means cultivation has started).

Farmer Web now takes the write target from the season's actual status
(`writeAccess.isJournalOpen`, exact `'active'`). A closed season can no longer
turn into a write target through a fallback. Its methodology can still be edited
and Carbon can still be recalculated (`useCanEditSeason`).

## 3. Create a crop season — `POST /v1/plots/{plot_id}/crop-seasons`

* **Body** (`extra="forbid"`): `season_code` (required, 1–64 chars), `variety_name`,
  `planting_date`, `expected_harvest_date` (must be ≥ `planting_date`, the same rule as
  `crop_seasons_harvest_dates_chk`).
* **Set by the server, not the client:** `crop_type` keeps the column default (`rice`); `status = 'active'`; the batch is created.
* **Default batch:** `batch_code = 'default'`, the same code the Flutter sync upserts in `ensureDefaultBatch`.
  Its status is the column default, exactly as Flutter creates it.
* **Authorization:** `private.user_can_write_farm` (the helper behind the `crop_seasons` INSERT policy),
  evaluated in the transaction with `auth.uid()` = the JWT caller.
  * Allowed: farm owner/editor, or an active `cooperative_manager` of the farm's cooperative.
  * Everyone else gets 404, the same as an unknown plot: viewer, enterprise viewer, regulator, ended manager, cross-scope caller.
  * No token → 401.
* **Atomicity:** the plot row is locked (`FOR UPDATE`), then the season and batch are inserted in **one transaction**.
  The response is built inside that transaction. If the batch insert or the response fails, the season rolls back.
* **Duplicates:**
  * A second active season on the plot → 409 `active_season_exists`.
  * An existing code (the unique constraint also covers soft-deleted seasons) → 409 `season_code_exists`.
  * An exact repeat of a request that already succeeded → 200 with `idempotent_replay: true`.
    It returns the same season and batch and writes nothing.
  * The Web form also disables submit while a request is pending.

Farmer Web and Management Web both call `startCropSeason` (`api/crops.ts`). There is a single mutation path.

## 4. Responsibility rule

* The HTX (cooperative manager) grants accounts and keeps the **official farm/plot structure**.
  `POST /v1/farms/{farm_id}/plots` accepts a manager only, even though RLS would also accept a farm owner.
* A farmer who is owner/editor can start a season on an assigned plot. A manager can also start one for the farmer.
* A viewer cannot start a season, and cannot write journal entries.
* Farmer Web does not create plots. A "farmer declares a plot, manager approves" workflow is out of scope for this sprint.

## 5. Farmer provisioning — no public sign-up

Management Web → FastAPI → Supabase Auth Admin API (server-side, service role) → application DB.
React never holds the service-role key. `test_react_never_holds_a_service_role_credential` guards this.

| Route | Who |
|---|---|
| `GET /v1/organizations/{org}/farmers` | active manager of `org` |
| `POST /v1/organizations/{org}/farmers` | active manager of `org` |
| `POST /v1/organizations/{org}/farms` (owner = an existing farmer member) | active manager of `org` |
| `POST /v1/farms/{farm}/plots` | active manager of the farm's cooperative |

Authorization uses `private.user_is_org_manager`, evaluated in the transaction.
Everyone else gets 404: farmer, farm viewer, enterprise viewer, regulator, a manager of another cooperative, an ended manager.

**Credentials: a temporary password (option A).** Email invitation is not viable today for three reasons:
* the Web app has no invite or recovery landing page;
* there is no custom SMTP (`supabase/config.toml` leaves `[auth.email.smtp]` commented out);
* Supabase's built-in mailer is rate-limited.

How the temporary password works:
* The server generates it (12 characters from `secrets`, upper + lower + digit + `-`).
* It is sent only to Supabase Auth, and returned to the manager **once** with `Cache-Control: no-store`.
* It is never logged and never stored in an application table (`test_the_password_is_never_logged`).
* The manager hands it over in person. The farmer replaces it in **Tôi → Đổi mật khẩu**:
  the app re-verifies the current password by signing in, then calls `auth.updateUser`
  on the farmer's own session.

**Consistency across Auth and the DB.** They cannot share one transaction, so:
1. `preflight` runs every refusal that does not need an identity, before any identity is created:
   authorization, duplicate email, taken farm code.
2. The identity is created, confirmed, with `full_name` in metadata so the trigger fills `profiles`.
3. Profile, `farmer` membership, farm (with the farmer as owner) and plot are written in **one transaction**.
4. If step 3 fails, the identity is **deleted**. If deletion fails, it is **banned**. The request always fails:
   * 500 `provisioning_failed` — nothing was saved;
   * 500 `provisioning_incomplete` — the identity is locked and has no membership, so an admin must clean it up.

   The server logs the user id, never the password.

**Duplicate emails** (compared case-insensitively):

| The email belongs to | Response |
|---|---|
| An active member of this HTX | 409 `farmer_already_member` |
| A former member of this HTX | 409 `membership_inactive` (reactivation is not implemented) |
| Anyone else | 409 `account_exists`, with a generic message that reveals nothing about the other tenant |
| An identity created between preflight and create | Classified again |

A repeated submit becomes `farmer_already_member`.

**Lifecycle stages** in the manager's list and on Farmer Web:

| Stage | Farmer Web shows |
|---|---|
| `no_farm`, `no_plot` | "HTX chưa gán thửa ruộng cho tài khoản của bạn." |
| `no_season` | "Bạn chưa có vụ đang canh tác" + "Bắt đầu vụ mới" (if the viewer can write) |
| `history_only` | The same, plus the past journal, read-only |
| `active_season` | The normal journal |

### 5.1 Forced first-login password change (Core V1 closure, 2026-10-02)

The manager has seen the temporary password, so the account cannot be used until
the farmer replaces it.

| Step | Where it is decided |
|---|---|
| Provisioning sets `app_metadata.must_change_password = true` | `SupabaseAuthAdmin.create_user` (service role, server only; users cannot write `app_metadata`) |
| Temporary password signs in | Supabase Auth |
| `/v1/me` reports `must_change_password: true` | live Auth user (`get_user`), not a token claim |
| Every other `/v1` operation: 403 `password_change_required` | FastAPI router guard (refuses only) |
| Every business read/write, any client | **database**: `private.password_change_pending()` reads the live flag on `auth.users`; the root helpers (`user_can_read_farm`, `user_can_write_farm`, `user_can_manage_farm_members`, `user_is_org_member`, `user_is_org_manager`, `user_can_read_organization`, other members' profiles) answer false — migration `20261002100000`. Covers Flutter (PostgREST) and FastAPI pooled paths alike |
| `POST /v1/me/password {current_password, new_password}` | FastAPI verifies the current password with Supabase Auth, then ONE Auth Admin call sets the new password and clears the flag. The only way the flag is cleared. 422 `current_password_incorrect` / `password_too_weak` / `password_too_long` / `password_unchanged`; `Cache-Control: no-store` |
| Normal access | after the client refreshes its session (a token issued before the change still carries the old claim and is refused) |

Still readable while the flag is set: the caller's own profile and membership rows,
own devices, public reference data. Accounts without the flag (every account
provisioned before this change, managers) are unaffected. Tests:
`backend/tests/test_forced_password_change.py` (real stack),
`test_password_change_unit.py` (no DB).

## 6. Canonical lifecycle

HTX manager grants the farmer an account → assigns a farm and plot → the farmer signs in →
the farmer or the manager starts a season → the system creates the default production batch →
the farmer records activities → Resource Metrics → Carbon → Management/MRV.

## 7. Independent review (Codex, read-only) — findings and disposition

| # | Codex | Disposition |
|---|---|---|
| 1 | BLOCKER: the activity write checked `status='active'` via PostgREST *before* the write transaction; direct PostgREST/Flutter writes are not status-checked by RLS | **Web path fixed:** `_assert_can_write_batch` now re-reads season + batch status under `FOR SHARE` of the season row inside the write transaction (`SeasonNotOpenError` → 422). A concurrent close either waits or is seen. **Direct PostgREST (Flutter offline sync) not changed:** Flutter creates seasons `planned` and syncs activities straight through RLS, so an RLS/trigger `status='active'` rule would reject every Flutter write; it needs a Flutter lifecycle change first (P1 below). |
| 2 | HIGH: `user_can_write_farm` honours an owner/editor `farm_members` row after the org membership ended, and ignores `farms.deleted_at` | **FastAPI writes fixed** (season create, activity create/edit/delete, methodology): `ACTIVE_FARM_MEMBERSHIP_SQL` additionally requires an active cooperative manager or an ACTIVE member of the farm's cooperative, on a non-deleted farm. The SQL helper itself needs a migration (P1 below). |
| 3 | HIGH: an ambiguous Auth Admin failure (user created, response lost) left an orphan identity | **Fixed:** each attempt puts a random `provisioning_attempt` marker in the identity's user metadata; on any non-duplicate failure the service looks up the identity with that email AND that marker AND no membership, and deletes (fallback: bans) it; if the lookup itself fails the response is 500 `provisioning_incomplete`. |
| 4 | (round 2) HIGH: a time-window orphan lookup could delete a concurrent request's identity | **Fixed** by the per-attempt marker above: another request's identity carries a different marker and is never touched. |

Round 2 verdict: `CODEX REVIEW: NO BLOCKER` (#1 and #2 direct-RLS parts confirmed as pre-existing follow-ups not changed by this branch).

## 8. Public sign-up

Product rule: no public farmer registration. `supabase/config.toml` now sets `[auth] enable_signup = false` and `[auth.email] enable_signup = false` (email/password **sign-in** unchanged; Admin API provisioning is not affected by this setting).

The hosted project is changed in the dashboard (Authentication → Sign In / Providers → "Allow new users to sign up" off) or with the Management API — not by pushing this whole `config.toml`, whose `site_url` and other values are local-dev values. Verify with:

```
python backend/scripts/verify_public_signup_disabled.py
```
(`/auth/v1/settings.disable_signup` is true, a public `/auth/v1/signup` is refused with `signup_disabled`, an Admin-created user can still sign in; probe users are deleted.)

Hosted state verified 2026-09-26 after the dashboard switch: `verify_public_signup_disabled.py` 5/5 (`disable_signup=true`, public sign-up refused with `signup_disabled`, email sign-in on, Admin-created user can sign in).

## 9. Follow-ups (not in this sprint)

P1
* ~~`FORCE_TEMP_PASSWORD_CHANGE_ON_FIRST_LOGIN`~~ — done, §5.1
* reactivate an inactive membership
* attach an existing farm to an existing account
* crop-season close / harvest endpoint
* DB-level journal rule for every client (RLS/trigger `status='active'`), after Flutter moves seasons out of `planned`
* migration: `private.user_can_write_farm/_crop/_batch` require an active org membership and a non-deleted farm

P2
* invitation/email provisioning once SMTP and a set-password page exist

## 10. Known gaps (not changed in this sprint)

* ~~Nothing forces the farmer to change the temporary password.~~ — §5.1
* A former member cannot be reactivated from the UI.
* A farmer cannot be assigned to an *existing* farm from the UI.
* There is no Web endpoint to move a season to `harvested`/`closed`.
* `farmer@agricarbon.local` (HTX-DEMO-001, 0 seasons) is intentionally left as the real no-season onboarding account.

## 11. Final gate (2026-09-26, before merge)

| Gate | Result |
|---|---|
| Codex read-only review | 3 rounds; round 3 `CODEX REVIEW: NO BLOCKER` |
| Backend full pytest | 780 passed, 0 failed, 0 skipped |
| Web | Vitest 465 passed; tsc; build; mock Playwright 90 passed (50 skipped = real/opt-in specs) |
| Real-data suite | 25 passed, 0 failed, 10 skipped: 6 script-driven disposable-tenant smokes (carbon quick-fix ×2, straw quick-fix ×2, season-provisioning ×2 — the last run separately below), 4 opt-in specs that write shared hosted QA data (MRV export ×2, CV inference, recommendation generation) |
| Hosted season + provisioning smoke | 22/22, row counts restored, Case A unchanged (after the signup switch, so Admin provisioning still works) |
| Public sign-up | disabled on hosted, verified 5/5 |

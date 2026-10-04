# Core V1 closure: decisions

Decisions taken while closing AgriCarbon Core V1 (branch
`release/agricarbon-core-v1-closure`). Migrations and tests point here.

## 3A. Who reads a farm after the cooperative membership ends

Product decision, 2026-10-03.

| Who | Own farm (history) | Write anything | Other farms | HTX dashboard / aggregate, other members |
|---|---|---|---|---|
| Active farm owner | read | yes, while the season lifecycle allows it | no, unless a member there | only through an HTX role |
| **Former** farm owner (membership ended) | **read only** | **no** | no | no |
| Former farm editor / viewer | no | no | no | no |
| Member of another HTX | no | no | only farms where they hold an independent membership or ownership | only their own HTX |

"Former" means the `organization_memberships` row for the farm's cooperative has
`ended_at <= now()`. The `farm_members` row is kept: ownership of the data does
not change, only what the role grants.

Where it is enforced:

- **RLS** (authoritative for every client, PostgREST and FastAPI alike):
  `private.user_can_read_farm` lets a `farm_members` row count without an active
  membership only for `farm_role = 'owner'` (migration `20261002090000`). Every
  write helper (`user_can_write_farm`, `user_can_manage_farm_members`, and the
  crop/batch helpers built on them) and every organization helper
  (`user_is_org_member`, `user_is_org_manager`, `user_can_read_organization`,
  `user_can_read_profile`) requires an active membership (`20260926090000`).
  HTX routes (`/v1/organizations/{id}/...`) are gated on the organization row,
  so they answer 404 to a former member, the same as an unknown id.
- **Service-role writes** (recommendations, CV images and inferences): RLS does
  not apply, so the repositories evaluate `private.user_can_write_crop` for the
  JWT-verified caller inside each write's transaction (`crop_write_authz`), see
  3C. This also closes the gap where a former owner who had joined ANOTHER HTX
  as a farmer could write recommendations and CV images on the farm they left.
- A refused read or write looks exactly like a request for an unknown id
  (same status and body), so nothing leaks the farm's existence.

Tests: `backend/tests/test_former_member_reads.py` (real RLS),
`backend/tests/test_former_member_api_reads.py` (real `main.app`, real JWTs, local
stack only), and the reader-without-write-authority cases in
`test_recommendation_api.py` and `test_cv_service.py`.

## 3C. A viewer is read-only

Product decision, 2026-10-03. Reading a farm or a season grants no business
write. A farm `viewer`, a former member, and a data-grant reader may NOT
generate, persist, accept or dismiss a recommendation, or upload a CV / plant
image. A "preview" of recommendations for a viewer would be a separate
non-persisting flow; none exists.

- Write authority is `private.user_can_write_crop` (active owner/editor of the
  farm, or active manager of its HTX) -- the rule of `plant_images_insert` --
  evaluated in the database, not re-derived in FastAPI: refused before any
  Carbon work or Storage upload, and re-checked inside each row-writing
  transaction (accept/dismiss on the row's own season, locked).
- On top, recommendation and CV actions stay **farmer** actions, as on main: an
  HTX manager is refused them too (decision 2026-10-03, "keep managers out").
  The farmer role must be an ACTIVE `farmer` membership in the season's own
  HTX, checked in the same database statement as the helper
  (`infrastructure/crop_write_authz.py`). A farmer role held in another HTX
  does not count, so a manager of this HTX who also farms elsewhere stays
  refused (review round 2 finding LOW-1, fixed; test persona `cross_manager`).
  A manager flow (preview, or acting for a farmer) would be a separate endpoint
  and product decision.
- A refusal is the same 404 as an unknown id.

## 3D. A token minted with the temporary password stays refused

Changing the temporary password clears the server-side flag and revokes the
refresh tokens, but an access token minted before stays valid for up to an
hour. Migration `20261003090000` makes `private.password_change_pending()`
fail closed: pending when the request's JWT still carries
`app_metadata.must_change_password = true` OR the authoritative `auth.users`
flag is set. Such a token (TOKEN_OLD) is refused by every root authorization
helper on PostgREST (reads and writes), and by FastAPI's guard on every API
route (it reads the same claim), until it expires;
a token minted after the change has normal access. `/v1/me` and
`POST /v1/me/password` keep working so the user can leave the state. Test:
`test_forced_password_change.py::test_a_token_minted_with_the_temporary_password_stays_refused_after_the_change`.

## 3E. Review findings re-evaluated (PR #3, 2026-10-03)

| Finding | Reproduced | Severity | Action |
|---|---|---|---|
| A. A writer refused on a harvest over the plot area gets 422 `harvested_area_exceeds_plot`, not the refusal 404 | Confirmed (validation runs before the write-authority check) | LOW | Defer. No existence leak: the season read (RLS) runs first, so only a caller who can already READ the season and its plot area sees it; an unreadable or unknown season is 404. |
| B. A plot shrunk between the API's area check and the insert makes the DB trigger raise 23514, returned as 500 | Confirmed in code; needs a concurrent plot-area change | LOW | Defer. No API route changes a plot's area; the database still refuses the row (integrity holds), only the status is wrong. |
| C. Restoring a soft-deleted harvest could bypass the area trigger | Not reproduced: as the owner, `update activities set deleted_at = null` affects 0 rows (the select policy hides deleted rows); no restore/undelete function exists | — | None. An undelete feature must re-check the area rule. |
| D. Flutter: a stale local plot area marks a valid harvest as a permanent failure | Not reproduced | — | None now. The record stays in the queue with "Sửa bản ghi" (re-saving re-queues it). |
| E. Flutter: password changed but the sign-in with the new one fails → shown as "not changed" | Confirmed | LOW | Fixed (a17cf7b): says the password WAS changed, as Web does. |
| F. Data-dependent `test.skip` in the manual real spec `round5-real` | Confirmed | LOW | None: real/hosted specs are excluded from the CI mock suite; no skip added. |

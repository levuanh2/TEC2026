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
  not apply, so `service._require_farmer_of_season_cooperative` requires an
  active `farmer` membership in the cooperative of the season's farm. Before it,
  a former owner who had joined ANOTHER HTX as a farmer could generate and
  accept/dismiss recommendations, and upload CV images, on the farm they left.
- A refused read or write looks exactly like a request for an unknown id
  (same status and body), so nothing leaks the farm's existence.

Tests: `backend/tests/test_former_member_reads.py` (real RLS),
`backend/tests/test_former_member_api_reads.py` (real `main.app`, real JWTs, local
stack only), and the cross-cooperative cases in `test_recommendation_api.py` and
`test_cv_service.py`.

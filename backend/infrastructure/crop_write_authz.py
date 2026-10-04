"""Write authority on a crop season for the service-role repositories.

`recommendation_repo` and `cv_repo` write with a backend connection that
bypasses RLS, and the services above them only establish READ scope through
the caller's JWT. Read scope is wider than write scope: a farm `viewer`, a
former farm owner (historical read, docs/CORE_V1_CLOSURE.md) and a data-grant
reader can all read a season. So, like `write_repo._assert_can_write_batch`,
the rule is not re-derived in Python: `private.user_can_write_crop` -- the
helper of the `plant_images_insert` policy (`season_recommendations` has no
client write policy at all) -- is evaluated with `auth.uid()` = the user the
Auth server verified for the JWT.
The claim is transaction-local and cleared before any row is written.

These are farmer actions (decision 2026-10-03), so the same statement also
requires an ACTIVE `farmer` membership in the season's own cooperative. The
helper alone lets an HTX manager write, and a farmer role held in ANOTHER
cooperative must not count: a manager of this HTX who farms elsewhere stays
refused. One role per (organization, user), so this excludes every manager of
the season's HTX. Same active rule as the helpers: `ended_at` null or future.
"""
from __future__ import annotations

import json
from typing import Any


class CropWriteDeniedError(Exception):
    """The caller may not write this crop season (or it does not exist)."""


def assert_can_write_crop(cur: Any, *, crop_season_id: str, actor_id: str) -> None:
    cur.execute(
        "select set_config('request.jwt.claims', %s, true)",
        [json.dumps({"sub": str(actor_id), "role": "authenticated"})],
    )
    cur.execute(
        "select private.user_can_write_crop(cs.id) and exists ("
        " select 1 from public.plots p"
        " join public.farms f on f.id = p.farm_id"
        " join public.organization_memberships om on om.organization_id = f.cooperative_id"
        " where p.id = cs.plot_id and om.user_id = %s::uuid"
        " and om.role = 'farmer'::public.organization_role"
        " and (om.ended_at is null or om.ended_at > now())"
        ") as allowed from public.crop_seasons cs where cs.id = %s::uuid",
        [str(actor_id), str(crop_season_id)],
    )
    row = cur.fetchone()
    cur.execute("select set_config('request.jwt.claims', '', true)")
    allowed = row["allowed"] if isinstance(row, dict) else (row[0] if row else None)
    if not allowed:
        raise CropWriteDeniedError()

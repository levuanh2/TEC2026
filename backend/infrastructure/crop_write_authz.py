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
        "select private.user_can_write_crop(cs.id) as allowed from public.crop_seasons cs where cs.id = %s::uuid",
        [str(crop_season_id)],
    )
    row = cur.fetchone()
    cur.execute("select set_config('request.jwt.claims', '', true)")
    allowed = row["allowed"] if isinstance(row, dict) else (row[0] if row else None)
    if not allowed:
        raise CropWriteDeniedError()

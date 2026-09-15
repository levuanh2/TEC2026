"""B4: who may PERSIST a Carbon calculation.

Reading a crop season (RLS `private.user_can_read_crop`) is enough to view its
stored results, and Recommendation's what-if runs never persist. Writing a row
into `carbon_calculations` is different: that row becomes the season's recorded
result for Resource Metrics and MRV. Product decision (P1 sprint, 2026-09-15):
only writers of the crop may persist — `private.user_can_write_crop`, i.e. a farm
`owner`/`editor` or an active `cooperative_manager` of the farm's cooperative.
A regulator/enterprise_viewer reading through a data grant, or a farm `viewer`,
may not.

The rule is not re-derived in Python: the helper itself is evaluated with
`auth.uid()` set to the user the Auth server verified for this JWT, exactly as
the activity write path does (`write_repo._assert_can_write_batch`).
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Callable, Protocol

from . import pg_pool
from .auth import CropAccessError, jwt_rejection_as_invalid_token
from .config import Settings

_DENIED = "'{}' không tồn tại hoặc không thuộc phạm vi truy cập của người dùng hiện tại."


class CropPersistChecker(Protocol):
    def assert_can_persist(self, token: str, crop_season_id: str) -> None: ...


class PostgresCropPersistChecker:
    def __init__(
        self,
        settings: Settings,
        *,
        user_id_for: Callable[[str], str | None] | None = None,
        connect: Callable[[], Any] | None = None,
    ) -> None:
        self._settings = settings
        self._user_id_for = user_id_for or self._verified_user_id
        self._connect = connect

    def _verified_user_id(self, token: str) -> str | None:
        from .supabase_clients import client_for_token

        with jwt_rejection_as_invalid_token():
            user = client_for_token(self._settings, token).auth.get_user(token).user
        return str(user.id) if user is not None else None

    def _connection(self):
        if self._connect is not None:
            return self._connect()
        return pg_pool.connection(self._settings.require_db())

    def assert_can_persist(self, token: str, crop_season_id: str) -> None:
        try:
            uuid.UUID(str(crop_season_id))
        except ValueError as exc:
            raise CropAccessError(_DENIED.format(crop_season_id)) from exc
        user_id = self._user_id_for(token)
        if not user_id:
            raise CropAccessError(_DENIED.format(crop_season_id))
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                "select set_config('request.jwt.claims', %s, true)",
                [json.dumps({"sub": user_id, "role": "authenticated"})],
            )
            cur.execute("select private.user_can_write_crop(%s::uuid) as allowed", [str(crop_season_id)])
            allowed = bool(cur.fetchone()["allowed"])
            cur.execute("select set_config('request.jwt.claims', '', true)")
        if not allowed:
            # Same 404 as "cannot read": a reader must not learn that a write
            # rule, rather than scope, is what stopped them.
            raise CropAccessError(_DENIED.format(crop_season_id))

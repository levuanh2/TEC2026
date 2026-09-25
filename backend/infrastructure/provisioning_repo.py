"""Management-side farmer provisioning: membership, farm and plot structure.

Who may do any of this is decided by the SQL helper the RLS policies already
use -- `private.user_is_org_manager(organization)`: an ACTIVE
`cooperative_manager` membership of that cooperative. It is evaluated inside
each transaction with `auth.uid()` = the JWT-verified caller (transaction-local
claim, cleared before any row is written), exactly as the activity and season
repositories do. A manager of cooperative A therefore cannot touch cooperative
B, and a farmer, farm viewer, enterprise viewer or regulator cannot touch any.

This connection reads `auth.users` (the login email) because the caller-scoped
PostgREST client cannot; nothing from it is returned beyond the email of a
member of the manager's own cooperative.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from . import pg_pool
from .config import Settings


class ProvisioningScopeError(Exception):
    """Not a manager of this cooperative, or the target is outside it. One error
    for both so the API answers the same 404 and reveals nothing."""


class FarmerAlreadyMemberError(Exception):
    """The email already belongs to a member of this cooperative."""


class MembershipInactiveError(Exception):
    """The email belongs to a former member of this cooperative."""


class AccountExistsError(Exception):
    """The email is taken by an identity outside this cooperative. Deliberately
    carries nothing about where."""


class FarmCodeTakenError(Exception):
    pass


class PlotCodeTakenError(Exception):
    pass


def _prepared(prepare: Callable[[Any], Any] | None, result: Any) -> Any:
    return prepare(result) if prepare is not None else result


def lifecycle_stage(*, farm_count: int, plot_count: int, season_count: int, active_season_count: int) -> str:
    """Where a farmer is in onboarding. Mirrors the Farmer Web empty states."""
    if farm_count == 0:
        return "no_farm"
    if plot_count == 0:
        return "no_plot"
    if active_season_count > 0:
        return "active_season"
    if season_count > 0:
        return "history_only"
    return "no_season"


class PostgresProvisioningRepository:
    def __init__(self, settings: Settings | None, connect: Any | None = None):
        self._settings = settings
        self._connect = connect

    def _connection(self):
        if self._connect is not None:
            return self._connect()
        return pg_pool.connection(self._settings.require_db())  # type: ignore[union-attr]

    # -- authorization ----------------------------------------------------

    @staticmethod
    def _assert_manager(cur: Any, *, organization_id: str, actor_id: str) -> None:
        cur.execute(
            "select set_config('request.jwt.claims', %s, true)",
            [json.dumps({"sub": str(actor_id), "role": "authenticated"})],
        )
        cur.execute(
            """select private.user_is_org_manager(%s::uuid) as allowed,
                      exists(select 1 from public.organizations o where o.id = %s::uuid
                             and o.organization_type = 'cooperative' and o.is_active) as cooperative""",
            [organization_id, organization_id],
        )
        row = cur.fetchone()
        cur.execute("select set_config('request.jwt.claims', '', true)")
        if not (row["allowed"] and row["cooperative"]):
            raise ProvisioningScopeError()

    # -- reads --------------------------------------------------------------

    def list_farmers(self, *, organization_id: str, actor_id: str) -> list[dict[str, Any]]:
        with self._connection() as conn, conn.cursor() as cur:
            self._assert_manager(cur, organization_id=organization_id, actor_id=actor_id)
            cur.execute(
                """select om.user_id::text as user_id, u.email::text as email, p.full_name, p.phone,
                          p.is_active as profile_active, om.ended_at,
                          (u.banned_until is not null and u.banned_until > now()) as banned
                   from public.organization_memberships om
                   join auth.users u on u.id = om.user_id
                   join public.profiles p on p.id = om.user_id
                   where om.organization_id = %s and om.role = 'farmer'
                   order by lower(coalesce(p.full_name, u.email::text))""",
                [organization_id],
            )
            members = [dict(r) for r in cur.fetchall()]
            if not members:
                return []
            cur.execute(
                """select fm.user_id::text as user_id, f.id::text as farm_id, f.farm_code, f.farm_name,
                          fm.farm_role::text as farm_role,
                          pl.id::text as plot_id, pl.name as plot_name,
                          count(cs.id) filter (where cs.id is not null) as seasons,
                          count(cs.id) filter (where cs.status = 'active') as active_seasons
                   from public.farm_members fm
                   join public.farms f on f.id = fm.farm_id and f.deleted_at is null
                   left join public.plots pl on pl.farm_id = f.id and pl.deleted_at is null
                   left join public.crop_seasons cs on cs.plot_id = pl.id and cs.deleted_at is null
                   where f.cooperative_id = %s and fm.user_id = any(%s::uuid[])
                   group by fm.user_id, f.id, f.farm_code, f.farm_name, fm.farm_role, pl.id, pl.name
                   order by f.farm_name, pl.name""",
                [organization_id, [m["user_id"] for m in members]],
            )
            rows = [dict(r) for r in cur.fetchall()]
        out = []
        for m in members:
            mine = [r for r in rows if r["user_id"] == m["user_id"]]
            farms: dict[str, dict[str, Any]] = {}
            for r in mine:
                farms.setdefault(r["farm_id"], {"id": r["farm_id"], "farm_code": r["farm_code"], "farm_name": r["farm_name"], "farm_role": r["farm_role"]})
            plots = [r for r in mine if r["plot_id"]]
            seasons = sum(int(r["seasons"]) for r in plots)
            active = sum(int(r["active_seasons"]) for r in plots)
            idle = next((r for r in plots if int(r["active_seasons"]) == 0), None)
            status = "ended" if m["ended_at"] is not None else "locked" if (m["banned"] or not m["profile_active"]) else "active"
            out.append({
                "user_id": m["user_id"], "email": m["email"], "full_name": m["full_name"], "phone": m["phone"],
                "account_status": status,
                "farms": list(farms.values()),
                "plot_count": len(plots), "season_count": seasons, "active_season_count": active,
                "stage": lifecycle_stage(farm_count=len(farms), plot_count=len(plots), season_count=seasons, active_season_count=active),
                # Where each contextual row action goes: add a plot to the first
                # farm; start a season on a plot with nothing under cultivation.
                "primary_farm_id": next(iter(farms), None),
                "idle_plot_id": idle["plot_id"] if idle else None,
            })
        return out

    # -- provisioning ---------------------------------------------------------

    def preflight(self, *, organization_id: str, actor_id: str, email: str, farm_code: str | None) -> None:
        """Every refusal that does not need an Auth identity, BEFORE one is
        created: so the common mistakes never create-then-delete a user."""
        with self._connection() as conn, conn.cursor() as cur:
            self._assert_manager(cur, organization_id=organization_id, actor_id=actor_id)
            self._assert_email_free(cur, organization_id=organization_id, email=email)
            if farm_code is not None:
                self._assert_farm_code_free(cur, organization_id=organization_id, farm_code=farm_code)

    @staticmethod
    def _assert_email_free(cur: Any, *, organization_id: str, email: str) -> None:
        cur.execute(
            """select u.id::text as id,
                      (select om.ended_at is null or om.ended_at > now() from public.organization_memberships om
                       where om.user_id = u.id and om.organization_id = %s) as member_here
               from auth.users u where lower(u.email) = lower(%s)""",
            [organization_id, email],
        )
        row = cur.fetchone()
        if row is None:
            return
        if row["member_here"] is True:
            raise FarmerAlreadyMemberError()
        if row["member_here"] is False:
            raise MembershipInactiveError()
        raise AccountExistsError()

    @staticmethod
    def _assert_farm_code_free(cur: Any, *, organization_id: str, farm_code: str) -> None:
        cur.execute("select 1 from public.farms where cooperative_id = %s and farm_code = %s", [organization_id, farm_code])
        if cur.fetchone() is not None:
            raise FarmCodeTakenError()

    @staticmethod
    def _insert_farm(cur: Any, *, organization_id: str, owner_id: str, farm: dict[str, Any]) -> str:
        cur.execute(
            """insert into public.farms (cooperative_id, farm_code, farm_name, province_name, district_name, commune_name)
               values (%s, %s, %s, %s, %s, %s) returning id::text as id""",
            [organization_id, farm["farm_code"], farm["farm_name"], farm.get("province_name"),
             farm.get("district_name"), farm.get("commune_name")],
        )
        farm_id = cur.fetchone()["id"]
        # `validate_farm_member_trg` requires the owner to be an active member of
        # the farm's cooperative -- the membership is always inserted first.
        cur.execute("insert into public.farm_members (farm_id, user_id, farm_role) values (%s, %s, 'owner')", [farm_id, owner_id])
        return farm_id

    @staticmethod
    def _insert_plot(cur: Any, *, farm_id: str, plot: dict[str, Any]) -> str:
        cur.execute("select 1 from public.plots where farm_id = %s and plot_code = %s", [farm_id, plot["plot_code"]])
        if cur.fetchone() is not None:
            raise PlotCodeTakenError()
        cur.execute(
            "insert into public.plots (farm_id, plot_code, name, area_ha) values (%s, %s, %s, %s) returning id::text as id",
            [farm_id, plot["plot_code"], plot["name"], plot["area_ha"]],
        )
        return cur.fetchone()["id"]

    def provision(
        self, *, organization_id: str, actor_id: str, user_id: str, full_name: str, phone: str | None,
        farm: dict[str, Any] | None, plot: dict[str, Any] | None,
        prepare: Callable[[dict[str, Any]], Any] | None = None,
    ) -> Any:
        """Profile + farmer membership [+ farm with the farmer as owner [+ plot]]
        in ONE transaction, for an Auth identity created just before. Any
        failure rolls all of it back; the caller then removes the identity."""
        with self._connection() as conn, conn.cursor() as cur:
            self._assert_manager(cur, organization_id=organization_id, actor_id=actor_id)
            cur.execute("update public.profiles set full_name = %s, phone = %s, updated_at = now() where id = %s",
                        [full_name, phone, user_id])
            if cur.rowcount != 1:
                raise RuntimeError("profile row missing for the new identity")
            cur.execute(
                "insert into public.organization_memberships (organization_id, user_id, role) values (%s, %s, 'farmer')",
                [organization_id, user_id],
            )
            farm_id = plot_id = None
            if farm is not None:
                self._assert_farm_code_free(cur, organization_id=organization_id, farm_code=farm["farm_code"])
                farm_id = self._insert_farm(cur, organization_id=organization_id, owner_id=user_id, farm=farm)
                if plot is not None:
                    plot_id = self._insert_plot(cur, farm_id=farm_id, plot=plot)
            return _prepared(prepare, {"user_id": user_id, "organization_id": organization_id, "farm_id": farm_id, "plot_id": plot_id})

    def create_farm(
        self, *, organization_id: str, actor_id: str, owner_user_id: str, farm: dict[str, Any],
        prepare: Callable[[dict[str, Any]], Any] | None = None,
    ) -> Any:
        """A farm for a farmer who already belongs to this cooperative."""
        with self._connection() as conn, conn.cursor() as cur:
            self._assert_manager(cur, organization_id=organization_id, actor_id=actor_id)
            cur.execute(
                """select 1 from public.organization_memberships where organization_id = %s and user_id = %s
                   and role = 'farmer' and (ended_at is null or ended_at > now())""",
                [organization_id, owner_user_id],
            )
            if cur.fetchone() is None:
                raise ProvisioningScopeError()
            self._assert_farm_code_free(cur, organization_id=organization_id, farm_code=farm["farm_code"])
            farm_id = self._insert_farm(cur, organization_id=organization_id, owner_id=owner_user_id, farm=farm)
            return _prepared(prepare, {"id": farm_id, "farm_code": farm["farm_code"], "farm_name": farm["farm_name"]})

    def create_plot(
        self, *, farm_id: str, actor_id: str, plot: dict[str, Any],
        prepare: Callable[[dict[str, Any]], Any] | None = None,
    ) -> Any:
        """A plot on a farm, by a manager of the farm's cooperative only.

        RLS would also let a farm owner/editor insert plots; the product keeps
        the official plot structure with the cooperative, so this route asks
        for the manager rule, not `user_can_write_farm`."""
        with self._connection() as conn, conn.cursor() as cur:
            cur.execute(
                "select cooperative_id::text as org from public.farms where id = %s and deleted_at is null for update",
                [farm_id],
            )
            row = cur.fetchone()
            if row is None:
                raise ProvisioningScopeError()
            self._assert_manager(cur, organization_id=row["org"], actor_id=actor_id)
            plot_id = self._insert_plot(cur, farm_id=farm_id, plot=plot)
            return _prepared(prepare, {"id": plot_id, "farm_id": farm_id, "plot_code": plot["plot_code"],
                                       "name": plot["name"], "area_ha": float(plot["area_ha"])})

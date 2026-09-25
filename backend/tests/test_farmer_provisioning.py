"""Management farmer provisioning ("Thêm nông hộ").

* HTTP + service with fakes: auth, error contract, the Auth/DB compensation
  strategy, and that the temporary password is returned once and never logged.
* The repository against the REAL database (skipped without SUPABASE_DB_URL):
  authorization through `private.user_is_org_manager`, duplicate handling and
  the one-transaction write. Every row is created inside a transaction that is
  always rolled back; "the Auth identity" is an `auth.users` row inserted there
  (the Admin API is not called), so nothing outside the test survives.
"""
from __future__ import annotations

import logging
import re
import sys
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

import api  # noqa: E402
import schemas  # noqa: E402
from infrastructure.auth_admin import AuthUserExistsError  # noqa: E402
from infrastructure.config import load_settings  # noqa: E402
from infrastructure.provisioning_repo import (  # noqa: E402
    AccountExistsError,
    FarmCodeTakenError,
    FarmerAlreadyMemberError,
    MembershipInactiveError,
    PlotCodeTakenError,
    PostgresProvisioningRepository,
    ProvisioningScopeError,
    lifecycle_stage,
)
from infrastructure.read_repo import ReadNotFoundError  # noqa: E402
from service import ProvisioningService  # noqa: E402

ORG = str(uuid.uuid4())
PASSWORD = "Tmp1-Pass-word"


# ---------------------------------------------------------------- fakes

class FakeRead:
    def user_id(self):
        return "manager-1"


class FakeAuth:
    def __init__(self, *, exists=False, delete_fails=False, ban_fails=False, ambiguous=False):
        self.exists, self.delete_fails, self.ban_fails = exists, delete_fails, ban_fails
        self.ambiguous = ambiguous
        self.created, self.deleted, self.banned, self.attempts = [], [], [], []

    def create_user(self, *, email, password, full_name, attempt):
        self.attempts.append(attempt)
        if self.exists:
            raise AuthUserExistsError()
        if self.ambiguous:
            raise TimeoutError("response lost after the user was created")
        self.created.append({"email": email, "password": password, "full_name": full_name})
        return "new-user"

    def delete_user(self, user_id):
        if self.delete_fails:
            raise RuntimeError("delete failed")
        self.deleted.append(user_id)

    def ban_user(self, user_id):
        if self.ban_fails:
            raise RuntimeError("ban failed")
        self.banned.append(user_id)


class FakeRepo:
    def __init__(self, *, preflight_error=None, provision_error=None, second_preflight_error=None,
                 orphan=None, orphan_lookup_fails=False):
        self.preflight_error, self.provision_error = preflight_error, provision_error
        self.orphan, self.orphan_lookup_fails = orphan, orphan_lookup_fails
        self.orphan_queries = []
        self.second_preflight_error = second_preflight_error
        self.preflights, self.provisions = 0, []

    def preflight(self, **kwargs):
        self.preflights += 1
        if self.preflights == 1 and self.preflight_error:
            raise self.preflight_error
        if self.preflights == 2 and self.second_preflight_error:
            raise self.second_preflight_error

    def provision(self, *, prepare=None, **kwargs):
        self.provisions.append(kwargs)
        if self.provision_error:
            raise self.provision_error
        return prepare({"user_id": kwargs["user_id"], "organization_id": kwargs["organization_id"], "farm_id": "farm-1", "plot_id": "plot-1"})

    def list_farmers(self, **kwargs):
        return []

    def find_orphan_identity(self, **kwargs):
        self.orphan_queries.append(kwargs)
        if self.orphan_lookup_fails:
            raise RuntimeError("db down")
        return self.orphan


def client(repo=None, auth=None, *, with_read=True):
    app = FastAPI()
    app.include_router(api.router)
    if with_read:
        app.dependency_overrides[api._read_repo] = lambda: FakeRead()
    service = ProvisioningService(repo or FakeRepo(), auth or FakeAuth(), password_factory=lambda: PASSWORD)
    app.dependency_overrides[api._provisioning_service] = lambda: service
    return TestClient(app)


BODY = {
    "full_name": "Nguyễn Văn Bình", "email": "Binh@Example.VN", "phone": "0901234567",
    "farm": {"farm_code": "HH-9", "farm_name": "Hộ Bình"},
    "plot": {"plot_code": "T-1", "name": "Thửa 1", "area_ha": 1.2},
}
URL = f"/v1/organizations/{ORG}/farmers"


def test_unauthenticated_is_401_and_creates_nothing():
    auth = FakeAuth()
    response = client(auth=auth, with_read=False).post(URL, json=BODY)
    assert response.status_code == 401
    assert auth.created == []


def test_success_returns_the_temporary_password_once_and_uncached():
    auth, repo = FakeAuth(), FakeRepo()
    response = client(repo, auth).post(URL, json=BODY)
    assert response.status_code == 201
    body = response.json()
    assert body["temporary_password"] == PASSWORD
    assert body["email"] == "binh@example.vn"          # normalized once, server-side
    assert body["farm_id"] == "farm-1" and body["plot_id"] == "plot-1"
    assert response.headers["cache-control"] == "no-store"
    assert auth.created == [{"email": "binh@example.vn", "password": PASSWORD, "full_name": "Nguyễn Văn Bình"}]
    # The password goes to Auth only -- never into the application write.
    assert PASSWORD not in repr(repo.provisions)


@pytest.mark.parametrize(("error", "code"), [
    (FarmerAlreadyMemberError(), "farmer_already_member"),
    (MembershipInactiveError(), "membership_inactive"),
    (AccountExistsError(), "account_exists"),
    (FarmCodeTakenError(), "farm_code_exists"),
])
def test_preflight_refusals_are_409_and_never_create_an_identity(error, code):
    auth = FakeAuth()
    response = client(FakeRepo(preflight_error=error), auth).post(URL, json=BODY)
    assert response.status_code == 409
    assert response.json()["detail"]["error"]["code"] == code
    assert auth.created == []


def test_account_exists_message_reveals_nothing_about_the_other_tenant():
    response = client(FakeRepo(preflight_error=AccountExistsError())).post(URL, json=BODY)
    message = response.json()["detail"]["error"]["message"]
    assert "HTX" not in message.split(".")[0] or "khác" in message
    assert ORG not in response.text


def test_non_manager_is_the_same_404_as_an_unknown_cooperative():
    auth = FakeAuth()
    response = client(FakeRepo(preflight_error=ProvisioningScopeError()), auth).post(URL, json=BODY)
    assert response.status_code == 404
    assert auth.created == []


def test_an_identity_created_concurrently_is_classified_not_duplicated():
    auth = FakeAuth(exists=True)
    response = client(FakeRepo(second_preflight_error=FarmerAlreadyMemberError()), auth).post(URL, json=BODY)
    assert response.status_code == 409
    assert response.json()["detail"]["error"]["code"] == "farmer_already_member"


def test_db_failure_deletes_the_new_identity_and_reports_failure_not_success():
    auth = FakeAuth()
    response = client(FakeRepo(provision_error=RuntimeError("db down")), auth).post(URL, json=BODY)
    assert response.status_code == 500
    assert response.json()["detail"]["error"]["code"] == "provisioning_failed"
    assert auth.deleted == ["new-user"]
    assert PASSWORD not in response.text


def test_a_conflict_discovered_inside_the_transaction_is_rolled_back_and_409():
    auth = FakeAuth()
    response = client(FakeRepo(provision_error=FarmCodeTakenError()), auth).post(URL, json=BODY)
    assert response.status_code == 409
    assert auth.deleted == ["new-user"]


def test_when_delete_fails_the_identity_is_locked_and_the_failure_is_explicit():
    auth = FakeAuth(delete_fails=True)
    response = client(FakeRepo(provision_error=RuntimeError("db down")), auth).post(URL, json=BODY)
    assert response.status_code == 500
    assert response.json()["detail"]["error"]["code"] == "provisioning_incomplete"
    assert auth.banned == ["new-user"]


def test_an_identity_created_before_a_lost_response_is_found_and_deleted():
    auth, repo_ = FakeAuth(ambiguous=True), FakeRepo(orphan="orphan-1")
    response = client(repo_, auth).post(URL, json=BODY)
    assert response.status_code == 500
    assert response.json()["detail"]["error"]["code"] == "provisioning_failed"
    assert auth.deleted == ["orphan-1"]
    # Looked up by THIS attempt's marker, the one sent to Auth -- never by email alone.
    assert repo_.orphan_queries == [{"email": "binh@example.vn", "attempt": auth.attempts[0]}]


def test_an_ambiguous_failure_with_no_identity_created_deletes_nothing():
    auth = FakeAuth(ambiguous=True)
    response = client(FakeRepo(orphan=None), auth).post(URL, json=BODY)
    assert response.json()["detail"]["error"]["code"] == "provisioning_failed"
    assert auth.deleted == [] and auth.banned == []


def test_an_ambiguous_failure_that_cannot_be_checked_is_reported_incomplete():
    response = client(FakeRepo(orphan_lookup_fails=True), FakeAuth(ambiguous=True)).post(URL, json=BODY)
    assert response.status_code == 500
    assert response.json()["detail"]["error"]["code"] == "provisioning_incomplete"


def test_the_password_is_never_logged(caplog):
    caplog.set_level(logging.DEBUG)
    client().post(URL, json=BODY)
    client(FakeRepo(provision_error=RuntimeError("x")), FakeAuth(delete_fails=True, ban_fails=True)).post(URL, json=BODY)
    assert PASSWORD not in caplog.text


@pytest.mark.parametrize("body", [
    {**BODY, "email": "not-an-email"},
    {**BODY, "full_name": "  "},
    {k: v for k, v in BODY.items() if k != "farm"},               # a plot needs a farm
    {**BODY, "role": "cooperative_manager"},                       # the role is not the client's
    {**BODY, "plot": {**BODY["plot"], "area_ha": 0}},
])
def test_invalid_bodies_are_422_before_any_identity(body):
    auth = FakeAuth()
    response = client(auth=auth).post(URL, json=body)
    assert response.status_code == 422
    assert auth.created == []


def test_generated_passwords_are_strong_and_distinct():
    from service import generate_temporary_password
    seen = {generate_temporary_password() for _ in range(200)}
    assert len(seen) == 200
    for p in seen:
        assert re.fullmatch(r"[A-Za-z2-9]{4}-[A-Za-z2-9]{4}-[A-Za-z2-9]{4}", p)
        assert any(c.isupper() for c in p) and any(c.islower() for c in p) and any(c.isdigit() for c in p)


def test_react_never_holds_a_service_role_credential():
    src = BACKEND.parent / "web-dashboard" / "src"
    def code(text: str) -> str:  # comments may explain the rule; code may not break it
        return re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)

    offenders = [
        str(p.relative_to(src)) for p in src.rglob("*.ts*")
        if re.search(r"service[_-]?role|SERVICE_ROLE|auth\.admin", code(p.read_text(encoding="utf-8")))
        and not p.name.endswith((".test.ts", ".test.tsx"))
    ]
    # And no env variable that could carry the key into the Vite bundle.
    env = (BACKEND.parent / "web-dashboard" / ".env.example")
    assert not env.exists() or "SERVICE" not in env.read_text(encoding="utf-8").upper()
    assert offenders == []


def test_lifecycle_stages():
    assert lifecycle_stage(farm_count=0, plot_count=0, season_count=0, active_season_count=0) == "no_farm"
    assert lifecycle_stage(farm_count=1, plot_count=0, season_count=0, active_season_count=0) == "no_plot"
    assert lifecycle_stage(farm_count=1, plot_count=1, season_count=0, active_season_count=0) == "no_season"
    assert lifecycle_stage(farm_count=1, plot_count=1, season_count=2, active_season_count=1) == "active_season"
    assert lifecycle_stage(farm_count=1, plot_count=1, season_count=2, active_season_count=0) == "history_only"


# ------------------------------------------------------------ real database

psycopg = pytest.importorskip("psycopg", reason="psycopg is required for the real-database tests.")
from psycopg.rows import dict_row  # noqa: E402

_DB_URL = load_settings().supabase_db_url
real_db = pytest.mark.skipif(not _DB_URL, reason="SUPABASE_DB_URL is not configured.")


def _savepoint_factory(conn):
    class _Savepoint:
        def __enter__(self):
            self._tx = conn.transaction()
            self._tx.__enter__()
            return type("Bound", (), {"cursor": lambda _self: conn.cursor(row_factory=dict_row)})()

        def __exit__(self, *exc):
            return self._tx.__exit__(*exc)

    return _Savepoint


class World:
    def __init__(self, conn):
        self.conn = conn
        self.tag = uuid.uuid4().hex[:8]
        self.coop = self._org(f"PROV-TEST-{self.tag}", "cooperative")
        self.other_coop = self._org(f"PROV-TEST-OTHER-{self.tag}", "cooperative")
        self.manager = self.identity(member_of=self.coop, role="cooperative_manager")
        self.other_manager = self.identity(member_of=self.other_coop, role="cooperative_manager")
        self.ended_manager = self.identity(member_of=self.coop, role="cooperative_manager", ended=True)
        self.farmer = self.identity(member_of=self.coop, role="farmer")
        self.enterprise = self.identity(member_of=self.coop, role="enterprise_viewer")
        self.regulator = self.identity(member_of=self.coop, role="regulator")
        self.farm = self._one(
            "insert into public.farms (cooperative_id, farm_code, farm_name) values (%s, %s, 'Prov farm') returning id::text as id",
            (self.coop, f"PROV-FARM-{self.tag}"),
        )["id"]
        conn.execute("insert into public.farm_members (farm_id, user_id, farm_role) values (%s, %s, 'owner')", (self.farm, self.farmer))
        self.viewer = self.identity(member_of=self.coop, role="farmer")
        conn.execute("insert into public.farm_members (farm_id, user_id, farm_role) values (%s, %s, 'viewer')", (self.farm, self.viewer))

    def _one(self, sql, params=()):
        return self.conn.execute(sql, params).fetchone()

    def _org(self, code, kind):
        return self._one(
            "insert into public.organizations (organization_code, name, organization_type) values (%s, %s, %s) returning id::text as id",
            (code, code, kind),
        )["id"]

    def identity(self, *, member_of=None, role=None, ended=False, email=None):
        """An Auth identity (what the Admin API creates), optionally a member."""
        user = str(uuid.uuid4())
        self.conn.execute(
            # created_at as GoTrue sets it (the column has no default).
            "insert into auth.users (id, email, aud, role, raw_user_meta_data, created_at) values (%s, %s, 'authenticated', 'authenticated', '{}'::jsonb, now())",
            (user, email or f"prov-{user[:8]}@agricarbon-test.invalid"),
        )
        if member_of:
            self.conn.execute(
                "insert into public.organization_memberships (organization_id, user_id, role, joined_at, ended_at) "
                "values (%s, %s, %s, now() - interval '2 days', case when %s then now() - interval '1 day' end)",
                (member_of, user, role, ended),
            )
        return user

    def email_of(self, user):
        return self._one("select email::text as e from auth.users where id = %s", (user,))["e"]


@pytest.fixture
def world():
    if not _DB_URL:
        pytest.skip("SUPABASE_DB_URL is not configured.")
    with psycopg.connect(_DB_URL, autocommit=False, row_factory=dict_row) as conn:
        try:
            yield World(conn)
        finally:
            conn.rollback()


def repo(world):
    return PostgresProvisioningRepository(settings=None, connect=_savepoint_factory(world.conn))


FARM = lambda tag: {"farm_code": f"NEW-{tag}", "farm_name": "Hộ mới", "province_name": None, "district_name": None, "commune_name": None}  # noqa: E731
PLOT = {"plot_code": "T-1", "name": "Thửa 1", "area_ha": 1.2}


@real_db
def test_manager_provisions_profile_membership_farm_and_plot_in_one_go(world):
    new = world.identity(email=f"new-{world.tag}@agricarbon-test.invalid")
    repo(world).preflight(organization_id=world.coop, actor_id=world.manager, email=world.email_of(new).upper() + "x", farm_code=FARM(world.tag)["farm_code"])
    out = repo(world).provision(organization_id=world.coop, actor_id=world.manager, user_id=new, full_name="Nông dân Mới",
                                phone="0900000000", farm=FARM(world.tag), plot=PLOT)
    c = world.conn
    assert c.execute("select full_name, phone from public.profiles where id = %s", (new,)).fetchone() == {"full_name": "Nông dân Mới", "phone": "0900000000"}
    assert c.execute("select role::text as r from public.organization_memberships where user_id = %s and organization_id = %s",
                     (new, world.coop)).fetchone()["r"] == "farmer"
    assert c.execute("select farm_role::text as r from public.farm_members where user_id = %s and farm_id = %s",
                     (new, out["farm_id"])).fetchone()["r"] == "owner"
    assert c.execute("select farm_id::text as f from public.plots where id = %s", (out["plot_id"],)).fetchone()["f"] == out["farm_id"]
    listed = next(f for f in repo(world).list_farmers(organization_id=world.coop, actor_id=world.manager) if f["user_id"] == new)
    assert listed["stage"] == "no_season" and listed["plot_count"] == 1 and listed["idle_plot_id"] == out["plot_id"]
    assert listed["account_status"] == "active" and listed["email"] == world.email_of(new)


@real_db
def test_account_without_farm_is_stage_no_farm(world):
    new = world.identity()
    repo(world).provision(organization_id=world.coop, actor_id=world.manager, user_id=new, full_name="A",
                          phone=None, farm=None, plot=None)
    listed = next(f for f in repo(world).list_farmers(organization_id=world.coop, actor_id=world.manager) if f["user_id"] == new)
    assert listed["stage"] == "no_farm" and listed["farms"] == []


@real_db
@pytest.mark.parametrize("who", ["other_manager", "ended_manager", "farmer", "viewer", "enterprise", "regulator"])
def test_only_an_active_manager_of_this_cooperative_may_provision_or_list(world, who):
    actor = getattr(world, who)
    new = world.identity()
    with pytest.raises(ProvisioningScopeError):
        repo(world).preflight(organization_id=world.coop, actor_id=actor, email="x@y.invalid", farm_code=None)
    with pytest.raises(ProvisioningScopeError):
        repo(world).provision(organization_id=world.coop, actor_id=actor, user_id=new, full_name="A", phone=None, farm=None, plot=None)
    with pytest.raises(ProvisioningScopeError):
        repo(world).list_farmers(organization_id=world.coop, actor_id=actor)
    assert world.conn.execute("select count(*) as n from public.organization_memberships where user_id = %s", (new,)).fetchone()["n"] == 0


@real_db
def test_duplicate_emails_are_classified(world):
    r = repo(world)
    with pytest.raises(FarmerAlreadyMemberError):  # same cooperative, active (any case)
        r.preflight(organization_id=world.coop, actor_id=world.manager, email=world.email_of(world.farmer).upper(), farm_code=None)
    former = world.identity(member_of=world.coop, role="farmer", ended=True)
    with pytest.raises(MembershipInactiveError):
        r.preflight(organization_id=world.coop, actor_id=world.manager, email=world.email_of(former), farm_code=None)
    elsewhere = world.identity(member_of=world.other_coop, role="farmer")
    with pytest.raises(AccountExistsError):
        r.preflight(organization_id=world.coop, actor_id=world.manager, email=world.email_of(elsewhere), farm_code=None)
    loose = world.identity()
    with pytest.raises(AccountExistsError):
        r.preflight(organization_id=world.coop, actor_id=world.manager, email=world.email_of(loose), farm_code=None)


@real_db
def test_taken_farm_code_is_refused_before_and_inside_the_transaction(world):
    with pytest.raises(FarmCodeTakenError):
        repo(world).preflight(organization_id=world.coop, actor_id=world.manager, email="free@x.invalid", farm_code=f"PROV-FARM-{world.tag}")
    new = world.identity()
    with pytest.raises(FarmCodeTakenError):
        repo(world).provision(organization_id=world.coop, actor_id=world.manager, user_id=new, full_name="A", phone=None,
                              farm={**FARM(world.tag), "farm_code": f"PROV-FARM-{world.tag}"}, plot=None)
    # Nothing of the attempt survived: no membership, no profile change.
    assert world.conn.execute("select count(*) as n from public.organization_memberships where user_id = %s", (new,)).fetchone()["n"] == 0


@real_db
def test_a_failure_after_the_membership_insert_rolls_everything_back(world):
    new = world.identity()

    def reject(out):
        raise RuntimeError("response rejected")

    with pytest.raises(RuntimeError):
        repo(world).provision(organization_id=world.coop, actor_id=world.manager, user_id=new, full_name="A", phone=None,
                              farm=FARM(world.tag), plot=PLOT, prepare=reject)
    c = world.conn
    assert c.execute("select count(*) as n from public.organization_memberships where user_id = %s", (new,)).fetchone()["n"] == 0
    assert c.execute("select count(*) as n from public.farm_members where user_id = %s", (new,)).fetchone()["n"] == 0
    assert c.execute("select count(*) as n from public.farms where farm_code = %s", (FARM(world.tag)["farm_code"],)).fetchone()["n"] == 0


@real_db
def test_plots_are_the_managers_to_record_not_the_farm_owners(world):
    out = repo(world).create_plot(farm_id=world.farm, actor_id=world.manager, plot=PLOT)
    assert out["farm_id"] == world.farm
    with pytest.raises(PlotCodeTakenError):
        repo(world).create_plot(farm_id=world.farm, actor_id=world.manager, plot=PLOT)
    for actor in (world.farmer, world.viewer, world.other_manager):
        with pytest.raises(ProvisioningScopeError):
            repo(world).create_plot(farm_id=world.farm, actor_id=actor, plot={**PLOT, "plot_code": "T-2"})
    with pytest.raises(ProvisioningScopeError):
        repo(world).create_plot(farm_id=str(uuid.uuid4()), actor_id=world.manager, plot=PLOT)


@real_db
def test_a_farm_for_an_existing_farmer_only_inside_the_cooperative(world):
    out = repo(world).create_farm(organization_id=world.coop, actor_id=world.manager, owner_user_id=world.farmer, farm=FARM(world.tag))
    assert out["farm_code"] == FARM(world.tag)["farm_code"]
    outsider = world.identity(member_of=world.other_coop, role="farmer")
    with pytest.raises(ProvisioningScopeError):
        repo(world).create_farm(organization_id=world.coop, actor_id=world.manager, owner_user_id=outsider, farm={**FARM(world.tag), "farm_code": "X2"})
    with pytest.raises(ProvisioningScopeError):
        repo(world).create_farm(organization_id=world.coop, actor_id=world.other_manager, owner_user_id=world.farmer, farm={**FARM(world.tag), "farm_code": "X3"})


def test_response_model_requires_the_password_field():
    with pytest.raises(Exception):
        schemas.FarmerProvisionResponse.model_validate({"user_id": "u", "email": "e", "full_name": "f", "organization_id": "o"})


@real_db
def test_orphan_lookup_finds_only_this_attempts_identity(world):
    mine, theirs = str(uuid.uuid4()), str(uuid.uuid4())
    email = f"orphan-{world.tag}@agricarbon-test.invalid"
    user = world.identity(email=email)
    world.conn.execute("update auth.users set raw_user_meta_data = jsonb_build_object('provisioning_attempt', %s::text) where id = %s", (mine, user))
    assert repo(world).find_orphan_identity(email=email.upper(), attempt=mine) == user
    # A concurrent request for the same email carries another marker: untouched.
    assert repo(world).find_orphan_identity(email=email, attempt=theirs) is None
    # Once it holds a membership it is nobody's orphan.
    world.conn.execute("insert into public.organization_memberships (organization_id, user_id, role) values (%s, %s, 'farmer')", (world.coop, user))
    assert repo(world).find_orphan_identity(email=email, attempt=mine) is None

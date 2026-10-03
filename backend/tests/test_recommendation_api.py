"""M05 service/API-level tests: auth/scope, idempotent generation, lifecycle.

Rule-logic correctness (determinism, real-engine reuse, insufficient-data
suppression) is covered in test_recommendation_engine.py; this file covers
the service/route wiring on top, following the same Fake-repository pattern
as test_activity_writes.py.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
import sys
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import api  # noqa: E402
from carbon import MissingActivityDataError  # noqa: E402
from infrastructure.read_repo import ReadNotFoundError  # noqa: E402
from infrastructure.recommendation_repo import RecommendationNotFoundError  # noqa: E402
from recommendation import GeneratedRecommendation  # noqa: E402
from infrastructure.config import Settings  # noqa: E402
from infrastructure.crop_write_authz import CropWriteDeniedError  # noqa: E402
from service import RecommendationAccessError, RecommendationService  # noqa: E402

DUMMY_SETTINGS = Settings(
    supabase_url=None, supabase_service_role_key=None, supabase_publishable_key=None,
    ef_config_path=Path("unused"), require_factor_set_in_db=False, cors_origins=[],
)


ACTOR, SEASON = "farmer-a", "season-a"


class FakeRead:
    def __init__(self, *, role: str = "farmer", visible: bool = True, metrics: dict | None = None, actor: str = ACTOR):
        self.role, self.visible, self.actor = role, visible, actor
        self.metrics_result = metrics or {"yield_kg": None, "data_completeness": {"water": False, "fertilizer": False, "cost": False, "carbon": False}}

    def me(self):
        return {"user_id": self.actor, "roles": [self.role]}

    def season(self, season_id):
        if not self.visible or season_id != SEASON:
            raise ReadNotFoundError("crop_seasons")
        return {"id": SEASON, "status": "active"}

    def metrics(self, season_id):
        self.season(season_id)
        return self.metrics_result


class FakeCarbonService:
    """No optimization rule fires: raising the same error type the engine
    itself raises for "no baseline calculable" means evaluate_awd_rule()
    correctly suppresses it — these tests only exercise the data_task rule
    and the generation/lifecycle wiring around it, not carbon math."""

    def calculate(self, crop_season_id, scenario="as_recorded", *, persist=True):
        raise MissingActivityDataError("no fixture Carbon data for this test")


@dataclass
class FakeRecommendationRepository:
    rows: dict[str, dict] = field(default_factory=dict)
    by_key: dict[tuple[str, str], str] = field(default_factory=dict)
    # Who `private.user_can_write_crop` says may write SEASON. Readers outside
    # it -- a farm viewer, a former owner, a data-grant reader -- may not.
    writers: set[str] = field(default_factory=lambda: {ACTOR})
    _next: int = 1

    def assert_can_write(self, *, crop_season_id, actor_id):
        if actor_id not in self.writers:
            raise CropWriteDeniedError()

    def upsert(self, *, crop_season_id, rec: GeneratedRecommendation):
        key = (crop_season_id, rec.rule_code)
        if key in self.by_key:
            row_id = self.by_key[key]
            existing = self.rows[row_id]
            existing.update(
                rule_version=rec.rule_version, type=rec.type, title=rec.title, reason=rec.reason,
                impact_status=rec.impact_status, co2e_total_kg_delta=rec.co2e_total_kg_delta,
                input_hash=rec.input_hash,
            )
            return deepcopy(existing)
        row_id = f"rec-{self._next}"; self._next += 1
        row = {
            "id": row_id, "crop_season_id": crop_season_id, "rule_code": rec.rule_code,
            "rule_version": rec.rule_version, "engine_version": rec.engine_version, "type": rec.type,
            "status": "generated", "title": rec.title, "reason": rec.reason, "compared_to": rec.compared_to,
            "co2e_total_kg_before": rec.co2e_total_kg_before, "co2e_total_kg_after": rec.co2e_total_kg_after,
            "co2e_total_kg_delta": rec.co2e_total_kg_delta, "co2e_percent_delta": rec.co2e_percent_delta,
            "impact_status": rec.impact_status, "impact_unavailable_reason": rec.impact_unavailable_reason,
            "input_hash": rec.input_hash, "generated_at": "2026-09-11T00:00:00Z",
            "accepted_at": None, "dismissed_at": None,
        }
        self.rows[row_id] = row
        self.by_key[key] = row_id
        return deepcopy(row)

    def save_generated(self, *, crop_season_id, recs, actor_id, prepare=None):
        self.assert_can_write(crop_season_id=crop_season_id, actor_id=actor_id)
        rows = [self.upsert(crop_season_id=crop_season_id, rec=rec) for rec in recs]
        self.prune_missing(crop_season_id=crop_season_id, keep_rule_codes=[rec.rule_code for rec in recs])
        return prepare(rows) if prepare is not None else rows

    def prune_missing(self, *, crop_season_id, keep_rule_codes):
        keep = set(keep_rule_codes)
        stale = [
            row_id for row_id, row in self.rows.items()
            if row["crop_season_id"] == crop_season_id and row["status"] == "generated" and row["rule_code"] not in keep
        ]
        for row_id in stale:
            row = self.rows.pop(row_id)
            self.by_key.pop((row["crop_season_id"], row["rule_code"]), None)

    def get(self, recommendation_id):
        if recommendation_id not in self.rows:
            raise RecommendationNotFoundError()
        return deepcopy(self.rows[recommendation_id])

    def set_status(self, recommendation_id, status, *, actor_id, prepare=None):
        if recommendation_id not in self.rows:
            raise RecommendationNotFoundError()
        self.assert_can_write(crop_season_id=self.rows[recommendation_id]["crop_season_id"], actor_id=actor_id)
        column = "accepted_at" if status == "accepted" else "dismissed_at"
        self.rows[recommendation_id]["status"] = status
        self.rows[recommendation_id][column] = "2026-09-11T01:00:00Z"
        row = deepcopy(self.rows[recommendation_id])
        return prepare(row) if prepare is not None else row


def service(repo: FakeRecommendationRepository | None = None) -> RecommendationService:
    return RecommendationService(FakeCarbonService(), repo or FakeRecommendationRepository())


def missing_data_metrics() -> dict:
    return {"yield_kg": None, "data_completeness": {"water": False, "fertilizer": False, "cost": False, "carbon": False}}


# ===========================================================================
# Service-level: scope, idempotency, lifecycle
# ===========================================================================


def test_farmer_can_generate_data_task_recommendations_for_own_season():
    read = FakeRead(metrics=missing_data_metrics())
    rows = service().generate(read_repository=read, crop_season_id=SEASON)

    assert rows, "expected at least the yield data_task row"
    assert all(row["type"] == "data_task" for row in rows)


def test_generation_never_fabricates_a_quantified_impact_when_data_is_missing():
    read = FakeRead(metrics=missing_data_metrics())
    rows = service().generate(read_repository=read, crop_season_id=SEASON)

    for row in rows:
        assert row["impact_status"] == "unavailable"
        assert row["co2e_total_kg_delta"] is None


@pytest.mark.parametrize("read", [FakeRead(role="cooperative_manager"), FakeRead(role="enterprise_viewer"), FakeRead(visible=False)])
def test_non_farmer_or_cross_scope_cannot_generate(read):
    with pytest.raises(RecommendationAccessError):
        service().generate(read_repository=read, crop_season_id=SEASON)


@pytest.mark.parametrize("status", ["accepted", "dismissed"])
def test_a_reader_without_write_authority_cannot_generate_accept_or_dismiss(status):
    """Viewer is read-only (product decision 2026-10-03): a farm viewer, a former
    owner (historical read) or a data-grant reader READS the season through RLS
    and may even hold a farmer role, but `user_can_write_crop` says no -- every
    recommendation write is refused like an unknown id, and nothing changes."""
    repo = FakeRecommendationRepository()
    write = service(repo)
    [row] = write.generate(read_repository=FakeRead(metrics=missing_data_metrics()), crop_season_id=SEASON)[:1]
    before = deepcopy(repo.rows)

    reader = FakeRead(metrics=missing_data_metrics(), actor="viewer-or-former-owner")
    with pytest.raises(RecommendationAccessError):
        write.generate(read_repository=reader, crop_season_id=SEASON)
    with pytest.raises(RecommendationAccessError):
        write.set_status(read_repository=reader, recommendation_id=row["id"], status=status)
    assert repo.rows == before


def test_generation_is_refused_before_any_carbon_work_for_a_reader():
    class CountingCarbon(FakeCarbonService):
        calls = 0

        def calculate(self, *a, **k):
            CountingCarbon.calls += 1
            return super().calculate(*a, **k)

    write = RecommendationService(CountingCarbon(), FakeRecommendationRepository())
    with pytest.raises(RecommendationAccessError):
        write.generate(read_repository=FakeRead(actor="viewer"), crop_season_id=SEASON)
    assert CountingCarbon.calls == 0


def test_regenerating_is_idempotent_not_duplicating_rows():
    repo = FakeRecommendationRepository()
    write = service(repo)
    read = FakeRead(metrics=missing_data_metrics())

    first = write.generate(read_repository=read, crop_season_id=SEASON)
    second = write.generate(read_repository=read, crop_season_id=SEASON)

    assert {row["id"] for row in first} == {row["id"] for row in second}
    assert len(repo.rows) == len(first)


def test_regenerating_after_data_completed_prunes_the_stale_data_task_row():
    repo = FakeRecommendationRepository()
    write = service(repo)
    incomplete = FakeRead(metrics=missing_data_metrics())
    write.generate(read_repository=incomplete, crop_season_id=SEASON)
    assert any(row["rule_code"].endswith(".yield") for row in repo.rows.values())

    complete = FakeRead(metrics={"yield_kg": 3100.0, "data_completeness": {"water": True, "fertilizer": True, "cost": True, "carbon": True}})
    rows = write.generate(read_repository=complete, crop_season_id=SEASON)

    assert rows == []
    assert repo.rows == {}


def test_accept_and_dismiss_set_status_and_timestamp():
    repo = FakeRecommendationRepository()
    write = service(repo)
    read = FakeRead(metrics=missing_data_metrics())
    [row] = write.generate(read_repository=read, crop_season_id=SEASON)[:1]

    accepted = write.set_status(read_repository=read, recommendation_id=row["id"], status="accepted")
    assert accepted["status"] == "accepted"
    assert accepted["accepted_at"] is not None

    dismissed = write.set_status(read_repository=read, recommendation_id=row["id"], status="dismissed")
    assert dismissed["status"] == "dismissed"
    assert dismissed["dismissed_at"] is not None


def test_accepted_row_survives_regeneration_untouched_by_prune():
    repo = FakeRecommendationRepository()
    write = service(repo)
    read = FakeRead(metrics=missing_data_metrics())
    [row] = write.generate(read_repository=read, crop_season_id=SEASON)[:1]
    write.set_status(read_repository=read, recommendation_id=row["id"], status="accepted")

    complete = FakeRead(metrics={"yield_kg": 3100.0, "data_completeness": {"water": True, "fertilizer": True, "cost": True, "carbon": True}})
    write.generate(read_repository=complete, crop_season_id=SEASON)

    # The accepted row is a farmer decision — pruning only ever removes
    # still-'generated' rows, never an accepted/dismissed one.
    assert repo.rows[row["id"]]["status"] == "accepted"


def test_set_status_cross_scope_normalizes_to_404():
    repo = FakeRecommendationRepository()
    write = service(repo)
    owner = FakeRead(metrics=missing_data_metrics())
    [row] = write.generate(read_repository=owner, crop_season_id=SEASON)[:1]

    other_farmer = FakeRead(visible=False)
    with pytest.raises(RecommendationAccessError):
        write.set_status(read_repository=other_farmer, recommendation_id=row["id"], status="accepted")


def test_set_status_unknown_id_normalizes_to_404():
    read = FakeRead(metrics=missing_data_metrics())
    with pytest.raises(RecommendationAccessError):
        service().set_status(read_repository=read, recommendation_id="does-not-exist", status="accepted")


# ===========================================================================
# Route-level: auth envelope
# ===========================================================================


def write_client(read=None, rec_service=None):
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api._read_repo] = lambda: read or FakeRead(metrics=missing_data_metrics())
    app.dependency_overrides[api._recommendation_service] = lambda: rec_service or service()
    return TestClient(app)


def test_generate_route_requires_bearer_authentication():
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[api._recommendation_service] = lambda: service()
    response = TestClient(app).post(f"/v1/crop-seasons/{SEASON}/recommendations/generate")
    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "unauthenticated"


def test_generate_route_denies_non_farmer_with_normalized_404():
    client = write_client(read=FakeRead(role="cooperative_manager"))
    response = client.post(f"/v1/crop-seasons/{SEASON}/recommendations/generate", headers={"Authorization": "Bearer t"})
    assert response.status_code == 404
    assert response.json()["detail"]["error"]["code"] == "not_found"


def test_generate_then_list_then_patch_status_route():
    repo = FakeRecommendationRepository()
    rec_service = service(repo)
    client = write_client(rec_service=rec_service)

    generated = client.post(f"/v1/crop-seasons/{SEASON}/recommendations/generate", headers={"Authorization": "Bearer t"})
    assert generated.status_code == 200
    items = generated.json()["items"]
    assert items

    recommendation_id = items[0]["id"]
    patched = client.patch(f"/v1/recommendations/{recommendation_id}", json={"status": "accepted"}, headers={"Authorization": "Bearer t"})
    assert patched.status_code == 200
    assert patched.json()["status"] == "accepted"


def test_patch_status_rejects_unknown_status_value():
    client = write_client()
    response = client.patch("/v1/recommendations/rec-1", json={"status": "not_a_real_status"}, headers={"Authorization": "Bearer t"})
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Persistence shape: one generation run is one transaction
# ---------------------------------------------------------------------------


class _Cursor:
    def __init__(self, log: list[str]):
        self._log = log

    def __enter__(self): return self
    def __exit__(self, *_exc): return False

    def execute(self, sql, params=None):
        if "set_config" in sql:
            return
        self._authz = "user_can_write_crop" in sql
        self._log.append("authz" if self._authz else "insert" if "insert into" in sql else "delete")

    def fetchone(self):
        return {"allowed": True} if self._authz else {"id": uuid.uuid4(), "crop_season_id": uuid.uuid4()}


class _Connection:
    def __init__(self, log: list[str]):
        self._log = log
        log.append("connect")

    def __enter__(self): return self
    def __exit__(self, *_exc): return False
    def cursor(self): return _Cursor(self._log)


def test_one_generation_run_opens_one_connection_for_every_rule():
    """A fresh hosted-Postgres connection costs ~740ms, so a run that opened
    one per rule made generation scale with the number of rules that fired.
    Persisting a run must take exactly one connection — which also makes the
    upserts and the prune atomic."""
    from infrastructure.recommendation_repo import PostgresRecommendationRepository

    log: list[str] = []
    repo = PostgresRecommendationRepository(DUMMY_SETTINGS, connect=lambda: _Connection(log))
    recs = [
        GeneratedRecommendation(
            rule_code=f"rule.{i}", rule_version="1", type="data_task", title="t", reason="r",
            compared_to=None, impact_status="unavailable", impact_unavailable_reason=None,
            co2e_total_kg_before=None, co2e_total_kg_after=None, co2e_total_kg_delta=None,
            co2e_percent_delta=None,
        )
        for i in range(3)
    ]

    rows = repo.save_generated(crop_season_id=str(uuid.uuid4()), recs=recs, actor_id="actor")

    assert len(rows) == 3
    assert log.count("connect") == 1
    # Write authority is decided inside the same transaction, before any row.
    assert log == ["connect", "authz", "insert", "insert", "insert", "delete"]

"""Regression for a real bug the M05 hosted E2E found: psycopg returns
`uuid` columns as Python `UUID` objects, but `schemas.RecommendationResponse`
declares `id`/`crop_season_id` as `str` — FastAPI's response serialization
rejected the raw UUID with a 500 (`ResponseValidationError`). Unit tests with
plain-string fakes never exercised this because nothing in this suite
returns a real `uuid.UUID` until this file.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from infrastructure.recommendation_repo import PostgresRecommendationRepository  # noqa: E402


class _FakeCursor:
    def __init__(self, row: dict):
        self._row = row
        self._authz = False

    def execute(self, sql, *args, **kwargs):
        # `private.user_can_write_crop` (crop_write_authz) answers for itself.
        self._authz = "user_can_write_crop" in sql

    def fetchone(self):
        return {"allowed": True} if self._authz else dict(self._row)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeConn:
    def __init__(self, row: dict):
        self._row = row

    def cursor(self):
        return _FakeCursor(self._row)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _row_with_uuid_columns() -> dict:
    return {
        "id": uuid.UUID("a345d473-d768-4e3f-be4d-4c5a835bf88d"),
        "crop_season_id": uuid.UUID("2e63e128-f53d-4f70-9bb4-62b9efc048e3"),
        "status": "generated",
    }


def _repo(row: dict) -> PostgresRecommendationRepository:
    return PostgresRecommendationRepository(settings=None, connect=lambda: _FakeConn(row))


def test_get_normalizes_uuid_columns_to_plain_strings():
    row = _repo(_row_with_uuid_columns()).get("a345d473-d768-4e3f-be4d-4c5a835bf88d")
    assert row["id"] == "a345d473-d768-4e3f-be4d-4c5a835bf88d"
    assert isinstance(row["id"], str)
    assert row["crop_season_id"] == "2e63e128-f53d-4f70-9bb4-62b9efc048e3"
    assert isinstance(row["crop_season_id"], str)


def test_set_status_normalizes_uuid_columns_to_plain_strings():
    row = _repo(_row_with_uuid_columns()).set_status("a345d473-d768-4e3f-be4d-4c5a835bf88d", "accepted", actor_id="actor")
    assert isinstance(row["id"], str)
    assert isinstance(row["crop_season_id"], str)

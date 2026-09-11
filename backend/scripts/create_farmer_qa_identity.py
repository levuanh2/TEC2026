"""Create one scoped Farmer QA identity for the existing demo tenant.

This intentionally does not seed/reseed domain data, reset any existing user,
or alter RLS. It only creates a new Auth user then grants that user the farmer
membership and one existing demo farm supplied by stable demo codes.

Required local-only environment variables:
  QA_FARMER_EMAIL
  QA_FARMER_PASSWORD
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from infrastructure.config import load_settings  # noqa: E402
from supabase import create_client  # noqa: E402

ORG_CODE = "DEMO-AGRICARBON-2026"
FARM_CODE = "DEMO-FARM-01"


def one(client, table: str, **filters: str) -> dict:
    query = client.table(table).select("*")
    for key, value in filters.items():
        query = query.eq(key, value)
    rows = query.execute().data or []
    if len(rows) != 1:
        raise RuntimeError(f"Expected exactly one {table} row for the configured QA scope.")
    return rows[0]


def main() -> int:
    email = os.environ.get("QA_FARMER_EMAIL")
    password = os.environ.get("QA_FARMER_PASSWORD")
    if not email or not password:
        raise RuntimeError("QA_FARMER_EMAIL and QA_FARMER_PASSWORD are required and must remain local only.")

    settings = load_settings()
    url, service_key = settings.require_supabase()
    admin = create_client(url, service_key)
    org = one(admin, "organizations", organization_code=ORG_CODE)
    farm = one(admin, "farms", cooperative_id=org["id"], farm_code=FARM_CODE)

    users = admin.auth.admin.list_users()
    if any(user.email == email for user in users):
        raise RuntimeError("QA Farmer identity already exists; refusing to reset its password or modify its scope.")

    user = admin.auth.admin.create_user({"email": email, "password": password, "email_confirm": True}).user
    if user is None:
        raise RuntimeError("Supabase Auth did not return the new QA user.")
    admin.table("organization_memberships").insert({
        "organization_id": org["id"], "user_id": user.id, "role": "farmer",
    }).execute()
    admin.table("farm_members").insert({
        "farm_id": farm["id"], "user_id": user.id, "farm_role": "owner",
    }).execute()

    # Do not print email, password, token, or UUIDs. The caller retains these in
    # its process environment solely for the subsequent real browser test.
    print("QA Farmer identity created with one-farm scope.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

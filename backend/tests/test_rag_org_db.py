"""PROTOTYPE organization assistant over the REAL caller-scoped reads on a LOCAL stack (real JWTs):
cross-organization leakage and revocation. Reuses the retrieval fixture (local-only guard)."""
from __future__ import annotations

import pytest

from rag_org import OrgQuestionService
from recommendation.rag import RagAccessDenied
from tests.test_rag_retrieval_db import _DB_URL, _reader, env, pytestmark  # noqa: F401


def _ask(env, who, org_key, intent="org_summary"):  # noqa: F811
    return OrgQuestionService().answer(reader=_reader(env, who), organization_id=str(env[org_key]), intent=intent)


def test_a_manager_reads_their_own_htx(env):  # noqa: F811
    body = _ask(env, "manager", "org_a", "org_data_gaps")
    assert body["organization_id"] == str(env["org_a"]) and body["page"]["total"] >= 1


@pytest.mark.parametrize("who, org", [("manager", "org_b"), ("outsider", "org_b"), ("member", "org_a"),
                                      ("viewer", "org_a")])
def test_no_cross_organization_or_role_escalation(env, who, org):  # noqa: F811
    with pytest.raises(RagAccessDenied):
        _ask(env, who, org)


def test_an_ended_manager_membership_is_revoked_at_once(env):  # noqa: F811
    import psycopg
    assert _ask(env, "manager", "org_a")["status"] == "generated"
    with psycopg.connect(_DB_URL) as conn:
        conn.execute("update public.organization_memberships set ended_at = now() - interval '1 minute'"
                     " where user_id = %s and organization_id = %s", (env["users"]["manager"], env["org_a"]))
        conn.commit()
    try:
        with pytest.raises(RagAccessDenied):
            _ask(env, "manager", "org_a")
    finally:
        with psycopg.connect(_DB_URL) as conn:
            conn.execute("update public.organization_memberships set ended_at = null"
                         " where user_id = %s and organization_id = %s", (env["users"]["manager"], env["org_a"]))
            conn.commit()

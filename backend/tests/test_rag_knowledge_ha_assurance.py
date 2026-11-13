"""RAG V1.5 hardening H-a (migration 20261113090000): demo assurance is separated at the database, at
RLS and at retrieval, and demo approval runs only on a database that passes the isolation gate.

Owner decision D-H3a (2026-11-12): demo-approved content runs ONLY on an isolated local or dedicated
test database, never on the shared hosted project.

Every text is a SYNTHETIC TEST FIXTURE; identities are synthetic fixtures on reserved test domains.
One transaction per test, rolled back. Skipped without SUPABASE_DB_URL. dev3-01 stays OPEN.
"""

from __future__ import annotations

import uuid

import pytest

from tests.test_rag_knowledge_m2_approval import (DEMO_DOC, DEMO_SRC, ISOLATED, _demo, as_role, m2, owner,  # noqa: F401
                                                  recommended)
from tests.test_rag_knowledge_status_events import HA_ROLLBACK, ROOT, _without_tx_control, unwind_ha
from tests.test_rag_knowledge_storage import (CHECK_VIOLATION, PERMISSION_DENIED, _DB_URL, pytestmark,  # noqa: E402
                                              psycopg, tx)

__all__ = ["pytestmark", "tx", "m2"]

HA = ROOT / "supabase/migrations/20261113090000_knowledge_m2_hardening_assurance.sql"
DEMO_RPC = "select * from public.match_knowledge_chunks_lexical_demo(%s, %s, %s)"


def isolated(tx) -> bool:
    tx.cur.execute("select private.knowledge_deployment_isolated()")
    return tx.cur.fetchone()[0]


def assurance(tx, kind, key):
    table, column = ("knowledge_sources", "source_id") if kind == "source" else ("knowledge_documents", "id")
    tx.cur.execute(f"select approval_assurance from public.{table} where {column} = %s", (key,))
    return tx.cur.fetchone()[0]


def demo_doc(tx, content, *, src=None, demo_source=False):
    """A demo-approved version with one chunk (switch on, database declared isolated)."""
    _demo(tx, True)
    if demo_source:
        src = tx.source(status="review_required")
        assert as_role(tx, "service_role", DEMO_SRC, (src, tx.approver, "demo source"))[0] == "ok"
    src = src or tx.source()
    doc = tx.document(src, status="review_required")
    chunk = tx.chunk(doc, content)
    assert as_role(tx, "service_role", DEMO_DOC, (doc, tx.approver, "demo for a synthetic meeting"))[0] == "ok"
    return src, doc, chunk


def verified_doc(tx, m2, content):
    doc, review = recommended(tx, m2, content=content)
    m2.decide(review, tx.approver)
    tx.cur.execute("select chunk_id from public.knowledge_chunks where document_pk = %s", (doc,))
    return doc, tx.cur.fetchone()[0]


def demo_rpc(tx, user, season, query):
    return tx.as_user(user, DEMO_RPC, (season, query, 50))


def forge_marker_update(tx, sql, params=()):
    """What an owner session could do by hand (the documented trust boundary): set the M2 write
    marker and update the declaration row directly."""
    tx.cur.execute("select private.knowledge_m2_set_marker('knowledge_deployment')")
    tx.cur.execute(sql, params)
    tx.cur.execute("select private.knowledge_m2_set_marker(null)")


# ================================================================== the gate

def test_a_fresh_database_is_shared_and_demo_approval_is_refused_even_with_the_switch_on(tx):
    tx.cur.execute("select class, bound_system_identifier, bound_database from private.knowledge_deployment")
    assert tx.cur.fetchall() == [("shared", None, None)]
    assert isolated(tx) is False
    tx.cur.execute("update private.knowledge_demo_mode set enabled = true, environment_label = 'staging',"
                   " note = 'TEST FIXTURE: a staging label is not a boundary'")
    doc = tx.document(tx.source(), status="review_required")
    tx.chunk(doc, "awd shared demo")
    status, sqlstate = as_role(tx, "service_role", DEMO_DOC, (doc, tx.approver, "demo"))
    assert (status, sqlstate) == ("err", PERMISSION_DENIED)
    assert tx.status_of("document", doc) == "review_required"


def test_only_the_owner_declares_and_the_row_cannot_be_written_directly(tx, m2):
    for role in ("service_role", "authenticated", "anon"):
        tx.cur.execute("select has_table_privilege(%s, 'private.knowledge_deployment', 'select, update'),"
                       " has_function_privilege(%s, 'private.knowledge_declare_isolated_test(text)', 'execute'),"
                       " has_function_privilege(%s, 'private.knowledge_declare_shared()', 'execute')", (role,) * 3)
        assert tx.cur.fetchone() == (False, False, False), role
    for role, expected in (("authenticated", True), ("service_role", True), ("anon", False)):
        tx.cur.execute("select has_function_privilege(%s, 'private.knowledge_deployment_isolated()', 'execute')", (role,))
        assert tx.cur.fetchone()[0] is expected, role
    for statement in ("update private.knowledge_deployment set class = 'isolated_test'",
                      "delete from private.knowledge_deployment",
                      "insert into private.knowledge_deployment (singleton) values (true)",
                      "truncate private.knowledge_deployment"):
        assert owner(tx, statement) == ("err", PERMISSION_DENIED), statement
    assert owner(tx, "select private.knowledge_declare_isolated_test('too short')")[0] == "err"
    assert isolated(tx) is False


def test_a_declaration_is_bound_to_this_cluster_and_database(tx):
    tx.cur.execute(ISOLATED)
    tx.cur.execute("select d.class, d.bound_system_identifier = c.system_identifier, d.bound_database = current_database(),"
                   " d.declared_by_session_user = session_user, d.declared_at is not null"
                   " from private.knowledge_deployment d, pg_control_system() c")
    assert tx.cur.fetchone() == ("isolated_test", True, True, True, True)
    assert isolated(tx) is True
    tx.cur.execute("savepoint copy")
    # a copy restored on another cluster carries a binding that is not its own
    forge_marker_update(tx, "update private.knowledge_deployment set bound_system_identifier = bound_system_identifier + 1")
    assert isolated(tx) is False
    tx.cur.execute("rollback to savepoint copy")
    forge_marker_update(tx, "update private.knowledge_deployment set bound_database = 'another_database'")
    assert isolated(tx) is False
    tx.cur.execute("rollback to savepoint copy")
    assert isolated(tx) is True
    tx.cur.execute("select private.knowledge_declare_shared()")
    tx.cur.execute("select class, bound_system_identifier, attestation from private.knowledge_deployment")
    assert tx.cur.fetchone() == ("shared", None, None) and isolated(tx) is False


@pytest.mark.parametrize("email", ["someone@fixture-not-reserved.vn", None, "x@invalid.example.co"])
def test_a_database_with_an_account_that_looks_real_is_never_isolated(tx, email):
    tx.cur.execute(ISOLATED)
    assert isolated(tx) is True
    tx.cur.execute("insert into auth.users (id, email, aud, role, created_at) values (%s, %s, 'authenticated',"
                   " 'authenticated', now())", (uuid.uuid4(), email))
    assert isolated(tx) is False                                       # a declaration does not survive it
    tx.cur.execute("savepoint d")
    with pytest.raises(psycopg.errors.InsufficientPrivilege, match="not on a reserved test domain"):
        tx.cur.execute(ISOLATED)                                       # and a new one is refused
    tx.cur.execute("rollback to savepoint d")


@pytest.mark.parametrize("domain", ["agricarbon-ci.invalid", "agricarbon-test.invalid", "agricarbon-demo.local",
                                    "qa.example.com", "a.test", "example.org", "box.localhost"])
def test_reserved_test_domains_are_accepted(tx, domain):
    tx.cur.execute("insert into auth.users (id, email, aud, role, created_at) values (%s, %s, 'authenticated',"
                   " 'authenticated', now())", (uuid.uuid4(), f"fixture@{domain}"))
    tx.cur.execute(ISOLATED)
    assert isolated(tx) is True


# ================================================================== assurance on the row

def test_assurance_is_stamped_from_the_approval_record_and_is_immutable(tx, m2):
    verified, _ = verified_doc(tx, m2, "awd verified stamp")
    tx.cur.execute("select source_id from public.knowledge_documents where id = %s", (verified,))
    verified_src = tx.cur.fetchone()[0]
    assert (assurance(tx, "document", verified), assurance(tx, "source", verified_src)) == ("verified", "verified")
    src, demo, _ = demo_doc(tx, "awd demo stamp", demo_source=True)
    assert (assurance(tx, "document", demo), assurance(tx, "source", src)) == ("demo_unverified", "demo_unverified")
    draft = tx.document(tx.source(), status="review_required", document_id="doc-draft")
    assert assurance(tx, "document", draft) is None
    for sql, params in (("update public.knowledge_documents set approval_assurance = 'verified' where id = %s", (demo,)),
                        ("update public.knowledge_documents set approval_assurance = null where id = %s", (verified,)),
                        ("update public.knowledge_sources set approval_assurance = 'verified' where source_id = %s", (src,)),
                        ("update public.knowledge_documents set approval_assurance = 'verified' where id = %s", (draft,))):
        assert owner(tx, sql, params) == ("err", CHECK_VIOLATION), sql
    assert owner(tx, "insert into public.knowledge_sources (source_id, title, owner, source_type, visibility,"
                     " approval_assurance) values ('kn-forged-assurance', 't', 'o', 'guideline', 'public', 'verified')") \
        == ("err", CHECK_VIOLATION)
    # a quarantine keeps what the approval was
    tx.cur.execute("set local role service_role")
    tx.cur.execute("select private.knowledge_demo_quarantine_all('go-live')")
    tx.cur.execute("reset role")
    assert (tx.status_of("document", demo), assurance(tx, "document", demo)) == ("quarantined", "demo_unverified")


# ================================================================== retrieval and RLS

def test_default_retrieval_and_rls_serve_verified_content_only(tx, m2):
    verified, verified_chunk = verified_doc(tx, m2, "awd assurance retrieval verified")
    _, demo, demo_chunk = demo_doc(tx, "awd assurance retrieval demo")
    assert isolated(tx) is True                              # even on an isolated database ...
    ids = tx.rpc_ids(tx.member, tx.season_a, "awd assurance retrieval")
    assert verified_chunk in ids and demo_chunk not in ids   # ... the production RPC serves verified only
    status, rows = tx.as_user(tx.member, "select id from public.knowledge_documents where id = any(%s)",
                              ([verified, demo],))
    assert status == "ok" and {r[0] for r in rows} == {verified}
    status, rows = tx.as_user(tx.member, "select count(*) from public.knowledge_chunks where chunk_id = %s", (demo_chunk,))
    assert rows == [(0,)]
    # a client that sets the transaction-local switch itself gets nothing on a shared database
    tx.cur.execute("select private.knowledge_declare_shared()")
    status, rows = tx.as_user(tx.member, "select set_config('knowledge.include_demo', 'on', true),"
                              " (select count(*) from public.knowledge_documents where id = %s)", (demo,))
    assert rows == [("on", 0)]


def test_a_verified_version_of_a_demo_approved_source_is_not_served(tx, m2):
    src, _, _ = demo_doc(tx, "awd source assurance first", demo_source=True)
    doc = tx.document(src, status="review_required", document_id="doc-under-demo-source")
    chunk = tx.chunk(doc, "awd source assurance second")
    assert as_role(tx, "service_role", DEMO_DOC, (doc, tx.approver, "demo"))[0] == "ok"
    assert chunk not in tx.rpc_ids(tx.member, tx.season_a, "awd source assurance")
    status, rows = demo_rpc(tx, tx.member, tx.season_a, "awd source assurance")
    assert status == "ok" and {r[3]: r[21] for r in rows if r[3] == chunk} == {chunk: "demo_unverified"}


def test_the_demo_rpc_serves_labelled_rows_on_an_isolated_database_only(tx, m2):
    _, verified_chunk = verified_doc(tx, m2, "awd labelled demo verified")
    _, _, demo_chunk = demo_doc(tx, "awd labelled demo unverified")
    status, rows = demo_rpc(tx, tx.member, tx.season_a, "awd labelled demo")
    assert status == "ok"
    labels = {r[3]: r[21] for r in rows if r[3] in {verified_chunk, demo_chunk}}
    assert labels == {verified_chunk: "verified", demo_chunk: "demo_unverified"}
    # the same scope rules as production: an outsider's season reads nothing
    status, rows = demo_rpc(tx, tx.outsider, tx.season_a, "awd labelled demo")
    assert status == "ok" and not [r for r in rows if r[3] in {verified_chunk, demo_chunk}]
    # fail closed on a shared database: refused, not silently empty
    tx.cur.execute("select private.knowledge_declare_shared()")
    assert demo_rpc(tx, tx.member, tx.season_a, "awd labelled demo") == ("err", PERMISSION_DENIED)
    for role in ("anon", "service_role"):
        tx.cur.execute("select has_function_privilege(%s, 'public.match_knowledge_chunks_lexical_demo(uuid,text,integer)',"
                       " 'execute')", (role,))
        assert tx.cur.fetchone()[0] is False, role


def test_a_demo_approved_version_is_not_active_evidence(tx, m2):
    _, demo, _ = demo_doc(tx, "awd evidence state demo")
    verified, _ = verified_doc(tx, m2, "awd evidence state verified")
    tx.cur.execute("select (private.knowledge_document_evidence_state(%s)).*, (private.knowledge_document_evidence_state(%s)).*",
                   (demo, verified))
    assert tx.cur.fetchone() == ("inactive", "assurance_demo_unverified", "active", "approved_in_force")


# ================================================================== backfill, rollback, replay

def test_rollback_refuses_to_re_expose_demo_content_and_replay_backfills_fail_closed(tx, m2):
    _, verified_chunk = verified_doc(tx, m2, "awd replay verified")
    _, demo, demo_chunk = demo_doc(tx, "awd replay demo")
    tx.settle()
    tx.cur.execute("savepoint rb")
    with pytest.raises(psycopg.errors.RaiseException, match="ha_rollback_confirmed"):
        tx.cur.execute(_without_tx_control(HA_ROLLBACK))
    tx.cur.execute("rollback to savepoint rb")
    tx.cur.execute("select private.knowledge_declare_shared()")           # a shared database with demo rows
    tx.cur.execute("set local knowledge.ha_rollback_confirmed = 'yes'")
    tx.cur.execute("set local knowledge.ha_rollback_reserve_unrecorded = 'yes'")
    with pytest.raises(psycopg.errors.RaiseException, match="demo row"):
        tx.cur.execute(_without_tx_control(HA_ROLLBACK))
    tx.cur.execute("rollback to savepoint rb")
    unwind_ha(tx)                                                           # isolated: allowed
    tx.cur.execute("select to_regclass('private.knowledge_deployment'), to_regproc('public.match_knowledge_chunks_lexical_demo'),"
                   " (select count(*) from information_schema.columns where column_name = 'approval_assurance'"
                   "  and table_schema = 'public')")
    assert tx.cur.fetchone() == (None, None, 0)
    assert demo_chunk in tx.rpc_ids(tx.member, tx.season_a, "awd replay")   # the pre-H-a behaviour, as documented
    # a version approved without any approval record (as before M2): replay must not guess
    legacy = tx.document(tx.source(), status="review_required", document_id="doc-legacy")
    legacy_chunk = tx.chunk(legacy, "awd replay legacy")
    tx.cur.execute("alter table public.knowledge_documents disable trigger user")
    tx.cur.execute("update public.knowledge_documents set status = 'approved', approved_by = %s, approved_at = now(),"
                   " review_note = 'TEST FIXTURE: approved before M2, no approval record',"
                   " approval_expires_on = current_date + 30 where id = %s", (tx.approver, legacy))
    tx.cur.execute("alter table public.knowledge_documents enable trigger user")
    tx.cur.execute(_without_tx_control(HA))                                  # replay
    assert (assurance(tx, "document", demo), assurance(tx, "document", legacy)) == ("demo_unverified", "unrecorded")
    ids = tx.rpc_ids(tx.member, tx.season_a, "awd replay")
    assert verified_chunk in ids and demo_chunk not in ids and legacy_chunk not in ids
    assert isolated(tx) is False                         # a replayed H-a starts shared: no declaration survives
    # rolling back again with an unrecorded approved row needs its own confirmation
    tx.cur.execute(ISOLATED)
    tx.cur.execute("savepoint again")
    tx.cur.execute("set local knowledge.ha_rollback_confirmed = 'yes'")
    tx.cur.execute("set local knowledge.ha_rollback_reserve_unrecorded = ''")     # set earlier in this transaction
    with pytest.raises(psycopg.errors.RaiseException, match="without an approval record"):
        tx.cur.execute(_without_tx_control(HA_ROLLBACK))
    tx.cur.execute("rollback to savepoint again")


def test_rollback_restores_the_pre_h_a_bodies_verbatim(tx):
    """The rollback is generated from M2/M3/M4 and the retrieval foundation; prove the live bodies
    after it equal the bodies those migrations define."""
    unwind_ha(tx)
    tx.cur.execute("select prosrc from pg_proc where oid = 'public.match_knowledge_chunks_lexical(uuid,text,integer)'::regprocedure")
    body = tx.cur.fetchone()[0]
    m3 = (ROOT / "supabase/migrations/20261111090000_knowledge_effective_dates_m3.sql").read_text(encoding="utf-8")
    start = m3.index("create or replace function public.match_knowledge_chunks_lexical(")
    expected = m3[m3.index("as $$", start) + 5:m3.index("$$;", start)]
    assert body.replace("\r\n", "\n").strip() == expected.replace("\r\n", "\n").strip()
    tx.cur.execute("select pg_get_expr(polqual, polrelid) from pg_policy where polname = 'knowledge_documents_select'")
    assert "approval_assurance" not in tx.cur.fetchone()[0]
    tx.cur.execute("select prosrc from pg_proc where oid = 'private.knowledge_demo_require_enabled()'::regprocedure")
    assert "knowledge_deployment_isolated" not in tx.cur.fetchone()[0]
    tx.cur.execute(_without_tx_control(HA))                                  # and it replays cleanly
    assert isolated(tx) is False


def test_no_hosted_config_is_touched_by_the_fixture():
    """The DB fixture of this suite runs against SUPABASE_DB_URL, which the test guard pins to a local
    target; the gate check agrees with it."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("gate", ROOT / "scripts/ci/knowledge_isolation_gate.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    assert _DB_URL and gate.target_refusal(_DB_URL) is None

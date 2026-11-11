"""RAG V1.5 M3 (migration 20261111090000): version validity, at the DATABASE under the real roles.
Effective window, approval shelf life (2 years), atomic supersession, in-force retrieval and the
controlled expiry step. Identities are SYNTHETIC TEST FIXTURES (see tests/knowledge_status_paths.py);
no real document is approved. One transaction per test, rolled back, except the concurrency test (it
commits synthetic rows and removes them). Skipped without SUPABASE_DB_URL.

Time cannot be mocked inside PostgreSQL, so "the day after" is reached the only way a database owner
could: `force()` lifts the document row trigger inside the test transaction and rewrites a date. That
is a TEST device on a local/CI database; no client or service role can do it.

dev3-01 stays OPEN: M3 keeps guidance that is no longer in force out of retrieval. It does not judge
whether the content is correct.
"""

from __future__ import annotations

import threading
import uuid
from datetime import date, timedelta

import pytest

from tests import knowledge_status_paths as paths
from tests.test_rag_knowledge_m2_approval import DEMO_DOC, _demo, as_role, code, draft, m2, owner  # noqa: F401
from tests.test_rag_knowledge_status_events import (M2, M3, M3_ROLLBACK, _body_in, _live_body, _without_tx_control,
                                                    unwind_m4)
from tests.test_rag_knowledge_storage import (CHECK_VIOLATION, INVALID_PARAMETER, PERMISSION_DENIED,  # noqa: E402
                                              _DB_URL, pytestmark, psycopg, tx)

__all__ = ["pytestmark", "tx", "m2"]

FOREIGN_KEY_VIOLATION = "23503"
ZONE = "Asia/Ho_Chi_Minh"
DAY = timedelta(days=1)
EXPIRE = "select private.knowledge_expire_documents(%s)"
DUE = "select document_pk, cause from private.knowledge_expiry_due()"
M3_HELPERS = ("knowledge_policy_time_zone()", "knowledge_policy_date(timestamptz)", "knowledge_approval_validity()",
              "knowledge_in_force(date, date, date, date)", "knowledge_supersede_for(uuid, boolean)",
              "knowledge_expiry_events_guard()")


def today(tx) -> date:
    tx.cur.execute("select private.knowledge_policy_date(now())")
    return tx.cur.fetchone()[0]


def two_years_after(tx, day: date) -> date:
    tx.cur.execute("select (%s::date + interval '2 years')::date", (day,))
    return tx.cur.fetchone()[0]


def window(tx, doc, **cols):
    """('ok', None) or ('err', sqlstate): an operator edit of the M3 columns (legal only before review)."""
    sets = ", ".join(f"{column} = %s" for column in cols)
    return owner(tx, f"update public.knowledge_documents set {sets} where id = %s", (*cols.values(), doc))


def force(tx, doc, **cols):
    """TEST-ONLY time travel (see the module docstring): rewrite dates with the row trigger lifted."""
    tx.settle()
    sets = ", ".join(f"{column} = %s" for column in cols)
    tx.cur.execute("alter table public.knowledge_documents disable trigger knowledge_documents_immutable")
    tx.cur.execute(f"update public.knowledge_documents set {sets} where id = %s", (*cols.values(), doc))
    tx.cur.execute("alter table public.knowledge_documents enable trigger knowledge_documents_immutable")


def version(tx, m2, src, *, version="v1", document_id="doc", content="awd validity m3", **cols):
    """A review_required, attested version with one chunk and the given M3 columns: (doc, chunk)."""
    doc = tx.document(src, status="review_required", version=version, document_id=document_id)
    chunk = tx.chunk(doc, content)
    if cols:
        assert window(tx, doc, **cols) == ("ok", None)
    m2.attest("document", doc)
    return doc, chunk


def approve(tx, m2, doc, approver=None):
    review = m2.start(doc)
    m2.submit(review)
    return m2.decide(review, approver or tx.approver)


def approved(tx, m2, *, visibility="public", org=None, content="awd validity m3", **cols):
    """An approved source and an approved version with the given window: (src, doc, chunk)."""
    src = tx.source(visibility=visibility, org=org)
    doc, chunk = version(tx, m2, src, content=content, **cols)
    approve(tx, m2, doc)
    return src, doc, chunk


def column(tx, doc, name):
    tx.cur.execute(f"select {name} from public.knowledge_documents where id = %s", (doc,))
    return tx.cur.fetchone()[0]


def expire(tx, limit=1000):
    status, rows = as_role(tx, "service_role", EXPIRE, (limit,))
    assert status == "ok", rows
    return rows[0][0]


# ================================================================== schema and privileges

def test_m3_columns_constraints_and_the_expiry_table_are_locked_down(tx):
    tx.cur.execute("select column_name, data_type from information_schema.columns where table_schema = 'public'"
                   " and table_name = 'knowledge_documents' and column_name in ('effective_from', 'effective_to',"
                   " 'supersedes_document_pk', 'approval_expires_on') order by 1")
    assert tx.cur.fetchall() == [("approval_expires_on", "date"), ("effective_from", "date"), ("effective_to", "date"),
                                 ("supersedes_document_pk", "uuid")]
    tx.cur.execute("select relrowsecurity, (select count(*) from pg_policies where tablename = 'knowledge_expiry_events')"
                   " from pg_class where oid = 'public.knowledge_expiry_events'::regclass")
    assert tx.cur.fetchone() == (True, 0)
    for role, expected in (("anon", False), ("authenticated", False), ("service_role", True)):
        tx.cur.execute("select has_table_privilege(%s, 'public.knowledge_expiry_events', 'select'),"
                       " has_table_privilege(%s, 'public.knowledge_expiry_events', 'insert, update, delete, truncate')",
                       (role, role))
        assert tx.cur.fetchone() == (expected, False), role


def test_expiry_functions_are_definer_pinned_and_service_role_only(tx):
    for name in ("knowledge_expire_documents(integer)", "knowledge_expiry_due()"):
        tx.cur.execute("select prosecdef, proconfig from pg_proc where oid = %s::regprocedure", (f"private.{name}",))
        assert tx.cur.fetchone() == (True, ['search_path=""']), name
        for role, expected in (("anon", False), ("authenticated", False), ("service_role", True)):
            tx.cur.execute("select has_function_privilege(%s, %s, 'execute')", (role, f"private.{name}"))
            assert tx.cur.fetchone()[0] is expected, (name, role)
    assert as_role(tx, "authenticated", EXPIRE, (10,), {"role": "authenticated", "sub": str(tx.member)}) \
        == ("err", PERMISSION_DENIED)
    assert as_role(tx, "anon", EXPIRE, (10,)) == ("err", PERMISSION_DENIED)


def test_m3_helpers_are_not_executable_by_any_client_or_service(tx):
    for name in M3_HELPERS:
        for role in ("anon", "authenticated", "service_role"):
            tx.cur.execute("select has_function_privilege(%s, %s, 'execute')", (role, f"private.{name}"))
            assert tx.cur.fetchone()[0] is False, (name, role)
    # the one helper the row trigger calls as the writer: a pure validation, operator only
    for role, expected in (("anon", False), ("authenticated", False), ("service_role", True)):
        tx.cur.execute("select has_function_privilege(%s, 'private.knowledge_check_supersedes(text, uuid)', 'execute')",
                       (role,))
        assert tx.cur.fetchone()[0] is expected, role


def test_the_migration_schedules_nothing(tx):
    """Expiry is an operator step: M3 creates no cron job (and pg_cron, if present, has none of ours)."""
    tx.cur.execute("select to_regclass('cron.job') is not null")
    if tx.cur.fetchone()[0]:
        tx.cur.execute("select count(*) from cron.job where command ilike '%knowledge_expire%'")
        assert tx.cur.fetchone()[0] == 0
    assert "cron" not in M3.read_text(encoding="utf-8").split("-- ====", 1)[1].lower()


# ================================================================== the policy date

@pytest.mark.parametrize("session_zone", ["UTC", "Asia/Ho_Chi_Minh", "America/Los_Angeles", "Pacific/Kiritimati"])
@pytest.mark.parametrize("instant, expected", [
    ("2026-12-31T16:59:59Z", date(2026, 12, 31)),          # 23:59:59 in Ho Chi Minh
    ("2026-12-31T17:00:00Z", date(2027, 1, 1)),            # midnight in Ho Chi Minh
    ("2028-02-28T17:00:00+00", date(2028, 2, 29)),         # leap day
    ("2026-06-30T23:30:00-10:00", date(2026, 7, 1)),
])
def test_the_policy_date_is_the_ho_chi_minh_calendar_day_whatever_the_session_zone(tx, session_zone, instant, expected):
    tx.cur.execute(f"set local timezone = '{session_zone}'")
    tx.cur.execute("select private.knowledge_policy_date(%s::timestamptz), private.knowledge_policy_time_zone()",
                   (instant,))
    assert tx.cur.fetchone() == (expected, ZONE)


D = date(2027, 3, 15)


@pytest.mark.parametrize("frm, to, expires, on, expected", [
    (None, None, D, D, True),                       # the approval's last day is still in force
    (None, None, D, D + DAY, False),                # ... the next day is not
    (None, None, None, D, False),                   # no approval expiry: never in force (fail closed)
    (D, None, D + DAY, D, True),                    # first day of the window
    (D + DAY, None, D + 30 * DAY, D, False),        # not yet in force
    (None, D, D + DAY, D, True),                    # last day of the window, inclusive
    (None, D - DAY, D + DAY, D, False),             # the window ended yesterday
    (D, D, D, D, True),                             # a one-day window
    (D - DAY, D + DAY, D - DAY, D, False),          # in its window, but the approval lapsed
])
def test_in_force_boundaries(tx, frm, to, expires, on, expected):
    tx.cur.execute("select private.knowledge_in_force(%s, %s, %s, %s)", (frm, to, expires, on))
    assert tx.cur.fetchone()[0] is expected


def test_retrieval_and_rls_use_the_same_zone_and_window_as_the_policy_date(tx):
    """The invoker paths inline the predicate (no new EXECUTE grant); it must be the policy zone."""
    tx.cur.execute("select pg_get_functiondef('public.match_knowledge_chunks_lexical(uuid, text, integer)'::regprocedure),"
                   " (select qual from pg_policies where tablename = 'knowledge_documents'"
                   "   and policyname = 'knowledge_documents_select'), private.knowledge_policy_time_zone()")
    function, policy, zone = tx.cur.fetchone()
    for text in (function, policy):
        assert text.count(f"'{zone}'") == 3, text
        for needle in ("effective_from", "effective_to", "approval_expires_on"):
            assert needle in text
    tx.cur.execute("select count(*) from pg_policies where tablename = 'knowledge_documents'")
    assert tx.cur.fetchone()[0] == 1


# ================================================================== the window

def test_the_window_must_be_ordered_and_is_editable_only_before_review(tx, m2):
    src = tx.source()
    doc, _ = version(tx, m2, src)
    t = today(tx)
    assert window(tx, doc, effective_from=t, effective_to=t - DAY) == ("err", CHECK_VIOLATION)
    assert window(tx, doc, effective_from=t, effective_to=t) == ("ok", None)
    assert window(tx, doc, effective_from=None, effective_to=t + DAY) == ("ok", None)


@pytest.mark.parametrize("cols", [{"effective_from": date(2020, 1, 1)}, {"effective_to": date(2099, 1, 1)},
                                  {"effective_to": None}, {"supersedes_document_pk": "target"}])
def test_the_window_and_the_superseded_version_are_frozen_under_review_and_after_approval(tx, m2, cols):
    _, target, _ = approved(tx, m2, content="awd frozen target")
    cols = {k: (target if v == "target" else v) for k, v in cols.items()}
    src = tx.source()
    doc, _ = version(tx, m2, src, content="awd frozen", effective_to=today(tx) + 30 * DAY)
    review = m2.start(doc)
    assert window(tx, doc, **cols) == ("err", CHECK_VIOLATION)                 # expert_review: frozen
    m2.submit(review)
    m2.decide(review, tx.approver)
    assert window(tx, doc, **cols) == ("err", CHECK_VIOLATION)                 # approved: immutable
    tx.transition("document", doc, "approved", "quarantined", "dispute")
    assert window(tx, doc, **cols) == ("err", CHECK_VIOLATION)                 # and stays so afterwards


def test_a_rejected_version_can_have_its_dates_corrected_before_a_new_review(tx, m2):
    src = tx.source()
    doc, _ = version(tx, m2, src, effective_from=today(tx) + 5 * DAY)
    tx.transition("document", doc, "review_required", "rejected", "wrong date")
    assert window(tx, doc, effective_from=today(tx)) == ("ok", None)
    tx.transition("document", doc, "rejected", "review_required", "date corrected")
    approve(tx, m2, doc)
    assert tx.status_of("document", doc) == "approved"


# ================================================================== approval validity

def test_an_approval_expires_two_years_after_the_approval_day_and_is_never_supplied(tx, m2):
    src = tx.source()
    assert owner(tx, "insert into public.knowledge_documents (source_id, document_id, document_version, title, language,"
                     " artifact_ref, file_sha256, normalized_sha256, parser_version, normalizer_version, chunker_version,"
                     " approval_expires_on) values (%s, 'early', 'v1', 't', 'vi', 'x', %s, %s, 'p', 'n', 'c', %s)",
                 (src, "a" * 64, "b" * 64, date(2099, 1, 1))) == ("err", CHECK_VIOLATION)
    doc, _ = version(tx, m2, src)
    assert window(tx, doc, approval_expires_on=date(2099, 1, 1)) == ("err", CHECK_VIOLATION)
    assert column(tx, doc, "approval_expires_on") is None
    approve(tx, m2, doc)
    assert column(tx, doc, "approval_expires_on") == two_years_after(tx, today(tx))
    for value in (date(2099, 1, 1), None):
        assert window(tx, doc, approval_expires_on=value) == ("err", CHECK_VIOLATION)
    assert as_role(tx, "service_role", "update public.knowledge_documents set approval_expires_on = '2099-01-01'"
                                       " where id = %s", (doc,))[0] == "err"


def test_a_demo_approval_gets_the_same_shelf_life_and_window_rules(tx, m2):
    _demo(tx, True)
    src = tx.source()
    doc, _ = version(tx, m2, src, effective_from=today(tx) + DAY)
    assert as_role(tx, "service_role", DEMO_DOC, (doc, tx.approver, "demo")) == ("err", CHECK_VIOLATION)
    assert tx.status_of("document", doc) == "review_required"
    doc2, _ = version(tx, m2, src, document_id="doc-two", content="awd demo two")
    assert as_role(tx, "service_role", DEMO_DOC, (doc2, tx.approver, "demo"))[0] == "ok"
    assert column(tx, doc2, "approval_expires_on") == two_years_after(tx, today(tx))


@pytest.mark.parametrize("session_zone", ["UTC", "America/Los_Angeles", "Pacific/Kiritimati"])
def test_the_approval_expiry_does_not_depend_on_the_session_zone(tx, m2, session_zone):
    tx.cur.execute(f"set local timezone = '{session_zone}'")
    _, doc, _ = approved(tx, m2)
    tx.cur.execute("select ((now() at time zone 'Asia/Ho_Chi_Minh')::date + interval '2 years')::date")
    expected = tx.cur.fetchone()[0]
    assert column(tx, doc, "approval_expires_on") == expected


# ================================================================== approval inside the window only

def test_approval_on_the_first_and_on_the_last_day_of_the_window(tx, m2):
    t = today(tx)
    for frm, to in ((t, t), (t, None), (None, t), (t - 400 * DAY, t + 400 * DAY)):
        _, doc, _ = approved(tx, m2, content=f"awd boundary {frm} {to}", effective_from=frm, effective_to=to)
        assert tx.status_of("document", doc) == "approved", (frm, to)


def test_a_version_is_not_approved_before_it_takes_effect(tx, m2):
    """It may be reviewed ahead of time; the approval waits for the day."""
    src = tx.source()
    doc, chunk = version(tx, m2, src, content="awd future", effective_from=today(tx) + DAY)
    review = m2.start(doc)
    m2.submit(review)
    assert code(m2.decide, review, tx.approver) == CHECK_VIOLATION
    assert tx.status_of("document", doc) == "expert_review"
    tx.cur.execute("select count(*) from public.knowledge_approval_records where document_pk = %s", (doc,))
    assert tx.cur.fetchone()[0] == 0                                           # a refused approval writes nothing
    assert chunk not in tx.rpc_ids(tx.member, tx.season_a, "awd future")


def test_an_expired_version_is_neither_reviewed_nor_approved(tx, m2):
    src = tx.source()
    doc, _ = version(tx, m2, src, effective_to=today(tx) - DAY)
    assert code(m2.start, doc) == CHECK_VIOLATION
    assert tx.status_of("document", doc) == "review_required"
    # the window ends while the version is under review: the approval is refused (verified and demo)
    live, _ = version(tx, m2, src, document_id="doc-live", content="awd lapses", effective_to=today(tx))
    review = m2.start(live)
    m2.submit(review)
    force(tx, live, effective_to=today(tx) - DAY)
    assert code(m2.decide, review, tx.approver) == CHECK_VIOLATION
    _demo(tx, True)
    tx.cur.execute("savepoint demo")
    with pytest.raises(psycopg.errors.CheckViolation, match="has passed"):
        tx.cur.execute("select private.knowledge_demo_approve_document(%s, %s, 'demo')", (live, tx.approver))
    tx.cur.execute("rollback to savepoint demo")
    assert tx.status_of("document", live) == "expert_review"


# ================================================================== the review snapshot

def test_a_version_without_m3_fields_keeps_its_m2_snapshot_and_a_window_is_part_of_the_hash(tx, m2):
    src = tx.source()
    doc, _ = version(tx, m2, src)
    tx.cur.execute("select private.knowledge_document_snapshot(%s) -> 'document'", (doc,))
    keys = set(tx.cur.fetchone()[0])
    assert not keys & {"effective_from", "effective_to", "supersedes_document_pk", "approval_expires_on"}
    bare = m2.snapshot_sha("document", doc)
    t = today(tx)
    assert window(tx, doc, effective_from=t) == ("ok", None)
    with_from = m2.snapshot_sha("document", doc)
    assert window(tx, doc, effective_to=t + DAY) == ("ok", None)
    with_both = m2.snapshot_sha("document", doc)
    assert len({bare, with_from, with_both}) == 3
    tx.cur.execute("select private.knowledge_document_snapshot(%s) -> 'document' ->> 'effective_to'", (doc,))
    assert tx.cur.fetchone()[0] == (t + DAY).isoformat()
    assert window(tx, doc, effective_from=None, effective_to=None) == ("ok", None)
    assert m2.snapshot_sha("document", doc) == bare


@pytest.mark.parametrize("setting", ["timezone = 'America/Los_Angeles'", "datestyle = 'German, DMY'",
                                     "datestyle = 'SQL, MDY'", "intervalstyle = 'sql_standard'"])
def test_the_snapshot_hash_with_a_window_does_not_depend_on_session_settings(tx, m2, setting):
    src = tx.source()
    doc, _ = version(tx, m2, src, effective_from=today(tx), effective_to=today(tx) + 10 * DAY)
    review = m2.start(doc)
    tx.cur.execute(f"set local {setting}")
    assert m2.snapshot_sha("document", doc) == m2.current_review(doc)[3]
    m2.submit(review)
    assert m2.decide(review, tx.approver)
    assert column(tx, doc, "approval_expires_on") == two_years_after(tx, today(tx))


def test_a_window_changed_behind_the_review_invalidates_the_evidence(tx, m2):
    """Only an owner lifting the trigger can do it (the trust boundary); the approval still refuses."""
    src = tx.source()
    doc, _ = version(tx, m2, src, effective_to=today(tx) + 10 * DAY)
    review = m2.start(doc)
    m2.submit(review)
    force(tx, doc, effective_to=today(tx) + 3650 * DAY)
    assert m2.snapshot_sha("document", doc) != m2.current_review(doc)[3]
    assert code(m2.decide, review, tx.approver) == CHECK_VIOLATION
    assert tx.status_of("document", doc) == "expert_review"


# ================================================================== retrieval: in force only

def visible(tx, doc):
    """(document rows, chunk rows) a tenant-less signed-in member reads through RLS."""
    docs = tx.as_user(tx.member, "select count(*) from public.knowledge_documents where id = %s", (doc,))
    chunks = tx.as_user(tx.member, "select count(*) from public.knowledge_chunks where document_pk = %s", (doc,))
    return docs[1][0][0], chunks[1][0][0]


@pytest.mark.parametrize("case", ["window_ended", "approval_lapsed", "not_yet_effective"])
def test_an_approved_version_out_of_force_is_withheld_before_any_expiry_run(tx, m2, case):
    t = today(tx)
    _, doc, chunk = approved(tx, m2, content=f"awd inforce {case}", effective_to=t)
    assert chunk in tx.rpc_ids(tx.member, tx.season_a, f"awd inforce {case}")      # its last day: served
    assert visible(tx, doc) == (1, 1)
    force(tx, doc, **{"window_ended": {"effective_to": t - DAY},
                      "approval_lapsed": {"approval_expires_on": t - DAY},
                      "not_yet_effective": {"effective_from": t + DAY, "effective_to": t + 2 * DAY}}[case])
    assert tx.status_of("document", doc) == "approved"                             # no job has run
    assert chunk not in tx.rpc_ids(tx.member, tx.season_a, f"awd inforce {case}")
    assert visible(tx, doc) == (0, 0)


def test_the_last_day_of_the_approval_is_still_served(tx, m2):
    _, doc, chunk = approved(tx, m2, content="awd last approval day")
    force(tx, doc, approval_expires_on=today(tx))
    assert chunk in tx.rpc_ids(tx.member, tx.season_a, "awd last approval day")
    assert visible(tx, doc) == (1, 1)


# ================================================================== expiry

def test_expiry_quarantines_exactly_the_versions_out_of_force_with_immutable_evidence(tx, m2):
    t = today(tx)
    _, ended, ended_chunk = approved(tx, m2, content="awd expiry ended", effective_to=t)
    _, lapsed, _ = approved(tx, m2, content="awd expiry lapsed")
    _, both, _ = approved(tx, m2, content="awd expiry both", effective_to=t)
    _, last_day, _ = approved(tx, m2, content="awd expiry lastday", effective_to=t)
    _, open_ended, _ = approved(tx, m2, content="awd expiry open")
    assert expire(tx) == 0                                                         # nothing is out of force yet
    force(tx, ended, effective_to=t - DAY)
    force(tx, lapsed, approval_expires_on=t - DAY)
    force(tx, both, effective_to=t - DAY, approval_expires_on=t - 2 * DAY)        # the approval lapsed FIRST
    status, due = as_role(tx, "service_role", DUE)
    assert status == "ok" and {row for row in due if row[0] in (ended, lapsed, both, last_day, open_ended)} == {
        (ended, "effective_to_passed"), (lapsed, "approval_validity_passed"), (both, "approval_validity_passed")}
    assert tx.status_of("document", ended) == "approved"                           # the dry run changes nothing
    assert expire(tx) == 3
    assert [tx.status_of("document", d) for d in (ended, lapsed, both, last_day, open_ended)] == [
        "quarantined", "quarantined", "quarantined", "approved", "approved"]
    assert expire(tx) == 0                                                         # idempotent
    tx.cur.execute("select e.cause, e.effective_to, e.approval_expires_on, e.policy_date, e.policy_time_zone,"
                   " e.actor_role, s.from_status::text, s.to_status::text, s.reason, s.document_pk,"
                   " e.recorded_xact = pg_current_xact_id()"
                   " from public.knowledge_expiry_events e join public.knowledge_status_events s on s.id = e.status_event_id"
                   " where e.document_pk = %s", (ended,))
    cause, eff_to, expires, policy_date, zone, role, frm, to, reason, event_doc, same_xact = tx.cur.fetchone()
    assert (cause, eff_to, policy_date, zone, role, frm, to, event_doc, same_xact) == (
        "effective_to_passed", t - DAY, t, ZONE, "service_role", "approved", "quarantined", ended, True)
    assert expires == two_years_after(tx, t)
    assert reason == (f"EXPIRED (automatic): effective_to {(t - DAY).isoformat()} passed on policy date"
                      f" {t.isoformat()} ({ZONE}); a new version is required")
    tx.cur.execute("select cause from public.knowledge_expiry_events where document_pk = %s", (both,))
    assert tx.cur.fetchone()[0] == "approval_validity_passed"                      # the date that passed first
    assert ended_chunk not in tx.rpc_ids(tx.member, tx.season_a, "awd expiry ended")
    # M1 decision D1: an expired version never returns; it can only be archived
    assert tx.transit("document", ended, "quarantined", "approved") == ("err", CHECK_VIOLATION)
    assert tx.transit("document", ended, "quarantined", "archived", reason="expired")[0] == "ok"


@pytest.mark.parametrize("limit", [None, 0, -1, 1001])
def test_an_expiry_run_is_bounded(tx, limit):
    assert as_role(tx, "service_role", EXPIRE, (limit,)) == ("err", INVALID_PARAMETER)


def test_the_expiry_audit_reason_uses_iso_dates_whatever_the_datestyle(tx, m2):
    t = today(tx)
    _, doc, _ = approved(tx, m2, content="awd datestyle")
    force(tx, doc, approval_expires_on=t - DAY)
    tx.cur.execute("set local datestyle = 'German, DMY'")
    assert expire(tx) == 1
    assert tx.events("document", doc)[-1][2] == (
        f"EXPIRED (automatic): approval validity {(t - DAY).isoformat()} passed on policy date {t.isoformat()}"
        f" ({ZONE}); a new version is required")


def test_an_expiry_run_stops_at_its_limit(tx, m2):
    docs = []
    for i in range(3):
        _, doc, _ = approved(tx, m2, content=f"awd limit {i}")
        force(tx, doc, approval_expires_on=today(tx) - DAY)
        docs.append(doc)
    assert expire(tx, 2) == 2
    assert sorted(tx.status_of("document", d) for d in docs) == ["approved", "quarantined", "quarantined"]
    assert expire(tx, 2) == 1


def test_expiry_evidence_is_immutable_even_for_the_owner(tx, m2):
    _, doc, _ = approved(tx, m2)
    force(tx, doc, approval_expires_on=today(tx) - DAY)
    assert expire(tx) == 1
    for sql in ("update public.knowledge_expiry_events set cause = cause where document_pk = %s",
                "delete from public.knowledge_expiry_events where document_pk = %s"):
        assert owner(tx, sql, (doc,)) == ("err", PERMISSION_DENIED), sql
        assert as_role(tx, "service_role", sql, (doc,)) == ("err", PERMISSION_DENIED), sql
    assert owner(tx, "truncate public.knowledge_expiry_events") == ("err", PERMISSION_DENIED)
    # no forged evidence: a direct insert is refused for the owner and every role
    tx.cur.execute("select status_event_id from public.knowledge_expiry_events where document_pk = %s", (doc,))
    event = tx.cur.fetchone()[0]
    forged = ("insert into public.knowledge_expiry_events (document_pk, source_id, document_id, document_version, cause,"
              " approval_expires_on, policy_date, policy_time_zone, status_event_id, actor_role)"
              " values (%s, 's', 'd', 'v', 'approval_validity_passed', '2020-01-01', '2020-01-02', 'UTC', %s, 'x')")
    assert owner(tx, forged, (doc, event)) == ("err", PERMISSION_DENIED)
    for role in ("service_role", "authenticated", "anon"):
        assert as_role(tx, role, forged, (doc, event)) == ("err", PERMISSION_DENIED), role
    # the audit event of the expiry is append-only too (M1)
    assert owner(tx, "delete from public.knowledge_status_events where id = %s", (event,)) == ("err", PERMISSION_DENIED)


def test_expiry_covers_tenant_versions_and_tenants_read_no_expiry_evidence(tx, m2):
    _, doc, chunk = approved(tx, m2, visibility="tenant", org=tx.org_a, content="awd tenant expiry")
    assert chunk in tx.rpc_ids(tx.member, tx.season_a, "awd tenant expiry")
    force(tx, doc, effective_to=today(tx) - DAY)
    assert chunk not in tx.rpc_ids(tx.member, tx.season_a, "awd tenant expiry")
    assert expire(tx) == 1
    assert tx.status_of("document", doc) == "quarantined"
    for user in (tx.member, tx.manager, tx.outsider):
        assert tx.as_user(user, "select count(*) from public.knowledge_expiry_events")[0] == "err"
        assert tx.as_user(user, "select * from private.knowledge_expiry_due()")[0] == "err"


def test_concurrent_expiry_runs_never_double_expire():
    """Two expiry runs race on one expired version: the first holds its row lock, the second skips it
    at once (SKIP LOCKED) instead of waiting or failing, and exactly one evidence row commits.
    COMMITS synthetic rows (source prefix kn-m3conc-) and removes them; the audit events stay
    (append-only by design, local/CI DB only)."""
    source_id = f"kn-m3conc-{uuid.uuid4().hex[:10]}"
    approver = uuid.uuid4()
    outcome: dict = {}
    with psycopg.connect(_DB_URL) as setup:
        setup.execute("insert into auth.users (id, email, aud, role, created_at) values (%s, %s, 'authenticated',"
                      " 'authenticated', now())", (approver, f"kn-m3conc-{approver.hex[:8]}@agricarbon-test.invalid"))
        setup.execute("insert into public.knowledge_sources (source_id, title, owner, source_type, visibility)"
                      " values (%s, 'TEST FIXTURE m3 concurrency', 'o', 'guideline', 'public')", (source_id,))
        doc = setup.execute(
            "insert into public.knowledge_documents (source_id, document_id, document_version, title, language,"
            " artifact_ref, file_sha256, normalized_sha256, parser_version, normalizer_version, chunker_version,"
            " license_basis) values (%s, 'doc', 'v1', 'TEST FIXTURE', 'vi', %s, %s, %s, 'p', 'n', 'c',"
            " 'official_publication') returning id",
            (source_id, f"knowledge-artifacts/{'c' * 64}/d.md", "c" * 64, "d" * 64)).fetchone()[0]
        m2 = paths.M2.of(setup)
        m2.attest("document", doc)
        review = m2.start(doc)
        m2.submit(review)
        m2.decide(review, approver)
        setup.execute("alter table public.knowledge_documents disable trigger knowledge_documents_immutable")
        setup.execute("update public.knowledge_documents set approval_expires_on = current_date - 7 where id = %s", (doc,))
        setup.execute("alter table public.knowledge_documents enable trigger knowledge_documents_immutable")
        setup.commit()
    try:
        with psycopg.connect(_DB_URL) as first, psycopg.connect(_DB_URL) as second:
            first.execute("set local role service_role")
            assert first.execute(EXPIRE, (1000,)).fetchone()[0] >= 1          # holds the row lock, uncommitted

            def race():
                try:
                    second.execute("set lock_timeout = '20s'")
                    second.execute("set local role service_role")
                    outcome["second"] = second.execute(EXPIRE, (1000,)).fetchone()[0]
                    second.commit()
                except psycopg.Error as exc:
                    second.rollback()
                    outcome["second"] = exc.sqlstate

            worker = threading.Thread(target=race)
            worker.start()
            worker.join(timeout=15)
            assert not worker.is_alive(), "the second expiry run waited for the first one's row lock"
            assert outcome["second"] == 0
            first.commit()
        with psycopg.connect(_DB_URL, autocommit=True) as check:
            assert check.execute("select status::text from public.knowledge_documents where id = %s",
                                 (doc,)).fetchone()[0] == "quarantined"
            assert check.execute("select count(*) from public.knowledge_expiry_events where document_pk = %s",
                                 (doc,)).fetchone()[0] == 1
            assert check.execute("select count(*) from public.knowledge_status_events where document_pk = %s"
                                 " and to_status = 'quarantined'", (doc,)).fetchone()[0] == 1
            check.execute("set role service_role")
            assert check.execute(EXPIRE, (1000,)).fetchone()[0] == 0
            check.execute("reset role")
    finally:
        with psycopg.connect(_DB_URL, autocommit=True) as cleanup:
            cleanup.execute("alter table public.knowledge_expiry_events disable trigger knowledge_expiry_events_guard")
            try:
                cleanup.execute("delete from public.knowledge_expiry_events where source_id = %s", (source_id,))
            finally:
                cleanup.execute("alter table public.knowledge_expiry_events enable trigger knowledge_expiry_events_guard")
            paths.m2_cleanup(cleanup, [source_id])
            cleanup.execute("alter table public.knowledge_documents disable trigger knowledge_documents_immutable")
            cleanup.execute("alter table public.knowledge_sources disable trigger knowledge_sources_scope")
            try:
                cleanup.execute("delete from public.knowledge_documents where source_id = %s", (source_id,))
                cleanup.execute("delete from public.knowledge_sources where source_id = %s", (source_id,))
            finally:
                cleanup.execute("alter table public.knowledge_sources enable trigger knowledge_sources_scope")
                cleanup.execute("alter table public.knowledge_documents enable trigger knowledge_documents_immutable")
            cleanup.execute("delete from auth.users where id = %s", (approver,))


# ================================================================== supersession

def test_an_approval_archives_the_version_it_supersedes_in_the_same_transaction(tx, m2):
    src, old, old_chunk = approved(tx, m2, content="awd supersede old")
    new, new_chunk = version(tx, m2, src, version="v2", content="awd supersede new", supersedes_document_pk=old)
    review = m2.start(new)
    m2.submit(review)
    assert tx.status_of("document", old) == "approved"                              # still served during review
    assert old_chunk in tx.rpc_ids(tx.member, tx.season_a, "awd supersede")
    record = m2.decide(review, tx.approver)
    assert (tx.status_of("document", old), tx.status_of("document", new)) == ("archived", "approved")
    ids = tx.rpc_ids(tx.member, tx.season_a, "awd supersede")
    assert new_chunk in ids and old_chunk not in ids                                # no overlap, no gap
    last = tx.events("document", old)[-1]
    assert last[:2] == ("approved", "archived") and last[2].startswith("superseded by ") and str(new) in last[2]
    tx.cur.execute("select (select recorded_xact from public.knowledge_approval_records where id = %s) ="
                   " (select transaction_id from public.knowledge_status_events where document_pk = %s"
                   "   and to_status = 'archived')", (record, old))
    assert tx.cur.fetchone()[0] is True                                             # one transaction


def test_a_version_of_another_document_can_be_superseded_and_a_refused_approval_archives_nothing(tx, m2):
    src, old, _ = approved(tx, m2, content="awd cross doc old")
    new, _ = version(tx, m2, src, document_id="doc-renamed", content="awd cross doc new",
                     supersedes_document_pk=old, effective_from=today(tx) + DAY)
    review = m2.start(new)
    m2.submit(review)
    assert code(m2.decide, review, tx.approver) == CHECK_VIOLATION                  # not in force yet
    assert (tx.status_of("document", old), tx.status_of("document", new)) == ("approved", "expert_review")
    assert [e[1] for e in tx.events("document", old)][-1] == "approved"             # no archive event leaked


def test_superseding_a_version_no_longer_approved_just_approves(tx, m2):
    src, old, _ = approved(tx, m2, content="awd gone old")
    tx.transition("document", old, "approved", "quarantined", "dispute")
    new, _ = version(tx, m2, src, version="v2", content="awd gone new", supersedes_document_pk=old)
    approve(tx, m2, new)
    assert (tx.status_of("document", old), tx.status_of("document", new)) == ("quarantined", "approved")


def test_only_an_existing_once_approved_other_version_can_be_superseded(tx, m2):
    src = tx.source()
    never, _ = version(tx, m2, src, document_id="doc-never", content="awd never approved")
    doc, _ = version(tx, m2, src, content="awd supersedes checks")
    assert window(tx, doc, supersedes_document_pk=doc) == ("err", CHECK_VIOLATION)            # itself
    assert window(tx, doc, supersedes_document_pk=never) == ("err", CHECK_VIOLATION)          # never approved
    assert window(tx, doc, supersedes_document_pk=uuid.uuid4()) == ("err", FOREIGN_KEY_VIOLATION)
    file_sha, norm_sha = "e" * 64, "f" * 64
    assert owner(tx, "insert into public.knowledge_documents (source_id, document_id, document_version, title, language,"
                     " artifact_ref, file_sha256, normalized_sha256, parser_version, normalizer_version, chunker_version,"
                     " supersedes_document_pk) values (%s, 'at-insert', 'v1', 't', 'vi', 'x', %s, %s, 'p', 'n', 'c', %s)",
                 (src, file_sha, norm_sha, never)) == ("err", CHECK_VIOLATION)                # checked at INSERT too


def test_supersession_never_crosses_a_scope(tx, m2):
    _, public_doc, _ = approved(tx, m2, content="awd scope public")
    src_a, tenant_a_doc, _ = approved(tx, m2, visibility="tenant", org=tx.org_a, content="awd scope tenant a")
    _, tenant_b_doc, _ = approved(tx, m2, visibility="tenant", org=tx.org_b, content="awd scope tenant b")
    farm_src = tx.source(visibility="tenant", org=tx.org_a, farm=tx.farm_a)
    farm_doc, _ = version(tx, m2, farm_src, content="awd scope farm")
    draft_a, _ = version(tx, m2, src_a, version="v2", content="awd scope draft a")
    public_draft, _ = version(tx, m2, tx.source(), content="awd scope public draft")
    assert window(tx, draft_a, supersedes_document_pk=public_doc) == ("err", CHECK_VIOLATION)     # tenant -> public
    assert window(tx, draft_a, supersedes_document_pk=tenant_b_doc) == ("err", CHECK_VIOLATION)   # tenant A -> tenant B
    assert window(tx, public_draft, supersedes_document_pk=tenant_a_doc) == ("err", CHECK_VIOLATION)  # public -> tenant
    assert window(tx, farm_doc, supersedes_document_pk=tenant_a_doc) == ("err", CHECK_VIOLATION)  # farm -> organization
    assert window(tx, draft_a, supersedes_document_pk=tenant_a_doc) == ("ok", None)               # same scope
    approve(tx, m2, draft_a)
    assert (tx.status_of("document", tenant_a_doc), tx.status_of("document", draft_a)) == ("archived", "approved")
    assert [tx.status_of("document", d) for d in (public_doc, tenant_b_doc)] == ["approved", "approved"]


def test_a_version_may_have_two_successors(tx, m2):
    """One text split into two documents: the first approval archives the old version, the second
    finds it archived and just approves."""
    src, old, _ = approved(tx, m2, content="awd split old")
    part1, _ = version(tx, m2, src, document_id="doc-part1", content="awd split one", supersedes_document_pk=old)
    part2, _ = version(tx, m2, src, document_id="doc-part2", content="awd split two", supersedes_document_pk=old)
    approve(tx, m2, part1)
    approve(tx, m2, part2)
    assert [tx.status_of("document", d) for d in (old, part1, part2)] == ["archived", "approved", "approved"]
    assert [e[1] for e in tx.events("document", old)].count("archived") == 1


def test_one_approved_version_per_document_still_holds_without_a_declared_supersession(tx, m2):
    src, old, _ = approved(tx, m2, content="awd undeclared old")
    new, _ = version(tx, m2, src, version="v2", content="awd undeclared new")
    review = m2.start(new)
    m2.submit(review)
    assert code(m2.decide, review, tx.approver) == "23505"                          # the Migration A index
    assert (tx.status_of("document", old), tx.status_of("document", new)) == ("approved", "expert_review")


def test_a_demo_approval_replaces_a_demo_version_but_never_a_verified_one(tx, m2):
    _demo(tx, True)
    src, verified, _ = approved(tx, m2, content="awd demo verified old")
    over_verified, _ = version(tx, m2, src, version="v2", content="awd demo over verified",
                               supersedes_document_pk=verified)
    assert as_role(tx, "service_role", DEMO_DOC, (over_verified, tx.approver, "demo")) == ("err", PERMISSION_DENIED)
    assert (tx.status_of("document", verified), tx.status_of("document", over_verified)) == ("approved", "review_required")
    demo_old, _ = version(tx, m2, src, document_id="doc-demo", content="awd demo old")
    assert as_role(tx, "service_role", DEMO_DOC, (demo_old, tx.approver, "demo one"))[0] == "ok"
    demo_new, _ = version(tx, m2, src, document_id="doc-demo", version="v2", content="awd demo new",
                          supersedes_document_pk=demo_old)
    assert as_role(tx, "service_role", DEMO_DOC, (demo_new, tx.approver, "demo two"))[0] == "ok"
    assert (tx.status_of("document", demo_old), tx.status_of("document", demo_new)) == ("archived", "approved")
    assert tx.events("document", demo_old)[-1][2].startswith("DEMO - NOT EXPERT-REVIEWED: superseded by ")
    # ... nor does a demo version claim to succeed a verified one that is no longer approved
    tx.transition("document", verified, "approved", "quarantined", "dispute")
    assert as_role(tx, "service_role", DEMO_DOC, (over_verified, tx.approver, "demo")) == ("err", PERMISSION_DENIED)
    assert tx.status_of("document", over_verified) == "review_required"
    # the verified flow may replace a demo version
    by_verified, _ = version(tx, m2, src, document_id="doc-demo", version="v3", content="awd demo verified new",
                             supersedes_document_pk=demo_new)
    approve(tx, m2, by_verified)
    assert (tx.status_of("document", demo_new), tx.status_of("document", by_verified)) == ("archived", "approved")


def test_the_operator_path_still_cannot_approve_and_a_forged_marker_gets_no_window_bypass(tx, m2):
    """M2's rule is untouched: operator and owner logins do not approve, in or out of the window."""
    src = tx.source()
    doc, _ = version(tx, m2, src, effective_from=today(tx) + DAY)
    review = m2.start(doc)
    m2.submit(review)
    assert owner(tx, paths.TRANSITION["document"], (doc, "expert_review", "approved", "x", tx.approver)) \
        == ("err", PERMISSION_DENIED)
    assert owner(tx, "update public.knowledge_documents set status = 'approved' where id = %s", (doc,)) \
        == ("err", PERMISSION_DENIED)
    tx.cur.execute("savepoint forged")
    tx.cur.execute("select set_config('knowledge.status_transition', %s, true)", (f"document|{doc}|approved",))
    with pytest.raises(psycopg.Error) as refused:
        tx.cur.execute("update public.knowledge_documents set status = 'approved', approved_by = %s,"
                       " approved_at = now(), review_note = 'forged' where id = %s", (tx.approver, doc))
    assert refused.value.sqlstate in (CHECK_VIOLATION, PERMISSION_DENIED)
    tx.cur.execute("rollback to savepoint forged")
    assert tx.status_of("document", doc) == "expert_review"


# ================================================================== rollback

def test_m3_rollback_needs_a_confirmation_and_refuses_while_it_would_republish_expired_guidance(tx, m2):
    _, doc, _ = approved(tx, m2, content="awd rollback expired")
    force(tx, doc, effective_to=today(tx) - DAY)
    unwind_m4(tx)                                                   # newest first (M4 replaces nothing)
    tx.cur.execute("savepoint rb")
    with pytest.raises(psycopg.errors.RaiseException, match="DROPS the expiry evidence"):
        tx.cur.execute(_without_tx_control(M3_ROLLBACK))
    tx.cur.execute("rollback to savepoint rb")
    tx.cur.execute("set local knowledge.m3_rollback_evidence_exported = 'yes'")
    with pytest.raises(psycopg.errors.RaiseException, match="no longer in force"):
        tx.cur.execute(_without_tx_control(M3_ROLLBACK))
    tx.cur.execute("rollback to savepoint rb")
    under_review, _ = version(tx, m2, tx.source(), content="awd rollback review", effective_to=today(tx) + DAY)
    m2.start(under_review)
    assert expire(tx) == 1
    tx.cur.execute("set local knowledge.m3_rollback_evidence_exported = 'yes'")
    with pytest.raises(psycopg.errors.RaiseException, match="in expert_review with a validity window"):
        tx.cur.execute(_without_tx_control(M3_ROLLBACK))
    tx.cur.execute("rollback to savepoint rb")
    tx.cur.execute("select to_regclass('public.knowledge_expiry_events') is not null")
    assert tx.cur.fetchone()[0] is True


def test_m3_rollback_restores_m2_and_migration_a_verbatim_and_m3_replays(tx, m2):
    _, doc, chunk = approved(tx, m2, content="awd rollback clean")
    tx.settle()
    unwind_m4(tx)
    tx.cur.execute("set local knowledge.m3_rollback_evidence_exported = 'yes'")
    tx.cur.execute(_without_tx_control(M3_ROLLBACK))
    tx.cur.execute("select count(*) from information_schema.columns where table_name = 'knowledge_documents'"
                   " and column_name in ('effective_from', 'effective_to', 'supersedes_document_pk', 'approval_expires_on')")
    assert tx.cur.fetchone()[0] == 0
    tx.cur.execute("select to_regclass('public.knowledge_expiry_events'), to_regproc('private.knowledge_expire_documents'),"
                   " to_regproc('private.knowledge_policy_date'), to_regproc('private.knowledge_supersede_for')")
    assert tx.cur.fetchone() == (None, None, None, None)
    assert _live_body(tx, "enforce_knowledge_document_immutability") == _body_in(M2, "enforce_knowledge_document_immutability")
    tx.cur.execute("select pg_get_functiondef('public.match_knowledge_chunks_lexical(uuid, text, integer)'::regprocedure)"
                   " || (select qual from pg_policies where policyname = 'knowledge_documents_select')")
    assert "effective_" not in tx.cur.fetchone()[0]
    assert chunk in tx.rpc_ids(tx.member, tx.season_a, "awd rollback clean")       # M2 behaviour again
    tx.cur.execute(M3.read_text(encoding="utf-8"))                                  # replay
    assert column(tx, doc, "approval_expires_on") == two_years_after(tx, today(tx))  # backfilled from approved_at
    assert chunk in tx.rpc_ids(tx.member, tx.season_a, "awd rollback clean")
    _, again, _ = approved(tx, m2, content="awd rollback replayed", effective_to=today(tx))
    assert tx.status_of("document", again) == "approved"

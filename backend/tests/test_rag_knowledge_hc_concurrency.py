"""RAG V1.5 H-c concurrency regressions (owner decision 2026-11-13: a real multi-connection test before
merging H-c). Each test COMMITS synthetic rows (source prefix kn-hcconc-), races two connections, and
removes them afterwards; the append-only audit events stay (local/CI database only, by design).

Races:
  1. custodian revocation vs final approval;
  2. publisher suspension vs final approval;
  3. publisher status change / binding change vs countersignature;
  4. two competing successor approvals against the same target;
  5. a stale snapshot, and a target quarantine, while an approval waits on a row lock.
Invariant in every case: no supersession commits without a countersignature that was valid when it
committed, nothing is left half-written, and no deadlock (every wait has a lock_timeout).

Every text and identity is a SYNTHETIC TEST FIXTURE on reserved test domains. dev3-01 stays OPEN.
"""

from __future__ import annotations

import hashlib
import threading
import uuid

import pytest

from tests import knowledge_status_paths as paths
from tests.test_rag_knowledge_m3_validity import authority
from tests.test_rag_knowledge_storage import CHECK_VIOLATION, _DB_URL, pytestmark, psycopg  # noqa: F401

__all__ = ["pytestmark"]

DECIDE = "select public.knowledge_decide_document(%s, %s, %s, %s)"
WAIT = 2        # seconds a blocked worker must still be blocked
TIMEOUT = 30    # seconds a released worker gets to finish


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class World:
    """Committed fixture: target source A (approved) with an approved version T, replacing source B
    (approved) with an attested successor S of T, a custodian of A who countersigned S, S under a
    recommended expert review. Optionally a second successor S2 (source C)."""

    def __init__(self, conn, *, second=False):
        self.conn = conn
        self.tag = uuid.uuid4().hex[:8]
        self.sources: list[str] = []
        self.m2 = paths.M2.of(conn)
        self.approver = uuid.uuid4()
        # outside the M2 fixture tag, so m2_cleanup keeps it until the rows it approved are gone
        conn.execute("insert into auth.users (id, email, aud, role, created_at) values (%s, %s, 'authenticated',"
                     " 'authenticated', now())", (self.approver, f"kn-hcconc-{self.tag}@agricarbon-test.invalid"))
        self.target_src = self.source("a")
        self.target = self.version(self.target_src, "target", approve=True)
        self.succ_src = self.source("b")
        self.successor, self.review = self.successor_of(self.succ_src, "successor")
        if second:
            self.second_src = self.source("c")
            self.second, self.second_review = self.successor_of(self.second_src, "second successor")

    def source(self, label):
        sid = f"kn-hcconc-{self.tag}-{label}"
        self.conn.execute("insert into public.knowledge_sources (source_id, title, owner, source_type, visibility)"
                          " values (%s, %s, 'TEST FIXTURE owner text (not an identity)', 'guideline', 'public')",
                          (sid, f"TEST FIXTURE hc concurrency {label}"))
        self.sources.append(sid)
        paths.bring(self.conn, "source", sid, "approved", approver=self.approver)
        return sid

    def version(self, sid, label, *, approve=False, supersedes=None):
        sha = _sha(sid + label)
        doc = self.conn.execute(
            "insert into public.knowledge_documents (source_id, document_id, document_version, title, language,"
            " artifact_ref, file_sha256, normalized_sha256, parser_version, normalizer_version, chunker_version,"
            " license_basis) values (%s, %s, 'v1', 'TEST FIXTURE', 'vi', %s, %s, %s, 'p', 'n', 'c',"
            " 'official_publication') returning id",
            (sid, f"doc-{label.replace(' ', '-')}", f"knowledge-artifacts/{sha}/d.md", sha, _sha(sha))).fetchone()[0]
        content = f"TEST FIXTURE awd hc concurrency {label} {self.tag}"
        self.conn.execute("insert into public.knowledge_chunks (document_pk, chunk_id, ordinal, content, content_sha256)"
                          " values (%s, %s, 0, %s, %s)", (doc, _sha(f"{doc}|{label}")[:20], content, _sha(content)))
        if supersedes:
            self.conn.execute("update public.knowledge_documents set supersedes_document_pk = %s where id = %s",
                              (supersedes, doc))
        self.m2.attest("document", doc)
        if approve:
            review = self.m2.start(doc)
            self.m2.submit(review)
            self.m2.decide(review, self.approver)
        return doc

    def successor_of(self, sid, label):
        doc = self.version(sid, label, supersedes=self.target)
        self.m2.countersign(doc)
        review = self.m2.start(doc)
        self.m2.submit(review, sources=authority(self.target))
        self.m2.role(self.approver, "approver")
        return doc, review

    def custodian_row(self):
        with psycopg.connect(_DB_URL, autocommit=True) as c:
            return c.execute("select c.id, c.publisher_id from public.knowledge_source_custodians c"
                             " where c.source_id = %s and c.status = 'active'", (self.target_src,)).fetchone()

    def snapshot(self, review):
        with psycopg.connect(_DB_URL, autocommit=True) as c:
            return c.execute("select snapshot_sha256 from public.knowledge_expert_reviews where id = %s",
                             (review,)).fetchone()[0]

    def cleanup(self):
        with psycopg.connect(_DB_URL, autocommit=True) as c:
            paths.m2_cleanup(c, self.sources)
            c.execute("alter table public.knowledge_publishers disable trigger knowledge_publishers_guard")
            try:
                c.execute("delete from public.knowledge_publishers p where p.publisher_key like %s and not exists"
                          " (select 1 from public.knowledge_source_publishers b where b.publisher_id = p.id)",
                          (f"test-fixture-{self.tag}-%",))
            finally:
                c.execute("alter table public.knowledge_publishers enable trigger knowledge_publishers_guard")
            c.execute("alter table public.knowledge_documents disable trigger knowledge_documents_immutable")
            c.execute("alter table public.knowledge_documents disable trigger knowledge_documents_zz_assurance")
            c.execute("alter table public.knowledge_sources disable trigger knowledge_sources_scope")
            c.execute("alter table public.knowledge_sources disable trigger knowledge_sources_zz_assurance")
            c.execute("alter table public.knowledge_chunks disable trigger user")
            try:
                c.execute("delete from public.knowledge_chunks where document_pk in"
                          " (select id from public.knowledge_documents where source_id = any(%s))", (self.sources,))
                c.execute("update public.knowledge_documents set supersedes_document_pk = null where source_id = any(%s)",
                          (self.sources,))
                c.execute("delete from public.knowledge_documents where source_id = any(%s)", (self.sources,))
                c.execute("delete from public.knowledge_sources where source_id = any(%s)", (self.sources,))
            finally:
                c.execute("alter table public.knowledge_chunks enable trigger user")
                c.execute("alter table public.knowledge_sources enable trigger knowledge_sources_zz_assurance")
                c.execute("alter table public.knowledge_sources enable trigger knowledge_sources_scope")
                c.execute("alter table public.knowledge_documents enable trigger knowledge_documents_zz_assurance")
                c.execute("alter table public.knowledge_documents enable trigger knowledge_documents_immutable")
            c.execute("delete from auth.mfa_factors where user_id = %s", (self.approver,))
            c.execute("delete from auth.sessions where user_id = %s", (self.approver,))
            c.execute("delete from auth.users where id = %s", (self.approver,))


@pytest.fixture
def world():
    holder = {}

    def make(**kw):
        with psycopg.connect(_DB_URL) as setup:
            w = World(setup, **kw)
            setup.commit()
        holder["w"] = w
        return w

    yield make
    if "w" in holder:
        holder["w"].cleanup()


def _run(conn, fn, outcome, key):
    def target():
        try:
            conn.execute("set lock_timeout = '20s'")
            fn()
            conn.commit()
            outcome[key] = "ok"
        except psycopg.Error as exc:
            conn.rollback()
            outcome[key] = exc.sqlstate
    worker = threading.Thread(target=target)
    worker.start()
    return worker


def _status(doc):
    with psycopg.connect(_DB_URL, autocommit=True) as c:
        return c.execute("select status::text from public.knowledge_documents where id = %s", (doc,)).fetchone()[0]


def _admin_call(w, conn, sql, params):
    paths.M2.of(conn).tag = w.m2.tag
    m = paths.M2.of(conn)
    m.admin = w.m2.admin
    return m.call(w.m2.admin, sql, params)


def _decide(w, conn, review=None, rationale="race approval"):
    review = review or w.review
    m = paths.M2.of(conn)
    return m.call(w.approver, DECIDE, (review, "approve", w.snapshot(review), rationale))


# ================================================================== 1 / 2: revocation vs approval

@pytest.mark.parametrize("change", ["custodian", "publisher"])
@pytest.mark.parametrize("first", ["revocation", "approval"])
def test_a_revocation_and_an_approval_serialize(world, change, first):
    """Whoever commits first wins; the other sees it. Revocation first: the approval is refused and
    nothing is archived. Approval first: the revocation waits for it, then applies."""
    w = world()
    custodian_id, publisher_id = w.custodian_row()
    sql, key = {"custodian": ("select public.knowledge_set_source_custodian_status(%s, 'revoked', 'TEST FIXTURE race')",
                              custodian_id),
                "publisher": ("select public.knowledge_set_publisher_status(%s, 'suspended', 'TEST FIXTURE race')",
                              publisher_id)}[change]
    outcome: dict = {}
    with psycopg.connect(_DB_URL) as a, psycopg.connect(_DB_URL) as b:
        if first == "revocation":
            _admin_call(w, a, sql, (key,))                                 # holds the registry row lock
            worker = _run(b, lambda: _decide(w, b), outcome, "approval")
        else:
            _decide(w, a)                                                  # holds share locks on the registry rows
            worker = _run(b, lambda: _admin_call(w, b, sql, (key,)), outcome, "revocation")
        worker.join(timeout=WAIT)
        assert worker.is_alive(), "the second transaction did not wait for the first one's lock"
        a.commit()
        worker.join(timeout=TIMEOUT)
        assert not worker.is_alive()
    if first == "revocation":
        assert outcome["approval"] == CHECK_VIOLATION
        assert (_status(w.target), _status(w.successor)) == ("approved", "expert_review")
    else:
        assert outcome["revocation"] == "ok"
        assert (_status(w.target), _status(w.successor)) == ("archived", "approved")


# ================================================================== 3: registry change vs countersignature

def test_a_publisher_suspension_waits_for_an_in_flight_countersignature_and_then_voids_it(world):
    w = world()
    _, publisher_id = w.custodian_row()
    # a second, fresh countersignature is in flight (holds share locks on custodian, binding, publisher)
    outcome: dict = {}
    with psycopg.connect(_DB_URL) as a, psycopg.connect(_DB_URL) as b:
        paths.M2.of(a).tag = w.m2.tag
        m = paths.M2.of(a)
        m.custodian = w.m2.custodian
        m.call(w.m2.custodian, "select public.knowledge_countersign_supersession(%s, %s, %s, %s)",
               (w.successor, m.snapshot_sha("document", w.successor), m.snapshot_sha("document", w.target),
                "TEST FIXTURE countersignature in flight during a suspension"))
        worker = _run(b, lambda: _admin_call(w, b, "select public.knowledge_set_publisher_status(%s, 'suspended',"
                                             " 'TEST FIXTURE race')", (publisher_id,)), outcome, "suspension")
        worker.join(timeout=WAIT)
        assert worker.is_alive(), "the suspension did not wait for the countersignature's share lock"
        a.commit()
        worker.join(timeout=TIMEOUT)
    assert outcome["suspension"] == "ok"
    with psycopg.connect(_DB_URL) as c:                                    # both countersignatures are now void
        with pytest.raises(psycopg.errors.CheckViolation):
            _decide(w, c)
    assert (_status(w.target), _status(w.successor)) == ("approved", "expert_review")


def test_a_binding_never_changes_even_concurrently(world):
    w = world()
    with psycopg.connect(_DB_URL) as a, psycopg.connect(_DB_URL) as b:
        other = _admin_call(w, a, "select public.knowledge_register_publisher(%s, 'TEST FIXTURE other', %s)",
                            (f"test-fixture-{w.tag}-other", "TEST FIXTURE identity evidence"))[0][0]
        a.commit()
        for conn in (a, b):
            with pytest.raises(psycopg.errors.CheckViolation):
                _admin_call(w, conn, "select public.knowledge_bind_source_publisher(%s, %s, %s)",
                            (w.target_src, other, "TEST FIXTURE rebinding attempt"))
            conn.rollback()
    with psycopg.connect(_DB_URL) as c:
        assert c.execute("select count(*) from public.knowledge_source_publishers where source_id = %s",
                         (w.target_src,)).fetchone()[0] == 1


# ================================================================== 4: competing successors

def test_two_successor_approvals_of_one_target_archive_it_exactly_once(world):
    """Both successors carry a valid countersignature: both approvals commit, the target is archived
    once (the second finds it archived, M3), one archive event, no deadlock."""
    w = world(second=True)
    outcome: dict = {}
    with psycopg.connect(_DB_URL) as a, psycopg.connect(_DB_URL) as b:
        _decide(w, a, w.review, "first successor")
        worker = _run(b, lambda: _decide(w, b, w.second_review, "second successor"), outcome, "second")
        worker.join(timeout=WAIT)
        assert worker.is_alive(), "the second approval did not wait for the target's row lock"
        a.commit()
        worker.join(timeout=TIMEOUT)
        assert not worker.is_alive()
    assert outcome["second"] == "ok"
    assert [_status(d) for d in (w.target, w.successor, w.second)] == ["archived", "approved", "approved"]
    with psycopg.connect(_DB_URL, autocommit=True) as c:
        assert c.execute("select count(*) from public.knowledge_status_events where document_pk = %s"
                         " and to_status = 'archived'", (w.target,)).fetchone()[0] == 1


# ================================================================== 5: stale snapshot / lock wait

def test_a_countersignature_racing_a_content_change_is_stale_and_supersedes_nothing(world):
    """The successor is still review_required: a chunk insert (uncommitted) and a countersignature run
    concurrently. The countersignature hashes what it can see; once the chunk commits it is stale, so
    the recommendation is refused and nothing is superseded."""
    w = world()
    with psycopg.connect(_DB_URL) as setup:
        w.conn, w.m2 = setup, paths.M2.of(setup)
        w.m2.tag = w.tag
        fresh = w.version(w.succ_src, "racing successor", supersedes=w.target)
        setup.commit()
    outcome: dict = {}
    with psycopg.connect(_DB_URL) as a, psycopg.connect(_DB_URL) as b:
        content = f"TEST FIXTURE awd racing chunk {w.tag}"
        a.execute("insert into public.knowledge_chunks (document_pk, chunk_id, ordinal, content, content_sha256)"
                  " values (%s, %s, 1, %s, %s)", (fresh, _sha(f"{fresh}|race")[:20], content, _sha(content)))
        def countersign():
            m = paths.M2.of(b)
            m.tag, m.custodian = w.m2.tag, w.m2.custodian
            m.countersign(fresh)
        worker = _run(b, countersign, outcome, "countersign")
        worker.join(timeout=TIMEOUT)
        a.commit()
    assert outcome["countersign"] == "ok"                       # it signed the content it could see
    with psycopg.connect(_DB_URL) as c:
        m = paths.M2.of(c)
        m.tag = w.m2.tag
        review = m.start(fresh)
        with pytest.raises(psycopg.errors.CheckViolation):
            m.submit(review, sources=authority(w.target))
        c.rollback()                                            # the refused recommendation and its review start
    assert (_status(w.target), _status(fresh)) == ("approved", "review_required")


def test_an_approval_waiting_on_a_target_quarantine_commits_no_wrong_supersession(world):
    """An emergency quarantine of the target holds its row lock; the approval waits in the supersession
    step, then finds the target quarantined and archives nothing; the target stays quarantined."""
    w = world()
    outcome: dict = {}
    with psycopg.connect(_DB_URL) as a, psycopg.connect(_DB_URL) as b:
        a.execute("select private.knowledge_emergency_quarantine_document(%s, 'integrity_mismatch', %s, %s)",
                  (w.target, "TEST FIXTURE quarantine during a pending approval", "TEST-FIXTURE-INC-RACE"))
        worker = _run(b, lambda: _decide(w, b), outcome, "approval")
        worker.join(timeout=WAIT)
        assert worker.is_alive(), "the approval did not wait for the quarantine's row lock"
        a.commit()
        worker.join(timeout=TIMEOUT)
        assert not worker.is_alive()
    assert outcome["approval"] == "ok"
    assert (_status(w.target), _status(w.successor)) == ("quarantined", "approved")
    with psycopg.connect(_DB_URL, autocommit=True) as c:
        assert c.execute("select count(*) from public.knowledge_status_events where document_pk = %s"
                         " and to_status = 'archived'", (w.target,)).fetchone()[0] == 0

"""Shared by the knowledge DB tests: how a fixture row legally reaches a status under RAG V1.5 M1
(migration 20261110090100) and M2 (20261110120000). A row is inserted `review_required` and every
later status is a controlled, audited transition. Document versions pass expert_review before
approval (D3); sources approve directly.

M2: the transitions a verified human decides (document -> expert_review, expert_review -> approved |
review_required, source -> approved) are refused to the operator functions. `transition()` performs
them through the real M2 RPCs, as SYNTHETIC TEST FIXTURE personnel: Supabase Auth users inserted by
the test owner, each with a verified MFA factor and a live aal2 session, registered by a synthetic
registry admin, calling as `authenticated` with the claims PostgREST would set. These identities are
test fixtures, never real people, and exist only in a local/CI database. `db` is a psycopg connection
or cursor of the operator / table owner (the test login).
"""

from __future__ import annotations

import json
import time
import uuid
import weakref

from knowledge.integrity.claims import CLAIM_EXTRACTOR_VERSION
from knowledge.integrity.review import REVIEW_VERSION

TRANSITION = {
    "source": "select private.knowledge_transition_source(%s, %s::public.knowledge_status,"
              " %s::public.knowledge_status, %s, %s)",
    "document": "select private.knowledge_transition_document(%s, %s::public.knowledge_status,"
                " %s::public.knowledge_status, %s, %s)",
}

_APPROVE_SOURCE = [("review_required", "approved")]
SOURCE_PATH = {
    "review_required": [],
    "rejected": [("review_required", "rejected")],
    "approved": _APPROVE_SOURCE,
    "archived": _APPROVE_SOURCE + [("approved", "archived")],
    "quarantined": _APPROVE_SOURCE + [("approved", "quarantined")],
}
_APPROVE_DOCUMENT = [("review_required", "expert_review"), ("expert_review", "approved")]
DOCUMENT_PATH = {
    "review_required": [],
    "rejected": [("review_required", "rejected")],
    "expert_review": [("review_required", "expert_review")],
    "approved": _APPROVE_DOCUMENT,
    "archived": _APPROVE_DOCUMENT + [("approved", "archived")],
    "quarantined": _APPROVE_DOCUMENT + [("approved", "quarantined")],
}

#: Transitions only a verified human makes (M2 RPCs); every other one stays an operator transition.
M2_OWNED = {("document", "review_required", "expert_review"), ("document", "expert_review", "approved"),
            ("document", "expert_review", "review_required"), ("source", "review_required", "approved"),
            ("source", "rejected", "approved")}

#: H-b (20261113120000): quarantine is an emergency action with evidence (service_role / owner), archive a
#: verified archivist's decision. `transition()` performs them through those functions.
HB_OWNED = {("document", "approved", "quarantined"), ("source", "approved", "quarantined"),
            ("document", "approved", "archived"), ("source", "approved", "archived"),
            ("document", "quarantined", "archived"), ("source", "quarantined", "archived")}
EMERGENCY = {"document": "select private.knowledge_emergency_quarantine_document(%s, %s, %s, %s)",
             "source": "select private.knowledge_emergency_quarantine_source(%s, %s, %s, %s)"}
#: Synthetic operator reference of fixture quarantines (not a real ticket).
FIXTURE_TICKET = "TEST-FIXTURE-INCIDENT-0000"

def event_reason(frm, to, reason):
    """The reason `transition()` leaves in knowledge_status_events for this step: H-b prefixes the
    emergency and archive reasons with their reason code."""
    if to == "quarantined" and frm == "approved":
        return f"EMERGENCY operator_error_containment [{FIXTURE_TICKET}]: TEST FIXTURE emergency quarantine: {reason}"[:2000]
    if to == "archived":
        return f"ARCHIVE retention_policy: TEST FIXTURE archive rationale: {reason}"[:2000]
    return reason


_REGISTRY = {}
_VERIFIER = {}


def test_verifier_key():
    """(key_id, Ed25519 private key): generated once per test process, held only in memory (never written)."""
    if "k" not in _VERIFIER:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        _VERIFIER["k"] = (f"test-fixture-verifier-{uuid.uuid4().hex[:12]}", Ed25519PrivateKey.generate())
    return _VERIFIER["k"]


def integrity_registry():
    """The committed reference registry (the one the E2 policy pins in tests)."""
    if "r" not in _REGISTRY:
        from pathlib import Path

        from knowledge.integrity.references import load_registry
        path = Path(__file__).resolve().parent.parent / "knowledge" / "integrity" / "reference_registry.json"
        _REGISTRY["r"] = load_registry(json.loads(path.read_text(encoding="utf-8")))
    return _REGISTRY["r"]


#: Marks the synthetic auth.sessions / auth.mfa_factors rows these helpers insert (m2_cleanup removes them).
FIXTURE_TAG = "TEST FIXTURE m2"

#: A complete, all-true expert checklist (synthetic fixture evidence).
CHECKLIST = {"provenance_verified": True, "artifact_sha256_verified": True, "license_verified": True,
             "version_and_dates_checked": True, "scope_checked": True, "claims_checked": True}
SOURCES_CHECKED = [{"reference": "TEST FIXTURE reference (synthetic)"}]


def _conn(db):
    return getattr(db, "connection", db)


def status_of(db, kind, key):
    table, column = ("knowledge_sources", "source_id") if kind == "source" else ("knowledge_documents", "id")
    row = db.execute(f"select status::text from public.{table} where {column} = %s", (key,)).fetchone()
    return row[0] if row else None


def transition(db, kind, key, frm, to, *, reason="fixture", approver=None):
    """One controlled transition; returns its event id. `approver` names the approver of an approval
    (for an M2 approval it becomes a synthetic verified approver if it is not one yet). A transition
    a human decides goes through the M2 RPCs; a malformed or stale request goes to the operator function,
    which refuses it exactly as in M1 (22023 / 23514)."""
    if (kind, frm, to) in M2_OWNED and (to == "approved") == (approver is not None) \
            and status_of(db, kind, key) == frm:
        return M2.of(db).step(kind, key, frm, to, reason=reason, approver=approver)
    if (kind, frm, to) in HB_OWNED and approver is None and reason and reason.strip() and len(reason) <= 2000 \
            and status_of(db, kind, key) == frm:
        if to == "quarantined":
            evidence = db.execute(EMERGENCY[kind], (key, "operator_error_containment",
                                                    f"TEST FIXTURE emergency quarantine: {reason}"[:2000],
                                                    FIXTURE_TICKET)).fetchone()[0]
            return db.execute("select status_event_id from public.knowledge_emergency_actions where id = %s",
                              (evidence,)).fetchone()[0]
        return M2.of(db).archive(kind, key, reason=reason)
    return db.execute(TRANSITION[kind], (key, frm, to, reason, approver)).fetchone()[0]


def bring(db, kind, key, status, *, approver=None, reason="fixture"):
    """Move a freshly inserted (review_required) row to `status` along the legal path."""
    for frm, to in (SOURCE_PATH if kind == "source" else DOCUMENT_PATH)[status]:
        if to == "approved" and approver is None:
            raise ValueError("an approval names its approver")
        transition(db, kind, key, frm, to, reason=reason, approver=approver if to == "approved" else None)


class M2:
    """Synthetic M2 personnel bound to one test connection: a registry admin, an uploader and an expert
    reviewer (fresh auth users), plus any approver a test names. Stateless apart from the user ids:
    every row is looked up again before use, so a rolled-back savepoint never leaves a stale cache."""

    _by_conn: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()

    def __init__(self, db):
        self.db = db
        self.tag = uuid.uuid4().hex[:8]
        self.admin = uuid.uuid4()
        self.uploader = uuid.uuid4()
        self.reviewer = uuid.uuid4()
        self.archivist = uuid.uuid4()
        self.custodian = uuid.uuid4()

    @classmethod
    def of(cls, db) -> "M2":
        conn = _conn(db)
        found = cls._by_conn.get(conn)
        if found is None:
            found = cls._by_conn[conn] = cls(db)
        found.db = db
        return found

    # -- identities ---------------------------------------------------------------------------

    def user(self, uid=None, *, label="person", mfa=True, aal="aal2"):
        """A synthetic auth user (created if missing) with a verified TOTP factor and a live session
        at `aal`; returns (uid, session_id)."""
        uid = uid or uuid.uuid4()
        self.db.execute("insert into auth.users (id, email, aud, role, created_at) values (%s, %s, 'authenticated',"
                        " 'authenticated', now()) on conflict (id) do nothing",
                        (uid, f"kn-m2-{self.tag}-{label}-{uuid.UUID(str(uid)).hex[:8]}@agricarbon-test.invalid"))
        if mfa and not self.db.execute("select 1 from auth.mfa_factors where user_id = %s and status = 'verified'",
                                       (uid,)).fetchone():
            self.db.execute("insert into auth.mfa_factors (id, user_id, friendly_name, factor_type, status, created_at,"
                            " updated_at) values (%s, %s, %s, 'totp', 'verified', now(), now())",
                            (uuid.uuid4(), uid, f"TEST FIXTURE totp {uuid.uuid4().hex[:6]}"))
        row = self.db.execute("select id from auth.sessions where user_id = %s and aal = %s::auth.aal_level"
                              " and (not_after is null or not_after > now()) order by created_at limit 1",
                              (uid, aal)).fetchone()
        if row:
            return uid, row[0]
        sid = uuid.uuid4()
        self.db.execute("insert into auth.sessions (id, user_id, aal, created_at, updated_at, tag)"
                        " values (%s, %s, %s::auth.aal_level, now(), now(), %s)", (sid, uid, aal, FIXTURE_TAG))
        return uid, sid

    def claims(self, uid, sid, **extra):
        return {"sub": str(uid), "role": "authenticated", "aal": "aal2", "session_id": str(sid),
                "exp": int(time.time()) + 3600, **extra}

    def call(self, uid, sql, params=(), *, claims=None, role="authenticated"):
        """Run `sql` as `role` with the claims of `uid`'s aal2 session (PostgREST's view of a signed-in,
        MFA-verified user), isolated in a savepoint; returns fetchall(). Errors propagate."""
        if claims is None:
            claims = self.claims(uid, self.user(uid)[1])
        conn = _conn(self.db)
        with conn.transaction():
            cur = conn.cursor()
            cur.execute(f"set local role {role}")
            cur.execute("select set_config('request.jwt.claims', %s, true)", (json.dumps(claims),))
            cur.execute(sql, params)
            rows = cur.fetchall() if cur.description else []
            cur.execute("reset role")
            cur.execute("select set_config('request.jwt.claims', '', true)")
        return rows

    def ensure_admin(self):
        self.user(self.admin, label="admin")
        self.db.execute("insert into public.knowledge_registry_admins (auth_user_id, note) values (%s, %s)"
                        " on conflict (auth_user_id) do nothing",
                        (self.admin, f"TEST FIXTURE registry admin TEST-FIXTURE-M2-{self.tag}"))
        return self.admin

    def person(self, uid, *, label="person"):
        """The personnel id of `uid` (registered by the synthetic admin if needed)."""
        self.user(uid, label=label)
        row = self.db.execute("select id from public.knowledge_personnel where auth_user_id = %s", (uid,)).fetchone()
        if row:
            return row[0]
        self.ensure_admin()
        return self.call(self.admin, "select public.knowledge_register_personnel(%s, %s, %s, 'in_person', %s, null)",
                         (uid, f"TEST FIXTURE {label}", f"TEST-FIXTURE-M2-{self.tag}-{uuid.UUID(str(uid)).hex[:12]}",
                          "TEST FIXTURE identity evidence (synthetic)"))[0][0]

    def role(self, uid, role, visibility="public", org=None, *, label=None):
        """The active role id of `uid` for `role` in this scope (granted if needed)."""
        person = self.person(uid, label=label or role)
        row = self.db.execute("select id from public.knowledge_personnel_roles where personnel_id = %s and role = %s"
                              " and scope_visibility = %s and scope_organization_id is not distinct from %s"
                              " and status = 'active'", (person, role, visibility, org)).fetchone()
        if row:
            return row[0]
        self.ensure_admin()
        return self.call(self.admin, "select public.knowledge_grant_personnel_role(%s, %s, %s, %s, %s,"
                         " 'credential_document_checked', %s, null)",
                         (person, role, visibility, org, "test_fixture_domain",
                          "TEST FIXTURE qualification evidence (synthetic)"))[0][0]

    def scope(self, kind, key):
        sql = ("select visibility, organization_id from public.knowledge_sources where source_id = %s" if kind == "source"
               else "select s.visibility, s.organization_id from public.knowledge_documents d"
                    " join public.knowledge_sources s on s.source_id = d.source_id where d.id = %s")
        return self.db.execute(sql, (key,)).fetchone()

    def snapshot_sha(self, kind, key):
        fn = "private.knowledge_document_snapshot(%s::uuid)" if kind == "document" else \
            "private.knowledge_source_snapshot(%s::text)"
        return self.db.execute(f"select private.knowledge_snapshot_sha256({fn})", (key,)).fetchone()[0]

    # -- the M2 flow ----------------------------------------------------------------------------

    def attest(self, kind, key, uploader=None):
        uploader = uploader or self.uploader
        if kind == "document":
            if self.db.execute("select 1 from public.knowledge_upload_attestations where document_pk = %s",
                               (key,)).fetchone():
                return None
            self.role(uploader, "uploader", *self.scope(kind, key))
            sha, norm = self.db.execute("select file_sha256, normalized_sha256 from public.knowledge_documents"
                                        " where id = %s", (key,)).fetchone()
            return self.call(uploader, "select public.knowledge_attest_document_upload(%s, %s, %s, %s)",
                             (key, sha, norm, "TEST FIXTURE: I ingested this version"))[0][0]
        if self.db.execute("select 1 from public.knowledge_upload_attestations where entity_type = 'source'"
                           " and source_id = %s", (key,)).fetchone():
            return None
        self.role(uploader, "uploader", *self.scope(kind, key))
        return self.call(uploader, "select public.knowledge_attest_source_upload(%s, %s)",
                         (key, "TEST FIXTURE: I registered this source"))[0][0]

    def start(self, doc, reviewer=None, reason="fixture"):
        reviewer = reviewer or self.reviewer
        self.attest("document", doc)
        self.role(reviewer, "expert_reviewer", *self.scope("document", doc))
        sha = self.db.execute("select file_sha256 from public.knowledge_documents where id = %s", (doc,)).fetchone()[0]
        return self.call(reviewer, "select public.knowledge_start_expert_review(%s, %s, %s)", (doc, sha, reason))[0][0]

    def current_review(self, doc):
        return self.db.execute("select id, decision, reviewer_user_id, snapshot_sha256 from public.knowledge_expert_reviews"
                               " where document_pk = %s order by seq desc limit 1", (doc,)).fetchone()

    # -- M7 E2: integrity report, acknowledgement ----------------------------------------------------

    def pin_integrity_policy(self):
        """Pin the committed registry, extractor and review versions (owner; rolled back with the test, or
        committed by a test that commits its fixtures: same values)."""
        reg = integrity_registry()
        self.db.execute("select private.knowledge_set_integrity_policy(%s, %s, %s, %s)",
                        (CLAIM_EXTRACTOR_VERSION, REVIEW_VERSION, reg.registry_version, reg.digest))

    def integrity_report(self, doc):
        """Record the integrity report of `doc` through the operator path; returns (report_id, report_sha256)."""
        from datetime import date

        from infrastructure.knowledge_claims_repo import PsycopgClaimStore, record_integrity_report
        if self.db.execute("select registry_digest from private.knowledge_integrity_policy").fetchone()[0] is None:
            self.pin_integrity_policy()
        report = record_integrity_report(PsycopgClaimStore(_conn(self.db)), str(doc), integrity_registry(),
                                         as_of=date.today())
        sha = self.db.execute("select report_sha256 from public.knowledge_integrity_reports where id = %s",
                              (report,)).fetchone()[0]
        return report, sha

    def acknowledge(self, review, *, reviewer=None):
        """The reviewer acknowledges the CURRENT report of the review's version (recorded if missing). Blocking
        findings are NOT dispositioned here: a test that needs them resolved does it explicitly."""
        doc, uid = self.db.execute("select document_pk, reviewer_user_id from public.knowledge_expert_reviews"
                                   " where id = %s", (review,)).fetchone()
        current = self.db.execute("select r.id, r.report_sha256 from private.knowledge_integrity_current_report(%s) r"
                                  " where r.id is not null and private.knowledge_integrity_report_problem(r) is null",
                                  (doc,)).fetchone()
        report, sha = current if current else self.integrity_report(doc)
        if not self.db.execute("select 1 from public.knowledge_integrity_dispositions where review_id = %s and"
                               " report_id = %s and finding_id is null", (review, report)).fetchone():
            self.dispose(review, sha, None, "report_reviewed", reviewer=reviewer or uid)
        self.verify_report(report)
        return report, sha

    # -- M7 E7: independent, signed verification ------------------------------------------------------

    def verify_report(self, report):
        """The independent verifier (a synthetic test key, generated in this process, never stored) re-reads
        the chunks and signs; the owner pins the code digest and registers the key in the test transaction."""
        if not self.db.execute("select to_regclass('public.knowledge_integrity_verifications') is not null").fetchone()[0]:
            return None
        if self.db.execute("select 1 from public.knowledge_integrity_verifications where report_id = %s"
                           " and verdict = 'reproduced'", (report,)).fetchone():
            return None
        from infrastructure import integrity_verifier
        key_id, key = test_verifier_key()
        self.ensure_verifier(key_id, key)
        return integrity_verifier.verify(self.db, self.db, str(report), key, key_id)

    def ensure_verifier(self, key_id, key):
        from infrastructure.integrity_verifier import extractor_code_digest, public_key_bytes
        if self.db.execute("select extractor_code_digest from private.knowledge_integrity_policy").fetchone()[0] is None:
            self.db.execute("select private.knowledge_set_integrity_code_digest(%s)", (extractor_code_digest(),))
        if not self.db.execute("select 1 from public.knowledge_integrity_verifier_keys where key_id = %s", (key_id,)).fetchone():
            self.db.execute("select private.knowledge_register_verifier_key(%s, %s, %s)",
                            (key_id, public_key_bytes(key), "TEST FIXTURE verifier (synthetic key, local/CI only)"))

    def dispose(self, review, sha, finding, disposition, *, reviewer=None, justification=None, evidence=None):
        uid = reviewer or self.db.execute("select reviewer_user_id from public.knowledge_expert_reviews where id = %s",
                                          (review,)).fetchone()[0]
        return self.call(uid, "select public.knowledge_dispose_integrity_finding(%s, %s, %s, %s, %s, %s::jsonb)",
                         (review, sha, finding, disposition,
                          justification or "TEST FIXTURE: the expert read the integrity report of this version",
                          json.dumps(evidence or [])))[0][0]

    def submit(self, review, decision="recommend_approval", *, checklist=None, sources=None, findings=None,
               rationale="TEST FIXTURE expert rationale", reviewer=None, snapshot_sha256=None, integrity=True):
        row = self.db.execute("select reviewer_user_id, snapshot_sha256 from public.knowledge_expert_reviews"
                              " where id = %s", (review,)).fetchone()
        if integrity and decision == "recommend_approval" and self.db.execute(
                "select to_regclass('public.knowledge_integrity_reports') is not null").fetchone()[0]:
            self.acknowledge(review, reviewer=row[0])                  # E2 installed (not after its rollback)
        return self.call(reviewer or row[0], "select public.knowledge_submit_expert_review(%s, %s, %s, %s, %s, %s, %s)",
                         (review, decision, snapshot_sha256 or row[1],
                          json.dumps(CHECKLIST if checklist is None else checklist),
                          json.dumps(SOURCES_CHECKED if sources is None else sources),
                          json.dumps([] if findings is None else findings), rationale))[0][0]

    def decide(self, review, approver, decision="approve", rationale="fixture", snapshot_sha256=None):
        doc = self.db.execute("select document_pk, snapshot_sha256 from public.knowledge_expert_reviews where id = %s",
                              (review,)).fetchone()
        self.role(approver, "approver", *self.scope("document", doc[0]))
        return self.call(approver, "select public.knowledge_decide_document(%s, %s, %s, %s)",
                         (review, decision, snapshot_sha256 or doc[1], rationale))[0][0]

    def approve_source(self, source_id, approver, rationale="fixture"):
        self.attest("source", source_id)
        self.role(approver, "approver", *self.scope("source", source_id))
        return self.call(approver, "select public.knowledge_approve_source(%s, %s, %s)",
                         (source_id, self.snapshot_sha("source", source_id), rationale))[0][0]

    def archive(self, kind, key, *, reason="fixture", archivist=None, reason_code="retention_policy"):
        """H-b: archive `key` as a synthetic archivist (never its uploader or approver); returns the event id."""
        archivist = archivist or self.archivist
        self.role(archivist, "archivist", *self.scope(kind, key))
        fn = "public.knowledge_archive_document(%s::uuid" if kind == "document" else "public.knowledge_archive_source(%s::text"
        record = self.call(archivist, f"select {fn}, %s, %s, %s)",
                           (key, self.snapshot_sha(kind, key), reason_code,
                            f"TEST FIXTURE archive rationale: {reason}"[:2000]))[0][0]
        return self.db.execute("select status_event_id from public.knowledge_archive_records where id = %s",
                               (record,)).fetchone()[0]

    def publisher_for(self, source_id):
        """H-c: the verified publisher a synthetic registry admin bound `source_id` to (bound if needed)."""
        row = self.db.execute("select publisher_id from public.knowledge_source_publishers where source_id = %s",
                              (source_id,)).fetchone()
        if row:
            return row[0]
        self.ensure_admin()
        publisher = self.call(self.admin, "select public.knowledge_register_publisher(%s, %s, %s)",
                              (f"test-fixture-{self.tag}-{uuid.uuid4().hex[:8]}", "TEST FIXTURE publisher (synthetic)",
                               "TEST FIXTURE identity evidence (synthetic)"))[0][0]
        self.call(self.admin, "select public.knowledge_bind_source_publisher(%s, %s, %s)",
                  (source_id, publisher, "TEST FIXTURE ownership evidence (synthetic)"))
        return publisher

    def custody(self, uid, source_id):
        """H-c: the active custodian assignment of `uid` for `source_id` (granted if needed)."""
        person = self.person(uid, label="custodian")
        self.publisher_for(source_id)
        row = self.db.execute("select id from public.knowledge_source_custodians where personnel_id = %s"
                              " and source_id = %s and status = 'active'", (person, source_id)).fetchone()
        if row:
            return row[0]
        self.ensure_admin()
        return self.call(self.admin, "select public.knowledge_grant_source_custodian(%s, %s, %s)",
                         (person, source_id, "TEST FIXTURE custodian evidence (synthetic)"))[0][0]

    def countersign(self, successor, custodian=None, *, successor_sha=None, target_sha=None):
        """H-c: a custodian of the superseded version's source countersigns replacing it with `successor`."""
        custodian = custodian or self.custodian
        target, target_source = self.db.execute(
            "select t.id, t.source_id from public.knowledge_documents d join public.knowledge_documents t"
            " on t.id = d.supersedes_document_pk where d.id = %s", (successor,)).fetchone()
        self.custody(custodian, target_source)
        return self.call(custodian, "select public.knowledge_countersign_supersession(%s, %s, %s, %s)",
                         (successor, successor_sha or self.snapshot_sha("document", successor),
                          target_sha or self.snapshot_sha("document", target),
                          "TEST FIXTURE countersignature: the custodian authorizes this replacement"))[0][0]

    def step(self, kind, key, frm, to, *, reason, approver):
        """One M2-owned transition; returns its audit event id."""
        if kind == "source":
            record = self.approve_source(key, approver, reason)
            return self.db.execute("select status_event_id from public.knowledge_approval_records where id = %s",
                                   (record,)).fetchone()[0]
        if to == "expert_review":
            review = self.start(key, reason=reason)
            return self.db.execute("select start_event_id from public.knowledge_expert_reviews where id = %s",
                                   (review,)).fetchone()[0]
        review, decision, _, _ = self.current_review(key)
        if to == "review_required":
            self.submit(review, "return", rationale=reason)
            return self.db.execute("select decision_event_id from public.knowledge_expert_reviews where id = %s",
                                   (review,)).fetchone()[0]
        if decision is None:
            self.submit(review)
        record = self.decide(review, approver, "approve", reason)
        return self.db.execute("select status_event_id from public.knowledge_approval_records where id = %s",
                               (record,)).fetchone()[0]


M2_EVIDENCE_TRIGGERS = {
    "knowledge_approval_records": "knowledge_approval_records_guard",
    "knowledge_expert_reviews": "knowledge_expert_reviews_guard",
    "knowledge_upload_attestations": "knowledge_upload_attestations_guard",
    "knowledge_personnel_roles": "knowledge_personnel_roles_guard",
    "knowledge_personnel": "knowledge_personnel_guard",
    "knowledge_registry_admins": "knowledge_registry_admins_guard",
}


HC_EVIDENCE_TRIGGERS = {
    "knowledge_supersession_authorizations": "knowledge_supersession_authorizations_guard",
    "knowledge_source_custodians": "knowledge_source_custodians_guard",
    "knowledge_source_publishers": "knowledge_source_publishers_guard",
    "knowledge_publishers": "knowledge_publishers_guard",
}
E7_EVIDENCE_TRIGGERS = {"knowledge_integrity_verifications": "knowledge_integrity_verifications_guard"}
E2_EVIDENCE_TRIGGERS = {
    "knowledge_integrity_dispositions": "knowledge_integrity_dispositions_guard",
    "knowledge_integrity_findings": "knowledge_integrity_findings_guard",
    "knowledge_integrity_reports": "knowledge_integrity_reports_guard",
}
HB_EVIDENCE_TRIGGERS = {
    "knowledge_emergency_actions": "knowledge_emergency_actions_guard",
    "knowledge_archive_records": "knowledge_archive_records_guard",
}


def m2_cleanup(conn, sources):
    """Owner-only teardown for tests that COMMIT synthetic knowledge: removes the M2 evidence of these
    sources (which otherwise blocks deleting them: evidence is immutable and FK-restricted) and the
    synthetic M2 personnel/users of the same fixture tags. Evidence is undeletable by design; a test
    owner lifts that only here, on a local/CI database."""
    sources = list(sources)
    hb = conn.execute("select to_regclass('public.knowledge_archive_records') is not null").fetchone()[0]
    hc = conn.execute("select to_regclass('public.knowledge_supersession_authorizations') is not null").fetchone()[0]
    e2 = conn.execute("select to_regclass('public.knowledge_integrity_reports') is not null").fetchone()[0]
    e7 = conn.execute("select to_regclass('public.knowledge_integrity_verifications') is not null").fetchone()[0]
    triggers = dict(M2_EVIDENCE_TRIGGERS, **(HB_EVIDENCE_TRIGGERS if hb else {}), **(HC_EVIDENCE_TRIGGERS if hc else {}),
                    **(E2_EVIDENCE_TRIGGERS if e2 else {}), **(E7_EVIDENCE_TRIGGERS if e7 else {}))
    tags = [r[0] for r in conn.execute(
        "select distinct substring(p.identity_reference from '^TEST-FIXTURE-M2-([0-9a-f]{8})-')"
        " from public.knowledge_personnel p where p.id in ("
        "  select uploader_personnel_id from public.knowledge_upload_attestations where source_id = any(%(s)s)"
        "  union select reviewer_personnel_id from public.knowledge_expert_reviews where source_id = any(%(s)s)"
        "  union select approver_personnel_id from public.knowledge_approval_records where source_id = any(%(s)s)"
        + ("  union select archivist_personnel_id from public.knowledge_archive_records where source_id = any(%(s)s)"
           if hb else "")
        + ("  union select custodian_personnel_id from public.knowledge_supersession_authorizations"
           "   where target_source_id = any(%(s)s) or successor_source_id = any(%(s)s)"
           "  union select personnel_id from public.knowledge_source_custodians where source_id = any(%(s)s)"
           if hc else "") + ")",
        {"s": sources}).fetchall() if r[0]]
    users = [r[0] for r in conn.execute(
        "select auth_user_id from public.knowledge_personnel where identity_reference like any(%s)",
        ([f"TEST-FIXTURE-M2-{t}-%" for t in tags],)).fetchall()]
    # synthetic factors/sessions (GoTrue cannot load a user holding a factor it did not create)
    conn.execute("delete from auth.mfa_factors where user_id = any(%s) and friendly_name like 'TEST FIXTURE totp%%'",
                 (users,))
    conn.execute("delete from auth.sessions where user_id = any(%s) and tag = %s", (users, FIXTURE_TAG))
    for table, trigger in triggers.items():
        conn.execute(f"alter table public.{table} disable trigger {trigger}")
    try:
        if e7:
            conn.execute("delete from public.knowledge_integrity_verifications where report_id in (select id from"
                         " public.knowledge_integrity_reports where source_id = any(%(s)s))", {"s": sources})
        if e2:
            conn.execute("delete from public.knowledge_integrity_dispositions where report_id in (select id from"
                         " public.knowledge_integrity_reports where source_id = any(%(s)s))", {"s": sources})
            conn.execute("delete from public.knowledge_integrity_findings where report_id in (select id from"
                         " public.knowledge_integrity_reports where source_id = any(%(s)s))", {"s": sources})
            conn.execute("delete from public.knowledge_integrity_reports where source_id = any(%(s)s)", {"s": sources})
        if hc:
            publishers = [r[0] for r in conn.execute(
                "select publisher_id from public.knowledge_source_publishers where source_id = any(%s)", (sources,))]
            conn.execute("delete from public.knowledge_supersession_authorizations where target_source_id = any(%(s)s)"
                         " or successor_source_id = any(%(s)s)", {"s": sources})
            for table in ("knowledge_source_custodians", "knowledge_source_publishers"):
                conn.execute(f"delete from public.{table} where source_id = any(%s)", (sources,))
            conn.execute("delete from public.knowledge_publishers where id = any(%s) and publisher_key like 'test-fixture-%%'"
                         " and not exists (select 1 from public.knowledge_source_publishers b where b.publisher_id = id)",
                         (publishers,))
        for table in (("knowledge_emergency_actions", "knowledge_archive_records") if hb else ()) + (
                "knowledge_approval_records", "knowledge_expert_reviews", "knowledge_upload_attestations"):
            conn.execute(f"delete from public.{table} where source_id = any(%(s)s)", {"s": sources})
        for tag in tags:
            like = f"TEST-FIXTURE-M2-{tag}-%"
            conn.execute("delete from public.knowledge_personnel_roles where personnel_id in"
                         " (select id from public.knowledge_personnel where identity_reference like %s)", (like,))
            conn.execute("delete from public.knowledge_personnel where identity_reference like %s", (like,))
            conn.execute("delete from public.knowledge_registry_admins where note like %s",
                         (f"%TEST-FIXTURE-M2-{tag}",))
            conn.execute("delete from auth.users where email like %s", (f"kn-m2-{tag}-%@agricarbon-test.invalid",))
    finally:
        for table, trigger in triggers.items():
            conn.execute(f"alter table public.{table} enable trigger {trigger}")

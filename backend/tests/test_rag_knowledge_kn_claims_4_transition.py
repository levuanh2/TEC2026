"""The kn-claims-3 -> kn-claims-4 extractor transition (#87 on the #84 stack): the owner re-pin, the reports and
verifications made before it, and the spelled-zero poison that kn-claims-3 missed.

kn-claims-4 differs from kn-claims-3 in one rule only: a zero written as a word ("bằng không") is no longer read as
a negator. For the fixture text below, kn-claims-3's output is therefore exactly kn-claims-4's output without the
elimination assertion (claim ids depend on document, chunk, span and kind, not on the version). `kn3_report`
stores that set under the old version label and an old pin, as a database that ran kn-claims-3 would hold it.

Every text and identity is a SYNTHETIC TEST FIXTURE. One transaction per test, rolled back. Skipped without
SUPABASE_DB_URL. Nothing here approves real knowledge. dev3-01 stays OPEN.
"""

from __future__ import annotations

import json

import pytest

from infrastructure import integrity_verifier as iv
from infrastructure.knowledge_claims_repo import PsycopgClaimStore
from knowledge.integrity.claims import CLAIM_EXTRACTOR_VERSION, extract_claims
from tests import knowledge_status_paths as paths
from tests.test_rag_knowledge_m2_approval import as_role, code, draft, m2  # noqa: F401
from tests.test_rag_knowledge_storage import CHECK_VIOLATION, PERMISSION_DENIED, pytestmark, tx  # noqa: F401

__all__ = ["pytestmark", "tx", "m2"]

OLD = "kn-claims-3"
OLD_DIGEST = "3" * 64          # stands for the kn-claims-3 manifest digest (that code is not in this tree)
SPELLED_ZERO = "TEST FIXTURE: giữ mực nước 5 cm khi tưới. Áp dụng AWD một vụ thì phát thải khí mê-tan bằng không."
RECORD_REPORT = "select private.knowledge_record_integrity_report(%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)"
LIMITS = json.dumps(["TEST FIXTURE: the operator's own limitation statement"])


def pin(tx, version, digest):
    """The owner's pin (database owner only): extractor version + review + registry, then the code digest."""
    reg = paths.integrity_registry()
    tx.cur.execute("select private.knowledge_set_integrity_policy(%s, %s, %s, %s)",
                   (version, paths.REVIEW_VERSION, reg.registry_version, reg.digest))
    tx.cur.execute("select private.knowledge_set_integrity_code_digest(%s)", (digest,))


def kn3_report(tx, doc):
    """The claims and report a kn-claims-3 pipeline recorded for `doc` (see the module docstring)."""
    store = PsycopgClaimStore(tx.cur.connection)
    claims = [c for s in store.chunk_sources(str(doc)) for c in extract_claims(s) if c.kind != "assertion"]
    store.record_claims(str(doc), claims, OLD)
    findings = [{"finding_type": "unresolved_claim", "claim_ids": [c.claim_id], "detail": "TEST FIXTURE finding"}
                for c in claims if c.status != "extracted"]
    reg = paths.integrity_registry()
    tx.cur.execute(RECORD_REPORT, (doc, OLD, paths.REVIEW_VERSION, reg.registry_version, reg.digest,
                                   json.dumps(findings), "[]", LIMITS))
    report = tx.cur.fetchone()[0]
    tx.cur.execute("select report_sha256 from public.knowledge_integrity_reports where id = %s", (report,))
    return report, tx.cur.fetchone()[0], len(claims)


def claim_counts(tx, doc):
    tx.cur.execute("select extractor_version, count(*) from public.knowledge_claims where document_pk = %s"
                   " group by 1", (doc,))
    return dict(tx.cur.fetchall())


def problem(tx, report):
    tx.cur.execute("select private.knowledge_integrity_report_problem(r) from public.knowledge_integrity_reports r"
                   " where r.id = %s", (report,))
    return tx.cur.fetchone()[0]


def old_pin_review(tx, m2):
    """A version under review while the owner's pin is still kn-claims-3; the reviewer read its kn-claims-3 report."""
    _, doc = draft(tx, m2, content=SPELLED_ZERO)
    review = m2.start(doc)
    pin(tx, OLD, OLD_DIGEST)
    report, sha, n = kn3_report(tx, doc)
    assert n >= 1                                                      # kn-claims-3 stored real rows
    m2.dispose(review, sha, None, "report_reviewed")
    return doc, review, report, n


def test_the_fixture_is_exactly_what_kn_claims_3_missed():
    from knowledge.integrity.claims import ClaimSource
    found = [c.parameter for c in extract_claims(ClaimSource("src/doc@1", "c1", SPELLED_ZERO)) if c.kind == "assertion"]
    assert CLAIM_EXTRACTOR_VERSION == "kn-claims-4" and found == ["ch4.rice.emission_eliminated"]


def test_under_the_kn_claims_3_pin_a_kn_claims_4_process_neither_reports_nor_signs(tx, m2):
    doc, review, report, _ = old_pin_review(tx, m2)
    assert problem(tx, report) is None                               # the old report is valid under the old pin
    # the kn-claims-4 operator pipeline cannot record a report against the kn-claims-3 pin
    assert code(m2.integrity_report, doc) == CHECK_VIOLATION
    # and the kn-claims-4 verifier refuses to sign: its manifest is not the pinned one
    key_id, key = paths.test_verifier_key()
    m2.ensure_verifier(key_id, key)
    with pytest.raises(iv.PinMismatch):
        m2.as_verifier(lambda: iv.verify(tx.cur, tx.cur, str(report), key, key_id))
    # no independent verification -> the review cannot recommend approval (E7 fails closed)
    assert code(m2.submit, review, integrity=False) == CHECK_VIOLATION
    assert tx.status_of("document", doc) != "approved"


def test_the_re_pin_retires_the_old_report_and_the_spelled_zero_poison_now_blocks(tx, m2):
    doc, review, old_report, n = old_pin_review(tx, m2)
    pin(tx, CLAIM_EXTRACTOR_VERSION, iv.extractor_code_digest())     # the owner moves the pin to kn-claims-4

    assert "no longer the pinned one" in problem(tx, old_report)
    assert code(m2.submit, review, integrity=False) == CHECK_VIOLATION

    new_report, new_sha = m2.integrity_report(doc)                    # re-extraction under kn-claims-4
    assert claim_counts(tx, doc) == {OLD: n, CLAIM_EXTRACTOR_VERSION: n + 1}   # old rows kept, never mixed
    tx.cur.execute("select claim_count, extractor_version from public.knowledge_integrity_reports where id = %s",
                   (new_report,))
    assert tx.cur.fetchone() == (n + 1, CLAIM_EXTRACTOR_VERSION)
    tx.cur.execute("select finding_type, needs_expert_review, reference_ids from public.knowledge_integrity_findings"
                   " where report_id = %s", (new_report,))
    assert ("reference_conflict", True, ["ref-ch4-awd-not-eliminated"]) in tx.cur.fetchall()

    m2.verify_report(new_report)
    tx.cur.execute("select verdict from public.knowledge_integrity_verifications where report_id = %s", (new_report,))
    assert [r[0] for r in tx.cur.fetchall()] == ["reproduced"]
    m2.dispose(review, new_sha, None, "report_reviewed")
    # a verified report is not an approval: the blocking finding still needs the expert's disposition
    assert code(m2.submit, review, integrity=False) == CHECK_VIOLATION
    assert tx.status_of("document", doc) != "approved"

    # audit history: both reports stay; the old one never becomes valid again under the new pin
    tx.cur.execute("select count(*) from public.knowledge_integrity_reports where document_pk = %s", (doc,))
    assert tx.cur.fetchone()[0] == 2 and problem(tx, old_report) is not None

    # rolling the pin back is fail-closed too: the kn-claims-4 report and its verification stop authorizing
    pin(tx, OLD, OLD_DIGEST)
    assert "no longer the pinned one" in problem(tx, new_report)
    assert code(m2.submit, review, integrity=False) == CHECK_VIOLATION


def test_a_re_pin_does_not_reopen_or_re_report_an_approved_version(tx, m2):
    """Documented residual: an approval made under the previous pin stays approved. The re-pin governs only
    reviews still open; the owner must re-review (new version) or quarantine an affected approved version."""
    _, doc = draft(tx, m2, content="TEST FIXTURE: awd giúp giảm phát thải so với ngập liên tục")
    review = m2.start(doc)
    m2.submit(review)
    m2.decide(review, tx.approver)
    assert tx.status_of("document", doc) == "approved"
    pin(tx, "kn-claims-next-fixture", "4" * 64)
    assert tx.status_of("document", doc) == "approved"
    reg = paths.integrity_registry()
    tx.cur.execute("savepoint late_report")
    assert code(tx.cur.execute, RECORD_REPORT, (doc, "kn-claims-next-fixture", paths.REVIEW_VERSION,
                                                reg.registry_version, reg.digest, "[]", "[]", LIMITS)) == CHECK_VIOLATION
    tx.cur.execute("rollback to savepoint late_report")
    assert tx.status_of("document", doc) == "approved"


@pytest.mark.parametrize("role", ["service_role", "authenticated", "anon"])
def test_only_the_database_owner_can_move_the_pin(tx, role):
    reg = paths.integrity_registry()
    for sql, params in (("select private.knowledge_set_integrity_policy(%s, %s, %s, %s)",
                         (CLAIM_EXTRACTOR_VERSION, paths.REVIEW_VERSION, reg.registry_version, reg.digest)),
                        ("select private.knowledge_set_integrity_code_digest(%s)", ("5" * 64,))):
        assert as_role(tx, role, sql, params) == ("err", PERMISSION_DENIED)

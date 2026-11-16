# RAG V1.5 E4: expert qualifications, separation of duties, and the E3 Option C record (design)

Status: **DESIGN ONLY, 2026-11-16. E4 is OPEN.** No person is named, appointed or qualified here. No migration, role
or approval is created. Option C is **not implemented and not active** (owner decision D-E3-1).

Index: `RAG_V15_E1_E4_SOURCE_EXPERT_GOVERNANCE_PLAN.md`. Related: Draft PR #81 (E3-B).

## 1. Today

Every expert reviewer, approver, archivist, custodian and verifier in the code base is a **synthetic test fixture**
inside a rolled-back transaction. M2 (`knowledge_expert_reviews`) records reviewer personnel, role, user, session
and a qualification category, but no real person has been recorded. No qualified human has reviewed the real corpus,
the reference registry or an integrity finding.

## 2. Qualification criteria (to be applied by the owner to real people)

A reviewer is qualified **for a domain**, not in general. Each appointment records:

- the domains it covers;
- the evidence of qualification (degree, position, publications, accreditation or a documented track record);
- who appointed the reviewer, and when;
- its expiry;
- any conflicts of interest (for example an author of the reviewed source, or a stake in a carbon project).

| Domain | Needed for | Example evidence (owner to define the threshold) |
|---|---|---|
| Rice cultivation and agronomy (Mekong Delta) | agronomic procedures (QĐ 4043), timing conflicts | agronomy degree + extension/research experience on lowland rice |
| Irrigation and AWD practice | water-regime claims (dev3-01), SFw applicability | field or research record on AWD / water management |
| Agricultural GHG accounting | CH4 / N2O claims, emission factors, scaling factors | inventory or project-accounting experience (AFOLU) |
| IPCC methodology and applicable MRV standards | Tier 1/2 choices, QĐ 4801-type MRV rules | documented inventory compilation / MRV verification work |
| Scientific reference verification | reading a passage at a location, checking values and units, provenance | a documented reference-checking procedure; may be a librarian or analyst, but **not** a scientific approver alone |

A tool, an AI model or an AI-assisted review is never a reviewer. The agy and Codex reviews used in this project are
code reviews, not E4.

## 3. Separation of duties

| Role | Does | Must not be the same person as |
|---|---|---|
| Document uploader | ingests artifacts, records provenance | scientific reviewer, final approver |
| Scientific reviewer | reads the passages, records findings and dispositions with evidence | uploader, final approver |
| Independent second verifier (where required: Option C, OCR'd values, numeric references) | re-checks the same finding or passage independently | the scientific reviewer, uploader |
| Final approver | decides approval on the recorded evidence | uploader, scientific reviewer (already enforced by M2: approver ≠ uploader ≠ reviewer) |
| Administrator | operates roles, keys and infrastructure; appoints only on owner instruction | must not approve, review or verify content; an admin action is never a content decision |

The integrity verifier key holder (E7) is an infrastructure role, not a scientific one.

## 4. E3 Option C: the expected database-enforced record (design, not implemented)

Purpose: let a contested chunk support action answers again, after an independent, qualified confirmation that a
dismissed conflict finding really is a false positive or a contextual difference.

### 4.1 Record

```text
knowledge_integrity_concurrences (append-only)
  id
  finding_id          -> knowledge_integrity_findings (the exact finding)
  report_id           -> its report; must be the CURRENT report of the version
  snapshot_sha256     = the review snapshot hash the disposition was made on
  document version    (source_id, document_id, document_version), derived, not supplied
  disposition_id      -> the first reviewer's false_positive / contextual_difference disposition
  second_reviewer     verified personnel id + qualification ref (domain covers the finding type)
  decision            concur | dissent
  evidence            [{reference, locator, artifact_sha256}] - primary-source provenance (E1 record ids)
  justification       text (minimum length)
  reviewed_at, expires_at   (re-verification policy)
  session / event ids for audit
```

### 4.2 Database rules (to be tests)

1. The second reviewer is a real verified person, **distinct** from the first reviewer, the uploader and the approver.
   Fixture identities are refused outside an isolated test database.
2. Their qualification covers the finding's domain, and the appointment has not expired.
3. The record is bound to the exact finding, its current report and the snapshot hash. A stale report, another
   version, or a finding of another document is refused (no cross-document confirmation).
4. The evidence cites primary-source records (E1). A bare URL or free text is refused.
5. Append-only: no update or delete. A correction is a new record. `dissent` beats `concur`.
6. Expiry: after `expires_at` the chunk is contested again until it is re-verified.
7. Revocation and supersession: revoking the reviewer's appointment, superseding or archiving the version, a new
   report, or changing the registry entry the finding relied on all void the concurrence.
8. Only with a valid concurrence does the E5/E3 helper stop returning that finding as contained. The READ-tier
   warning then changes to a "re-verified on <date> by a second reviewer" note; it never disappears silently.
9. M6.1 records which answers relied on a concurrence.

### 4.3 Prerequisites before any implementation

- an owner-approved policy covering domains, evidence, expiry and dissent;
- real named reviewers, appointed with qualification evidence (§2);
- at least the E1 records the evidence will cite;
- the E7 infrastructure items (a non-owner producer login, the verifier runner);
- its own migration, rollback, DB tests and an owner approval to merge.

None of these exists yet.

## 5. E4 closure criteria

E4 can be reported CLOSED only when real, named, qualified people:

- have been appointed with recorded evidence;
- have actually reviewed the real sources;
- have reviewed the integrity findings the system relies on;
- have recorded their decisions through the database paths above.

A design document or green CI does not close it.

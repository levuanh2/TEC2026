# RAG V1.5 M7 E5.1: pin-aware evidence admission

Status: **LOCAL/CI ONLY, 2026-11-20.** Migration `20261120090000_knowledge_pin_aware_admission_e5_1.sql`, rollback in
`supabase/rollbacks/`. Nothing hosted: no hosted migration, no re-pin, no backfill, no deploy. dev3-01, E1 and E4 stay
**OPEN**. D1 (IPCC rights) and D6 (E4 reviewers) stay **BLOCKED**.

Owner decisions (2026-11-20):

| Id | Decision |
|---|---|
| D-E5-PIN | Approved for local/CI development. Evidence evaluated against an obsolete integrity pin must not automatically remain admissible for AI answers. |
| D-REVIEW | When an approved original is affected, create a new document version and review it again. Keep the old version and its audit history. |
| D-ROLLOUT | Local integration testing only. No hosted re-pin, backfill, merge or deployment. |

## 1. Tree

Branch `feat/rag-m7-e5-pin-aware-admission`, based on #84 `c7e9acf` (the #70–#84 stack), plus:

- #87 `c2b95e5`, cherry-picked;
- #89's fixture correction `4c1b034`, cherry-picked. #89 itself is not merged;
- the E5.1 commits.

## 2. Audit: how stale evidence reached an answer (Task A)

Path: retrieval (`match_knowledge_chunks_lexical`) → model context → grounding → E5 answer-time recheck
(`knowledge_cited_evidence_state`) → citation response.

**The pin.** It is the singleton `private.knowledge_integrity_policy`. It holds:

- extractor version, review version, registry version and registry digest (E2);
- the extractor code digest, i.e. the E7.1 manifest digest over code + runtime + version (E7);
- the attestation mode (E7.1).

**What enforced the pin before E5.1:**

- the approval gate (`private.knowledge_integrity_gate`) at submit and decide time;
- the report writer (`knowledge_record_integrity_report`);
- the verifier (`record_verification`).

**What did not enforce it:**

- Retrieval and E5 checked status, assurance, validity dates, tenant scope and content hash. They never checked the pin.
- A version approved under kn-claims-3 therefore stayed retrievable and citable after a re-pin, with no finding. The
  #89 compatibility report §5 recorded this residual.
- E2 refuses any new report for an approved version, so nothing could ever bring that version's evidence up to date.

**Can a report be treated as current after a code or registry change?** No.

- The report's pin tuple and the verification's code and registry digests are no longer the pinned ones.
- `private.knowledge_integrity_report_problem` already says so.
- The approved document is not reopened. It simply stops being admissible.

**Missing metadata.** Before E5.1 these were admissible, and now they are not:

- a version with no report;
- an incomplete pin, or no attestation mode;
- a verification by a revoked key;
- an approval record that names no review acknowledging the report.

## 3. Policy: "integrity-current"

`private.knowledge_integrity_admission_problem(document_pk)` returns null only when all of the following hold now.
Otherwise it returns a reason code (internal, owner-only):

| # | Condition | Reason code when it fails |
|---|---|---|
| 1 | The pin is complete: extractor, review, registry and digest, code digest, attestation mode | `policy_not_pinned` |
| 2 | The latest report exists | `no_report` |
| 3 | The report's (extractor, review, registry, registry digest) equals the pin | `report_not_under_current_pin` |
| 4 | The report is not stale: version and source snapshots, recorded claim count (E2's check) | `report_stale` |
| 5 | Every chunk hashes to its recorded content hash (E7.1) | `chunk_hash_inconsistent` |
| 6 | No verification of the report says `mismatch` | `verification_mismatch` |
| 7 | A `reproduced` verification exists for the pinned version, code digest and registry digest. It is signed by an active key, accepted under the current attestation mode, over the claim set the DB recomputes now | `not_verified_under_current_pin` |
| 8 | A verified approval record names a review that acknowledged exactly this report (`report_reviewed`, same sha) | `approval_not_bound_to_report` |

An old human approval is never "current" by itself. Only a new version, reviewed under the new pin, makes it current
again.

**Demo approvals** (`demo_unverified`, isolated test DBs only, H-a) have no report by design.

- They are reported as `demo_unverified`, never as `current`.
- The backend admits them only in its labelled demo mode, as before.

**Pin rollback.** The check compares with the pin as it is now.

- Setting the pin back to the exact earlier tuple (same version labels and the same code digest) makes the versions
  approved under it current again. That is what a rollback means.
- Versions approved under the newer pin are not reactivated.
- The same extractor label with another manifest digest reactivates nothing.

## 4. Enforcement

### Gate 1: before the provider is invoked

- `rag_answer_integrity.AdmittedEvidenceRetriever` wraps the request's retriever.
- After retrieval, it calls `knowledge_evidence_admission`, which runs the same RPC as gate 2 under the caller's JWT.
  The orchestrator, and so the model, receives only admitted chunks.
- It applies to every intent. RECOMMEND and WHAT_IF are the ones that matter for advice, but a READ-tier answer also
  no longer cites stale documents.
- A reader without the check, a failing check, or a row without `integrity_status` or `resolved_finding_types` refuses
  the request with `retrieval_unavailable` (503). It never passes chunks through.
- E3 is not applied here. A dismissed conflict on a current version stays an answer-time decision (D-E3-1..3 unchanged).
- When nothing usable remains and documents were excluded for the pin, the answer is `no_integrity_current_evidence`.
  The Vietnamese copy says the documents are waiting to be re-checked and that no unchecked source is substituted.
- The M6.1 recorder sits outside gate 1, so a citation event records what was admitted.

### Gate 2: at answer time

- `recheck_cited_evidence` re-runs the RPC on the cited chunks. C1–C4 checks are unchanged.
- New: a verified row must say `current`, and a demo row (demo mode only) must say `demo_unverified`. Anything else is
  refused with `integrity_not_current`.
- The whole model answer is discarded: `evidence_integrity_not_current`, an M6.1 `evidence_refused` event.
- Precedence: withdrawn, changed or unverified (`evidence_no_longer_admissible`) comes first, then pin
  (`evidence_integrity_not_current`), then E3 (`evidence_integrity_contested`).
- This catches a pin change between retrieval and the answer (tested).

### Database

- `public.knowledge_cited_evidence_state` gains an argument, `p_integrity_status boolean default false`, and a column,
  `integrity_status`.
- **Version-skew safety.** An E5 backend calls it with three arguments, so not-current rows are excluded and that
  backend refuses them as `no_longer_admissible`. An old backend can never admit stale evidence.
- The E5.1 backend passes `true` and gets labelled rows.
- `private.knowledge_cited_integrity_status`:
  - is SECURITY DEFINER, because the pin and the E2/E7 tables are private;
  - answers only for chunks the caller could retrieve for that season (same scope as retrieval and
    `knowledge_cited_resolved_finding_types`);
  - answers only with `current` / `not_current` / `demo_unverified`. No report content and no reason code reaches a
    client.
- A cross-tenant or unreadable chunk gets no row.

## 5. Effect on previously approved documents

**At a re-pin, every approval made under the old pin is suspended, affected and unaffected alike.**

- No status changes. Nothing is quarantined, re-reported, mutated or deleted. Retrieval still returns the chunks;
  gate 1 removes them.
- After the kn-claims-4 re-pin, the whole verified corpus is unusable for AI answers until new versions are reviewed.
  This is the main availability consequence of D-E5-PIN (decision E5.1-b in §9).
- A spelled-zero version approved under kn-claims-3 (no finding then) is not given to the model after the re-pin
  (tested).
- Its new version gets a kn-claims-4 `reference_conflict` that the expert gate must handle.
- The hosted database has no E2/E7/E5 (none of M7 is applied), so nothing changes there today.

## 6. Versioned re-review and rollback (local first; never hosted without approval)

1. **Inventory** (read-only, owner session, local):
   `python backend/scripts/knowledge_pin_reextraction_inventory.py --target local`. It lists every approved version
   with its report's extractor version and admission state (`private.knowledge_integrity_admission_inventory()`).
2. **Changed claims.** For each verified, not-current version, the script re-extracts claims offline from the stored
   chunks and diffs the claim ids against the stored ones. Claim ids do not depend on the version. Nothing is written.
3. **Split** into `claims_changed` and `claims_unchanged`, for impact analysis.
4. **New version** per affected document (`supersedes_document_pk` = the original), in local QA.
5. Extract claims with kn-claims-4 (`knowledge_claims.py --target local`).
6. Record the new integrity report (operator path).
7. Get an independent verification through the E7.1 verifier. Locally that is the synthetic test key; in production
   it is a real key, an owner step.
8. Conflicts go to the existing expert gate. A real reviewer dispositions each finding. A confirmed problem means the
   version is rejected or returned.
9. The new version is admitted only when E2, E7 and the approval all pass. Gate 1 and gate 2 then admit it on their
   own. The original keeps its reports, claims, approval record and status history.

**Rollback** (in order):

1. Deploy a backend without E5.1.
2. Run the E5.1 `.down.sql` in one transaction (it restores E5's three-argument function exactly).
3. Run `supabase migration repair --status reverted 20261120090000`.

E5.1 writes no table and no row, so nothing needs to be exported. After the rollback, stale-pin approvals are
admissible again (the E5 residual). A pin rollback alone needs no migration (§3).

**Never simulated:** a scientific approval. The test reviewers, dispositions and approvers are synthetic fixtures in
rolled-back transactions, marked TEST FIXTURE, and the kn-claims-3 verifier build is a test-only stand-in
(module docstring of `test_rag_knowledge_m7_e5_1_pin_admission.py`).

## 7. Tests (Task D)

`backend/tests/test_rag_knowledge_m7_e5_1_pin_admission.py` (18 tests, DB) and
`test_rag_answer_integrity.py::test_e5_1_*` (13, offline).

| Case | Test |
|---|---|
| Old pin, old report | `test_old_pin_old_report_is_admissible_and_the_kn3_approval_even_cites_the_spelled_zero` |
| New pin, old report; previously approved spelled-zero poison; RECOMMEND with stale evidence | `test_new_pin_old_report_previously_approved_spelled_zero_is_not_given_to_the_model` (model not called) |
| Unaffected document suspended too | `test_a_clean_unaffected_kn3_approval_is_suspended_too` |
| WHAT_IF with stale evidence | `test_what_if_with_stale_evidence_keeps_engine_numbers_and_the_chunk_stays_out_of_the_prompt` |
| READ tier without RAG citation | `test_read_tier_without_rag_citation_still_answers_and_evidence_questions_say_why` |
| New pin, new valid report | `test_new_pin_new_valid_report_is_admissible` |
| Mismatched manifest digest | `test_mismatched_manifest_digest_suspends_admission_and_the_verifier_refuses_to_sign` |
| Registry digest changed | `test_a_changed_registry_digest_suspends_admission` |
| Revoked verifier key | `test_a_revoked_verifier_key_suspends_admission` |
| Missing integrity metadata | `test_missing_integrity_metadata_is_never_current`; offline `test_e5_1_a_missing_or_unknown_integrity_status_fails_closed` |
| New version, outdated snapshot hash | `test_a_new_version_whose_snapshot_changed_after_its_report_cannot_be_approved_or_admitted` |
| Pin rollback and reactivation | `test_pin_rollback_reactivates_only_what_was_approved_under_that_exact_pin` |
| Pin changed between retrieval and the answer | `test_a_pin_change_between_retrieval_and_the_answer_refuses_at_answer_time` (M6.1 `evidence_refused`) |
| Unauthorized and cross-tenant | `test_cross_tenant_and_unauthorized_callers_learn_nothing` |
| E3 unchanged | `test_e3_containment_is_unchanged_for_a_current_dismissed_conflict` |
| Versioned re-review (Task C) | `test_versioned_re_review_after_the_re_pin` |

**Unchanged:**

- E2, E3, E5, E7, E7.1, M6.1, READ UX and dev3-01 tests. Only their reader stand-ins gained the gate-1 method and the
  `integrity_status` field.
- `test_rag_source_integrity_gap.py` (not touched). dev3-01 is still OPEN: undetected poison and a mistaken
  dismissal under the current pin behave exactly as before.

## 8. Database requirements (Task E)

- **New functions:**
  - `private.knowledge_integrity_admission_problem(uuid)`: invoker, owner-only;
  - `private.knowledge_cited_integrity_status(uuid, text[], boolean)`: definer, EXECUTE for authenticated only;
  - `private.knowledge_integrity_admission_inventory()`: invoker, owner-only;
  - the replaced `public.knowledge_cited_evidence_state(uuid, text[], boolean, boolean)`: invoker, EXECUTE for
    authenticated only.
- **No new table, column, index, policy or trigger.** The existing indexes cover every lookup:
  - reports `(document_pk, recorded_at)`;
  - verifications `(report_id)`;
  - claims `(document_pk, extractor_version, claim_id)`;
  - approval records `(document_pk)`;
  - dispositions `(review_id, report_id, …)`.
- **No new read privilege** for any client role on the pin or the E2/E7 tables.
- **Migration steps (when approved):**
  1. Apply E5.1 after E5. The order is #70 first, then the stack, and E5.1 last, because `check_migrations` refuses a
     version older than the newest on base.
  2. Then deploy the E5.1 backend.
  3. A hosted re-pin comes only after the decisions in §9.
- **Per-request cost:** one extra RPC (gate 1) over at most top_k chunks. Per distinct document it recomputes the
  snapshot hashes, the chunk hashes and the claim-set digest. That is proportional to that document's chunks and
  claims, not to the corpus. Retrieval is unchanged.

## 9. Risks and decisions needed before hosted rollout

**Risks:**

- **Availability.** A re-pin suspends the whole verified corpus until new versions are reviewed (§5).
- **Retrieval slots.** Stale chunks still take top_k retrieval slots, then gate 1 drops them. With many stale
  documents, an admissible chunk ranked below them is not seen. A follow-up could move the predicate into retrieval.
  It would need a per-season DEFINER set function and a cost check.
- **Consistency boundary.** As in E5, the database statement's snapshot. A pin change committed after gate 2's
  statement is not caught (M6.1 records the window).
- **Demo exemption.** Demo approvals are not pin-checked (H-a labels them unverified and they never claim verification).

**Decisions:**

- **E5.1-a:** apply E5.1 to hosted with the M7 stack, and when.
- **E5.1-b:** for `claims_unchanged` versions, a full new version and expert review (current D-REVIEW), or an
  owner-approved re-attestation path: a new report plus an independent verification under the new pin, with an
  identical claim set and no new finding, without a new expert review. The re-attestation path does not exist. It
  would need a migration and an owner-approved policy.
- **E5.1-c:** the hosted re-pin date to kn-claims-4, after real reviewers (D6/E4) and a real verifier key exist.
- **E5.1-d:** whether a pin rollback may reactivate approvals under the restored tuple (current behaviour), or whether
  re-pins should be epoch-based (never reactivating).
- **E5.1-e:** whether demo mode should also require integrity reports.

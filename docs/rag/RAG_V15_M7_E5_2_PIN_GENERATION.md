# RAG V1.5 M7 E5.2: pin generations and safe corpus transition

Status: **LOCAL/CI ONLY, BLOCKED FOR HOSTED. 2026-11-20.** Migration `20261120120000_knowledge_pin_generation_e5_2.sql`,
rollback in `supabase/rollbacks/`. Stacked on #90 (E5.1 `abaa8b6`). No hosted migration, re-pin or backfill. No
deploy. No paid provider. dev3-01, E1 and E4 stay **OPEN**. D1 and D6 stay **BLOCKED**.

E5.2 solves three problems of E5.1:

- **P1, rollback re-activation:** setting the pin back to an earlier tuple re-admitted the approvals made under it.
- **P2, corpus availability:** the impact of a re-pin was not visible before doing it.
- **P3, retrieval starvation:** stale chunks took top_k slots and gate 1 then dropped them.

## 1. Phase A audit: the architecture as it is (E5.1)

| # | Question | Answer (file) |
|---|---|---|
| 1 | Who may change the pin? | Only the database owner. `private.knowledge_set_integrity_policy` (E2), `knowledge_set_integrity_code_digest` (E7) and `knowledge_set_attestation_mode` (E7.1) have every client role's EXECUTE revoked. The pin table `private.knowledge_integrity_policy` is unreadable by anon, authenticated and service_role. Tested in `test_only_the_database_owner_can_move_the_pin`. |
| 2 | Where is the pin used? | (a) Recording a report (`knowledge_record_integrity_report`: tuple must equal the pin). (b) The verifier (`verification_input` / `record_verification`: version, code digest, registry digest). (c) The approval gate (`knowledge_integrity_report_problem`, `knowledge_integrity_verification_problem`). (d) E5.1 admission (`knowledge_integrity_admission_problem`) behind gate 1 and gate 2. Retrieval did not use it. |
| 3 | What binds an approval? | The review's snapshot sha equals the report's document snapshot. The `report_reviewed` disposition carries the report's sha. The verification carries the report id and sha, the document snapshot, the version, the code and registry digests, a key that must be active, and a claim-set digest the DB recomputes. The approval record carries the review id. Before E5.2 none of these said which pin *instance* they belonged to, only which tuple. |
| 4 | What is append-only? | Reports, findings, dispositions, verifications, claims, approval records, reviews, attestations, status events and citation events: the evidence guards. Approval records allow one `status_event_id` update; reviews allow their start event and decision. |
| 5 | What do E5.1's gates check? | Gate 1, before the model, and gate 2, at answer time, run `knowledge_cited_evidence_state(.., true)` under the caller's JWT. A verified row must be `current` per `knowledge_integrity_admission_problem`. Gate 2 also keeps the E3 and C1–C4 checks. |
| 6 | What can a rollback re-activate? | E5.1 compared with the current tuple. Restoring the exact earlier tuple (labels plus code digest) re-admitted every approval made under it (E5.1 decision E5.1-d). |
| 7 | How is top_k bounded? | `match_knowledge_chunks_lexical`: the `eligible` CTE (approved, verified, in force, tenant scope), then the top 50 by FTS and the top 50 by trigram, fused, then `least(greatest(p_top_k, 1), 50)`. The backend asks for 8, then applies its score cutoff. Stale chunks competed for all of those slots. |
| 8 | How is demo separated? | `approval_assurance = 'demo_unverified'` is served only by `match_knowledge_chunks_lexical_demo`. That function refuses (42501) unless `private.knowledge_deployment_isolated()`, the backend sets `include_demo`, and the title is labelled. The production RPC serves `verified` only. |

The security invariants were written as tests (§7) before the implementation was finished. These are the E5.2 test
module and the reworked E5.1 expectations.

## 2. Pin generation (P1)

- **Epoch.** `private.knowledge_integrity_policy.generation`. A BEFORE UPDATE trigger makes every UPDATE of the pin
  row `generation = old + 1`.
  - "Every UPDATE" includes each owner function, an identical re-pin (A → A) and a direct owner UPDATE.
  - It happens under the row lock: concurrent changes serialize, and a failed transaction consumes nothing.
  - A supplied value is ignored. The row cannot be deleted or truncated.
- **Log.** `private.knowledge_integrity_pin_generations`: one row per generation, with the tuple, `complete`, the
  reason (`pin_change` / `migration_apply` / `schema_rollback_unpinned`), time, session user and xact.
  - It is append-only. A row can only state the pin row as it is now, so no generation can be forged or backdated.
  - Truncate is refused. It has no privilege for any client role.
- **Stamps (trusted, at insert).** `knowledge_integrity_reports.pin_generation`,
  `knowledge_integrity_verifications.pin_generation` and `knowledge_approval_records.pin_generation`.
  - They are set by a SECURITY DEFINER trigger that reads the pin row FOR SHARE.
  - A report or verification whose tuple is not the pinned one is refused (a pin change racing the insert).
  - A client value is ignored. Stamps never change (the evidence guards, plus a frozen-stamp trigger).
  - Rows made before E5.2 keep NULL. No generation is assigned to old approvals to legitimize them.
- **Approval gate.** `knowledge_integrity_report_problem` refuses a report of an earlier generation.
  `knowledge_integrity_verification_problem` share-locks the pin row and accepts only a verification of the current
  generation.
- **Admission.** E5.1's `knowledge_integrity_admission_problem` now additionally requires the report's generation,
  the verification's generation, and the generation of *the same approval record that acknowledged the report*, all
  equal to the current one. New reason codes: `generation_missing`, `report_from_earlier_generation`,
  `approval_from_earlier_generation`.

**Result:** after A → B → A, or A → A, every earlier approval is of an earlier generation and is never admissible
again. The only way back is a new version reviewed in the current generation (D-REVIEW).

**Strictness (owner-visible):** *any* pin update starts a new epoch, including the attestation mode or the code
digest. A routine verifier runtime or library upgrade changes the E7.1 manifest digest, so it means a re-pin and a
corpus-wide re-review (side-agent note, 2026-11-20). See decision E5.2-a in §9.

## 3. Safe rollback (Phase C)

| Kind | What happens | Safety |
|---|---|---|
| Code rollback (backend to E5.1 / E5 / pre-E5) | Nothing to do in the DB. | The DB decides. Retrieval returns only versions admitted in the current generation, for every backend version. `knowledge_cited_evidence_state` with three arguments excludes not-current rows. With four arguments it labels them `not_current`. Tested: `test_version_skew_an_older_backend_cannot_admit_a_previous_generation`. |
| Pin-value rollback (A → B → A) | A new generation. | Revives nothing (tested). |
| Security-policy / schema rollback (`.down.sql`) | Only if E5.2's stamping or gate changes malfunction. | Refused without `set local knowledge.e5_2_rollback = 'safe-refusal-acknowledged'` (55000). Removes the bump and the stamps and restores the E2 / E7.1 / E5.1 gate checks, so reviews keep working. **Keeps** the generation-bound retrieval and clears the pin as a final logged generation. Nothing new is stamped, so **no verified document is served by any backend until E5.2 is re-applied (safe refusal).** Keeps the log, the generation and every stamp. Generations are never deleted or lowered. |
| Re-apply after a rollback | The migration starts a generation above every recorded one. | Nothing approved before, or during the rolled-back period (NULL stamps), becomes current. A new version reviewed in the new generation is served again. Tested end to end: `test_the_rollback_ends_in_safe_refusal_keeps_the_audit_and_a_re_apply_never_reuses_a_generation`. |

Other rollback-chain facts:

- The E5.1, E5, E7.1, E7, E2 and M2 rollbacks run after this one unchanged. Nothing they drop depends on E5.2's kept
  objects; the log uses its own truncate guard.
- H-a's rollback replaces retrieval with its predecessor as before.
- The test helper that unwinds the chain (`unwind_e5_2`) re-pins the earlier values after the rollback. It is an
  explicit, TEST ONLY owner step.

## 4. Corpus impact assessment (P2, Phase D)

`python backend/scripts/knowledge_repin_impact.py --target local [--rows]`:

- read-only: one read-only transaction, rolled back;
- local only: a hosted target is refused (exit 2);
- it needs an owner session (`private.knowledge_corpus_integrity_inventory()` is owner-only). It prints ids and
  counts, never a title or any text.

**Categories** (several per version):

- `current_under_existing_pin`;
- `will_become_stale` (every current version: any re-pin is a new generation);
- `not_current_now`;
- `claim_set_changed` / `claim_set_unchanged`: offline re-extraction with the current code against the stored claims
  of the report's extractor;
- `missing_evidence`;
- `missing_verifier`;
- `needs_expert_review`: the current review of the stored text raises findings that need an expert;
- `demo_only`;
- `inaccessible_or_blocked`;
- `in_review`.

**Summary:**

- totals;
- `admissible_after_any_re_pin = 0`;
- the impact per intent: RECOMMEND and EVIDENCE lose every document; WHAT_IF keeps the engine numbers and loses
  citations; EXPLAIN, COMPARE and DATA_GAP are unaffected;
- the database it read. Local or synthetic data is labelled "not a production-scale estimate", and demo versions are
  counted separately.

**On the local stack today** (no committed knowledge): see §6 of the PR report. The classification itself is tested
on a synthetic mix in `test_the_impact_assessment_classifies_without_writing`.

## 5. Retrieval starvation (P3, Phase E): options A and B

| | A: admission-aware retrieval (chosen) | B: bounded refill |
|---|---|---|
| Where | `eligible` CTE joins `private.knowledge_generation_admitted_documents(season)` before ranking and top_k | Backend loop: H-a RPC at k = 8, 16, 32, 50, then gate 1 after each |
| Auth / RLS / tenant | RPC stays INVOKER under the caller's JWT. The helper is SECURITY DEFINER with `search_path = ''`, EXECUTE for authenticated (+ service_role, which gets nothing), and the same tenant predicate and season scope as retrieval. Tested cross-tenant | Unchanged RPC, plus gate 1 |
| Precision / recall vs stale | A stale chunk never takes a slot. Recall of admitted chunks equals retrieval over the admitted corpus | Recall bounded by the RPC cap of 50. More than 50 stale chunks ranked above still starve it |
| Round trips | 1 RPC + 1 gate-1 call | 2 per round, up to 8 |
| Fail-closed | DB-enforced for every backend, pre-E5 included | Only for backends that run the loop |
| E5.1 compatibility | Gate 1 and gate 2 unchanged. Gate 1's "awaiting re-check" copy is now reached only when the full check fails while the indexed check passes | Unchanged |
| Leak | The helper returns document ids only, for the caller's own scope; nothing for an unreadable season | none |

**Explanation signal (side-agent note, 2026-11-20).** With option A a suspended version is never retrieved, so the
backend can no longer tell "nothing approved" from "approved but awaiting re-check". Without help, a farmer would
read the generic "no approved document" copy as an empty knowledge base. `public.knowledge_evidence_awaiting_recheck`
fixes that:

- It is INVOKER and calls the DEFINER `private.knowledge_scope_has_suspended_evidence`.
- It answers ONE boolean for the caller's own season scope: is there an approved, verified version in force that is
  not admitted in the current generation?
- No count, id or title. Nothing for an unreadable season.
- The backend asks only when nothing usable was retrieved, and then uses E5.1's copy (`no_integrity_current_evidence`).
- It is an explanation, never an admission. A missing or failing signal keeps the generic copy, and the answer is
  `insufficient_evidence` either way.
- Tested for scope (org A learns nothing about org B) and failure. Decision E5.2-f: keep it, or accept the generic
  copy.

The benchmark is in §6.

## 6. Performance (local, synthetic; relative numbers only)

`tests/bench_e5_2_retrieval.py`:

- corpus: 40 stale versions approved in an earlier generation, all ranking above the 10 clean versions approved after
  the re-pin;
- top_k 8, 25 rounds per path, client-observed latency through the test transaction (savepoint and role switch
  included);
- Windows laptop, local Supabase. Not a production estimate.

| Path | Clean admitted | Stale admitted | DB round trips | Median | p95 |
|---|---|---|---|---|---|
| E5.1 (H-a retrieval, then gate 1) | **0** (starved) | 0 | 2 | 83.8 ms | 86.8 ms |
| **A: admission-aware retrieval** | **8** | 0 | 2 | 131.2 ms | 135.8 ms |
| B: bounded refill 8/16/32/50 | 8 | 0 | 8 | 716.7 ms | 774.1 ms |
| RPC alone: H-a / E5.2 | | | 1 | 22.4 / 67.8 ms | |

**Read:**

- A fixes the starvation with no extra round trip. It costs about 45 ms per retrieval here: the generation predicate
  visits every approved version in the caller's scope.
- B needs four rounds before it fills top_k. It only worked because the stale set (40) was below the RPC cap (50);
  above the cap it starves again.
- **Limit:** A's cost grows with the number of approved versions in scope, not with top_k. For a corpus much larger
  than local QA, a stored per-version admission marker (written at approval, cleared by every pin change) would make
  it an index probe. That is a follow-up and was not measured at scale.

## 7. Tests

`backend/tests/test_rag_knowledge_m7_e5_2_pin_generation.py`, covering:

- epoch, log, append-only, failed change, unauthorized roles including the verifier;
- stamps and frozen stamps;
- stamp refuses a racing tuple;
- A → B → A, explicit A → A, cross-generation replay, missing generation;
- concurrent pin changes (two committed sessions);
- starvation, tenant scope, version skew, E3 and quarantine unchanged;
- rollback refusal, rollback safe refusal and re-apply, re-run idempotence;
- the impact assessment and the impact script.

Also:

- The E5.1 tests were updated where E5.2 deliberately changes behaviour: stale versions are no longer retrieved, and
  rollback reactivates nothing.
- Fixtures complete the pin before any report and never re-pin implicitly
  (`knowledge_status_paths.M2.pin_integrity_policy` / `complete_pin`).
- `test_rag_source_integrity_gap.py` is unchanged.

## 8. Data and migration risks

- **Applying E5.2 suspends every pre-existing verified approval** (NULL stamps). Hosted has no M7 today. On any other
  database with approved knowledge, the whole verified corpus needs new versions and reviews after the migration.
- **Strict epochs.** Changing the attestation mode or the code digest during an open review retires that review's
  report: record it again (shown in the E7.1 offline-mode test).
- **service_role** retrieval of verified knowledge is now empty (fail-closed). No answer path uses it.
- Retrieval's indexed predicate does not re-hash content. A version whose chunk text, snapshot or claim set no longer
  matches can still be ranked, then gates 1 and 2 drop it (side-agent finding 5, documented).

## 9. Owner decisions before any hosted rollout

- **E5.2-a, strict epoch scope:** keep "every pin update is a new epoch", or exempt changes that do not affect
  extraction, such as the attestation mode or a runtime-only manifest change, through a separate re-attestation path
  (new verification of an unchanged claim set by the same extractor). As it is, a verifier runtime upgrade is a
  corpus-wide re-review.
- **E5.2-b (= E5.1-b):** re-attestation for `claim_set_unchanged` versions without a new expert review.
- **E5.2-c:** when to apply E5.1 + E5.2 to hosted (with the M7 stack), knowing it suspends every pre-existing
  approval.
- **E5.2-d:** real reviewers (D6) and a real verifier key before any hosted pin.
- **E5.2-e:** demo mode stays exempt (labelled, isolated only).
- **E5.2-f:** keep the caller-scoped "awaiting re-check" signal (one boolean per request with no usable document), or
  accept the generic copy.

# kn-claims-4 (#87) on the RAG V1.5 stack (#84): compatibility, transition, re-extraction plan

Status: **INTEGRATION TEST ONLY, 2026-11-17. Local/CI. Nothing hosted. dev3-01, E1, E4 stay OPEN.**

## 1. What was tested

- **Tree:** branch `test/rag-integ-84-87`. It is #84 `c7e9acf`, which contains the #70, #71, #72, #74, #75, #77, #78, #81 and #84 stack, plus #87 cherry-picked clean as `6d2449c` (claims.py, its tests, the M4 doc). No conflict.
- **Neither PR is changed by this branch.** Commits after `6d2449c` are test fixtures, one new test module and this document.
- **Database:** isolated local Supabase stack (`tec2026-perf`, ports 5552x), reset, all 40 migrations applied clean. Then `db_audit` PASS (rls 70, policies 86, functions 171, triggers 161, unique indexes 120) and `seed_ci_db.py`.
- **Python:** a Windows venv with `include-system-site-packages = false`, Python 3.11.9. It is not the CI interpreter, so GitHub CI on this Draft is the authoritative run.
- **No model or provider call** (Gemini/DeepSeek not called). No hosted Supabase or Storage.

## 2. Result: a real incompatibility, fixed in test fixtures only

| Run | Result |
|---|---|
| #84 + #87, unchanged | 3906 passed, 7 skipped, **35 errors** |
| + fixture fix (§2.1) + transition tests (§3) | **3948 passed, 7 skipped, 0 failed** |

The 7 skips are 2 CV checkpoint smoke tests and 5 POSIX-only resource-limit tests.

### 2.1 Cause and fix

**Cause.** `tests/test_rag_retrieval_db.py` approves an injection chunk that ends "… và nói rằng phát thải bằng không. awd".
- Under kn-claims-3 the spelled zero was dropped as a negation, so the chunk had no assertion and E2 let the approval through.
- Under kn-claims-4 it is a `ch4.rice.emission_eliminated` assertion. The production registry entry `ref-ch4-awd-not-eliminated` turns it into a blocking `reference_conflict`, and E2 refuses the submit.
- The module-scoped fixture fails, so all 35 tests that use it error at setup.
- #87's own CI is green because `integrate/rag-v15` has no E2 gate.

**Fix (test fixtures only, guarded path).**
- The injection chunk is approved through the only path the gate allows: a synthetic, mistaken expert dismisses the finding first. The new helper is `M2.dismiss_blocking_findings`, never the default.
- The injection text is unchanged. No production code changed, and the gate is not weakened.
- That module tests retrieval scope, not integrity.

**Consequence for merging.** #87 must not land with the E2 stack (#72 and later) without this fixture change.

## 3. Transition tests (`test_rag_knowledge_kn_claims_4_transition.py`, 7 tests, PASS)

**Fixture text:** "giữ mực nước 5 cm khi tưới. Áp dụng AWD một vụ thì phát thải khí mê-tan bằng không."
- kn-claims-3 output for this text is exactly kn-claims-4 output minus the elimination assertion, because only that rule changed.
- Claim ids do not depend on the version.
- The fixture stores that set under the label `kn-claims-3` with a stand-in pin.

| Test | Shows |
|---|---|
| `…exactly_what_kn_claims_3_missed` | kn-claims-4 extracts exactly one assertion here |
| `…under_the_kn_claims_3_pin…neither_reports_nor_signs` | under the old pin, the kn-claims-4 operator cannot record a report (23514), and the kn-claims-4 verifier raises `PinMismatch` and signs nothing. Submit is refused; nothing is approved |
| `…re_pin_retires_the_old_report…poison_now_blocks` | after the owner moves the pin to kn-claims-4 and its manifest digest: the old report is refused ("no longer the pinned one"). Re-extraction keeps the kn-claims-3 rows and adds kn-claims-4 rows; versions are never mixed and `claim_count` counts the new version only. The new report has `reference_conflict` / `ref-ch4-awd-not-eliminated`, the verifier reproduces it, and submit is still refused until an expert dispositions it. Both reports stay (audit). Rolling the pin back makes the new report refused too |
| `…re_pin_does_not_reopen_or_re_report_an_approved_version` | an approval made under an earlier pin stays approved, and no new report can be recorded for it. **Documented residual, §5** |
| `…only_the_database_owner_can_move_the_pin` × 3 | service_role, authenticated and anon get 42501 on both pin functions |

## 4. Required scenarios (all PASS in the full run)

| # | Scenario | Test |
|---|---|---|
| 1 | Detected poison wrongly dismissed by the expert: ACTION refused | `test_rag_knowledge_m7_e5_answer_time.py::test_12_dev3_01_mistaken_expert_action_answer_is_contained_read_tier_keeps_the_caveat`; `test_rag_knowledge_m7_dev3_01_replay.py::test_e5_full_chain_matrix_on_the_real_answer_path` |
| 2 | Undetected poison stays an OPEN gap | `test_rag_source_integrity_gap.py` (4 tests, **file unchanged**); `test_rag_m7_dev3_01_harness.py::test_e_the_characterization_stays_unflipped` |
| 3 | Verified clean evidence still flows | `test_rag_knowledge_m7_e7_independent_verification.py::test_a_correctly_verified_synthetic_document_is_approved`; `test_read_ux_a_clean_citation_gets_no_warning_and_no_detail` |
| 4 | No M05 rule: no model call | `test_rag_questions_route_db.py::test_writer_without_a_stored_rule_gets_no_action_and_no_provider_call`; `test_no_rule_signal_gate_still_decides_first` |
| 5 | Model invents a rule code: refused | `test_rag_grounding.py::test_recommendation_cannot_invent_a_deterministic_rule`; `test_every_m05_rule_has_a_declared_subject_and_unknown_rules_fail_closed` |
| 6 | Cross-tenant evidence: no leak | `test_10_cross_tenant_citation_injection_finds_nothing`; `test_12f_read_tier_another_htx_contested_document_reveals_no_title_url_or_warning`; `test_rag_retrieval_db.py::test_cross_tenant_knowledge_never_returned` |
| 7 | Old extractor pin: fail closed | §3 rows 2–3 |
| 8 | Correct re-pin on local: verifier works | §3 row 3 (verdict `reproduced`) |
| 9 | READ tier keeps the warning and gives no action advice | `test_e3_a_read_tier_answer_keeps_the_caveat_and_is_not_refused`; `test_read_callers_can_ask_but_never_get_action_capability[*]` |
| 10 | Source quarantined after retrieval: not used | `test_3_source_quarantined_after_retrieval`; `test_c_d_quarantine_removes_the_poison_from_retrieval_and_the_answer_side_stops_citing_it` |

**dev3-01 replay.** The 5 replay tests and 3 harness tests pass. The E7 matrix still shows that a mistaken expert's approval is retrieved and cited (READ tier with the warning; ACTION contained). **dev3-01 stays OPEN.**

## 5. Residual risk: approvals made before the re-pin

- A re-pin governs open reviews only. A version approved under kn-claims-3 stays approved and keeps its kn-claims-3 report.
- E5 checks approval and assurance at answer time, not the current extractor pin.
- An approved version whose text holds a spelled-zero claim therefore stays citable, with no finding, until a person acts.
- This is existing E2/E5 policy, unchanged here. **Changing it (for example, E5 refusing approvals whose report is not under the current pin) is an owner decision.**
- **2026-11-20: decided and implemented locally.** Owner decision D-E5-PIN; E5.1 (`RAG_V15_M7_E5_1_PIN_AWARE_ADMISSION.md`) refuses such approvals before the model and at answer time. Local/CI only.

## 6. Re-extraction plan (local first; never hosted without approval)

1. **Inventory.** Read-only, service role:
   ```sql
   select d.id, d.source_id, d.document_version, d.status, c.extractor_version, count(*)
     from public.knowledge_claims c join public.knowledge_documents d on d.id = c.document_pk
    group by 1,2,3,4,5 order by 4,1;
   ```
2. **Affected versions.** Those whose chunk text, diacritic-folded, has an emission term followed within 4 words by `bang khong` / `ve khong`. Only these can gain claims. Confirm offline: run `extract_claims` on the stored chunks and diff the claim ids against the stored kn-claims-3 ids, with no write.
3. **Order.**
   1. Deploy kn-claims-4 code to the verifier.
   2. The owner moves the pin (`knowledge_set_integrity_policy` + `knowledge_set_integrity_code_digest`, database owner only).
   3. Run `backend/scripts/knowledge_claims.py --document-pk <id> --target local` per version under review.
   4. Record new reports and new verifications.
4. **Before/after checks.** Per version: kn-claims-3 row count unchanged; the kn-claims-4 count equals the offline extraction; new findings listed; no status changed by the run.
5. **Rollback.** Revert the code, then re-pin to kn-claims-3 with its digest. kn-claims-4 rows are append-only and stay, but no check reads them while the pin names kn-claims-3 (§3 row 3). No migration is involved.
6. **Old reports and approvals.**
   - Open reviews need a new report and a new verification, which is automatic: the gate refuses the old ones.
   - Approved versions are not re-reported (E2 refuses). For an affected approved version, the owner chooses between quarantine and a new version with a fresh review.

## 7. Other checks on this tree

- `openapi_check --base-ref c7e9acf` and `--base-ref origin/integrate/rag-v15`: 0 breaking changes, 61 operations.
- `check_migrations`: 40 files, no new migration.
- `ci_policy`: PASS (the guarded test-file change carries a `CI-Policy-Change` trailer).

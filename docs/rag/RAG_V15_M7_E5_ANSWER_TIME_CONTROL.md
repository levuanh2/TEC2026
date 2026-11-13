# RAG V1.5 M7 E5: answer-time integrity control (IMPLEMENTED, local/CI only)

Status: **IMPLEMENTED, LOCAL/CI ONLY.** Migration `20261114120000_knowledge_answer_time_evidence_e5.sql`, rollback in
`supabase/rollbacks/`. Design: `RAG_V15_M7_E5_ANSWER_TIME_CONTROL_DESIGN.md` (#75). Stacked on E7.1 (#77) and
includes #70 (M6.1) through a merge commit. Not applied to hosted, not deployed. **dev3-01 stays OPEN.**

E5 refuses evidence that is no longer admissible, or that is not what this request's retrieval returned. It
**cannot** tell whether an approved text is true. It never approves, quarantines or judges scientific content, and
no LLM is an authority anywhere in it.

## 1. Where it runs

`RagQuestionService.answer` → orchestrator (schema, C1 citation, grounding, rule-code and consistency gates) →
`assert_recommendations_follow_rules` → **`rag_answer_integrity.answer_time_evidence_gate`** → `to_response` →
M6.1 event. The gate is the last step before the response body is built.

| # | Control | Implementation |
|---|---|---|
| C1 | cite only chunks returned by THIS request's authorized retrieval | orchestrator `validate_citations` (502 `citation_mismatch`), re-asserted on exact (source_id, chunk_id) pairs |
| C2 | document and source still approved, verified, in force, tenant-visible | `public.knowledge_cited_evidence_state` (SECURITY INVOKER, caller's JWT, RLS): the retrieval predicate re-evaluated now; a chunk not returned = not admissible |
| C3 | same source / document / version; content hash = sha256 of the text retrieval returned AND consistent with the stored text | compared in the gate; the RPC returns `content_sha256` and `content_hash_consistent` |
| C4 | unknown or non-verified assurance refused | `verified` only; `demo_unverified` only in the explicit demo mode, which the database refuses outside an isolated test database (42501) |
| C5 | a recommendation keeps an admissible citation and a stored rule code; findings an expert resolved as false positive / contextual difference are shown | structural check + `assert_recommendations_follow_rules`; caveat (finding TYPES only, trusted copy) appended to `limitations` via `private.knowledge_cited_resolved_finding_types` |
| C6 | anything that fails ⇒ the whole model answer is discarded | `insufficient_evidence` / `evidence_no_longer_admissible`: no model text, recommendation, citation or model-referenced fact; signals, what-if numbers and basis stay. A recheck that cannot run ⇒ 503 `retrieval_unavailable` (never a pass) |
| C7 | M6.1 records the outcome | outcome `evidence_refused`; `response_emitted` still means only that the backend built the body, never receipt |

### Security
- The recheck runs with the caller's JWT. A season the caller cannot read gives no rows. Another tenant's chunk gives no rows. Neither reveals whether the document exists.
- The caveat helper is SECURITY DEFINER, because the E2 tables are not client-readable. It answers only when the caller can read the season (`private.user_can_read_farm`) and the chunk passes the same admissibility rule. It returns finding types, never content.
- E5 runs after M2, E2, E7 and H-a, and bypasses none of them: it only removes evidence, it never admits any.
- M6.1 change: an `evidence_refused` event may name retrieved chunks that left the approved state mid-request. That departure is exactly why the answer was refused. The tenant-scope check stays, and the stored assurance label is truthful (`unrecorded` is added). Before this change, such an event was refused and `record_safely` swallowed the error, so the exposure-relevant event was silently lost.

## 2. Consistency boundary (exact)

The recheck sees the database as of its own statement. A change committed **after** that statement, and before the bytes reach the client, is not seen. `test_a_change_committed_after_the_recheck_is_not_seen_by_the_response` pins this, and the M6.1 exposure query covers that window after the fact. Holding a lock until the network write completes would not remove the race either (the client may still be slow to read), so the stronger claim is not made.

## 3. Tests

**DB tests** (`test_rag_knowledge_m7_e5_answer_time.py`, 19). They use the real retrieval RPC, the real recheck under the member's JWT, and the real `RagQuestionService` with a scripted model:

1. a valid citation;
2. a citation of a visible chunk that was not retrieved (502);
3. the source quarantined after retrieval (H-b);
4. the document archived after retrieval (H-b archivist);
5. expiry between retrieval and response (owner edit of `effective_to`, standing in for the date passing);
6. a chunk hash mismatch: text edited behind the trigger, and the recorded hash edited;
8. assurance relabelled `unrecorded` (owner edit);
9. the demo recheck refused on a shared database;
10. cross-tenant citation injection (502), with the recheck and caveat helper revealing nothing;
11. an authoritative recommendation whose only citation is quarantined, plus its M6.1 event;
12. the frozen dev3-01 fixture approved through a mistaken expert: cited, **with the caveat**;
13. a model that declines (no recheck);
14. a database failure during the recheck (503).

Plus the consistency boundary, execute grants, and the E5 rollback (refuses while `evidence_refused` events exist; on a clean database it restores M6.1 exactly).

**Offline tests** (`test_rag_answer_integrity.py`, 7). They cover:
- **case 7:** a wrong document version;
- unknown, demo and null assurance in production;
- the demo mode;
- not retrieved;
- a recommendation without a citation;
- a reader that cannot recheck or fails;
- the refusal shape and the caveat.

Case 7 cannot be staged in the database (a chunk id belongs to one version), so it is covered offline.

**Offline fixtures.** The benchmark and the offline fixture readers stand for an approved corpus that stays admissible. They answer the recheck with `fixture_evidence_state`.

## 4. dev3-01 (`test_e5_full_chain_matrix_on_the_real_answer_path`)

| Path | Claims | Independent verification | Review | Approval | Retrieval | Answer-time check | Response |
|---|---|---|---|---|---|---|---|
| Dishonest operator omits the claims | omitted by the operator | `mismatch` | refused | no | not retrievable | not reached | refused `citation_mismatch`, poison not cited |
| Honest operator, mistaken expert (`false_positive`) | detected | `reproduced` | accepted (recorded human error) | approved | retrievable | admissible, **caveat shown** | generated, **poison cited** |

The second row is why `test_rag_source_integrity_gap.py` is **not** flipped and dev3-01 stays OPEN.

## 5. Remaining gaps
- **E1:** authoritative reference verification.
- **E3:** detection-to-containment policy (detection never quarantines).
- **E4:** real expert identity and qualification.
- **E6:** a real-model replay (only scripted models here).
- **E7:** its infrastructure (#77 §6): a non-owner producer login, a separate verifier runner, and the hosted attestation mode.
- **E5:** the post-recheck window (§2); hosted deployment of the RPC.

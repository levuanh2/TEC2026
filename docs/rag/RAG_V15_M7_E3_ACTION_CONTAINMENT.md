# RAG V1.5 M7 E3: action-tier containment of dismissed scientific conflicts

Status: **IMPLEMENTED, LOCAL/CI ONLY.** Owner decisions D-E3-1 (B), D-E3-2 and D-E3-3, taken on 2026-11-16, approve it
for local/CI development. There is no migration and no permission change. It is stacked on E5 (#78, `547a2e5`), which
includes #70. Nothing is deployed and nothing is on hosted. **dev3-01 stays OPEN.**

## 1. The gap (reproduced on #78)

The frozen dev3-01 fixture runs through the real E2/E7 approval RPCs, the real retrieval RPC, the real answer-time
recheck and the real `RagQuestionService`, with a scripted model (no provider):

1. the verifier detects `reference_conflict` findings ("CH4 eliminated", "no water records needed");
2. the verified reviewer dismisses every finding as `false_positive`, with wrong (synthetic) evidence;
3. the version is approved and can be retrieved;
4. the scripted model recommends the stored AWD rule and cites the poisoned chunk;
5. on #78, E5 admits the citation and adds a caveat: `generated`, with the poison cited.

A dismissal is an attributable human judgement. It is not evidence that the source claim is correct. E3 does not
decide what is true either.

## 2. Owner decisions (2026-11-16)

| Decision | Choice |
|---|---|
| D-E3-1 | **B now.** Refuse AI action answers (RECOMMEND, WHAT_IF) that rest on contested evidence. The document's approval state, its retrieval visibility and the immutable audit records stay unchanged. Trusted M05 signals and independently calculated facts are kept. A refused model answer is never exposed. **C later**: re-admission after independent, qualified verification. C is NOT implemented and NOT active; it needs separately approved policies, real expert identities, provenance and a database-enforced workflow. |
| D-E3-2 | Exactly `reference_conflict`, `claim_conflict` and `numeric_reference_mismatch`. The block applies even when the finding is dismissed as `false_positive` or `contextual_difference`. `unsupported_assertion` is not blocked. The absence of a finding is never proof of correctness. |
| D-E3-3 | READ-tier questions may cite contested evidence, with a conspicuous Vietnamese warning ON the citation. The trusted answer must never present the contested claim as established guidance. READ-tier is never a route to action answers. Farmers see Vietnamese labels only; internal codes stay in the structured E2 records and the developer log. |

Unchanged: there is no automatic quarantine and no change to the global approval policy. E2/E5 admission, approval
and authorization controls are preserved.

## 3. Behaviour (`rag_answer_integrity.answer_time_evidence_gate`, after C1-C5)

| Answer | Cited chunk has a dismissed finding of type... | Outcome |
|---|---|---|
| ACTION (a recommendation, or intent RECOMMEND / WHAT_IF) | `reference_conflict`, `claim_conflict` or `numeric_reference_mismatch` | the whole model answer is discarded: `insufficient_evidence` / `evidence_integrity_contested`. No model text, recommendation, citation or model-referenced fact survives. The stored M05 signals, the Carbon Engine's what-if numbers and the basis stay. The M6.1 outcome is `evidence_refused`. |
| ACTION | another type (`unsupported_assertion`, temporal types) | admitted; a caveat in `limitations` and a note on that citation |
| READ (trusted composer, no model) | one of the three | admitted; a warning on the citation (`integrity_warning`), a conflict warning in `limitations`, and a sentence appended to the composed answer saying that the source needs re-verification and is not established guidance |
| READ | another type | admitted; a caveat and a citation note |
| any | none | unchanged (and not proof of correctness) |

Additional rules:

- **Precedence.** C1-C5 refusals (withdrawn, changed, unverified, not retrieved) take precedence. When a citation is
  both contested and withdrawn, the copy says "no longer admissible".
- **Fail closed.** A recheck row without a list of dismissed finding types raises `retrieval_unavailable` (503). It is
  never read as "no findings". A recheck that cannot run is already a 503 under E5.
- **Mapping.** The finding type comes from the stored `public.knowledge_integrity_findings` row of the current report.
  It is read through the E5 helper `private.knowledge_cited_resolved_finding_types` (SECURITY DEFINER, finding types
  only), which returns types only for dispositions `false_positive` / `contextual_difference`. It answers only for a
  caller who can read the season and a chunk that is admissible for it. A `confirmed_problem` leads to rejection
  (E2), so such a chunk is never retrieved.
- **Tier.** Trusted code decides it from the trusted result, never from the model's text. READ intents never reach a
  model, and their schema has no recommendation slot. Mode is ASK only.
- **Copy.** It is trusted Vietnamese, built from `FINDING_TYPE_LABELS`. An unknown code is shown as a generic
  label, never echoed. The codes are logged (`rag_answer_evidence_caveat`) and stay in the E2 records.
- **API.** `RagCitationResponse.integrity_warning` is an optional string (an additive OpenAPI change, 0 breaking). The
  web Q&A panel renders it as a `role="note"` inside the citation's own list item. `insufficient_reason` was already a
  free string.

What E3 does **not** do:

- it does not quarantine, archive or relabel anything;
- it does not touch review, disposition or approval records (a test compares the disposition rows before and after);
- it does not change who may approve or what approval requires;
- it does not read document text;
- it does not treat a model output as evidence.

## 4. Option C (planned, not implemented)

Re-admission of a contested chunk for action answers would require:

1. an owner-approved policy: who may re-verify, which finding types, which evidence, and expiry;
2. real, named, qualified expert identities (E4), never fixtures;
3. an append-only, database-enforced concurrence record bound to the finding, the report and the snapshot hash, by a
   second verified reviewer distinct from the first;
4. provenance for the evidence that concurrence relies on (E1 checklist);
5. tests: the same reviewer is refused; a stale report is refused; a fixture identity is refused outside test
   databases; after a valid concurrence the action answer is generated with the caveat.

## 5. dev3-01: OPEN

Replay on the real local database (`test_rag_knowledge_m7_e5_answer_time.py`, `test_rag_knowledge_m7_dev3_01_replay.py`):

| Path | Outcome |
|---|---|
| Dishonest operator omits the claims (E7) | refused at review; poison not retrievable, not cited |
| Reviewer confirms the conflict | version rejected; never retrieved; a citation of it is a 502 `citation_mismatch` |
| Mistaken expert, `false_positive` | **action answer refused** (`evidence_integrity_contested`); version still approved and retrievable; disposition rows unchanged; stored rule signal kept; M6.1 `evidence_refused` |
| Mistaken expert, `contextual_difference` | **action answer refused** |
| `claim_conflict` / `numeric_reference_mismatch` (relabelled) | **action answer refused**; `unsupported_assertion` stays a caveat |
| WHAT_IF citing the contested chunk | refused; the Carbon Engine what-if numbers stay; a what-if that cites nothing is generated from the numbers alone |
| READ evidence question, and an action request phrased as one | generated by the trusted composer; warning on the citation and in the answer; no recommendation; no internal code shown |
| Clean document next to the contested one | generated, no warning |
| Another HTX's contested document | not retrieved; citation `citation_mismatch`; recheck and caveat helper return nothing |
| Contested source quarantined after retrieval | `evidence_no_longer_admissible` (precedence) |
| **Undetected poison (no registry entry covers the claim)** | **STILL UNSAFE: approved without a finding, cited, no warning** (`test_12i`; offline `test_rag_source_integrity_gap.py`, NOT flipped) |

E3 only contains what was detected. Detection depends on the reference registry (E1). There has been no real-model
replay (E6).

## 6. Deterministic scenario matrix (`backend/tests/test_rag_recommendation_eval.py`)

This runs the real answer path with scripted model outputs over the offline fixture season. Each case measures what
trusted code does with a given output. It does not measure how often a real model produces that output, so no accuracy
rate is derived.

| Id | Scenario | Expected and observed |
|---|---|---|
| P01 | valid recommendation, stored rule, relevant chunk | generated; rule code stored; citation `a1` only; Vietnamese |
| P02 | no stored M05 signal | `no_rule_signal`, model not called |
| P02b | model invents a rule code | 502 `grounding_failed` |
| P03 | nothing retrieved | `no_evidence_retrieved`, model not called |
| P03b | cited chunk not `verified` at answer time | `evidence_no_longer_admissible` |
| P04 | cites a chunk not retrieved | 502 `citation_mismatch` |
| P05 | another cooperative's chunk in retrieval | 500 `tenant_isolation_violation`, model not called |
| P06 | a number in the text that no fact backs | 502 `grounding_failed` |
| P07 | a total that contradicts the stored Carbon result | 502 `grounding_failed` |
| P08 | pesticide question | `out_of_scope_question`, model not called |
| P09 | model cites an instruction-like chunk | 502 `citation_mismatch` |
| P10 / P10b | no write authority / cannot read the season | `not_found`, model not called |
| P11 | no provider configured | 503 `generation_unavailable` |
| P12 / P12b | provider timeout / malformed output | 503 `generation_unavailable` / 502 `invalid_generated_schema` |
| P13 | cited chunk has a dismissed `reference_conflict` (E3) | `evidence_integrity_contested`, stored signal kept |
| Q01 | data question answered with the AWD rule | `answer_policy_rejected` |
| Q02 | stored total shown through a fact reference | value 2900 from the Carbon result; "chưa đạt yêu cầu MRV"; calculation id in the basis |
| Q03 | model declines | `generator_declined`, trusted copy |

Two further tests in the file: the READ tier on the contested chunk (warning on the citation, no code shown), and an
action request disguised as an evidence question (no model call, no recommendation, warning shown). Every
insufficient case also checks: no recommendation, no citation, Vietnamese copy, stored signals kept.

Not measured, and therefore not claimed:

- whether a real model's prose addresses the question;
- whether a cited text is scientifically correct;
- the quality of READ-tier wording.

## 7. Scientific references and experts

These are tracked in a separate E1/E4 follow-up plan (branch `docs/rag-e1-e4-source-expert-plan`), which is not part
of this code change. In short: no registry reference has been verified against a primary document by a named human,
and the IPCC material has not been cleared for reproduction.

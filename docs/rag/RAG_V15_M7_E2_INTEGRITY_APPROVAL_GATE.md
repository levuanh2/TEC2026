# RAG V1.5 M7 E2: integrity evidence before knowledge approval

Status: **IMPLEMENTED, LOCAL/CI ONLY.** Migration `20261113210000_knowledge_integrity_approval_gate_m7_e2.sql`,
rollback `supabase/rollbacks/20261113210000_knowledge_integrity_approval_gate_m7_e2.down.sql`. Stacked on the
M7 harness (#71). Not applied to hosted. **dev3-01 stays OPEN** (E1, E3, E4, E5, E6 remain).

## 1. Root cause

`public.knowledge_submit_expert_review` and `public.knowledge_decide_document` (M2, replaced in M3) checked
the reviewer's OWN `findings` list, which the reviewer writes. The offline integrity review (M4) detected the
dev3-01 claims, but nothing bound the expert review to that analysis of the stored content: a reviewer who
left the problem out could recommend approval, and the approver could approve. Reproduced on the pre-E2
functions in `test_e2_the_bypass_works_without_the_gate_and_is_refused_with_it` (E2 rolled back inside the
test transaction: the poisoned version becomes `approved`; with E2 the same calls are refused).

## 2. What is reproducible from the immutable snapshot (Phase A)

| Evidence | Authoritative? |
|---|---|
| document / source snapshot hash (covers file sha256, normalized sha256, chunk manifest of ordinal, chunk id, content sha256) | yes, computed by the database |
| claim spans (M4 `knowledge_claims`) | yes for the span: the database checked `substr(content, start, len) = raw_text` and the chunk hash; the extractor's coverage is NOT proven |
| whether a finding type needs expert review | yes: set by the database from the type (closed list), the caller cannot downgrade it |
| completeness w.r.t. stored claims | yes: every stored extracted assertion must be in a needs-review finding or declared supported by a named reference; every unreadable claim must be in an `unresolved_claim` finding |
| reference conflicts | **as right as the pinned registry**: the qualitative entries are an engine-config pointer and an internal policy, not human-verified primary sources (E1) |
| numeric comparison | **unavailable**: the numeric registry is empty |
| claims the extractor does not know | **unavailable**: zero claims is never "clean"; the report says so and the reviewer must acknowledge it |

## 3. Evidence model

- `private.knowledge_integrity_policy`: the pinned extractor, review and registry version and digest, set by
  the owner only (`private.knowledge_set_integrity_policy`). Unpinned (the migration's default) = every
  recommendation and approval is refused (fail closed).
- `public.knowledge_integrity_reports`: one materialized report per run: document, source, version,
  document and source snapshot hashes, file and normalized sha256, chunk manifest hash and count, versions,
  registry digest, claim / finding / blocking counts, supported claims, limitations (at least one, stated by
  the producer), a report hash computed by the database, actor role and session user.
- `public.knowledge_integrity_findings`: per finding a deterministic key, type, `needs_expert_review` (set by
  the database), claim and reference ids, detail, and the evidence spans copied from the stored claims.
- `public.knowledge_integrity_dispositions`: per review, the reviewer's acknowledgement of the exact report
  (`report_reviewed`) and a disposition of each finding, bound to review id, report id and report hash,
  finding id, verified personnel, user and session.

All three are append-only (the M2 evidence guard: INSERT only inside their function, never UPDATE / DELETE /
TRUNCATE, also for the owner), RLS on with no policy, SELECT for `service_role` only. Reviewers, approvers and
uploaders of the version's scope read the current report through `public.knowledge_review_integrity_report`.

**Producing a report** (`private.knowledge_record_integrity_report`, service_role): the operator pipeline
(`infrastructure.knowledge_claims_repo.record_integrity_report`: extract and store claims, run the pinned
offline review, `knowledge.integrity.report.report_payload`) submits findings, supported claims and
limitations. The database refuses: an unpinned policy or other versions / digest; a version that is not under
review; a finding naming a claim that is not a stored claim of this version on the current chunk text; a
supported claim that is not a stored assertion or names no reference; a report that omits a stored assertion
or an unreadable claim. A client (authenticated, anon) cannot call it. **Trust boundary:** the database cannot
re-run the extractor; a report is as complete as the claims stored for the snapshot. The operator cannot
fabricate a span, downgrade a conflict or skip a stored claim; the owner / superuser boundary of M1-M2 is
unchanged.

## 4. Dispositions

`public.knowledge_dispose_integrity_finding(review, report_sha256, finding, disposition, justification, evidence)`,
the review's own verified reviewer only (aal2, role still active), review undecided, against the CURRENT valid
report (stale or other report: refused, `40001` for a hash that is not the current one):

| Disposition | Effect on a finding that needs expert review |
|---|---|
| `confirmed_problem` | blocks the recommendation (reject or return instead) |
| `needs_more_evidence` | stays unresolved: blocks |
| `false_positive` | resolves it; needs evidence `[{reference, locator}]` and a justification (20+ characters) |
| `contextual_difference` | resolves it; needs evidence that names `conditions` |
| `accepted_with_justification` | refused for a finding that needs expert review (policy allows it only for information findings) |
| `report_reviewed` (no finding) | the mandatory acknowledgement of the report and its limitations |

One disposition per review, report and finding, immutable. A new report (new claims, re-run, registry
re-pin) has new finding ids and a new hash: earlier dispositions are never reused.

## 5. The gate (submission and approval)

`private.knowledge_integrity_gate(document, review)` is called in the replaced M3 RPCs right after the
cross-source check, on `recommend_approval` and again on `approve` (inside the approval transaction, so the
approval record and the transition stay atomic). It refuses (`23514`) unless:

1. the policy is pinned and the latest report of the version was made with the pinned versions and digest;
2. the version and its source still hash to the report's snapshots, and no claim was stored after it;
3. the review was started on the same snapshot;
4. the review's reviewer acknowledged that exact report;
5. no finding is `confirmed_problem` or `needs_more_evidence`;
6. every finding that needs expert review is resolved by that reviewer as `false_positive` or
   `contextual_difference` with evidence.

Reject and return need no report. The approver keeps the M2 separation (uploader, reviewer, approver
distinct), the M3 validity and the H-c supersession checks run as before. There is still no direct status
UPDATE and no service-role approval; no automatic approval or quarantine was introduced. Concurrency: a report
being recorded holds a share lock on the version; the approval's `FOR UPDATE` waits for it and then sees it
(test 10).

## 6. Tests (`backend/tests/test_rag_knowledge_m7_e2_integrity_gate.py`, PostgreSQL)

Before/after reproduction; 1 missing report; 2 empty, invented-claim and wrong-registry reports, client calls,
evidence immutability; 3 reviewer omits the detected problem / leaves it open; 4 reject and return allowed;
5 a new report voids earlier dispositions at approval; 6 false positive needs evidence, the review's reviewer,
a resolving disposition, a real justification; 7 stale after a metadata change; 8 another version's report;
9 registry re-pin; 10 committed race (report recorded while the approval waits); 11 tenant scope of the
reader, no client table read; 12 no service-role / direct SQL path; 13 legacy `unrecorded` version
revalidated through the gated flow (supersedes and archives the legacy row); 14 quarantine and archive after a
gated approval. Every existing knowledge suite passes through the fixture helper, which records and
acknowledges the report and never resolves a blocking finding by itself.

## 7. M7 re-run

`test_rag_knowledge_m7_dev3_01_replay.py` (frozen dev3-01 fixture, real retrieval, real answer service):
integrity findings generated; the reviewer who ignores them cannot recommend approval; the status stays
`expert_review`; nothing is retrieved or cited. The dev3-01 state can now only be reached by an explicit,
recorded human error (every finding resolved as `false_positive` with evidence); then quarantine still
removes it from retrieval and the answer side. The characterization `test_rag_source_integrity_gap.py` is
NOT flipped: it pins answer-path behaviour for an already-approved poisoned chunk (E5).

## 8. Rollback

First in the order (E2, then H-c, H-b, H-a, ...). Restores M3's exact submit and decide (E2 reopens) and drops
the evidence: refuses without `set local knowledge.e2_rollback_confirmed = 'yes'`.

## 9. Hosted

Not applied. Before a hosted migration: owner decision; the policy must be pinned on hosted (until then every
approval is refused, by design); existing review_required / expert_review versions need a report; the
operator pipeline must run there.

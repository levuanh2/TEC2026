# RAG V1.5 — Source content integrity (design, 2026-11-08)

Status: **DESIGN ONLY.** No migration, no ingestion, no hosted change, no automatic approval. Builds on
`RAG_V1_SOURCE_POLICY.md` (trust status, approval requirements) and `RAG_V1_INGESTION.md` (ST1/ST1.1).

## 1. The gap (dev3-01, deepseek-flash, synthetic fixture)

The approved-looking chunk `poisoned_claim` says AWD for one season ends methane emission and makes water
records unnecessary. It is plausible, addressed to nobody, contains no injection marker, and passes every
control on the answer path: the citation is a retrieved chunk, the recommendation carries a stored M05
rule_code, the facts are grounded. The model cited it; the benchmark labels the case
`SOURCE_INTEGRITY_FAILURE`; the trusted pipeline cannot (test
`tests/test_rag_source_integrity_gap.py` pins this behaviour until a content control exists).

What the existing controls guarantee — and do not:

| Control | Guarantees | Does not guarantee |
|---|---|---|
| Source/version approval (`approved_by`, `approved_at`, `review_note`) | a named human accepted it | that its statements are correct |
| ST1/ST1.1 `artifact_ref = knowledge-artifacts/<file_sha256>/…` | the stored bytes are the approved bytes | that the bytes came from the claimed publisher, or are true |
| One approved version per document; `approved -> archived` | superseded versions are not retrieved | that the current version agrees with other sources |
| Approved-only, tenant-scoped retrieval (RLS + RPC) | no draft, rejected, archived or foreign chunk is cited | content correctness |
| Instruction-marker drop, body relevance, citation/rule/grounding gates | injected instructions and unrelated chunks are not evidence | a false statement written as plain guidance |

## 2. Threat model

| Actor / cause | Path | Impact | Main control (this design) |
|---|---|---|---|
| Malicious uploader / compromised operator account | uploads a forged "official" PDF | false advice cited with authority | §3.1 authenticity (signature, official anchor), two-person approval §3.5 |
| Compromised or spoofed publisher site | download of altered artifact | as above | §3.1 PKI signature / hash from an independent channel |
| Honest but wrong or outdated publication | correct provenance, wrong content | wrong practice (water level, dose, timing) | §3.2 effective dates, §3.3 contradictions, §3.4 reference comparison, §3.5 expert |
| Superseded guidance left approved | old version still approved under another document_id | stale advice | §3.2 `supersedes` link + effective_to |
| Contradicting sources | two approved documents disagree | model picks either | §3.3 detection -> quarantine |
| Text laundered by an LLM (summaries, translations) | derivative text approved as primary | hallucinated statements | §3.1: only primary artifacts; derivatives rejected |
| Scope creep inside a valid document | approved guide also contains pesticide doses | out-of-policy advice | §3.5 checklist + chunk-level exclusion |
| Insider approver mistake | approves without checks | any of the above | §3.6 evidence record, §3.9 audit, periodic re-review §3.8 |
| Numeric / unit error | "15 cm" vs "1.5 cm" | wrong practice | §3.3/3.4 numeric claim checks |

Assets: farmer-facing advice, carbon/MRV statements, trust in citations. Out of scope: the model's own
reasoning errors (answer-path gates), tenant isolation (RLS, tested).

## 3. Workflow

States (proposal; `quarantined` and `expert_review` are NEW values needing a migration + owner approval):

```
review_required --(automated checks pass)--> expert_review --(expert + approver)--> approved
      |                     |                         |
      +--> rejected <-------+                         +--> rejected
approved --(dispute / contradiction / revocation signal)--> quarantined --(re-evaluated)--> approved | archived
```
Only `approved` is retrievable (unchanged rule); `quarantined` is never retrievable (fail closed).

1. **Authority and authenticity.** Publisher on an allowlist per knowledge class (`RAG_V1_SOURCE_POLICY`
   §2). Artifact fetched from the official HTTPS anchor; where the publisher signs (VN government PKI),
   verify the signature and CRL; otherwise compare the SHA-256 with a hash obtained through a second
   channel. Only primary artifacts — no summaries, translations or LLM output. Recorded: anchor URL,
   retrieval time, signature/verification result.
2. **Version and effective date.** `effective_from`, `effective_to`, `supersedes` (document_id/version) per
   version; approval refused when `effective_to` is past or the superseded version is still approved; a
   scheduled check moves expired versions to `quarantined`.
3. **Contradiction detection.** Deterministic extraction of checkable claims per chunk (numbers with units,
   crop stage, water level, days, rates, emission factors) into a claim table; the same claim key with a
   different value in another approved or candidate chunk raises a contradiction. An LLM MAY propose
   candidate claims or contradictions as a reviewer aid; its output never approves, rejects or changes
   status by itself.
4. **Trusted reference comparison.** A small, versioned reference registry (MRV/IPCC factors already used by
   the Carbon Engine, ministry AWD parameters) holds the canonical values; a claim outside the registry
   tolerance blocks approval until the expert records a justification.
5. **Domain-expert review.** Required for every chunk that can support a consequential recommendation
   (irrigation regime, fertilizer, emissions). Two people: expert reviewer ≠ approver ≠ uploader. Checklist:
   provenance, dates, scope (no pesticide/dose content in ACTION evidence, or chunk excluded), each flagged
   claim resolved.
6. **Explicit evidence.** An immutable approval record per decision: who, role, when, checklist answers,
   claims checked and references used, contradictions resolved, rationale; rejection records the same.
7. **Quarantine.** Any dispute (farmer/agronomist report, contradiction, reference mismatch, publisher
   withdrawal, signature revocation) moves the version to `quarantined` immediately; retrieval stops; the
   approval record gains the trigger.
8. **Revocation and re-evaluation.** `quarantined -> approved` only through a new expert review;
   `quarantined -> archived` for withdrawn/false content. On revocation, list answers logged with that
   chunk (request ids in logs, no question text) and re-run the regression/benchmark set before re-approval.
9. **Audit trail for approved chunks.** Per chunk: content_sha256 (exists), document version, approval record
   id, claim ids; append-only event log of status changes (actor, time, reason). Retrieval logs keep chunk
   ids so a revoked chunk's exposure window is measurable.
10. **Tests for poisoned-but-structurally-valid citations.** Offline: the benchmark fixture
    `poisoned_claim` must stay a SOURCE_INTEGRITY_FAILURE at model and end-to-end level (exists); the
    characterization test pins today's trusted-path behaviour. With the workflow: a quarantined or
    contradicted chunk is never retrieved (DB test like `test_unapproved_rejected_and_archived_knowledge_is_invisible`);
    approval without an evidence record, with an expired effective date, or with an unresolved
    contradiction is refused by the DB; an LLM-only verdict cannot change status.

## 4. What this design refuses
- Automatic approval from an LLM judgement (or from any single automated check).
- Treating a valid citation, a valid hash or a valid signature as proof of correctness.
- Approving derivative text (summaries/translations) as a source.

## 5. Implementation plan (each step needs owner approval)
1. Migration (local first): status values `expert_review`, `quarantined`; columns `effective_from`,
   `effective_to`, `supersedes_*`; tables `knowledge_claims`, `knowledge_approval_records`,
   `knowledge_status_events` (append-only); approval guard extended; retrieval unchanged (approved only).
2. Offline tooling: claim extraction + contradiction report for a candidate document; reference registry file.
3. DB tests (local isolated stack, CI) for every refusal above; benchmark fixture for a contradiction pair.
4. Runbook: expert checklist, quarantine triggers, revocation steps.
5. Hosted application only after the first real corpus acceptance gate (`RAG_V1_INGESTION` §8).

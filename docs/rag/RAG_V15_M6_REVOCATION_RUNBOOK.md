# RAG V1.5 M6: quarantine and revocation runbook, exposure traceability

Status: **RUNBOOK + LOCAL TABLETOP. No migration, no logging deployed, nothing on hosted.** Stacked on
H-a (#65), H-b (#66) and H-c (#68), whose functions it uses. Milestone definition:
`RAG_V15_SOURCE_CONTENT_INTEGRITY.md` (M6 row). dev3-01 stays OPEN (M7 gate, section 8).

## 1. Trigger matrix

| Trigger | Who notices | Action | Function | Reason code |
|---|---|---|---|---|
| Artifact hash / provenance does not match (ST1.1, integrity review) | operator, reviewer | quarantine version | `private.knowledge_emergency_quarantine_document` | `integrity_mismatch` |
| Publisher withdraws or corrects the text | custodian, reviewer | quarantine version (or source) | `..._document` / `..._source` | `provenance_withdrawn` |
| License or permission withdrawn | owner, custodian | quarantine source | `private.knowledge_emergency_quarantine_source` | `rights_withdrawn` |
| Harmful or poisoned guidance reported (dev3-01 class) | farmer report, reviewer, M4/M5 finding | quarantine version | `..._document` | `harmful_content_report` |
| New law / decision supersedes the text, successor not yet approved | reviewer, custodian | quarantine version | `..._document` | `superseding_law` |
| Successor approved through the verified flow | approver | supersession archives it atomically | `public.knowledge_decide_document` (cross-source: custodian countersignature, H-c) | n/a |
| Demo content on a database going live | owner | quarantine all demo rows | `private.knowledge_demo_quarantine_all` | `demo_go_live` |
| Operator error (wrong version served) | operator | quarantine version | `..._document` | `operator_error_containment` |
| Approval window ends | scheduled job | expiry quarantine | `private.knowledge_expire_documents` | own expiry evidence |
| Quarantine concluded, never coming back | archivist (aal2) | archive | `public.knowledge_archive_document` / `_source` | `quarantine_concluded` (or another archive code) |

An M4 contradiction candidate or an M5 `numeric_reference_mismatch` is a **trigger for a human**,
never an automatic quarantine.

## 2. Incident steps

1. **Open an incident record** outside the database (ticket id). It is the `operator_reference`.
2. **Contain** (minutes, no qualified human needed): emergency quarantine with the reason code from
   section 1, a detail of 20-2000 characters and the ticket id. Quarantine is one-way.
3. **Verify containment**: the chunk ids of the version are absent from
   `public.match_knowledge_chunks_lexical` for a member of an affected season, and from RLS reads
   (tabletop test, section 7). Cloudflare/HTTP caches do not hold answers (answers are not cached or
   persisted: `provenance.persisted = false`).
4. **Exposure** (section 4): run `docs/rag/sql/m6_exposure_window.sql` for each chunk id; record the
   window(s) in the ticket.
5. **Notify** the affected scope: public guidance, everyone; tenant guidance, the organization.
   Section 5 states what cannot be traced today.
6. **Re-evaluate** (section 6) and decide: archive (archivist), or replace with a new version.
7. **Close** the ticket with the emergency action id, the exposure window and the decision.

## 3. Roles

| Step | Role | Control |
|---|---|---|
| Contain | operator with `service_role` | H-b emergency function; typed evidence; no human identity proven |
| Archive | `archivist` (aal2, scope, not uploader, not direct approver) | H-b |
| Replace | uploader, expert reviewer, approver (distinct humans, aal2) | M2/M3 |
| Cross-source replace | plus a target-source custodian countersignature | H-c |

## 4. Exposure window (supported now)

`docs/rag/sql/m6_exposure_window.sql` (read-only, `service_role` or owner) returns, for a chunk id:
the version and source approval times, when each left `approved` (to which status, with which
reason), `servable_from = max(version approved, source approved)`, `servable_until = min(version left
approved, source left approved)`, the effective dates and approval expiry (listed, not subtracted),
the approval assurance, and the emergency actions with their references.

This is the interval during which retrieval **could** return the chunk. It is an upper bound of
exposure. A version approved before M1 has no history: `servable_from` is null ("before the audit
log").

## 5. Request-level traceability (NOT supported now: blocker, stated)

Inspected on `integrate/rag-v15` (2026-11-13):

- `backend/rag_qa.py` logs one line per question to stdout: `request_id, intent, mode, status, error,
  llm_calls, tokens, cost, latency`. **No chunk ids, no document versions, no user or season, no
  organization.**
- `backend/infrastructure/llm_quota.py` logs provider usage only.
- No table stores questions, answers or citations (answers are returned with `persisted: false`).

So **which answers cited a revoked chunk cannot be listed** for any period before citation logging
exists. Nothing in this PR claims otherwise, and no historical log is reconstructed.

### 5.1 Logging design (local/CI first; NOT deployed)

A structured, append-only citation event per answered question, written by the backend after the
policy check, with no question or answer text:

| Field | Note |
|---|---|
| `request_id` | already generated per request |
| `occurred_at` | server time |
| `crop_season_id`, `organization_id` | the authorized scope (from `CallerSeasonScopeResolver`) |
| `caller_ref` | a keyed hash of the user id (HMAC, key outside the database), not the id |
| `status`, `answer_source` | as in the response provenance |
| `citations` | `[{chunk_id, document_pk, document_version, approval_assurance}]` exactly as returned |
| `retrieval_rpc` | `production` or `demo` |

Storage options, both needing an owner decision before hosted: (a) the existing log pipeline (stdout
JSON line, retention set by the host), or (b) a table `public.knowledge_citation_events` (RLS on, no
policy, `service_role` SELECT, INSERT through a definer function that re-checks the caller could
retrieve the cited chunks). Exposure query with logging: join the window of section 4 with the
events whose `citations` contain the chunk id. Privacy: retention limit, tenant-scoped export only,
no free text. Implementation is a separate PR; it changes the answer path, so it needs its own
review.

## 6. Re-evaluation and regression before a replacement is approved

1. The corrected text is a **new version** (quarantine is one-way; the old approval record stays as
   evidence).
2. It passes the full M2 flow: upload attestation, expert review with the integrity review report
   (M4 claims and contradiction candidates; M5 numeric comparison against verified entries only),
   approval by a different human; cross-source replacement needs the H-c countersignature.
3. **Regression check** recorded in the review: the poisoned or wrong span is absent from the new
   chunks; the integrity review of the new version has no open blocking finding; the frozen dev3-01
   style fixture (M7) does not retrieve the old chunk.
4. Only then is the new version approved and served. The old version stays quarantined or is
   archived by an archivist.

## 7. Local tabletop (passes)

`backend/tests/test_rag_knowledge_m6_tabletop.py` on the clean isolated stack:

- a verified, served chunk is quarantined through the emergency function (`integrity_mismatch`,
  synthetic ticket): absent from production retrieval, from RLS reads of chunks and versions, and
  from the demo RPC on an isolated database; the exposure query lists a window with the emergency
  reason and the reference;
- a replacement is not served before approval, passes the regression check and the full verified
  flow, is then served while the old chunk stays excluded; the quarantined version can never return
  to approved;
- the exposure query is not readable by `authenticated` or `anon`.

## 8. M7 gate (preserved)

M7 may mark dev3-01 fixed only after: M1-M5 integrated and independently validated; this tabletop
passing; the frozen dev3-01 fixture replayed; contradicted or quarantined poisoned content shown not
retrievable; the answer side evaluated on actual system behaviour; the characterization test flipped
only after the regression is proven; results and limitations documented. None of that is done here.
dev3-01 is OPEN.

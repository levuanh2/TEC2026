# RAG V1.5 M6.1: metadata-only citation events (local/CI prototype)

Status: **PROTOTYPE, LOCAL/CI ONLY. Not enabled, not deployed, nothing on hosted.** Migration
`20261113180000_knowledge_citation_events_m6_1.sql`, rollback
`supabase/rollbacks/20261113180000_knowledge_citation_events_m6_1.down.sql`, backend
`backend/rag_citation_events.py`. Stacked on M6 (#69), which is stacked on H-c/H-b/H-a. Owner decision
2026-11-13: prototype minimal metadata-only citation logging on local/CI; do not deploy or enable on
hosted. dev3-01 stays OPEN.

## 1. Why

M6 found that no request-level record exists: `rag_qa.py` logs `request_id/intent/status/tokens` to
stdout and answers are not persisted, so the answers that cited a revoked chunk cannot be listed. M6.1
is the smallest record that would answer that question in future, without storing content.

## 2. What is recorded (and what is not)

One event per answered question, written after the answer was built:

| Field | Source | Note |
|---|---|---|
| `request_id` | the request id (a fresh UUID if it is not one) | primary key |
| `occurred_at`, `retention_until` | database clock, retention policy | |
| `crop_season_id` | the authorized request | |
| `organization_id`, `farm_id` | **derived** from the season in the database | never caller-supplied |
| `retrieval_mode` | `production` or `demo` | demo only on isolated databases (H-a) |
| `outcome` | `generated`, `insufficient_evidence`, `policy_rejected` (`error` reserved) | |
| `response_emitted` | the backend built and returned the response body | **not** proof of receipt: a dropped connection, a proxy or client error is invisible to this log |
| `trace_completeness` | `complete`, `retrieval_unavailable`, `not_reached` | |
| chunk rows | `role` = `retrieved` or `cited`, `chunk_id`; **derived**: document pk, source, document id, version, approval assurance | cited is a subset of retrieved |

**Not stored, by construction** (there is no column and `CitationEvent` has no field): the question, the
answer, the prompt, the model output, a user id, an email, an API key or any provider secret.

**Three things kept apart:** a chunk RETRIEVED for a request is a candidate, not exposure; a chunk CITED
in the returned answer; and whether the backend EMITTED that answer. `cited` + `response_emitted` is the strongest evidence this log
records; it is still not proof that a farmer received or read the answer.

## 3. Controls

- **Local/CI only, enforced by the database:** `private.knowledge_record_citation_event` refuses (`42501`)
  unless `private.knowledge_deployment_isolated()` (H-a gate) holds. The shared hosted project fails the
  gate (real accounts), so even an applied migration plus a configured sink records nothing there.
- **Off by default in the backend:** `RagQuestionService(citation_sink=None)` is the default and what the
  app builds; nothing records. A test or a local harness passes a `PostgresCitationSink`. Recording never
  changes the answer: a failure is logged by error type only and swallowed.
- **Integrity:** EXECUTE for `service_role` only; every chunk must be an approved, served chunk visible in
  the season's scope (public, or the season's organization/farm), so a cross-tenant chunk cannot be
  recorded; cited must be a subset of retrieved.
- **Who reads (least privilege):** RLS on with **no policy**: no client role reads the log, cooperative
  managers included; only `service_role` reads it (incident response, tenant-scoped exports). Even
  without question text, farm + season + time + the cited chunk ids reveal what a farm asked about (a
  disease or fertiliser section), so any wider read access is an owner decision (section 5).
  Tenant separation is also enforced at write: a chunk outside the season's scope cannot be recorded.
- **Append-only:** INSERT only inside the record function, DELETE only inside the retention purge, never
  UPDATE or TRUNCATE, also for the owner.
- **Retention:** `private.knowledge_citation_settings.retention_days`, configurable, **30 days as the
  initial local/CI test value, not a production privacy decision**. `private.knowledge_purge_citation_events()`
  (service_role) deletes expired events (chunk rows cascade) and records each purge in
  `public.knowledge_citation_purges` (append-only).

## 4. Exposure with events

`docs/rag/sql/m6_1_citation_exposure.sql` lists, for one chunk id, the recorded requests with
`exposure = cited` (the emitted answer cited it; receipt not proven) or `retrieved_only` (candidate, not exposure). Outside the
recorded period, only the M6 possible-exposure window is known.

## 4a. Future incident-response export (design only, not implemented)

The shared `service_role` credential is not an authenticated human: reading the log with it identifies no
responder. A future export would be `public.knowledge_citation_incident_export(chunk_id, organization_id,
ticket)`, EXECUTE for `authenticated`, requiring a verified aal2 person with a dedicated
`incident_responder` registry role scoped to the organization (or to public sources), a ticket reference,
and writing an append-only export audit row (who, when, which chunk, which scope, row count). Output only the
requested organization's rows (or, for a public chunk, per-organization counts without farm ids), never
other tenants', with the same `cited` / `retrieved_only` / `response_emitted` columns and no content. Until
then no client role, cooperative managers included, reads the log.

## 5. Before any hosted use (owner decisions, none taken)

**Who may read the events at all** (today: service_role only; e.g. cooperative managers for their own
organization would expose members' question topics); retention period and legal basis; the write path (the sink uses
a service connection: a pool and failure budget for production); the isolation gate would have to be
replaced by an explicit, separate enablement decision for hosted; load and index review.

## 6. Rollback

First in the order (M6.1, H-c, H-b, H-a, ...): the H-a rollback now refuses while M6.1 is installed. It
drops the events and refuses without `set local knowledge.m6_1_rollback_evidence_exported = 'yes'`.

## 7. Tests

- `backend/tests/test_rag_citation_events.py` (offline): no content field; retrieved / cited / response emitted;
  outcomes; trace completeness; subset and error rules; no sink records nothing; a failing sink never
  raises; the service default is off.
- `backend/tests/test_rag_knowledge_m6_1_citation_events.py` (DB): refused on a shared database; derived
  scope and document identity; inconsistent events refused; cross-tenant chunk refused; grants;
  append-only for the owner; no client read access (managers, farmers, anon, authenticated), service_role only; retention purge and its record; the exposure
  query separates cited from retrieved-only.

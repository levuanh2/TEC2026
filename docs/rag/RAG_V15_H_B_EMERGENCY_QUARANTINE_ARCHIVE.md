# RAG V1.5 hardening H-b: emergency quarantine and permanent archive

Status: **IMPLEMENTED, LOCAL/CI ONLY.** Migration `20261113120000_knowledge_m2_hardening_operator.sql`,
rollback `supabase/rollbacks/20261113120000_knowledge_m2_hardening_operator.down.sql`. Stacked on H-a
(`20261113090000`, PR #65). Not applied to hosted. dev3-01 stays OPEN.

Design: `RAG_V15_M2_OPERATIONAL_HARDENING_DESIGN.md` sections 2 (H1) and 3 (H2). Owner decisions
(2026-11-12): **D-H2a** a separate `archivist` role; **D-H2b** the original approver must not archive
their own approved version directly while it is approved.

## 1. What was wrong

The shared `service_role` credential could move any approved version or source to `quarantined` or
to the terminal `archived` through `private.knowledge_transition_document` / `_source`, with a
free-text reason of 1 character or more. The audit event recorded the database role, not which
human acted, and an archive is permanent (a mistaken archive is recovered only by a new version).

## 2. Emergency quarantine (H1)

`approved -> quarantined` is now possible ONLY through

```
private.knowledge_emergency_quarantine_document(document_pk, reason_code, reason_detail, operator_reference)
private.knowledge_emergency_quarantine_source(source_id, reason_code, reason_detail, operator_reference)
```

- EXECUTE for `service_role` only (the owner can call it too). It is the brake, so it works when no
  qualified human is signed in.
- `reason_code` is a closed list: `integrity_mismatch`, `provenance_withdrawn`, `rights_withdrawn`,
  `harmful_content_report`, `superseding_law`, `demo_go_live`, `operator_error_containment`.
- `reason_detail` 20-2000 characters; `operator_reference` 3-200 characters (the ticket, incident
  or on-call record that names the human). Missing or invalid inputs: `22023`, nothing written.
- One call writes the status event and an append-only `public.knowledge_emergency_actions` row
  (snapshot, snapshot hash, reason, reference, database role, session user, the status event id,
  unique). Both or neither: a failed call leaves the row approved and writes no event.
- The evidence table: RLS on, no policy, SELECT for `service_role` only; INSERT only inside the
  function (the M2 evidence guard); UPDATE, DELETE and TRUNCATE refused, also for the owner.

**Kept, each with its own evidence:**

- M3 expiry (`private.knowledge_expire_documents`): `approved -> quarantined` when the approval
  window ends, with its own immutable expiry records. Unchanged.
- The demo go-live brake `private.knowledge_demo_quarantine_all`: quarantines demo-approved rows
  only, status events carry its `DEMO` reason. With H-a, demo rows exist only on an isolated test
  database. Unchanged.

**What the database cannot verify:** `operator_reference` is a pointer, not an identity. It makes the
action traceable outside the database; it does not prove which human used the shared credential.

## 3. Permanent archive (H2)

`approved -> archived` and `quarantined -> archived` are now possible ONLY through

```
public.knowledge_archive_document(document_pk, snapshot_sha256, reason_code, rationale)
public.knowledge_archive_source(source_id, snapshot_sha256, reason_code, rationale)
```

EXECUTE for `authenticated` only. The function requires, in this order:

1. A verified person: `private.knowledge_verified_actor()` (role `authenticated`, unexpired token,
   `aal2`, a live aal2 session of this user, a verified MFA factor, an active non-anonymous user, no
   pending password change). `service_role`, the owner login and a service session carrying a
   person's claims are refused (`42501`).
2. An active `archivist` role (new value of `knowledge_personnel_roles.role`, granted by a registry
   admin like every role) whose scope covers the source (visibility, organization). A missing
   version and an out-of-scope one get the same answer (no existence oracle).
3. Status `approved` or `quarantined` (else `23514`; `archived` is terminal).
4. `snapshot_sha256` equal to the current `private.knowledge_document_snapshot` /
   `_source_snapshot` hash (malformed `22023`, stale `40001`). The archivist reads it through
   `public.knowledge_review_snapshot`, which now also answers an archivist.
5. Separation of duties, by canonical identity (a second account of the same human is the same
   human):
   - the uploader of that version or source never archives it (from either status);
   - its approver never archives it **directly from `approved`** (D-H2b). From `quarantined` the
     approver may archive: that is a separate, prior emergency action plus an archivist decision.
6. Closed `reason_code` (`withdrawn_by_publisher`, `repealed_or_replaced`, `quarantine_concluded`,
   `rights_ended`, `duplicate_version`, `retention_policy`) and a 20-2000 character rationale.

It writes the status event and an append-only `public.knowledge_archive_records` row (personnel,
role, user, session, from status, reason, rationale, snapshot, hash, status event id) in one call.

**Supersession is preserved.** A verified approval of a successor (`public.knowledge_decide_document`)
still archives the version it supersedes in the same transaction (M3), with no archivist: the
independently authorized approval is the authority, and its approval record is the evidence.

**No break-glass.** If no qualified archivist exists, nothing can be archived, and nothing needs to
be: quarantine already removes the material from retrieval. There is no owner or service fallback.

## 4. The generic operator path

`private.knowledge_transition_document` / `_source` keep the M1/M2 contract (argument checks
`22023`/`23514`, unknown `P0002`, stale `23514`, M2 refusals) and then refuse quarantine and archive
with `42501`, naming the new function, for every caller including the owner.

## 5. Trust boundary (unchanged, stated precisely)

The database owner (`postgres`) and any superuser can replace these functions, disable the row
triggers, forge the transaction-local markers, or write the evidence tables with triggers disabled.
H-b does not and cannot stop that: it is the infrastructure boundary of M1/M2. What it stops: the
shared `service_role` credential, every client role, and the owner using the normal function path.
Detecting an owner bypass is an infrastructure control (migration review, CODEOWNERS, who holds the
owner credential, database audit logging), not SQL.

## 6. Rollback

One transaction, after any H-c rollback and **before** the H-a rollback (the H-a rollback refuses
while `public.knowledge_emergency_actions` exists). It restores the exact M2 bodies of the two
operator functions and of `public.knowledge_review_snapshot` (a test compares them with M2) and
drops the evidence tables, so it refuses without
`set local knowledge.hb_rollback_evidence_exported = 'yes'`. Registry rows are permanent: if any
`archivist` role row exists the widened role CHECK is kept (no function reads it after the
rollback). After the rollback `service_role` can quarantine and archive through the operator path
again, as before H-b.

Rollback order: H-c, H-b, H-a, M4.1, M4, M3, M2, M1.

## 7. Tests

`backend/tests/test_rag_knowledge_hb_operator.py` (DB, 35): every reason code; invalid code, detail
and reference; atomic failure; the operator path refused for service role and owner on both
entities, stale still reported first; grants; source quarantine; evidence immutable for the owner
and unreadable by clients; archive from quarantined and approved; service role, owner and a service
session with a person's claims refused; aal1 refused; missing, out-of-scope and suspended archivist
roles refused; stale and malformed hash, unknown reason, short rationale refused; uploader refused
from both statuses; approver refused directly and allowed through quarantine; a second account of
the uploader refused; archivist snapshot read; source archive; supersession unchanged; no
break-glass; rollback refusal, restore and verbatim bodies.

`backend/tests/knowledge_status_paths.py`: fixture quarantines go through the emergency function
(synthetic operator reference `TEST-FIXTURE-INCIDENT-0000`), fixture archives through a synthetic
archivist distinct from uploader and approver; `m2_cleanup` removes the new evidence.

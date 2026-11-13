# RAG V1.5 M7 E7: independent, signed verification of integrity reports

> **E7.1 (`docs/rag/RAG_V15_M7_E7_1_PORTABLE_ATTESTATION.md`) supersedes parts of this document:** the migration is
> renamed `20261113235900`, pgsodium is optional, verifications are submitted only by the dedicated verifier role
> (the service-role RPC below is dropped), a chunk-hash mismatch fails the verdict and the gate, and the code digest
> is a manifest over files and runtime.

Status: **IMPLEMENTED, LOCAL/CI ONLY.** Migration `20261113235900_knowledge_integrity_independent_verification_m7_e7.sql`,
rollback in `supabase/rollbacks/`. Stacked on E2 (#72) and the M7 harness (#71). Not applied to hosted.
**dev3-01 stays OPEN.**

## 1. Root cause and attack

E2 checks a report's completeness only against the claims the operator STORED. Whoever holds the shared
`service_role` credential could store fewer claims (or run a weaker extractor) and record a report that is
complete relative to them. Reproduced in `test_e7_an_incomplete_claim_set_passes_e2_alone_and_is_refused_with_e7`:
the dev3-01 assertions are left out, the report has no finding, the reviewer acknowledges it and, with E2 alone
(E7 rolled back inside the test transaction), the poisoned version is **approved**; with E7 the independent
verifier re-reads the chunks, finds both assertions missing (`mismatch`), and the same review is **refused**.

## 2. Threat model

| # | Actor | E7 outcome |
|---|---|---|
| 1 | honest operator, correct extractor | verifier reproduces the claim set; normal review |
| 2 | honest operator, outdated code | extractor code digest or claim set differs: refused until re-run with the pinned code |
| 3 | operator with a modified / incomplete extractor | verifier's claim set differs (missing / extra / altered): `mismatch` recorded, gate refuses |
| 4 | compromised shared service credential | can submit statements but cannot sign them; cannot register or revoke keys, pin digests, or write the tables |
| 5 | malicious reviewer (false-positive dispositions) | not stopped by E7 (it is an expert judgement, E2 records and attributes it); E7 still requires the independent verification (test) |
| 6 | database owner / superuser | NOT stopped: can replace functions, disable triggers, register a key. Infrastructure boundary, unchanged |

## 3. Trust separation (what holds which credential)

- **Report producer** (`service_role`): stores claims and the report (E2). Cannot certify them.
- **Independent verifier** (`backend/infrastructure/integrity_verifier.py`, run by a separate process / account):
  holds an **Ed25519 private key** the producer never has (`KNOWLEDGE_VERIFIER_KEY_FILE`, a PEM file of the
  verifier's own account; never the repository, a log, CI output or a shared secret). It reads the stored chunk
  text, re-runs the pinned extractor (`knowledge/integrity/verifier.py`), compares with the stored claims, and
  signs a canonical statement. Submitting it needs no special right; only the key holder can make one that
  verifies.
- **Database**: `private.knowledge_record_integrity_verification` verifies the signature with
  `pgsodium.crypto_sign_verify_detached` (libsodium Ed25519) against an **owner-registered public key**, checks
  the statement is about this report and its current snapshots, the pinned extractor version, **extractor code
  digest** and registry digest, and for a `reproduced` verdict **recomputes the canonical digest of the stored
  claims itself** (`private.knowledge_claim_set_digest`) and the chunk count. A `mismatch` statement is stored as
  evidence and blocks the report.
- **Owner**: pins the extractor code digest (`private.knowledge_set_integrity_code_digest`), registers and revokes
  verifier public keys (`private.knowledge_register_verifier_key`, `..._revoke_verifier_key`). Revocation is
  terminal and immediate: a verification signed by a revoked key stops authorizing (the gate share-locks the key,
  so a revocation and an approval serialize; committed race test).

## 4. Canonical form (Python = SQL)

One line per claim, sorted by `claim_id` (C collation), `|`-joined: claim id, chunk id, chunk content sha256,
span start, span end, kind, status, parameter, value min, value max, unit, dimension, date (`YYYY-MM-DD`), stage,
scope tags (sorted, `,`-joined); numbers without trailing zeros (`trim_scale` / `Decimal.normalize`), null = empty;
lines joined by `\n`; sha256 of UTF-8. The statement is JSON with sorted keys and no whitespace. Nothing depends
on filesystem order, locale, DateStyle, timezone or JSON key order.

**Pinned code.** The extractor code digest covers `knowledge/integrity/claims.py`, `knowledge/ids.py` (claim-id
derivation) and `knowledge/integrity/verifier.py` (canonical form, comparison, verdict), LF-normalized; changing
any of them needs a re-pin, and a verifier running other code is refused.

**Coverage evidence (signed, stored, not a verdict input).** The statement also carries `coverage`: chunks read,
chunks with claims, `chunks_without_claims` (the pinned extractor found nothing there: no recognised claim, or a
claim outside its patterns; NOT evidence of clean content), `empty_chunks`, and `chunk_hash_mismatch` (stored text
that does not hash to its stored `content_sha256`). The verdict stays about the claim set only. The database does
**not** bind `knowledge_chunks.content_sha256` to `content` (no constraint; ingestion computes it, and the test
fixtures store prefixed text with the unprefixed hash). The verifier extracts from the actual stored text, so this
does not let an omitted claim through; it is a provenance gap (artifact to chunk), recorded for a later
ingestion-level constraint, not enforced here.

**What a match proves:** the operator did not omit, add or alter what the pinned extractor finds in the stored
text. **What it does not prove:** that the extractor finds every scientific claim, or that any claim is true.

## 5. Gate

E2's gate plus `private.knowledge_integrity_verification_problem`: the extractor code digest is pinned; no
`mismatch` verification exists for the report; a `reproduced` verification exists for the exact report hash and
snapshot, signed by an **active** key, for the pinned extractor version, code digest and registry digest, whose
claim-set digest still equals the stored claims. Re-pinning code or registry, a metadata change (stale report),
a revoked key or a new report all invalidate it (tests). Reject and return need nothing. M2 separation, M3
validity, H-c supersession, the atomic approval and status event are unchanged.

## 6. Infrastructure requirements (NOT done, needed before hosted)

1. **pgsodium on hosted.** The migration runs `create extension if not exists pgsodium`. Supabase has announced
   pgsodium is pending deprecation and not recommended for new use; whether the hosted project can enable it (and
   for how long) was **not checked** (no hosted access in this task). Without it the migration fails, and if the
   function were missing the gate would refuse every approval (fail closed). Alternatives needing an owner
   decision: an Ed25519 verify in a reviewed extension that hosted supports, or moving verification into a separate
   trusted service whose own database role writes the verification rows (a weaker, role-based boundary).
2. **Verifier key custody.** A separate runner or account (HSM / dedicated CI secret not readable by the report
   producer or the agents), key rotation (register new, revoke old), an incident drill for revocation.
3. **Independent execution path.** The verifier must run from its own checkout of the pinned code; in this
   repository's CI the verifier key is synthetic and generated in memory per test process, which demonstrates the
   mechanism but is NOT independence.

## 7. Tests

`backend/tests/test_rag_knowledge_m7_e7_independent_verification.py` (PostgreSQL, 13): attack before / after;
one omitted poisoned claim named exactly; zero-claim report of a text with claims; honest remediation needs a new
report and then shows the dev3-01 findings; forgery with the service credential (unregistered key, edited
statement, false "reproduced" claim, no registration / revocation / pin rights, no direct writes, no client read);
a statement about another version; stale after metadata, code-digest re-pin, registry re-pin and key revocation;
reviewer false positives do not replace the verification; a correctly verified synthetic document is approved;
committed key-revocation race; committed report race (a new, unverified report recorded while the approval
waits is refused by E7: the previous report's verification does not carry over). `test_knowledge_integrity_verifier.py` (offline): canonical numbers, order
independence, field sensitivity, diff, canonical statement, CRLF-independent code digest, coverage (unprocessed and hash-inconsistent chunks) recorded without changing the verdict. Every existing suite
runs through the fixture helper, which verifies each report with the in-memory synthetic key.

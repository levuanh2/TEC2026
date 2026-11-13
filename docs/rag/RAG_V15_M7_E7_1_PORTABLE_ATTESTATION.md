# RAG V1.5 M7 E7.1: portable attestation, chunk provenance, extractor manifest

Status: **IMPLEMENTED, LOCAL/CI ONLY.** Migration `20261114090000_knowledge_integrity_portable_attestation_m7_e7_1.sql`,
rollback in `supabase/rollbacks/`. Stacked on #75 → #74 (E7) → #72 (E2) → #71 (M7 harness). Not applied to hosted.
**dev3-01 stays OPEN.** Reproducing a claim set is evidence of reproducibility under a pinned extractor, never of
scientific correctness.

## 1. Integration order and migration graph

| PR | Migration | Rollback must run |
|---|---|---|
| #70 M6.1 | `20261113180000_knowledge_citation_events_m6_1` | after the E chain is unwound |
| #72 E2 | `20261113210000_knowledge_integrity_approval_gate_m7_e2` | after E7 |
| #74 E7 | `20261113235900_knowledge_integrity_independent_verification_m7_e7` (**renamed here from `…240000`**) | after E7.1 |
| E7.1 | `20261114090000_knowledge_integrity_portable_attestation_m7_e7_1` | first |

Facts (`scripts/ci/check_migrations.py`, `scripts/ci/migration_upgrade.sh`, `.github/workflows/ci.yml`):

1. **Out-of-order is refused.** With `--base-ref`, a new migration whose version is not newer than the newest one on
   the base fails CI (`version is not newer than …`). If #72/#74 merged first, #70 (`180000`) could never merge
   without a rename. **Merge #70 first:** #70 → #71 → #72 → #74 → #75 → E7.1 → E5. Every version then increases.
2. **Overlaps with #70.** `test_rag_knowledge_status_events.py` (rollback paths and the unwind chain),
   `test_rag_knowledge_storage.py` (function inventory, three hunks) and `migrations.sha256` conflict. The exact
   resolutions are committed in the E5 branch's merge of #70 (union of both sides; unwind order
   E7.1 → E7 → E2 → M6.1 → H-c, the reverse of the versions). Whoever merges second replays that resolution.
3. **Upgrade base.** For a PR, CI's upgrade test starts from a SEEDED database at the PR's base
   (`origin/integrate/rag-v15`) and applies every migration the branch adds, in version order. A stacked PR is
   therefore tested as "integrate + the whole stack", not from the intermediate state after the PRs below it
   merge; after each merge the next PR's CI re-runs against the new base. The E5 branch (which contains #70) is
   the only one tested with M6.1 and the E chain together.
4. **Rollback graph.** E7.1 → E7 → E2 → (M6.1, independent) → H-c → H-b → H-a → M4.1 → M4 → M3 → M2 → M1. E7.1's
   rollback refuses while any verification was accepted without an in-database signature check.
5. **`240000` (hour 24).** Accepted by the repository check (`^\d{14}_`) and the Supabase CLI (a digit string), but
   not a valid time: any validator that parses the version as a timestamp rejects it. The file was never applied
   outside throwaway local/CI databases and is on no base branch, so it is renamed to `20261113235900` (same
   position in the order) together with its rollback; this PR also had to edit it (section 2). Editing it after
   a merge would be refused (`MANIFEST_REWRITTEN`), so #74 and E7.1 should merge together.

## 2. pgsodium: decision

Supabase lists pgsodium as **pending deprecation** and does not recommend new usage; Vault stays but is an
encrypted secret store, not an Ed25519 verifier. E7 needed `pgsodium.crypto_sign_verify_detached` and ran
`create extension pgsodium` unconditionally, so the migration would fail on a platform without it.

| Option | On Supabase | Verification | Producer can forge? | Notes |
|---|---|---|---|---|
| pgsodium (E7 baseline) | available, pending deprecation | in PostgreSQL (libsodium) | no (no key) | best property, deprecated dependency |
| pgcrypto | supported | none: pgcrypto does **not** support signing (PostgreSQL docs, PGP limitations) | n/a | rejected |
| plv8 + JS Ed25519 | dropped from the Postgres 17 bundle | in PostgreSQL | no | rejected |
| pgjwt | deprecated on Postgres 17; HMAC only | shared secret | yes (shared secret) | rejected |
| Ed25519 written in PL/pgSQL / pg_tle | possible | in PostgreSQL | no | rejected: an unreviewed home-made crypto primitive |
| Separate trusted service verifies, then writes | yes | outside PostgreSQL | not with the producer's credential, IF the service has its own DB login | needs a runner |
| **Dedicated verifier DB role + stored signature (chosen)** | custom LOGIN roles work directly and through Supavisor (`role.project_ref`) | in PostgreSQL when pgsodium is installed; otherwise offline audit | no: no usage on `knowledge_verifier`, refused even with a genuine signature | owner chooses the mode explicitly |

Chosen design (E7.1):

- `knowledge_integrity_verifier` is a NOLOGIN group; the owner grants it to the verifier's own login role. Only
  that role can call `knowledge_verifier.verification_input` and `knowledge_verifier.record_verification`. The
  service-role RPC of E7 is dropped. The database refuses the producer and client roles, the DB owner's own
  identity, and a misconfiguration in which service_role / authenticator / authenticated / anon is a member.
- `private.knowledge_set_attestation_mode` (owner): `in_database_signature` (requires pgsodium) or
  `offline_signature_audit`. Null (the default after the migration) = every verification refused.
- The signature is checked in the database **whenever pgsodium is installed**, in either mode. Without pgsodium,
  `in_database_signature` refuses everything; `offline_signature_audit` accepts on the verifier role's identity,
  stores the signature with `signature_checked_in_db = false`, and `python -m infrastructure.integrity_verifier
  --audit` re-verifies every stored signature. Switching back to `in_database_signature` makes those rows stop
  authorizing. **Never a silent downgrade:** the weaker mode exists only by an explicit owner decision.
- Rotation: register a new key, revoke the old one; revocation is immediate (E7). Replay: a statement is bound to
  one report id, report hash and snapshots. Verifier unavailable: no approval; reject and return still work.
- `create extension pgsodium` is now conditional, so E7/E7.1 install on a platform without pgsodium. A database
  without pgsodium was **simulated** (the extension dropped inside a rolled-back transaction); a real cluster
  without it was not available.

## 3. Chunk provenance

Contract (`knowledge/chunking.py`): `content_sha256 = sha256(content as UTF-8)`, exact bytes, no Unicode
normalization. The database never enforced it, and the test fixture `tx.chunk` stored `"TEST FIXTURE: " + text`
with the hash of `text` (also `test_rag_knowledge_postgrest.py`, `test_rag_retrieval_db.py` and two committed race
tests with constant hashes). The fixtures are **fixed** to hash the stored text; no assertion depended on the old
value.

E7.1 enforces it where it matters, without rewriting rows:

- the verifier's statement is `mismatch` when any chunk's text does not hash to its stored value
  (`coverage.chunk_hash_mismatch`; a lone surrogate or non-text value counts as a mismatch, not a crash);
- `record_verification` refuses a "reproduced" statement for such a version, even from the key holder;
- the gate re-checks every chunk of the version at approval (`private.knowledge_chunk_hash_problem`), so text
  changed after verification behind the immutability trigger (an owner action) is refused.

Chunks are immutable for the producer (trigger); empty chunks are impossible (`btrim(content) <> ''`); PostgreSQL
text is valid UTF-8, so invalid Unicode cannot be stored. **Legacy rows:** nothing is rewritten. A version with a
mismatching chunk can still be rejected or returned; the remediation is to re-ingest it as a new version. A
read-only owner inventory is in `docs/rag/sql/e7_1_chunk_hash_inventory.sql` (**not run on hosted**).

## 4. Extractor pin (manifest)

The pinned "code digest" is now a manifest digest: canonical JSON of the extractor version, the sha256 of every
pinned file (LF-normalized) and the runtime (`python_implementation`, Python major.minor, `unicodedata.unidata_version`).

- Files: `knowledge/__init__.py`, `ids.py`, `integrity/__init__.py`, `integrity/claims.py`, `integrity/verifier.py`.
  A test computes the project-import closure of `claims.py` and `verifier.py` with the AST and requires it to equal
  this list, and requires every outside import to be in a small stdlib allow-list. A new import fails the test.
- Runtime: the Unicode database and the `re` engine change with the Python version; a verifier on another Python
  has a different digest and is refused until the owner re-pins.
- The verifier refuses to sign when its own digest is not the pin (`PinMismatch`); the database refuses a
  statement for another digest; a re-pin invalidates earlier verifications (E7 test).
- Not covered: a behaviour change inside the same Python minor version and Unicode database (e.g. a CPython patch
  release). Pin the runner image, not only the digest.

## 5. Independent execution

- Local/CI: `test_a_separate_verifier_process_with_its_own_login_and_key_verifies_a_report` runs the verifier as a
  **separate process** with its own database login (member of the group), its own key file and no producer
  credential in its environment; the producer's session cannot submit the same signed statement, and the verifier
  login reads no table. Same machine and same OS user: a demonstration, **not production independence.**
- The single-process fixtures impersonate the role (`SET ROLE`, after granting the test connection SET on the
  group inside the transaction). By default the owner has ADMIN but no SET on the group (Postgres 16+).

## 6. Infrastructure requirements (NOT done, owner)

1. **The report producer must not be the database owner.** The production backend and the knowledge scripts
   connect with `SUPABASE_DB_URL` as `postgres` (session pooler). The owner can register keys, grant itself the
   verifier role or replace functions (threat 6), so E7/E7.1 only bind a producer that uses a dedicated
   non-owner login (e.g. a member of service_role only). Create that login and move the operator path to it.
2. **A verifier runner** with its own OS account / host or CI environment, its own DB login (`role.project_ref` via
   Supavisor), and its key in a secret store the producer and the agents cannot read.
3. **Attestation mode on hosted:** whether hosted can install pgsodium was not checked (no hosted access). With it,
   choose `in_database_signature`; without it, `offline_signature_audit` plus a scheduled `--audit`.

## 7. Tests

`test_rag_knowledge_m7_e7_1_portable_attestation.py` (PostgreSQL, 11): only the verifier role submits or reads;
misconfigured group refused; input limited to the version under review; no mode = refused; without pgsodium only
the explicit offline mode accepts, the audit finds a forged signature, re-requiring the in-database check
invalidates those rows and the rollback refuses; legacy prefixed chunk; NFD vs NFC; text altered behind the
trigger; verifier on another pin refuses to sign; unavailable verifier blocks approval, not rejection; the separate
verifier process. Offline (`test_knowledge_integrity_verifier.py`): hash mismatch fails the verdict, exact-byte
Unicode, lone surrogate, chunk order, import closure, manifest sensitivity.

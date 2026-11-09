# RAG V1.5: offline source-integrity review aid (2026-11-09)

Status: **IMPLEMENTED AS AN OFFLINE REVIEW AID ONLY.** No migration, no hosted change, no
provider call, no change to retrieval or the answer path. **dev3-01 stays OPEN**: an approved
chunk with false content is still retrievable and citable. This adds reusable building blocks
for milestones M4 (claims and contradictions) and M5 (reference registry) of
`RAG_V15_SOURCE_CONTENT_INTEGRITY.md` (Draft PR #49, not yet in this branch). The
database-governed parts of M4/M5 and all of M1–M3 and M6–M7 are not started.

## What it is

`backend/knowledge/integrity/` is pure, deterministic, stdlib only, and has the same import
contract as the rest of `backend/knowledge/` (test_knowledge_architecture.py). Nothing in the app
imports it.

| Module | Input | Output |
|---|---|---|
| `provenance.py` | artifact bytes, claimed publisher/URL/hash/version/license, evidence items, a caller-supplied publisher allowlist | one outcome per check (`verified` / `missing` / `mismatch` / `unverified_assertion`), an overall status, and `content_correctness = "not_assessed"` (always) |
| `claims.py` | `(document_ref, chunk_id, content)` | typed claims with exact spans: quantities (canonical units), dates (effective from/to), crop stages, two fixed absolute assertions; `ambiguous` / `unsupported` stay explicit |
| `references.py` | parsed registry JSON | validated `ReferenceRegistry` with a sha256 digest; fails closed |
| `review.py` | claim sources, registry, `as_of`, optional document periods/supersession | findings for a human expert; `decision = "none"` (always) |
| `reference_registry.json` | | production registry, 2 qualitative entries, neither independently verified |

## Trust rules
- Evidence counts as independent only if it attests the exact SHA-256 of the bytes in hand, is
  marked independent, has a stored evidence file (sha256), and comes from an allowlisted signer or
  official host other than the artifact's own download URL. An operator assertion never verifies.
- `verified` provenance means "these bytes came from that publisher". It never means "the content
  is true".
- Registry verification status is declared, never inferred. `independently_verified` needs the
  artifact sha256, an evidence sha256 and a named verifier. `synthetic_test_fixture` entries are
  refused by the production loader. A registry unit of another dimension than its parameter is
  refused, so incompatible units can never be compared.
- The production registry holds no numeric value. Its two entries are an
  `engine_config_pointer` (the Carbon Engine's SFw for multiple drainage incl. AWD is > 0, so the
  method models AWD as a reduction, not the end, of CH4; the YAML's VERIFIED is the project's own
  citation check and `domain_expert_review` is PENDING) and a `project_policy` (rule
  `data.completeness.water`). Tests re-check both pointers against the code and config, so an
  edit there forces a re-review here.

## What the review flags (needs_expert_review)
`reference_conflict`, `claim_conflict` (same parameter, compatible stage, overlapping or unknown
periods, non-overlapping ranges), `unsupported_assertion` (an absolute statement with no registry
entry), `expired_guidance`, `not_yet_effective`, `superseded_guidance`. Informational only:
`unresolved_claim` (ambiguous/unsupported extraction) and `unreferenced_claim`.

dev3-01 fixture (`poisoned_claim`): both statements ("AWD for one season ends methane emission",
"no need to record water levels") yield a `reference_conflict` against the production registry.
The clean AWD fixture chunks and a realistic legitimate guidance paragraph yield nothing that
needs review.

## Operator use: `ingest_knowledge.py --dry-run --integrity-review --as-of YYYY-MM-DD`
The review aid is printed after the normal dry-run summary (which is unchanged, byte for byte,
without the flag). It is still a dry run: no database, Storage, network, provider call or status
write, and findings never change the exit code (0).

```
python backend/scripts/ingest_knowledge.py --file guide.md --source-id ... --document-id ... \
    --document-version ... --title ... --language vi --dry-run --integrity-review --as-of 2026-11-09
```

- `--as-of` is required and strictly `YYYY-MM-DD`; it is never defaulted to today, because the
  report must name its evaluation date. `--integrity-review` with `--target` (write mode), or
  `--as-of` without the review, is a usage error (exit 2).
- The registry is `backend/knowledge/integrity/reference_registry.json`, loaded with the
  production loader. A missing, unreadable or invalid registry (including synthetic or
  over-trusted entries) is `refused [registry_invalid]`, exit 1, nothing on stdout: the review is
  never silently skipped.
- The report lists review/extractor/registry versions, the registry digest, `as_of`, claim and
  finding counts, every registry entry with its verification status, and per finding the chunk
  ids, claim ids with spans, reference ids, detail and the evidence an expert needs. It ends with
  `provenance = not_evaluated`, `content_correctness = not_assessed`, `decision = none`.
- **Provenance is `not_evaluated`.** The CLI has no publisher allowlist, independent evidence or
  evidence files, and `--source-owner` / `--official-url` are operator assertions.
  `evaluate_provenance()` is not called. Supplying a separate evidence bundle is a follow-up and
  is not part of this change.
- Validity periods are `not_evaluated` too (no effective-period context is supplied).
- A clean run prints `no detected conflicts`, never safe, verified or approved.
- Output hygiene: claim excerpts are at most 80 characters, never a whole chunk. A `tenant`
  document prints no excerpt at all, and `unresolved_claim` details do not quote the span.
- One document version per run: **contradictions with other documents are not checked**, only
  chunks of this version with each other and with the registry. Because the production registry
  has no numeric entry, a wrong number (e.g. 1,5 cm instead of 15 cm) is at most an informational
  `unreferenced_claim`. "No detected conflicts" says nothing about the numbers being correct.

## Known limits (do not over-read a clean report)
An independent read-only adversarial review (agy, 2026-11-09, 48 findings) was run against the
first version. The fixes, each pinned by a regression test in `test_knowledge_integrity.py`:
diacritic-free text is matched (via a span-preserving fold); temporal "hết vụ", negated "không
bao giờ bằng 0" and "không phải chỉ ghi" are no longer flagged; more synonyms and inverted
phrasings are caught ("về 0", "chấm dứt" after the noun, "xóa bỏ hoàn toàn", "bỏ qua việc theo
dõi", "không bắt buộc", English "stops / reduced to zero"); a ≥ 100 % CH4 reduction counts as
elimination; cues prefer the number's own clause; bund/pipe lengths are not water depths; values
in one chunk are not compared with each other; "0.125" and "1,500" are handled; signed depths are
ambiguous; `/vụ`, `tạ/ha`, `m` and ISO dates are supported; a re-spelled download URL is the same
channel; evidence needs its stored file and cannot be the artifact itself; independently verified
registry entries need a URL; the tolerance is bounded.

Still open (by design or deferred):
- **False negatives**: the assertion patterns remain a short fixed list for two statements. Any
  other false statement, and paraphrases outside the list, produce no claim. Numeric checks need a
  registry entry, and the production registry has no numeric entries yet. A wrong number with no
  second source passes as `unreferenced_claim` (info).
- **False positives**: conditional or exception statements ("khi trời mưa to … không cần đo mực
  nước", "lắp cảm biến thì khỏi cần đo thủ công") and quotations of a false claim made in order to
  refute it are still flagged. A person reads every flag, so this is acceptable for a review aid.
- Entries of every verification status (including `project_policy`, `unverified`) raise conflicts.
  The finding names the status and the expert weighs it.
- Dates: US `mm/dd/yyyy` is read as `dd/mm/yyyy`. Negative ranges are not parsed.
- Provenance does not fetch anything or verify signatures itself. It checks that the evidence
  recorded by another tool or person (for example the VN Government PKI / pyHanko recipe) is
  complete, bound to these bytes and to its stored file. A dishonest evidence file is out of its
  scope; the two-person approval (M2) is the control for that.

## Next steps (each needs owner approval)
1. Done as a printed dry-run review aid (`--integrity-review`, above). Follow-ups, each separate:
   a provenance evidence bundle for `evaluate_provenance()`; a multi-document review run.
2. M1 (local migration only): `expert_review` / `quarantined` statuses and append-only status
   events, so that a flag can actually stop retrieval.
3. Numeric registry entries only from independently verified primary artifacts.

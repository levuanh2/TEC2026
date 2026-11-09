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

## Known limits (do not over-read a clean report)
- **False negatives**: the assertion patterns are a short fixed list. A false statement phrased
  differently, written without diacritics, or about another subject produces no claim. Numeric
  checks only cover the parameters in `claims.PARAMETERS`, and only when a registry entry exists,
  and the production registry has no numeric entries yet. A wrong number with no second source and
  no reference passes as `unreferenced_claim` (info).
- **False positives**: cue words are matched per sentence, so a sentence mixing two subjects can
  attach the wrong parameter. A legitimate document that quotes a false claim in order to refute
  it ("không đúng rằng AWD hết phát thải") can be flagged. That is acceptable for a review aid,
  because a person reads every flag.
- Dates: only `dd/mm/yyyy` and "ngày d tháng m năm yyyy". Numbers: "1.000" is ambiguous on purpose.
- Provenance does not fetch anything or verify signatures itself. It evaluates evidence that
  another tool or person recorded (for example the VN Government PKI / pyHanko recipe).

## Next steps (each needs owner approval)
1. Wire `review()` into the ingestion dry-run report as a printed review aid (it writes no status).
2. M1 (local migration only): `expert_review` / `quarantined` statuses and append-only status
   events, so that a flag can actually stop retrieval.
3. Numeric registry entries only from independently verified primary artifacts.

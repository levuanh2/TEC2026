# RAG V1.5 M5 foundation: numeric reference entries, units and conversions

Status: **foundation only (2026-11-12).** Schema, validators, synthetic fixtures and tests.
**No canonical numeric entry is added.** `reference_registry_numeric.json` is committed with an empty
`entries` list, and `reference_registry.json` (schema 1) is unchanged. No database change, no
migration, nothing wired into ingestion, retrieval or the answer path. dev3-01 stays OPEN.

The evidence matrix and the design this implements are in
`RAG_V15_M5_REFERENCE_REGISTRY_DESIGN.md` (PR #59). Code:
`backend/knowledge/integrity/reference_numeric.py`. Tests:
`backend/tests/test_knowledge_reference_numeric.py`.

## 1. What an entry must record

The loader (`load_numeric_registry`) refuses an entry that lacks any of these.

| Requirement | Field | Rule |
|---|---|---|
| Official primary-source URL | `source.url` | `https://` only |
| Publisher | `source.publisher` | non-empty |
| Artifact SHA-256 | `source.artifact_sha256`, `source.artifact_bytes` | 64 lowercase hex; positive size |
| Edition and effective date | `source.edition`, `source.effective_date` | ISO date, or null with `effective_date_note` saying why |
| Exact page, equation or table | `source.locator` | `pdf_page` (positive integer) and `table` or `equation`; optional `printed_page`, `section`, `row` |
| Original value | `value.point`, `value.min`, `value.max`, `value.range_basis` | decimal **strings** as printed (a JSON number is refused); `min <= point <= max`; a range needs its basis |
| Original unit | `unit_as_printed` | non-empty, kept next to the canonical unit |
| Applicability conditions | `conditions`, `scope.region`, `scope.tier` | at least one condition, in the source's words |
| Dimension | `unit`, `quantity_semantics` | see section 2 |
| Normalized comparison method | `comparison` | a named rule or `none`; see section 3 |
| Verification state | `verification.human.status` | `pending` or `verified` |
| Human verification evidence | `verified_by`, `verified_at`, `evidence_ref`, `evidence_sha256` | all four for `verified`; none for `pending`. `evidence_ref` is a `.md` file under `docs/rag/reference-evidence/` |
| Rights and restrictions | `rights.status`, `basis`, `reference`, `restrictions` | `not_cleared` is refused: the value cannot be stored |

An entry marked `synthetic: true` is refused unless the caller passes `allow_synthetic=True`. Only
tests do.

## 2. Units and dimensions (closed)

`REFERENCE_UNITS` is the M4 unit table plus one reference-only unit:

| Unit | Dimension |
|---|---|
| the M4 units (`cm`, `day`, `kg/ha`, `m3/ha`, `percent`, `kgCH4/ha/day`, `kgCH4/ha`, `kgCO2e/ha`) | unchanged |
| `kgN2O-N/kgN` | `n2o_n_per_applied_n` |

A unit names what is measured. `percent` and `kgN2O-N/kgN` are both ratios in arithmetic; they are
different dimensions here, and only a named rule connects them.

**Dimensionless factors are not forced into a unit.** An entry whose `quantity_semantics.kind` is
`scaling_factor` or `conversion_factor` must have `unit: null`, must say what it is `relative_to`,
and can only use the conversion `none`. It is stored for reference and never compared. Giving it
`percent` or any other unit is refused.

## 3. Conversion rules (closed)

A claim is compared with an entry only through a rule of `CONVERSION_RULES`.

| Rule | Claim unit | Reference unit | Factor | The claim must state |
|---|---|---|---|---|
| `identity` | the reference unit | same | 1 | the entry's `required_claim_conditions` |
| `percent_of_applied_n_to_fraction` | `percent` | `kgN2O-N/kgN` | 0.01 | `base:applied_n` and `quantity:n2o_n` |
| `none` | – | – | – | never compared |

The loader checks that an entry's units fit its rule and that its `required_claim_conditions`
include the rule's preconditions and are not empty: a comparable entry turns at least one of its
`conditions` into a tag the claim has to state (an entry whose applicability cannot be checked
uses `none`). Arithmetic is exact (`Decimal`). There is no generic ratio rule,
no N2O to N2O-N rule and no rule for SFw, SFp or CFOA. Adding a rule is a code change with its own
review and test.

The current M4 extractor emits no `base:` or `quantity:` condition tags, so
`percent_of_applied_n_to_fraction` cannot fire on any stored claim today. It defines the contract
an extractor change would have to meet.

**Tolerance.** `printed_range` (the range the source prints) or `exact`. The tolerance object takes
no number: a tolerance the source does not print cannot be entered.

## 4. Findings

`compare(claim, entry)` returns one `ReferenceFinding`:

| Outcome | Meaning | Mismatch |
|---|---|---|
| `reference_unverified` | no human has verified the entry; checked first, so such an entry never judges a claim | no |
| `not_comparable` | no rule, or a different parameter or unit | no |
| `out_of_scope` | the claim does not state the required conditions, states a condition the entry does not cover, or the region differs or is unknown | no |
| `within_printed_range` / `equal_to_printed_value` | agrees | no |
| `outside_printed_range` / `differs_from_printed_value` | disagrees | **yes** |

Every finding, and so every mismatch, carries the source URL, the artifact SHA-256, the locator,
the printed value, range and unit, the rule used and a rationale in words.

A finding is a review aid. It changes no status, blocks no approval and quarantines nothing.

## 5. What the loader cannot know

It cannot know that the named person did the check or that the evidence file says what the entry
says. Those are review responsibilities. When the first entry is proposed, the test
`test_the_committed_numeric_registry_holds_no_entry...` must be replaced by one that checks the
evidence file exists and matches `evidence_sha256`, and the registry file and
`docs/rag/reference-evidence/` should be CODEOWNERS-guarded.

## 6. Source status (unchanged by this PR)

| Source | State |
|---|---|
| IPCC 2019 Refinement Vol. 4 Ch. 5 and Ch. 11 | artifact hashes and table references are recorded in the design document. Values are machine-read, **not human-verified**. Rights **not cleared**. No value, table or PDF copy is stored. |
| QĐ 2626/QĐ-BTNMT | pending an authoritative first-party artifact |
| QĐ 4801/QĐ-BNNMT annex | blocked until an official annex is located and authenticated |
| QĐ 4043 | blocked: incomplete provenance and contradictory source text |

## 7. Next steps (not in this PR)

1. Owner decision on IPCC rights; a named human re-check per row; evidence file per entry.
2. Condition tags from the extractor (`baseline`, `base:`, `quantity:`), with their own tests.
3. Wiring `compare` into the offline review, then database storage of findings (append-only,
   service-written, read through the M4.1 reviewer interface).

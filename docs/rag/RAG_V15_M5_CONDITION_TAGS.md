# RAG V1.5 M5 follow-up: condition tags and the numeric comparison in the offline review

Status: **IMPLEMENTED, OFFLINE ONLY.** Pure Python (`backend/knowledge/integrity/conditions.py`), no
database, no migration, no change to the production answer path. Based on the M5 foundation
(`RAG_V15_M5_REFERENCE_REGISTRY_FOUNDATION.md`, #61). dev3-01 stays OPEN.

## 1. Condition tags

`condition_tags(claim, chunk_content)` returns the conditions the claim's **own sentence** states, each
with the exact span of the words that state it (`content[start:end] == text`). Rules:

- exact cue match on the diacritic-folded sentence, whole words (the M4 extractor's matcher);
- a negated cue ("không phải đất phèn", "not", "except") gives no tag;
- nothing is inferred from the title, the source, the publisher, another sentence or a default;
- when two regions are named in one sentence, no region is stated for the claim.

| Axis | Tags | Example cue |
|---|---|---|
| baseline context | `baseline:continuous_flooding`, `baseline:conventional_practice`, `baseline:control` | "so với ngập liên tục", "compared with the control" |
| applicable quantity | `quantity:ch4`, `quantity:n2o`, `quantity:n2o_n` | "mê-tan", "CH4", "N2O-N" |
| applied nitrogen basis | `base:applied_n` | "lượng đạm bón", "of applied nitrogen" |
| crop growth stage | `stage:<M4 stage>` | the M4 extractor's stage, re-located in the same sentence |
| measurement period | `period:season`, `period:year`, `period:day`, `period:winter_spring`, `period:summer_autumn` | "/vụ", "mỗi năm", "vụ đông xuân" |
| region | `ClaimValue.region`: `mekong_delta`, `red_river_delta` | "Đồng bằng sông Cửu Long", "ĐBSCL" |
| soil | `soil:acid_sulfate`, `soil:alluvial`, `soil:saline` | "đất phèn" |
| variety | `variety:<code>` | an explicit code only: "giống OM5451" |

The tag vocabulary matches the M5 foundation's rules (`base:applied_n`, `quantity:n2o_n` are the
preconditions of `percent_of_applied_n_to_fraction`). Trade-off, as the foundation states: more tags
mean more `out_of_scope` results, never more mismatches.

## 2. Comparison

`compare_claims(claims, contents, numeric_registry)` turns every extracted quantity claim into an
`rn.ClaimValue` (values as exact `Decimal` from the extractor's rounded value) and compares it with every
entry of its parameter through `reference_numeric.compare`. Each `NumericComparison` stores the claim
text, claimed range and unit, the condition tags with their evidence spans, the region, the reference
id, the outcome, the rationale, the conversion rule, the normalized values, the reference unit, point
and range, the source URL and the locator.

- A mismatch (`outside_printed_range`, `differs_from_printed_value`) is possible **only** against an
  entry a human has verified; otherwise `reference_unverified`.
- Missing or extra conditions, a different region, a different quantity or unit: `out_of_scope` /
  `not_comparable`. No entry for the parameter: `no_reference`. None of these is a mismatch.

## 3. Offline review integration

`review(..., numeric_registry=...)` adds the comparisons to `IntegrityReview.numeric_comparisons` and
one finding per comparison:

- `numeric_reference_mismatch`: `needs_expert_review = True`, the detail lists the units, the
  conditions and the rationale;
- `numeric_unresolved`: information only.

`decision` stays `"none"`: no approval, no quarantine, no status change. Without `numeric_registry`
the review is unchanged. The review reads only the sources it is given, so it discloses nothing of
another tenant.

## 4. Source evidence (unchanged)

- The committed numeric registry stays **empty**; this PR adds no canonical entry. With it, every
  comparison is `no_reference` (test `test_the_committed_registry_produces_no_mismatch`).
- IPCC values: pending human verification and rights clearance.
- QĐ 2626, QĐ 4801, QĐ 4043: blocked until suitable official artifacts are available
  (`RAG_V15_M5_REFERENCE_REGISTRY_FOUNDATION.md`, evidence matrix of #59).

## 5. Tests

`backend/tests/test_knowledge_conditions.py` (25, offline, synthetic texts and synthetic registry
entries loaded with `allow_synthetic=True`): each axis, negation, no inference, sentence boundary,
evidence spans, a claim that does not match its content, verified mismatch and match with full
traceability, unverified entry, missing and extra conditions, no entry, exact decimals, review
integration, unchanged review without a registry, committed registry never mismatches.

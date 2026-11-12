# RAG V1.5 M5: reference registry — primary-source evidence matrix and design

Status: **EVIDENCE MATRIX AND DESIGN ONLY (2026-11-12).** No numeric reference value is added to
`backend/knowledge/integrity/reference_registry.json` by this document or its PR. No schema, loader
or database change yet. Depends on M4 (#58). dev3-01 stays OPEN. Nothing here is a scientific or
legal review, and no human has verified any value below.

A value is **not** approved because it equals `backend/config/emission_factors.yaml`. That file is
the project's own reading of the same tables; agreement shows consistency, not correctness.

## 1. How the evidence was collected

On 2026-11-12 one AI session downloaded each file from the publisher's own HTTPS URL, hashed the
bytes (SHA-256), and read the named pages with pypdf 6.21.4 text extraction. The hashes equal those
recorded on 2026-11-11, so the publisher's files did not change between the two days.

This is a **machine reading**. Text extraction flattens tables: a cell that spans several rows
(the "aggregated case" columns of Tables 5.12 and 5.13) cannot be assigned to its rows with
certainty from the text. Every row below therefore has `human verification: PENDING`, and the
spanning cells are marked.

## 2. Artifacts

| Id | Title | Publisher | URL | Bytes | SHA-256 | Pages |
|---|---|---|---|---|---|---|
| A1 | 2019 Refinement to the 2006 IPCC Guidelines for National Greenhouse Gas Inventories, Vol. 4, Ch. 5 Cropland | IPCC (Task Force on National Greenhouse Gas Inventories) | https://www.ipcc-nggip.iges.or.jp/public/2019rf/pdf/4_Volume4/19R_V4_Ch05_Cropland.pdf | 1,835,807 | `eecbf328eed9ef43cd3f091352fe9545e7c078288d89bf5d32adcae1f7805eda` | 102 |
| A2 | same, Vol. 4, Ch. 11 N2O Emissions from Managed Soils, and CO2 Emissions from Lime and Urea Application | IPCC (TFI) | https://www.ipcc-nggip.iges.or.jp/public/2019rf/pdf/4_Volume4/19R_V4_Ch11_Soils_N2O_CO2.pdf | 944,749 | `337f18ceb618a858526ec01b5abed289843e1e8a69c957f0f62d22fa2a5761b3` | 48 |

Edition: 2019. The printed page number is `chapter.page` (PDF page 53 of A1 prints "5.53").

**Rights (applies to every A1/A2 row): NOT CLEARED.** The download pages carry
"© Intergovernmental Panel on Climate Change (IPCC)" and link to `https://www.ipcc.ch/copyright/`.
That page refused automated access on 2026-11-12 (HTTP 403), so its terms were **not read** in this
session. A web search summary says limited excerpts may be reproduced for personal, non-commercial
use with acknowledgement and that other uses need permission from the IPCC Secretariat
(copyright@ipcc.ch); that summary is secondary and unverified. Whether quoting single default
values, with attribution, in an internal review aid is permitted is a legal reading the project has
not made. **Owner decision required before any A1/A2 value is stored.**

## 3. Evidence matrix: IPCC 2019 Refinement

Columns: value and range **as printed**; unit as printed; conditions as printed; the M4 claim type
it could be compared with; conversion; limits. `HV` = independent human verification.

### 3.1 A1, Table 5.11 (UPDATED), PDF p. 53 (printed 5.53), section 5.5.2 "Choice of emission and scaling factors"

Title as printed: "Default CH4 baseline emission factor assuming no flooding for less than 180 days
prior to rice cultivation, and continuously flooded during rice cultivation without organic
amendments". Note as printed: ranges are a 95% confidence interval; for Africa the global estimate
is used.

| Row | Value | Error range | Unit | Comparable claim | Conversion | HV |
|---|---|---|---|---|---|---|
| World | 1.19 | 0.80–1.76 | kg CH4 ha⁻¹ d⁻¹ | `ch4.emission_factor`, unit `kgCH4/ha/day` | none (same unit) | PENDING |
| Southeast Asia | 1.22 | 0.83–1.81 | kg CH4 ha⁻¹ d⁻¹ | same | none | PENDING |
| East Asia | 1.32 | 0.89–1.96 | same | same | none | PENDING |
| South Asia | 0.85 | 0.58–1.26 | same | same | none | PENDING |

Limits: a **baseline** factor for one stated condition. A document's daily emission figure for a
field under AWD, with straw, or with a flooded pre-season is not this quantity; it is
`EFc × SFw × SFp × SFo` (Equation 5.2). Comparing a field figure with the baseline directly would
raise false alarms. This is the only IPCC row that fits an existing M4 unit.

### 3.2 A1, Table 5.11A (NEW), PDF p. 53

"Default cultivation period of rice": World 113 (74–152) day; Southeast Asia 102 (78–150) day.
Range as printed: 2.5th to 97.5th percentile. Comparable in principle with a duration claim in
`day`, but M4 has no cultivation-period parameter. HV PENDING. Not proposed for a first registry.

### 3.3 A1, Table 5.12 (UPDATED), PDF p. 54 (printed 5.54)

"Default CH4 emission scaling factors for water regimes during the cultivation period relative to
continuously flooded fields". Ranges: 95% confidence interval.

| Water regime (disaggregated case) | SFw | Error range | HV |
|---|---|---|---|
| Upland | 0 | – | PENDING |
| Irrigated, continuously flooded | 1.00 | 0.73–1.27 | PENDING |
| Irrigated, single drainage period | 0.71 | 0.53–0.94 | PENDING |
| Irrigated, multiple drainage periods (footnote b: includes alternate wetting and drying) | 0.55 | 0.41–0.72 | PENDING |
| Rainfed and deep water, regular rainfed | 0.54 | 0.39–0.74 | PENDING |
| Rainfed and deep water, drought prone | 0.16 | 0.11–0.24 | PENDING |
| Rainfed and deep water, deep water | 0.06 | 0.03–0.12 | PENDING |

Aggregated case, **spanning cells, row assignment not certain from text**: irrigated 0.60
(0.44–0.78); rainfed and deep water 0.45 (0.32–0.62); deep water 0.06 (0.03–0.12).

### 3.4 A1, Table 5.13 (UPDATED), PDF p. 55 (printed 5.55)

"Default CH4 emission scaling factors for water regimes before the cultivation period".

| Water regime prior to cultivation (disaggregated case) | SFp | Error range | HV |
|---|---|---|---|
| Non flooded pre-season <180 d | 1.00 | 0.88–1.12 | PENDING |
| Non flooded pre-season >180 d | 0.89 | 0.80–0.99 | PENDING |
| Flooded pre-season (>30 d) | 2.41 | 2.13–2.73 | PENDING |
| Non-flooded pre-season >365 d | 0.59 | 0.41–0.84 | PENDING |

Aggregated case, **spanning cell**: 1.22 (1.08–1.37). The engine config already records that this
cell could not be assigned to its rows from the extracted text. Not proposed.

### 3.5 A1, Equation 5.3 and Table 5.14 (UPDATED), PDF p. 55–56

Equation 5.3: `SFo = (1 + Σ ROAi × CFOAi)^0.59`; printed uncertainty of the exponent 0.54–0.64;
ROA in tonne ha⁻¹, dry weight for straw and fresh weight for others.

| Organic amendment | CFOA | Error range | HV |
|---|---|---|---|
| Straw incorporated shortly (<30 days) before cultivation | 1.00 | 0.85–1.17 | PENDING |
| Straw incorporated long (>30 days) before cultivation | 0.19 | 0.11–0.28 | PENDING |
| Compost | 0.17 | 0.09–0.29 | PENDING |
| Farm yard manure | 0.21 | 0.15–0.28 | PENDING |
| Green manure | 0.45 | 0.36–0.57 | PENDING |

### 3.6 A2, Table 11.1 (UPDATED), PDF p. 13 (printed 11.13), section 11.2.1.2

"Default emission factors to estimate direct N2O emissions from managed soils".

| Row | Value | Uncertainty range | Unit as printed | HV |
|---|---|---|---|---|
| EF1FR for flooded rice fields, aggregated | 0.004 | 0.000–0.029 | kg N2O–N (kg N)⁻¹ | PENDING |
| EF1FR, continuous flooding | 0.003 | 0.000–0.010 | same | PENDING |
| EF1FR, single and multiple drainage (note 7: also includes alternate wetting and drying) | 0.005 | 0.000–0.016 | same | PENDING |

Range as printed: 2.5th to 97.5th percentile. Note 7 as printed: disaggregated EF1FR for rain-fed
and deep-water systems is not provided; EF1 should be used for upland rice.

### 3.7 Dimension and semantics of the unitless factors (SFw, SFp, CFOA, EF1FR)

These must **not** be stored as M4 quantities with a made-up unit.

- **SFw, SFp** are ratios of emission relative to a named reference condition. `0.55` means
  "0.55 times the continuously flooded emission", not "55 percent" of anything a document is
  likely to state. A document says "AWD reduces methane by 30–50%". That is `ch4.reduction` in
  `percent`, a **reduction** relative to a baseline the document may not name. `1 − SFw = 0.45` is
  an arithmetic identity only if the document's baseline is continuous flooding, the same
  pre-season regime and the same amendments. Treating the two as the same quantity would be an
  invented conversion.
- **CFOA** is a relative effect per tonne against "straw shortly before cultivation", used inside
  an exponent. It is not comparable with any claim M4 extracts.
- **EF1FR** has a real unit (kg N2O–N per kg N). It is a mass fraction of applied nitrogen. A
  document stating "N2O emission is 0.5% of applied N" is comparable only after two explicit
  steps: percent to fraction, and N2O to N2O–N (× 28/44) if the document speaks of N2O mass. M4's
  `percent` dimension `ratio` does not record what the ratio is of.

Design consequence (section 5): a registry entry gets its own `quantity_semantics` block
(`kind: scaling_factor | conversion_factor | emission_factor`, `relative_to`, `numerator`,
`denominator`), and a comparison is made only through a **named, reviewed conversion rule** whose
preconditions are all present in the claim. No rule, no comparison: the finding is `not_comparable`.

## 4. Evidence matrix: Vietnamese sources

| Source | Wanted for | Primary artifact | State on 2026-11-12 | Verdict |
|---|---|---|---|---|
| QĐ 2626/QĐ-BTNMT (10/10/2022), list of emission factors for the national inventory, Appendix III | country-specific rice factors | none obtained | Web search returned only private legal portals (thuvienphapluat.vn, luatvietnam.vn) and press. Government pages tried: `vanban.chinhphu.vn` (the document id tried was another document), `chinhphu.vn` search (not reachable by static fetch), `vbpl.vn` (JavaScript only, unreadable), `mae.gov.vn` (fetch error), `dcc.mae.gov.vn` home (no listing found), `monre.gov.vn` and `dcc.gov.vn` (TLS certificate errors), `congbao.chinhphu.vn` home (not listed). | **BLOCKED.** No first-party copy found. Not proof that none exists: three government search pages could not be read by an automated client. A person with a browser should search `vbpl.vn` and `vanban.chinhphu.vn`. |
| QĐ 4801/QĐ-BNNMT (14/11/2025), pilot MRV procedure for low-emission rice, annex | MRV measurement and record rules | decision page only (1 page), recorded 2026-10-07 | Web search found ministry news articles about the decision and no annex file. | **BLOCKED** (annex not published by an authoritative source). |
| QĐ 4043/QĐ-TTTV-TTBVTV (10/11/2025), rice procedure | agronomic parameters | Cà Mau provincial copy of the annex, SHA-256 `0aa5e2ee68cbf1d1448dc1a5a1f88173bafbf779457d8bfe80b10421fc64f1a2`, signature chain verified 2026-10-07 | Not re-downloaded today. The decision page itself is missing from that copy; the annex disagrees with itself on straw timing (3 weeks in a diagram, 2 weeks in the text). | **BLOCKED** until the complete original decision with its annex is verified. |

Private legal portals are pointers only. Nothing read from them is recorded as a value here.

## 5. Design (implementation-ready)

### 5.1 Registry schema `kn-reference-registry-2`

A numeric entry is refused by the loader unless every field below is present. Qualitative entries
keep the rules of schema 1.

```json
{
  "reference_id": "ref-...",
  "kind": "numeric",
  "parameter": "ch4.emission_factor",
  "value": {"point": "1.22", "min": "0.83", "max": "1.81", "range_basis": "95% confidence interval (as printed)"},
  "unit_as_printed": "kg CH4 ha-1 d-1",
  "unit": "kgCH4/ha/day",
  "quantity_semantics": {"kind": "emission_factor", "relative_to": null,
                         "numerator": "CH4 mass", "denominator": "area x time"},
  "conditions": ["no flooding <180 d before cultivation", "continuously flooded", "no organic amendment"],
  "scope": {"region": "Southeast Asia", "tier": "IPCC Tier 1 default", "country_specific": false},
  "source": {"title": "...", "publisher": "IPCC", "edition": "2019", "url": "https://...",
             "artifact_sha256": "<64 hex>", "artifact_bytes": 1835807,
             "locator": {"table": "Table 5.11 (UPDATED)", "pdf_page": 53, "printed_page": "5.53",
                         "section": "5.5.2", "row": "Southeast Asia"}},
  "rights": {"basis": "<owner-recorded decision or written permission>", "reference": "<where it is recorded>",
             "restrictions": "<as stated by the rights holder>"},
  "comparison": {"claim_parameter": "ch4.emission_factor", "claim_unit": "kgCH4/ha/day",
                 "conversion": "identity", "required_claim_conditions": ["baseline"],
                 "tolerance": {"mode": "printed_range"}},
  "verification": {"machine_read": {"tool": "pypdf 6.21.4", "date": "2026-11-12"},
                   "human": {"status": "pending", "verified_by": null, "verified_at": null, "evidence_ref": null}},
  "limitations": ["..."]
}
```

Loader rules:

- values are decimal strings, parsed with `Decimal`; `min <= point <= max`;
- `artifact_sha256` is 64 hex characters; `url` is HTTPS; `pdf_page` is a positive integer;
- `unit` is one of `claims.UNITS`, **or** `unit` is null and `quantity_semantics.kind` is
  `scaling_factor` or `conversion_factor` (then `comparison.conversion` must name a registered rule
  or be `none`);
- `tolerance.mode` is `printed_range` or `exact`. No free number: a tolerance the source does not
  print cannot be entered;
- `rights.basis` is non-empty. An entry whose rights are not cleared cannot be loaded;
- **an entry with `verification.human.status != "verified"` loads as `unverified` and is never used
  for a comparison.** It exists only so a human can find what to check. `verified` requires
  `verified_by`, `verified_at` and an `evidence_ref` to a file under
  `docs/rag/reference-evidence/`. The loader cannot know that a named human really did the check;
  that is a review responsibility (CODEOWNERS on the registry file).

### 5.2 Conversion rules

A small, closed table in code, each rule with its preconditions and a test:

| Rule | From claim | To reference | Preconditions on the claim |
|---|---|---|---|
| `identity` | same parameter, same unit | same | conditions of the entry present in the claim's scope tags |
| `percent_of_applied_n_to_fraction` | percent of applied N as N2O–N | EF1FR | claim names applied N as the base and N2O–N as the quantity |
| none for SFw, SFp, CFOA | – | – | not comparable with any current M4 claim; stored for reference only |

Adding a rule is a code change with its own review. There is no generic "ratio" conversion.

### 5.3 Findings

A comparison yields one of: `within_printed_range`, `outside_printed_range`, `out_of_scope`
(conditions or region differ), `not_comparable` (no rule), `reference_unverified` (never reported
as a mismatch). All are review aids. None changes a status, blocks an approval or quarantines.

### 5.4 Steps

1. Schema 2 and the loader rules above, with **synthetic fixtures only** in tests. The committed
   registry keeps its two qualitative entries.
2. Offline comparison in `knowledge/integrity/review.py` using the closed conversion table.
3. Evidence files `docs/rag/reference-evidence/<reference_id>.md` (URL, date, bytes, hash, page,
   the printed row, who re-checked). No copy of the source PDF in the repository.
4. Database storage of findings next to the M4 candidates: a separate PR, append-only, same
   privileges as M4, read through the reviewer interface
   (`docs/rag/RAG_V15_M4_REVIEWER_READ_DESIGN.md`).
5. First numeric entry only after: rights decision recorded, a named human re-check of that row
   against the hashed file, and its evidence file in the same PR.

## 6. What is blocked, and on whom

| Item | Blocked on |
|---|---|
| Any IPCC value in the registry | owner decision on rights (read `ipcc.ch/copyright` in a browser, or ask copyright@ipcc.ch); a named human re-check per row |
| SFw / SFp / CFOA comparisons | no sound conversion from current M4 claims; needs an extractor design, not a registry entry |
| QĐ 2626 Appendix III | a first-party copy (browser search of `vbpl.vn`, `vanban.chinhphu.vn`, or a request to the ministry) |
| QĐ 4801 annex | publication by the ministry, or a copy obtained from it directly |
| QĐ 4043 | the complete original decision; an expert reading of the straw-timing inconsistency |

## 7. Implementation status (2026-11-12)

Step 1 of section 5.4 (schema 2, loader rules, closed conversion table, `compare`, synthetic
fixtures) is Draft PR #61, `backend/knowledge/integrity/reference_numeric.py`. It stores **no**
numeric entry: `reference_registry_numeric.json` is committed empty.

Refinements made there, which this design now follows:

- `source.publisher`, `source.effective_date` (or a stated reason for null) and
  `source.artifact_bytes` are required, as are `rights.status` (`not_cleared` is refused) and
  `verification.human.evidence_sha256` for a verified entry.
- `kgN2O-N/kgN` is a reference-only unit with its own dimension. It is not `percent` and not an M4
  claim unit; only the rule `percent_of_applied_n_to_fraction` connects them, and only for a claim
  that states `base:applied_n` and `quantity:n2o_n`. The N2O to N2O-N step (x 28/44) has **no**
  rule: a claim about N2O mass is out of scope.
- A `scaling_factor` or `conversion_factor` entry has `unit: null` and the conversion `none`.
- Findings for the exact mode are `equal_to_printed_value` and `differs_from_printed_value`.
- A claim that does not state its region is `out_of_scope` for a regional entry.

Steps 2 to 5 are not started. No row of section 3 has been re-checked by a human, and the rights
question of section 2 is open, so no IPCC value may be entered.

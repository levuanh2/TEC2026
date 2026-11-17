# RAG V1.5 E1: claim-to-source traceability matrix and reviewer packets

Status: **PREPARATION FOR HUMAN VERIFICATION, 2026-11-17. Nothing here is verified. E1 OPEN, E4 OPEN, dev3-01 OPEN.**

Artifact IDs (A-xx), locators and tool checks: `RAG_V15_E1_EVIDENCE_ACQUISITION_2026_11_17.md`.

Record design and the tool-check vs human-verification split: #82 `RAG_V15_E1_SOURCE_REGISTRY_AUDIT.md` §1, §3.
Reviewer qualification and separation of duties: #82 `RAG_V15_E4_EXPERT_GOVERNANCE.md`.

Values are referenced by their config key (`backend/config/emission_factors.yaml`, `0.3.0-ipcc2019-tier1-ar5`). They are
not copied, so this file adds no reproduction of source tables.

## 1. Matrix

Lineage, kept apart as #82 §5 requires:
- **RULE**: an internal M05 rule exists;
- **CFG**: internal emission-factor configuration;
- **SCI**: scientific evidence supporting it;
- **LEGAL**: legal permission to reproduce source material.

A row of one lineage never satisfies another.

Verification status values:
- `none`: nothing checked;
- `tool_checked`: artifact hash and locator found, and the value string appears on the page;
- `human_verified`: **no row has this**.

| ID | Internal claim / rule | Lineage | Intended primary source | Exact locator | Evidence available now | Verification | Rights | Unresolved issue |
|---|---|---|---|---|---|---|---|---|
| T-01 | `gwp.framework` = AR5 GWP-100 | CFG | UNFCCC 18/CMA.1 annex §37; 5/CMA.3 §25 | A-06 PDF p. 25 §37 ("D. Metrics"); A-07 PDF p. 4 §25 | A-06, A-07 (UN ODS); paragraph text names AR5 100-year GWPs, §25 names AR5 Table 8.A.1 | tool_checked | UN documents; locator only, no reproduction needed | the decisions govern Paris Agreement national reporting. Using them for a farm-level product is the owner's 2026-09-15 choice, not a requirement on the product |
| T-02 | `gwp.ch4`, `gwp.n2o` | CFG | AR5 WG1 Ch. 8, Table 8.A.1 | A-05 PDF p. 73 (printed 731), continues on p. 74 | A-05; strings present | tool_checked (string presence only) | **not cleared** (IPCC; #83) | the row choice (non-fossil methane) and the column ("no climate-carbon feedback") need a person |
| T-03 | config comment: Vietnam reports its national inventory with AR5 | CFG (comment) | Vietnam BUR / BTR / NIR | — | **none** | none | — | unsupported; must not be cited until an artifact exists |
| T-04 | config and docs: QĐ 2626 states no GWP framework | CFG (comment) | QĐ 2626/QĐ-BTNMT | whole document (A-08, 23 pp) | A-08 first-party; no GWP-related string on any page. The earlier "đã đọc" (read) relied on a private portal | tool_checked (absence by text search) | not assessed | a person confirms the absence, including tables and headers |
| T-05 | Eq. 5.1, Eq. 5.2 (Tier 1 rice CH4) | CFG / SCI | IPCC 2019 Vol. 4 Ch. 5 §5.5 | A-01 mentions on PDF pp. 49, 52 (definitions not yet located) | A-01 | none (location not confirmed) | **not cleared** | locate the equation definitions |
| T-06 | `factors.ch4_rice.efc` (Southeast Asia) | CFG / SCI | Table 5.11 (UPDATED) | A-01 PDF p. 53 (5.53) | point and bounds present | tool_checked | **not cleared** | region row and baseline conditions (no flooding <180 d before; continuous flooding; no organic amendment) need a person |
| T-07 | `factors.ch4_rice.sfw.*` (7 regimes; AWD = multiple drainage) | CFG / SCI | Table 5.12 (UPDATED), disaggregated column, footnote b | A-01 PDF p. 54 (5.54) | 6 values and the AWD footnote text present; `upland` = 0 not string-checked | tool_checked | **not cleared** | which column (disaggregated vs aggregated); the AWD classification; `upland` |
| T-08 | `factors.ch4_rice.sfp.*` (4 pre-season regimes) | CFG / SCI | Table 5.13 (UPDATED), disaggregated column | A-01 PDF p. 55 (5.55) | strings present | tool_checked | **not cleared** | config note: the aggregated-column layout is ambiguous in extraction; B1 conflict (T-19) |
| T-09 | `factors.ch4_rice.sfo_exponent` | CFG / SCI | Equation 5.3 | A-01 PDF p. 55 | present | tool_checked | **not cleared** | the dry-mass basis of ROA |
| T-10 | `factors.ch4_rice.cfoa.*` (5 amendments) | CFG / SCI | Table 5.14 (UPDATED), footnote a | A-01 PDF p. 56 (5.56) | present | tool_checked | **not cleared** | the straw double-counting rule (footnote a): incorporated straw vs burnt or surface straw |
| T-11 | `default_cultivation_days` (NOT_IMPLEMENTED; engine does not read it) | CFG | Table 5.11A (NEW) | A-01 PDF pp. 52–53 | present | tool_checked | **not cleared** | none while unused |
| T-12 | `factors.n2o_fertilizer.ef1fr.*` (AWD → single and multiple drainage) | CFG / SCI | Table 11.1 (UPDATED), note 7 | A-02 PDF p. 13 (11.13) | values and the note-7 AWD text present | tool_checked | **not cleared** | disaggregated vs aggregate choice; flooded-rice scope |
| T-13 | `n2o_n_to_n2o` = 44/28 | CFG | molecular masses (no source needed) | — | — | n/a | n/a | — |
| T-14 | `straw_burning.combustion_factor_rice` | CFG / SCI | IPCC 2006 Vol. 4 Ch. 2 Table 2.6 | A-04 PDF pp. 48–49 (2.48–2.49) | present | tool_checked | **not cleared** | row (rice residues, post-harvest field burning). #82 did not list this source |
| T-15 | `straw_burning.gef_ch4`, `gef_n2o` | CFG / SCI | same, Table 2.5 (agricultural residues) | A-04 PDF p. 47 (2.47) | present | tool_checked | **not cleared** | the column (agricultural residues); the original source the table cites |
| T-16 | Eq. 2.27 (fire emissions) | CFG / SCI | same | A-04 PDF p. 42 (2.42) | equation caption found (no value to check) | tool_checked (location only) | **not cleared** | — |
| T-17 | `straw_burning.co2_counted` = 0 (PENDING) | CFG | IPCC AFOLU convention; QĐ 4801 | — | none | none | — | QĐ 4801 annex missing |
| T-18 | `fuel.*` = null (PENDING) | CFG | QĐ 2626 Phụ lục I (energy) or IPCC 2006 Vol. 2 | A-08 PDF pp. 2–7 (candidate) | A-08 acquired | none | not assessed | **config stays null**; using 2626 needs D2/D3 and a person |
| T-19 | country-specific rice factors (NOT_USED); B1 attributes SFp values to 2626 | CFG / SCI | QĐ 2626 Phụ lục III, rice | A-08 PDF pp. 15–18 | A-08. The B1 SFp strings were **not** found on pp. 15–18 by text search | tool_checked (absence only) | not assessed | a person checks the rice tables; resolves the B1 vs 2626 vs IPCC conflict |
| T-20 | `reference_values` (CONTESTED, unused) | CFG | internal roadmap document | — | none | none | — | OI-01 |
| T-21 | `carbon_credit_price` (NOT_CONFIRMED) | CFG | TCAF / World Bank | — | none | none | — | owner |
| T-22 | M05 rule `water.awd_from_continuous_flooding` v1 | RULE (exists: `backend/recommendation/rules.py`) | SCI for its effect: T-07 (CH4 down), T-12 (N2O up); it fires only on a positive engine delta. Agronomic suitability: QĐ 4043 annex | A-10 PDF p. 3 (AWD, water level) | A-10 (signed, validated 2026-10-07); tool: AWD on p. 3, no flowering-stage term found (split-word text layer) | none for agronomy | 4043 annex: not assessed | the rule's existence proves nothing about suitability; flowering-stage water management (P-09); the 4043 decision page is missing |
| T-23 | M05 rules `data.completeness.{yield,water,fertilizer,cost}` v1 | RULE (exists) | MRV data requirements: QĐ 4801 annex | — | annex **not published**; 4043 annex p. 6 record-keeping text does not mention water (tool) | none | — | no external basis found; product policy only (#82 §5) |
| T-24 | registry R1 `ref-ch4-awd-not-eliminated` | RULE→SCI pointer (`engine_config_pointer`) | T-07 | A-01 p. 54 | the registry has `artifact_sha256: null`, although A-01's hash is now known | tool_checked via T-07 | **not cleared** | registry update not authorized here; `detection_only` (internal) |
| T-25 | registry R2 `ref-water-records-required` | RULE (`project_policy`) | T-23 | — | none external | none | — | stays internal, `detection_only` |
| T-26 | QĐ 1490 as policy context | context | QĐ 1490/QĐ-TTg | A-11 (scan) | complete scan; portal signature intact (2026-10-07) | none | not assessed | OCR policy (#82) |
| T-27 | "6 MRV steps" (backend/api.py, docs) | context | QĐ 4801 annex | — | press only | none | — | annex missing; never fill from press |
| T-28 | farmer copy "bộ hệ số đã xác minh" (`metricsView.ts:398`) | public claim | — | — | contradicted by `domain_expert_review: PENDING` and no `human_verified` record | — | — | owner decision D4 |

Summary of the 28 rows:
- 0 human-verified;
- 15 tool-checked: T-04 and T-19 only by the absence of a string, T-16 by location only, T-24 through T-07;
- 13 with no evidence, or not applicable.

Every IPCC-derived row is **not cleared** for rights.

## 2. Reviewer packets (Phase D)

For a **named, qualified reviewer** appointed under E4 (#82). The reviewer works from the artifact bytes (identified by
SHA-256), not from this repository's description of them. A packet is complete only when every † field is filled by
that person. A tool or an AI session never fills it.

### 2.1 Verification steps (all packets)

1. Obtain the artifact from the official URL; compute its SHA-256 and compare with the acquisition record. A mismatch
   stops the packet.
2. Open the stated page. Record the printed page, table or equation title, row and column labels, and footnotes, exactly
   as printed.
3. Compare each config value (by key) with the printed cell, unit, range basis and conditions. Record agree / differ /
   not applicable.
4. Check the applicability conditions against AgriCarbon's use (region, regime, baseline, unit conversion).
5. Record every conflict listed in the packet, and any new one.
6. Sign the record. Only then may a registry record move to `human_verified` (#82 §3). Rights stay a separate decision.

### 2.2 Blank human-verification record (copy once per packet)

```yaml
packet: P-xx
artifact_id: A-xx
artifact_sha256_recomputed: †        # reviewer computes
pages_examined: †
as_printed:                          # reviewer transcribes only what rights allow (D1); otherwise a passage hash
  title: †
  rows_columns: †
  units: †
  conditions_and_footnotes: †
comparison:                          # one line per config key
  - key: <config key>
    result: †                        # agree | differ | not_applicable
    note: †
applicability_to_agricarbon: †
conflicts_reviewed: †
outcome: †                           # verified | rejected | needs_more_evidence
reviewer_name: †
reviewer_qualification_ref: †        # E4 appointment record
conflict_of_interest_statement: †
reviewed_on: †
signature_or_attestation_ref: †
```

### 2.3 Packets

| Packet | Claim(s) | Source / locator | Document identity | Conditions, dates, units to check | Conflicting or missing evidence |
|---|---|---|---|---|---|
| P-01 | T-01, T-02, T-03: AR5 GWP-100 for CH4 and N2O, chosen per the UNFCCC decisions | A-05 PDF p. 73–74; A-06 p. 25 §37; A-07 p. 4 §25 | A-05 `9709d708…2836`; A-06 `14398be5…8ea3`; A-07 `dcc94073…1c98` | non-fossil methane row; 100-year column without climate-carbon feedback; the 5/CMA.3 exclusions; unit kgCO2e per kg gas | T-03 has no artifact; the AR4/AR6 alternatives (config) |
| P-02 | T-06: baseline CH4 emission factor, Southeast Asia | A-01 Table 5.11, p. 53 | A-01 `eecbf328…5eda` | region row; baseline definition; 95% CI basis; unit per ha per day | none known |
| P-03 | T-07, T-24: water-regime scaling factors; AWD classed as multiple drainage; AWD does not remove methane (R1) | A-01 Table 5.12, p. 54, footnote b | A-01 | disaggregated vs aggregated column; `upland` row; range basis | dev3-01 poison asserts the opposite of R1 |
| P-04 | T-08, T-19: pre-season scaling factors; B1 and QĐ 2626 rice factors | A-01 Table 5.13, p. 55; A-08 pp. 15–18; B1 (#82 §4) | A-01; A-08 `cf3f3e13…d468` (read the rendered number and date on p. 1) | disaggregated column; the aggregated-column layout; 2626 region and season breakdown | B1 values differ from IPCC 2019; B1's attribution to 2626 not found by text search |
| P-05 | T-09, T-10: organic-amendment exponent and conversion factors; straw double counting | A-01 Eq. 5.3, p. 55; Table 5.14, p. 56, footnote a | A-01 | dry-mass basis; incorporation timing; burnt or surface straw excluded | interaction with T-14/T-15 (burnt straw) |
| P-06 | T-12: EF1FR by water regime; AWD → single and multiple drainage | A-02 Table 11.1, p. 13, note 7 | A-02 `337f18ce…61b3` | flooded rice only; disaggregated vs aggregate; range basis; N2O-N unit | B1 states a different N2O factor |
| P-07 | T-14, T-15, T-16: straw burning combustion and emission factors | A-04 Eq. 2.27 p. 42; Table 2.5 p. 47; Table 2.6 pp. 48–49 | A-04 `88232073…ba091e` | rice residues row; post-harvest burning; agricultural-residues column; g per kg dry matter | whether the 2019 Refinement Vol. 4 Ch. 2 (`19R_V4_Ch02_Generic Methods.pdf`, **not acquired**) refines Tables 2.5/2.6 |
| P-08 | T-04, T-18, T-19: QĐ 2626 contents (no GWP framework; energy factors; rice factors) | A-08 pp. 1–23 | A-08; the Điện Biên listing; signatures (acquisition §1.3) | number and date on p. 1; current validity (whether 2626 has been amended or superseded since 2022) | provenance decisions D2/D3; text-layer table extraction |
| P-09 | T-22 and `UNDETECTED_POISON`: water management around flowering under AWD | A-10 p. 3 (and the full annex) | A-10 `0aa5e2ee…f1a2` (signature validated 2026-10-07) | the growth stage at which the field is kept flooded; the AWD dry-down depth and interval; the region | no flowering-stage term found by tool (split words); the 4043 decision page and effectivity missing; the source-internal straw conflict (2 vs 3 weeks) is known |
| P-10 | T-23, T-25: MRV requires water and irrigation records | QĐ 4801 annex (**not obtained**); A-10 p. 6 | A-09 is only the decision page | — | **blocked**: no artifact to review. The packet stays open until the annex exists |

Exact SHA-256 values are in the acquisition record §1.1; the packets use their prefixes.

## 3. What this does not do

- No `human_verified` status, reviewer identity, signature, approval or date is filled in, or implied.
- No registry entry, config value, rule or test is changed.
- `test_rag_source_integrity_gap.py` is untouched.
- No source text beyond locators is reproduced here.
- E1, E4 and dev3-01 stay OPEN.

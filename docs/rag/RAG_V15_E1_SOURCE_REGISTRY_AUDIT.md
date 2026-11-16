# RAG V1.5 E1: source registry audit and reference metadata record

Status: **AUDIT ONLY, 2026-11-16. E1 is OPEN.** No registry entry, corpus document, approval or verifier identity is
added. No backend file is changed. Nothing here verifies a source. "Found" never means "verified".

Index: `RAG_V15_E1_E4_SOURCE_EXPERT_GOVERNANCE_PLAN.md`. Related: E3 containment, Draft PR #81 (E3 only contains what
detection finds, and detection depends on this registry).

## 1. Two kinds of checks: never conflate them

| | Tool check (automated) | Scientific verification (human) |
|---|---|---|
| Who | scripts: download, SHA-256, PDF signature/chain, text-layer probe, parser dry run | a **named, qualified human** (E4) |
| Proves | which bytes were obtained from where, unchanged since; that a signature is intact and chains to an official anchor | that a passage at a stated location says what the entry claims, applies to the stated scope, and is used correctly |
| Can set `verification.status = verified` | **never** | yes, with an evidence file |

All checks recorded in this repository so far are **tool checks**, or machine readings by an AI session. None is a
human scientific verification.

## 2. Classification (as of `integrate/rag-v15` 5f7e730)

| # | Item | Class | Used by |
|---|---|---|---|
| R1 | `ref-ch4-awd-not-eliminated` (qualitative registry entry) | **Internal operational source** (pointer to the engine config, which cites IPCC 2019 Refinement Table 5.12) | M4/E2 detection (dev3-01) |
| R2 | `ref-water-records-required` (qualitative registry entry) | **Internal operational source** (M05 rule `data.completeness.water`) | M4/E2 detection (dev3-01) |
| N | numeric registry `kn-reference-registry-2` | empty | none |
| C | `backend/config/emission_factors.yaml` (`0.3.0-ipcc2019-tier1-ar5`) | **Internal operational source**. Its `VERIFIED` labels are the project's own citation check; `domain_expert_review: PENDING` | Carbon Engine |
| S1 | IPCC 2019 Refinement, Vol. 4 Ch. 5 Cropland (A1) | **Primary source found, NOT human-verified**; **unclear reproduction rights** | C, R1 (pointer), M5 design |
| S2 | IPCC 2019 Refinement, Vol. 4 Ch. 11 N2O / lime / urea (A2) | **Primary source found, NOT human-verified**; **unclear reproduction rights** | C, M5 design |
| S3 | IPCC AR5 WG1 (2013) Ch. 8 Table 8.A.1 (GWP-100) | **Secondary reference** in the repo: cited by C, no artifact, hash or page recorded | C |
| S4 | UNFCCC decision 18/CMA.1 annex para 37; 5/CMA.3 para 25 (choice of AR5 GWP) | **Secondary reference** in the repo: cited by C, no artifact recorded | C |
| V1 | QĐ 2626/QĐ-BTNMT (10/10/2022), national emission factor list | **Missing or inaccessible source** (no first-party copy) | none (wanted for country-specific rice factors) |
| V2 | QĐ 4801/QĐ-BNNMT (14/11/2025), pilot rice MRV procedure | **Incomplete document** (decision page only; annex not published) | none |
| V3 | QĐ 4043/QĐ-TTTV-TTBVTV (10/11/2025), rice procedure | **Incomplete document** (annex only, internally inconsistent) | none |
| V4 | QĐ 1490/QĐ-TTg (27/11/2023), 1 million ha high-quality, low-emission rice scheme | **Scan-only document** | none |
| B1 | NAEC book "Canh tác lúa và cà phê giảm nhẹ biến đổi khí hậu" (C1-04) | **Primary source found, NOT human-verified**; **unclear reproduction rights**; conflicts with C | none |
| P | QĐ 145/QĐ-TT-CLT (named in V3's reference list) | **Missing or inaccessible source**; status unknown officially | none |

No item is in the class **"primary source verified by named human"**.

## 3. Reference metadata record (design)

One record per claim or parameter. A source document may have many records. The record lives in the registry, or in a
sibling evidence manifest whose hash the registry entry stores. Fields marked † must be `null` with a stated reason
until genuinely completed. They must never be filled by a tool or an AI session.

```yaml
record_id: ref-<parameter>-<n>            # stable; a changed entry is a NEW record
source:
  source_id: <registry source id>
  publisher: <issuing authority, as printed>
  official_title: <full title, as printed on the artifact>
  document_number: <verified number | null + reason>   # never from a portal listing alone
  version_or_edition: <...>
  issue_date: <...>
  effective_date: <date | null + reason>
  official_url: <issuer's own HTTPS URL | null>
  acquisition_provenance: <how and when the bytes were obtained; landing page; chain of custody>
  artifact_bytes: <int>
  artifact_sha256: <hex>
  authenticity: <signature chain result + anchor | issuer page link | none>
location:
  pdf_page: <n>
  printed_page: <as printed>
  section: <...>
  table_or_equation: <...>
  paragraph_or_row: <row/column labels as printed>
claim:
  parameter: <e.g. ch4.rice.sfw.irrigated_multiple_drainage>
  statement: <what the entry asserts, in the project's words>
  verbatim_passage_sha256: <hash of the exact passage; the passage itself is stored only if rights allow>
applicability:
  region: <...>
  season_or_regime: <...>
  crop: <...>
  units: <as printed>
  conditions: <baseline, quantity per, tier>
rights:
  status: cleared_for_intended_use | not_cleared | unknown
  intended_use: [local_research | internal_validation | retrieval_corpus | public_output | commercial]
  basis: <licence text / written permission reference | null>
verification:
  tool_checks: [<what ran, version, date, result>]
  status: unverified | tool_checked | human_verified | rejected | superseded
  verifier_identity: †
  verifier_qualification_ref: †
  verified_on: †
  evidence_sha256: †
conflicts: [<finding ids, other records, internal inconsistencies>]
permitted_downstream_use: detection_only | caveat_only | trusted_reference | none
```

Rules:

- `trusted_reference` requires `verification.status = human_verified` and `rights.status = cleared_for_intended_use`
  for every use listed.
- `detection_only` lets an entry raise a finding for a human. It never becomes a recommendation rule or proof.
- An internal operational source can be `detection_only` at most, and only labelled `internal` (§5).

## 4. Records for the current items

Values are what has actually been recorded. "not recorded" means the project does not have it. No scientific value
is reproduced here.

| Field | R1 | R2 | S1 (A1) | S2 (A2) |
|---|---|---|---|---|
| publisher | AgriCarbon (config) → IPCC | AgriCarbon (rule) | IPCC (TFI); landing page footer "© 2026 Intergovernmental Panel on Climate Change (IPCC)" | same |
| official title | n/a | n/a | 2019 Refinement to the 2006 IPCC Guidelines for National Greenhouse Gas Inventories, Vol. 4, Ch. 5 Cropland | ..., Vol. 4, Ch. 11 N2O Emissions from Managed Soils, and CO2 Emissions from Lime and Urea Application |
| version / effective date | registry 2026-11-09.1 | rule_version 1 | edition 2019; effective date n/a (guidance) | same |
| URL / provenance | config pointer | `backend/recommendation/rules.py` | `https://www.ipcc-nggip.iges.or.jp/public/2019rf/pdf/4_Volume4/19R_V4_Ch05_Cropland.pdf`, downloaded by an AI session 2026-11-11 and 2026-11-12 | `.../19R_V4_Ch11_Soils_N2O_CO2.pdf`, same |
| bytes / SHA-256 | none | none | 1,835,807 / `eecbf328eed9ef43cd3f091352fe9545e7c078288d89bf5d32adcae1f7805eda` | 944,749 / `337f18ceb618a858526ec01b5abed289843e1e8a69c957f0f62d22fa2a5761b3` |
| location | Table 5.12 (via config) | rule code | per-table PDF/printed pages in `RAG_V15_M5_REFERENCE_REGISTRY_DESIGN.md` §3 | same |
| rights | n/a | n/a | **not cleared** (§2 of the rights doc) | **not cleared** |
| verification | `engine_config_pointer`; unverified | `project_policy`; unverified | tool-checked (hash, text extraction); **human: PENDING** | same |
| conflicts | — | — | spanning table cells ambiguous in the text extraction | B1 cites different SFp and N2O values |
| permitted use (proposed) | detection_only (internal) | detection_only (internal) | none until rights + human verification | none |

Vietnamese decisions: see §6. B1 (NAEC book): `https://khuyennongvn.gov.vn/data/documents/0/2026/04/02/hangweb/5-canh-tac-lua-cafe-18-3-out.pdf`,
13,251,754 bytes, SHA-256 `36f03ffaf4909042d67f45566ed4417f06d0689eaf11ebb01db6aba7b2d80c13` (recorded 2026-10-07). Rights: the site states only
"© Bản quyền của Trung tâm Khuyến nông quốc gia", and the book was authored by an IAE team, so rights are unclear and
written permission is needed. It conflicts with C (SFp, N2O) and with its own library title. Permitted use: none.

## 5. Internal operational sources (Phase 7 policy)

- Internal configuration (`emission_factors.yaml`) and M05 rule definitions (`backend/recommendation/rules.py`) may be
  catalogued with `source.publisher = AgriCarbon (internal)` and `permitted_downstream_use = detection_only`.
- They are never labelled externally verified or primary. A config `status: VERIFIED` is the project's own citation
  check, not a scientific verification.
- **A rule's existence does not prove the underlying claim.** `data.completeness.water` proves that the product
  asks for water data. It does not prove that MRV requires it.
- No numeric reference enters the numeric registry from internal config. Values must come from a verified primary
  record (§3).
- Keep two lineages apart:
  - operational lineage: which config version or rule version produced an output;
  - scientific provenance: which verified passage supports a claim.

  A record must not satisfy one with the other.
- A recommendation still needs admissible scientific evidence wherever the RAG contract requires cited, approved
  documents. A stored M05 signal is the deterministic decision, not its scientific justification.

## 6. Vietnamese government documents (first-party only; read-only searches 2026-11-16)

A matching document number alone never identifies the document: `datafiles.chinhphu.vn/.../2022/01/06.signed.pdf`
turned out to be a different decision than its number suggested (C1 inventory, 2026-10-07).

| | V1 QĐ 2626/QĐ-BTNMT | V2 QĐ 4801/QĐ-BNNMT | V3 QĐ 4043/QĐ-TTTV-TTBVTV | V4 QĐ 1490/QĐ-TTg |
|---|---|---|---|---|
| title (as known) | publishing the emission factor list for GHG inventory | pilot procedure for measurement, reporting and verification (MRV) in high-quality, low-emission rice cultivation, Mekong Delta | procedure for high-quality, low-emission rice production, Mekong Delta | scheme for 1 million ha high-quality, low-emission rice (Đề án) |
| issuer / date | Bộ TN&MT, 10/10/2022 (per search results; not read from an artifact) | Bộ NN&MT, 14/11/2025 | Cục Trồng trọt và BVTV, 10/11/2025 | Thủ tướng (KT. TTg, PTT Trần Lưu Quang), 27/11/2023 |
| first-party artifact | **none obtained**. 2026-11-16: the former ministry page `monre.gov.vn/VanBan/Pages/ChiTietVanBanChiDao.aspx?pID=2787` is listed by search but fails TLS (host presents an `mae.gov.vn` certificate); searches of `chinhphu.vn`, `vbpl.vn`, `mae.gov.vn`, `dcc.mae.gov.vn` returned only documents that cite 2626; private portals (thuvienphapluat.vn, luatvietnam.vn) are pointers only | decision page only: `https://dcc.mae.gov.vn/Pages/chitietvanban-DCC.aspx?ItemID=45`, 1,180,892 B, SHA-256 `0221402cb3876785f7b356c74ed2db14139d58f6884ce10a8c207aa46f05fe5d` (2026-10-07). **The annexed procedure is not published there.** 2026-11-16: official-domain searches found only news (khuyennongvn.gov.vn, ppd.gov.vn) and no annex. Công báo No. 54 (24/01/2026), returned by the search, is Thông tư 93/2025/TT-BNNMT (seed quality); it contains no "4801" (checked by text extraction; SHA-256 `918ed83fe227748b5ae8cebe15599a60a98b791e7468a03fb485869422452f4f`) | **annex only**: Cà Mau provincial host `storage-vnportal.vnpt.vn/cmu-khdn/5342/...`, 465,721 B, SHA-256 `0aa5e2ee68cbf1d1448dc1a5a1f88173bafbf779457d8bfe80b10421fc64f1a2`; 3 signatures of the Cục, chain validated strictly to the official Ban Cơ yếu G2 root with CRLs (2026-10-07). The decision page is absent | complete, `https://datafiles.chinhphu.vn/cpp/files/vbpq/2023/11/1490-ttg.signed.pdf`, 537,724 B, SHA-256 `bf9bed53f05e7752cc0c0cc0c34ebdcbc94911da0217b8ab6dc37f1307a69115`; portal signature intact; chain not validated |
| problems | identity is unconfirmed from an artifact; no appendix tables; current validity unknown | the pilot is valid until 31/12/2026; the landing page names a different signer than the PDF signature; the press "6 steps" are not in the artifact | internal conflict (straw: diagram "at least 3 weeks" vs prose "at least 2 weeks"); effectivity and supersession of QĐ 145 unknown; section-path extraction defect | scan, no text layer (11 CCITT images); 2023 administrative names |
| status | **BLOCKED** | **BLOCKED** for MRV methodology; decision metadata only (HOLD_PARTIAL, 2026-10-07) | **BLOCKED** for scientific authorization | **BLOCKED** (needs the OCR policy, `RAG_V15_E1_RIGHTS_AND_OCR.md` §3) |
| unblock with | the decision with its appendices from the issuer (a person with a browser on `vbpl.vn` / `vanban.chinhphu.vn` / `mae.gov.vn`, or a copy requested from the ministry) | the annex from the ministry or an official channel | the complete decision from Cục TT&BVTV, plus an expert reading of the conflict | an official text-layer edition, or an OCR review under the policy |

No provision, annex, table or value of these decisions is reproduced, inferred or filled from press coverage.

## 7. Gaps summary

1. No human-verified primary record exists, so E1 stays OPEN.
2. Both detection references are internal. The dev3-01 detection therefore rests on project policy, not on an
   external authority.
3. The IPCC material has unclear rights, and the repository already holds machine-read IPCC table rows (M5 design §3)
   and IPCC-derived default values (engine config, its fixtures). See the rights doc §2.4: an owner decision is needed.
4. All four Vietnamese decisions are BLOCKED for scientific authorization.
5. S3 and S4 have no artifact, hash or page record.

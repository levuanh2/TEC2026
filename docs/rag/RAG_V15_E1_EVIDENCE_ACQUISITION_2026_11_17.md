# RAG V1.5 E1: primary-source evidence acquisition (2026-11-17)

Status: **EVIDENCE PREPARATION ONLY. E1 OPEN, E4 OPEN, dev3-01 OPEN.**

This change does not touch code, config, registries, corpus, migrations or tests. It verifies no source and
qualifies no person. Every check below is a **tool check** (the bytes, the hash, the signature, and whether a string
appears on a page). None of it is a human scientific verification (#82, `RAG_V15_E1_SOURCE_REGISTRY_AUDIT.md` §1).

Companion: `RAG_V15_E1_CLAIM_TRACEABILITY.md` (claim → source matrix and reviewer packets).

Related documents in other Draft PRs, which this change does not edit:
- #82: `RAG_V15_E1_SOURCE_REGISTRY_AUDIT.md`, `RAG_V15_E1_RIGHTS_AND_OCR.md`, `RAG_V15_E4_EXPERT_GOVERNANCE.md`;
- #83: the IPCC copyright page as seen through a search index.

## 0. What changed since #82 (2026-11-16)

| # | Change | Effect |
|---|---|---|
| 1 | **QĐ 2626/QĐ-BTNMT obtained, complete and signed**, from an official provincial legal database (§1.3) | V1 moves from "missing" to "acquired; provenance partly tool-checked; human verification pending" |
| 2 | AR5 WG1 Ch. 8 and both UNFCCC decisions (18/CMA.1, 5/CMA.3) obtained, with locators | closes #82 gap 5 (S3, S4 had no artifact) at tool level |
| 3 | IPCC 2006 Vol. 4 Ch. 2 obtained, with locators. It is a primary source of three engine factors that #82 did not list | a new row, S5 |
| 4 | IPCC 2019 Ch. 5 and Ch. 11 re-downloaded: the bytes match the 2026-11-11 hashes. Front matter and errata checked | no artifact change; no reproduction terms in the front matter; no errata hit on the cited tables (tool) |
| 5 | QĐ 4801, QĐ 4043 (annex) and QĐ 1490 re-hashed: identical to 2026-10-07 | still incomplete (4801, 4043) and scan-only (1490) |
| 6 | Detection gap in the claim extractor: a spelled-out zero ("bằng không") is never extracted (§4.2) | dev3-01 coverage is narrower than the two registry entries suggest |
| 7 | A farmer-facing string calls the factor set "đã xác minh" (verified) (§3.3) | the claim goes beyond the recorded evidence. Owner decision |

## 1. Phase A: source acquisition

All downloads ran 2026-11-16 17:58–18:35 UTC (2026-11-17 ~01:00–01:35 +07) with a generic browser user agent, over HTTPS
with a verified certificate unless stated. Two downloads of the same URL gave identical bytes where tested. No artifact
is committed: the repository keeps the hash, never a copy.

### 1.1 Artifacts obtained (bytes in hand)

| ID | Document (as printed) | Issuer | Official URL | Bytes | SHA-256 | Notes |
|---|---|---|---|---|---|---|
| A-01 | 2019 Refinement to the 2006 IPCC Guidelines, Vol. 4, Ch. 5 Cropland | IPCC (TFI) | `https://www.ipcc-nggip.iges.or.jp/public/2019rf/pdf/4_Volume4/19R_V4_Ch05_Cropland.pdf` | 1,835,807 | `eecbf328eed9ef43cd3f091352fe9545e7c078288d89bf5d32adcae1f7805eda` | identical to 2026-11-11; 102 pp; PDF created 2023-06-16 (re-issue) |
| A-02 | same, Vol. 4, Ch. 11 N2O Emissions from Managed Soils, and CO2 from Lime and Urea | IPCC (TFI) | `…/4_Volume4/19R_V4_Ch11_Soils_N2O_CO2.pdf` | 944,749 | `337f18ceb618a858526ec01b5abed289843e1e8a69c957f0f62d22fa2a5761b3` | identical to 2026-11-11; 48 pp; created 2023-07-09 |
| A-03 | 2019 Refinement, Vol. 4 cover / front matter | IPCC | `…/4_Volume4/19R_V4_Cover.pdf` | 195,587 | `f5935d171aa770574c23f9edc6f4e437dc57a4305293ec202e621c86e41618dc` | p. 2: "© The Intergovernmental Panel on Climate Change (IPCC), 2019" and a citation instruction. **No reproduction or licence terms** |
| A-03b | 2019 Refinement, Overview front matter (Vol. 0) | IPCC | `…/0_Overview/19R_V0_00_Cover_Foreword_Preface_Dedication.pdf` | 286,793 | `fcda21b9daa7577b1f5ba35d2530df4f330ac790d8d64adff23e10cfddef8181` | same notice; no terms |
| A-03c | Edits and errata to the 2019 Refinement | IPCC | `https://www.ipcc-nggip.iges.or.jp/public/2019rf/Edits_and_errata.pdf` | 616,497 | `60238e56a3ab87540c5d2af1cebe6be4e98daf4211eae91aa4bd26e1e0baa510` | 27 pp. Only Vol. 4 Ch. 5 item found: Table 5A.3.3 (annex, unused). No hit for "rice", Tables 5.10–5.14, Table 11.x, EF1FR (tool search; a person must read the list) |
| A-04 | 2006 IPCC Guidelines, Vol. 4, Ch. 2 Generic Methodologies | IPCC (TFI) | `https://www.ipcc-nggip.iges.or.jp/public/2006gl/pdf/4_Volume4/V4_02_Ch2_Generic.pdf` | 839,363 | `8823207378e0aab1817c4a924c63d36a974e058f344426c73d6a66f599ba091e` | **new**; 59 pp |
| A-05 | Climate Change 2013: The Physical Science Basis (AR5 WG1), Ch. 8 Anthropogenic and Natural Radiative Forcing | IPCC | `https://www.ipcc.ch/site/assets/uploads/2018/02/WG1AR5_Chapter08_FINAL.pdf` | 19,360,338 | `9709d70802b4a78fe372f6a949d4d2af7bf31c38c1f666783d5b188702dc2836` | **new**; 82 pp |
| A-06 | FCCC/PA/CMA/2018/3/Add.2 (contains decision 18/CMA.1) | UNFCCC (UN document) | `https://documents.un.org/api/symbol/access?s=FCCC/PA/CMA/2018/3/Add.2&l=en&t=pdf` → `https://documents.un.org/doc/undoc/gen/g19/107/79/pdf/g1910779.pdf` | 637,238 | `14398be59a780bfdeedaf24a9bfe54cec35b50aea59a537c235498a3ebd98ea3` | **new**. The config's URL (`unfccc.int/…/CMA2018_03a02E.pdf`) returned a 212-byte bot-challenge page (Incapsula), not the PDF |
| A-07 | FCCC/PA/CMA/2021/10/Add.2 (contains decision 5/CMA.3) | UNFCCC (UN document) | `https://documents.un.org/api/symbol/access?s=FCCC/PA/CMA/2021/10/Add.2&l=en&t=pdf` → `…/g22/280/11/pdf/g2228011.pdf` | 789,442 | `dcc94073cdedb6caf16c9455d9106d984616cb1d0ddd3d4723319cfc84ed1c98` | **new** |
| A-08 | QĐ 2626/QĐ-BTNMT: "VV công bố Danh mục hệ số phát thải phục vụ kiểm kê khí nhà kính" (listing title) | Bộ Tài nguyên và Môi trường | listing: `https://qppl.dienbien.gov.vn/qlvb/vbpq.nsf/3d0f058120469ad34725726600365420/3335e811cbff37f6472588d90002edbf`; file: `…/3335E811CBFF37F6472588D90002EDBF/$file/2626-qd-btnmt_Signed.pdf` | 1,887,955 | `cf3f3e13201278e271137fcb84fa05a6ca9c727f5fbaa9cc172f02a02162d468` | **new, first-party copy**. §1.3 |
| A-08b | same decision, stamped variant (`dongdau4432_11-10-2022-10-51-38_2626-qd-btnmt_Signed.pdf`) | same listing | same listing | 2,315,159 | `9b6e8b1df42755056b27a73bc82687a48aa94ea1c4867109fb4f053452c426b6` | A-08 plus a later iText edit (stamp images on p. 1). Its signatures no longer cover the whole file. **A-08 is the record** |
| A-09 | QĐ 4801/QĐ-BNNMT (decision page only) | Bộ NN&MT | `https://dcc.mae.gov.vn/Pages/chitietvanban-DCC.aspx?ItemID=45` (single attachment) | 1,180,892 | `0221402cb3876785f7b356c74ed2db14139d58f6884ce10a8c207aa46f05fe5d` | identical to 2026-10-07; 1 page; **annex still not published** |
| A-10 | QĐ 4043/QĐ-TTTV-TTBVTV, annex "Quy trình …" only | Cục Trồng trọt và BVTV | `https://storage-vnportal.vnpt.vn/cmu-khdn/5342/Vanban/quy-trinh-4043-qt-san-xuat-lua-clc-va-ptt-vung-dbscl-1.pdf` | 465,721 | `0aa5e2ee68cbf1d1448dc1a5a1f88173bafbf779457d8bfe80b10421fc64f1a2` | identical to 2026-10-07; signatures validated then (C1 record). **Decision page still not found** |
| A-11 | QĐ 1490/QĐ-TTg | Thủ tướng Chính phủ | `https://datafiles.chinhphu.vn/cpp/files/vbpq/2023/11/1490-ttg.signed.pdf` | 537,724 | `bf9bed53f05e7752cc0c0cc0c34ebdcbc94911da0217b8ab6dc37f1307a69115` | identical to 2026-10-07. The portal page (`vanban.chinhphu.vn/?pageid=27160&docid=209054`) still offers only this scan; **no text-layer edition** |

### 1.2 Locators (tool check: caption found; value strings from the config present on that page or the next)

"Present" means only that the string occurs on that page. It does **not** mean the value sits in the right row
and column, or applies to the stated conditions. That is the human check (packets, companion doc §2).

| Artifact | Locator | PDF page | Printed page | Config strings present |
|---|---|---|---|---|
| A-01 | Table 5.11 (UPDATED) | 53 | 5.53 | yes (point and both bounds) |
| A-01 | Table 5.11A (NEW) | 52–53 | 5.52–5.53 | yes |
| A-01 | Table 5.12 (UPDATED) incl. footnote b (AWD) | 54 | 5.54 | yes, incl. "alternate wetting and drying" (`upland` value 0 not string-checked) |
| A-01 | Table 5.13 (UPDATED) | 55 | 5.55 | yes |
| A-01 | Equation 5.3 | 55 | 5.55 | yes |
| A-01 | Table 5.14 (UPDATED) | 56 | 5.56 | yes |
| A-01 | Equations 5.1, 5.2 | mentions on 52 and 49 (and in the contents, p. 4). Not confirmed to be the definitions | — | n/a |
| A-02 | Table 11.1 (UPDATED) incl. note 7 (AWD) | 13 | 11.13 | yes, incl. "alternate wetting and drying" |
| A-04 | Equation 2.27 | 42 | 2.42 | n/a |
| A-04 | Table 2.5 (agricultural residues) | 47 | 2.47 | yes |
| A-04 | Table 2.6 (rice residues) | 48–49 | 2.48–2.49 | yes |
| A-05 | Table 8.A.1 (continues on the next page) | 73 | 731 | yes ("28", "265", "Methane", "Nitrous") |
| A-06 | decision 18/CMA.1 starts | 18 | 18 | — |
| A-06 | annex §37 ("D. Metrics": 100-year GWP values from the IPCC AR5) | 25 | 25 | yes |
| A-07 | decision 5/CMA.3 starts | 2 | 2 | — |
| A-07 | §25 (the GWP values of 18/CMA.1 annex §37 are those in AR5 Table 8.A.1, with stated exclusions) | 4 | 4 | yes |
| A-08 | Phụ lục I / II / III / IV | 2 / 8 / 10 / 19 | — | — |
| A-08 | rice section (terms "canh tác lúa / lúa nước", "đông xuân / hè thu") | 15–18 | — | — |
| A-10 | water management incl. AWD and water-level observation | 3 | — | — |
| A-10 | record-keeping ("ghi chép …") | 6 | — | the passage does not mention water (tool) |

### 1.3 QĐ 2626/QĐ-BTNMT: identity and provenance (tool checks)

- **Host.** `qppl.dienbien.gov.vn` is the legal-document database of the Điện Biên provincial government, an official
  but secondary channel. It is the same class of route as QĐ 4043's Cà Mau copy. Listing metadata: number 2626/QĐ-BTNMT;
  "Ngày ban hành 10/10/2022"; "Người ký Lê Công Thành"; issuer Bộ Tài nguyên và Môi trường. TLS verified.
- **Structure.** 23 pages, a text layer on every page, no images. Four appendices (I energy p. 2; II industrial processes
  p. 8; III agriculture, forestry and land use p. 10; IV waste p. 19). "IPCC" appears on pp. 2–23.
- **Number and day are blank in the text layer** ("Số: /QĐ-BTNMT", "ngày tháng 10 năm 2022"). This is the known pattern of
  Vietnamese e-signed PDFs, which draw these values in signature widgets. The identity "2626, 10/10/2022" therefore
  rests on the listing, the stamped variant's file name, and the signing timestamps. **A person must read the rendered
  number and date on p. 1.**
- **Signatures (pyHanko 0.29, integrity mode).** 6 signatures, all intact and cryptographically valid, each with an
  embedded timestamp token:
  - two officials of the ministry (Cục Biến đổi khí hậu; Văn phòng Bộ), signed 10/10/2022;
  - "Thứ trưởng Lê Công Thành", timestamp 2022-10-11 03:16:51 UTC;
  - three by the organisation certificate "Bộ Tài nguyên và Môi trường", the last at 03:34:58 UTC.

  The last signature covers the **entire file**, untouched (`UNTOUCHED`). pyHanko's diff policy classes signature 1 as
  "EXTENDED_WITH_OTHER / ILLEGAL_MODIFICATIONS" (an update after a certification signature). Signatures 2–5 are
  "form filling, acceptable". The signature-1 class is recorded, not explained away.
- **Chain.** The signer certificates are issued by "Co quan chung thuc so Chinh phu" (Ban Cơ yếu G1). That CA and the G1
  root ("Co quan chung thuc so chuyen dung Chinh phu (RootCA)", DER SHA-256 `f7bc8905…`) were downloaded from the
  official PKI portal `https://dichvucong.ca.gov.vn/api/tainguyen/download/<id>`. Their SHA-1 values equal the portal
  listing. At the signing moment (2022-10-11), with SHA-1 explicitly allowed, the path builds signer → G1 CA → G1 root.
  **SHA-1 has to be allowed because the G1 CA certificates themselves are SHA-1-signed.** By default, pyHanko refuses
  that path.
- **Not established.**
  - A strict full-PDF validation (timestamps plus point-in-time revocation) reports `trusted=false`. No 2022 revocation
    data was available: today's CRL `cp.crl` was issued 2026-11-15. CRLs come over plain HTTP from `ca.gov.vn`;
    they are signed objects.
  - None of the 4 signer serials is listed in today's CRL. This is weak evidence: expired certificates (all expired
    2023) can be dropped from CRLs.
  - The decision is not confirmed on the issuer's own site (`monre.gov.vn` → `mae.gov.vn`; TLS mismatch recorded in #82).
- **Contents, tool level.**
  - No "GWP", "tiềm năng nóng lên", "CO2tđ / CO2 tương đương" string on any page. This is consistent with the config's
    statement that 2626 sets no GWP framework, which had been made from a private-portal reading.
  - The SFp values the NAEC book (B1) attributes to 2626 ("0,68", "1,90") were not found on the rice pages (pp. 15–18):
    "0,68" nowhere, "1,90" only on p. 5 (energy appendix). Table text extraction can split cells, so **a person must check
    this before any conclusion about B1.**
- **Rights.** A state administrative document. Its rights status for each intended use has not been assessed by counsel
  (owner decision, §5).

### 1.4 Still inaccessible or incomplete (no contents inferred)

| Item | Searched (2026-11-16/17) | State |
|---|---|---|
| QĐ 4801 MRV annex ("Quy trình", 6 steps, data requirements) | DCC page ItemID=45 (one attachment, unchanged); web search: press and conference reports only | **not published** on any official channel found |
| QĐ 4043 decision page (Điều 1–3, signer, effectivity, relation to QĐ 145) | web search: provincial news and press | **not found**. Number spelled 3 ways in secondary sources |
| QĐ 1490 text-layer edition | portal page and the scan above | **scan only** (OCR policy decision pending, #82) |
| Vietnam's GWP basis for national reporting (config comment "Việt Nam báo cáo quốc gia theo AR5") | not searched for in this round | **no artifact**. The comment is unsupported until a BUR/BTR or NIR is obtained |
| `unfccc.int` copy of the CMA decisions | 212-byte bot-challenge page | replaced by the UN ODS artifacts A-06/A-07 (same symbols) |
| IPCC 2006 Vol. 2 Ch. 3 / national fuel factors | not searched (fuel factors stay `null`) | 2626 Phụ lục I is now available as a candidate (A-08), with no change to the config |

## 2. Classification (update of #82 §2)

| Item | Class now |
|---|---|
| S1 A-01, S2 A-02 | primary source acquired, locators tool-checked; **not human-verified; rights not cleared** |
| S3 A-05 (AR5 Table 8.A.1) | **primary source acquired** (was "secondary reference, no artifact"); not human-verified; rights not cleared |
| S4 A-06/A-07 (UNFCCC decisions) | **primary source acquired** (was "no artifact"); not human-verified |
| S5 A-04 (IPCC 2006 Vol. 4 Ch. 2): new row | primary source acquired, locators tool-checked; not human-verified; rights not cleared |
| V1 A-08 (QĐ 2626) | **acquired from an official secondary host, complete, signature integrity valid; chain to the official G1 root only with SHA-1 allowed; number unread in text** (was "missing") |
| V2 QĐ 4801, V3 QĐ 4043, V4 QĐ 1490 | unchanged: incomplete / incomplete / scan-only |
| R1, R2, C (internal) | unchanged: internal operational sources, `detection_only` at most |
| B1 NAEC book | unchanged. Its attribution of SFp values to 2626 is now testable against A-08 (packet P-04) |

## 3. Phase C: IPCC-derived content in the repository

Two questions must stay apart:
- **copyright**: may this text or this set of values be reproduced, for this use?
- **scientific validity**: does the source say this, for these conditions?

A cleared licence does not make a value right, and a correct value does not make its reproduction lawful. #83 is
search-index evidence of the terms, **not a licence**.

### 3.1 Inventory (`integrate/rag-v15` 5f7e730)

| Use | Where | What exactly | Extent |
|---|---|---|---|
| Internal calculation configuration (individual factual values with citations) | `backend/config/emission_factors.yaml` | 27 `VERIFIED` values with uncertainty ranges and table and equation citations, across IPCC 2019 Ch. 5/Ch. 11, 2006 Ch. 2 and AR5 Table 8.A.1; plus **2 verbatim footnote quotes** (Table 5.12 b, Table 11.1 note 7) | one factor set, `0.3.0-ipcc2019-tier1-ar5` |
| Same, replicated in the database | hosted factor set `0.3.0` ("imported + published", `docs/CARBON_METHOD_SOURCES.md`) | the same values | not inspected here (no hosted access in this task) |
| Test fixtures | `backend/tests/fixtures/factor_sets/{wrong_unit,unverified_source,missing_gwp,incomplete_fuel,duplicate_factor}.yaml` | variants of the same set (≈50 citation lines each) | 5 files |
| Code comments and error text | `backend/carbon/methodology.py` (verbatim Table 5.14 footnote a in a comment; two CFOA values in an error message); `backend/infrastructure/mapping.py` (one SFw value in an error message); `backend/carbon/engine.py`, `models.py` (citations) | short excerpts and single values | ~30 lines |
| Documentation reproduction | `docs/rag/RAG_V15_M5_REFERENCE_REGISTRY_DESIGN.md` §3 (**machine-read rows of Tables 5.11, 5.11A, 5.12, 5.13, 5.14, 11.1 with captions and notes as printed**); `docs/CARBON_METHOD_SOURCES.md` (values per table + 2 verbatim footnotes); `docs/CARBON_METHOD.md`; `docs/methodology/carbon-factor-register.md` | table transcription (M5 §3 is the most extensive); value lists with citations | 4 documents |
| Database enum labels | `supabase/migrations/20260908000000_carbon_methodology_alignment.sql` (comments and enum names following the Table 5.12/5.13 categories) | category names, no values | 1 migration |
| Public-facing output | MRV exports (`backend/mrv/manifest.py` `factors_by_set`, with `source_reference` such as "Table 5.11") sent to cooperatives; web and Flutter labels of the IPCC water-regime categories (`web-dashboard/src/vocab.ts`, `app/lib/models/methodology_enums.dart`); the farmer copy in §3.3 | individual values plus citations in exports; category names in the UI | per export |
| Retrieval corpus | none committed. `reference_registry.json` holds locators only. The C1 decision kept IPCC text out of the corpus | — | hosted corpus not inspected |

### 3.2 Least-disruptive options (the owner chooses; none is applied here)

| Option | Applies to | Carbon Engine effect |
|---|---|---|
| O1 Keep the config's individual values with citations. Record a rights basis per intended use (permission / licence / counsel-confirmed exception) | config, DB factor set, fixtures | none |
| O2 Replace the M5 §3 table transcription with locators + page hashes (as §1.2 does) | M5 design doc | none |
| O3 Drop or shorten the verbatim footnote quotes in config, docs and comments; keep locators | config comments, 2 docs, 1 code comment | none (comments and strings only; error-message text would change) |
| O4 MRV exports: keep values and citations (auditability), add a source-attribution line. Or restrict export recipients | `backend/mrv` | none |
| O5 Correct the farmer copy in §3.3 to say what was checked | `web-dashboard` copy | none |
| O6 If permission for some use is refused: move to country-specific factors (QĐ 2626, A-08) | engine | **changes outputs**: needs region and season inputs, expert review, a new factor-set version. Not a quick fix |

No emission factor is removed, no calculation is changed, and no copyrighted material is redistributed by this
change.

### 3.3 Public verification claim (owner decision)

`web-dashboard/src/farmer/metricsView.ts:398`: "Máy chủ tính theo phương pháp IPCC 2019 với bộ hệ số đã xác minh; …". The
recorded evidence is narrower:
- the config's `VERIFIED` means the project's own citation check;
- `methodology.domain_expert_review` is `PENDING`;
- no record in the repository is human-verified (#82).

A neutral wording would describe what was checked (factors taken from the cited IPCC tables; not yet reviewed by an
expert). Copy change only; not made here.

## 4. Phase E: consequences for dev3-01

Method: the **existing** deterministic reviewer (`knowledge.integrity.review`) with the **production** registries
(qualitative `2026-11-09.1`, 2 entries; numeric `2026-11-12.0`, 0 entries), `as_of` 2026-11-17. Input: the
**existing** fixture texts only:
- `scripts/rag_llm_benchmark.py` `CHUNK_PRESETS`, `AWD_CHUNKS`, `SUBTLE_INJECTION` and `OFF_TOPIC_CHUNKS`;
- `UNDETECTED_POISON` from the #81 E3 tests.

No model, no network, no database. Run on the #84 tree (`c7e9acf` = the #78 → #81 → #84 stack), where the dev3-01 and
E3 fixtures exist.

### 4.1 Coverage

| Fixture (claim) | Extracted | Finding | Covered by |
|---|---|---|---|
| `poisoned_claim` (dev3-01): "one AWD season → no more methane" | assertion `ch4.rice.emission_eliminated` | `reference_conflict` (needs expert review) | R1 `ref-ch4-awd-not-eliminated`, an **internal** pointer to Table 5.12 (A-01 p. 54) |
| same chunk: "no need to record water level / irrigation data" | assertion `records.water.not_required` | `reference_conflict` | R2 `ref-water-records-required`, an **internal product rule** |
| `UNDETECTED_POISON` (E3 test_12i): "keep the field dry and cracked through flowering for the highest yield" | stage `flowering` only; no parameter | **none** | nothing |
| `marker_injection`, `subtle_injection`: "… phát thải bằng không" | **nothing** | none | (the injection controls, not integrity) |
| clean AWD, record-keeping and off-topic fixtures | stage only or nothing | none | — |

Only the dev3-01 chunk is detected, and only against two internal entries. Neither has an external, human-verified
authority behind it.

### 4.2 Extractor gap found: spelled-out zero

With the same extractor, these sentences are extracted as `ch4.rice.emission_eliminated`:
- "Phát thải mê-tan bằng 0.";
- "Phát thải mê-tan về 0.";
- "Methane emission drops to zero.".

These are extracted as **nothing**:
- "Phát thải mê-tan bằng không.";
- "… về không.";
- "Ruộng này có phát thải bằng không.".

The pattern lists "bằng không" and "về không", but the word "không" inside the match is taken as a negator and cancels
it. No existing test covers the spelled-out form; the digit form is tested.

Fixing it is a code change: a new extractor version, and therefore new claim ids. That needs owner approval and is not
done here.

### 4.3 Missing evidence needed to improve detection

| Gap | What would close it | Prerequisites |
|---|---|---|
| R1 rests on an internal pointer | a human-verified record of Table 5.12 (A-01 p. 54) for the multiple-drainage row (packet P-03) | E4 reviewer; the rights decision for storing the record |
| R2 rests on a product rule | the QĐ 4801 MRV annex, or another first-party MRV text that requires water records | the annex is not published (§1.4). The QĐ 4043 annex record-keeping passage (p. 6) does not mention water (tool) |
| any numeric poison (a wrong SFw, a wrong reduction percentage, a wrong EF1FR) | numeric registry entries from verified Table 5.11–5.14 / 11.1 records | empty registry; E4; rights (values as printed) |
| the flowering-stage dry-down claim (`UNDETECTED_POISON`) | a qualitative entry backed by a first-party agronomic source on water at flowering | candidate locator: QĐ 4043 annex p. 3 (AWD, water level). Whether it states a flowering-stage rule **must be read by a person**: the text layer splits words, and the tool search found no stage term. The complete 4043 decision is still missing |
| spelled-out zero | the extractor change in §4.2 | owner approval |

**dev3-01 stays OPEN.** The scenarios passing proves only that the two fixture phrasings are caught.
`test_rag_source_integrity_gap.py` is unchanged.

## 5. Owner decisions and actions

| # | Decision or action | Blocks |
|---|---|---|
| D1 | Rights basis per use for the IPCC-derived content (O1–O4). Read `ipcc.ch/copyright` in a browser (#83) | any registry entry storing printed values; M5 §3 |
| D2 | Accept, or not, the Điện Biên provincial copy of QĐ 2626 as provenance (analogous to the QĐ 4043 decision of 2026-10-07). Or obtain it from the ministry. A person reads the rendered number and date on p. 1 | any use of A-08 |
| D3 | Accept the G1 chain result with SHA-1 allowed, or require stronger evidence (a ministry copy with the same SHA-256) | same |
| D4 | Correct the farmer "đã xác minh" copy (§3.3) | public claim accuracy |
| D5 | Approve the extractor fix for spelled-out zero (§4.2) | dev3-01 coverage |
| D6 | Appoint qualified reviewers (E4) for packets P-01…P-10 | every `human_verified` record |
| D7 | Keep the config comment "Việt Nam báo cáo quốc gia theo AR5" only with an artifact | config accuracy |
| A1 | Obtain the QĐ 4801 annex and the QĐ 4043 decision from the issuers (written request) | R2 external basis; 4043 effectivity |

## Sources

Official artifacts are listed in §1.1. Search results used to find A-08 and to confirm that nothing newer exists:
- the Điện Biên listing (A-08);
- for QĐ 4801/4043: the NAEC conference report
  `https://khuyennongvn.gov.vn/1-trieu-hecta-chuyen-canh-lua-chat-luong-cao/hoi-nghi-trien-khai-quy-trinh-mrv-va-quy-trinh-san-xuat-lua-chat-luong-cao-phat-thai-thap-vung-dong-bang-song-cuu-long-31693.html`
  and press reports. These are pointers only, never evidence of contents.
